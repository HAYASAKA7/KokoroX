"""Explicit lifecycle storage for KokoroArc sessions."""

from __future__ import annotations

import copy
import errno
import json
import math
import os
import re
import stat
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from kokoroarc import __version__
from kokoroarc.errors import KokoroError
from kokoroarc.json_compat import find_json_incompatibility
from kokoroarc.packs.compiler import write_compiled_pack
from kokoroarc.state.transitions import MAX_APPLIED_EVENT_IDS, apply_event


_SESSION_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_CHARACTER_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
_COMPILED_PACK_HASH = re.compile(r"[a-f0-9]{64}")
SESSION_MANIFEST_MAX_BYTES = 64 * 1024
EVENT_RECORD_MAX_BYTES = 64 * 1024
RELATIONSHIP_STATE_MAX_BYTES = 4 * 1024 * 1024
_SESSION_LOCK_TIMEOUT_SECONDS = 5.0
_SESSION_LOCK_POLL_SECONDS = 0.01
_THREAD_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()
_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "artifact_id",
        "created_by",
        "session_id",
        "character_id",
        "character_version",
        "compiled_pack_hash",
        "scope",
        "state_revision",
        "active",
    }
)
_MINIMAL_EVENT_KEYS = frozenset(
    {
        "event_id",
        "novelty_key",
        "expected_state_revision",
        "confidence",
        "effects",
    }
)
_FULL_EVENT_KEYS = frozenset(
    {
        "schema_version",
        "artifact_id",
        "created_by",
        "event_id",
        "turn_id",
        "origin",
        "novelty_key",
        "expected_state_revision",
        "evaluator_version",
        "evidence",
        "confidence",
        "effects",
    }
)
_STATE_KEYS = frozenset(
    {
        "schema_version",
        "artifact_id",
        "created_by",
        "revision",
        "turn_index",
        "dimensions",
        "stage",
        "applied_event_ids",
        "recent_novelty",
    }
)
_DIMENSIONS = frozenset({"familiarity", "trust", "collaboration", "tension"})
_STAGES = frozenset({"unknown", "acquainted", "familiar", "trusted"})
_EVENT_FILENAME = re.compile(
    r"([1-9][0-9]*)-([a-z0-9]+(?:-[a-z0-9]+)*)\.json"
)
_WINDOWS_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)


def _atomic_write_json(value: dict[str, Any], target: Path) -> None:
    """Publish canonical JSON through the shared hardened atomic writer."""
    write_compiled_pack(value, target)


def _path_is_redirect(path: Path) -> bool:
    """Return whether *path* is a symlink, junction, or reparse point."""
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if is_junction is not None and is_junction():
            return True
        try:
            path_stat = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            return False
    except OSError as error:
        raise KokoroError(
            "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
        ) from error

    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return bool(reparse_flag and attributes & reparse_flag)


def _invalid(code: str, message: str) -> KokoroError:
    return KokoroError(code, message)


def _invalid_session_data() -> KokoroError:
    return KokoroError("SESSION_DATA_INVALID", "Session data is invalid.")


def _invalid_event() -> KokoroError:
    return KokoroError("INVALID_EVENT", "Interaction event is invalid.")


def _invalid_journal() -> KokoroError:
    return KokoroError(
        "STATE_JOURNAL_INVALID", "Session event journal is invalid."
    )


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = item
    return value


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _thread_lock_for(data_root: Path, session_id: str) -> threading.Lock:
    key = (os.path.normcase(str(data_root)), session_id)
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.Lock())


def _try_acquire_os_file_lock(handle: BinaryIO) -> bool:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EAGAIN}:
                return False
            raise
        return True

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _acquire_os_file_lock(handle: BinaryIO) -> None:
    deadline = time.monotonic() + _SESSION_LOCK_TIMEOUT_SECONDS
    while not _try_acquire_os_file_lock(handle):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise KokoroError(
                "SESSION_LOCK_TIMEOUT",
                "Session lock acquisition timed out.",
                retryable=True,
            )
        time.sleep(min(_SESSION_LOCK_POLL_SECONDS, remaining))


def _release_os_file_lock(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _session_lock_failed() -> KokoroError:
    return KokoroError(
        "SESSION_LOCK_FAILED", "Session lock operation failed."
    )


def _validate_session_id(session_id: object) -> str:
    if (
        not isinstance(session_id, str)
        or len(session_id) > 128
        or _SESSION_ID.fullmatch(session_id) is None
        or session_id in _WINDOWS_DEVICE_NAMES
    ):
        raise _invalid("INVALID_SESSION_ID", "Session ID is invalid.")
    return session_id


def _validate_character_id(character_id: object) -> str:
    if (
        not isinstance(character_id, str)
        or len(character_id) > 64
        or _CHARACTER_ID.fullmatch(character_id) is None
    ):
        raise _invalid("INVALID_CHARACTER_ID", "Character ID is invalid.")
    return character_id


def _validate_character_version(character_version: object) -> str:
    if (
        not isinstance(character_version, str)
        or len(character_version) > 64
        or _SEMVER.fullmatch(character_version) is None
    ):
        raise _invalid(
            "INVALID_CHARACTER_VERSION", "Character version is invalid."
        )
    return character_version


def _validate_compiled_pack_hash(compiled_pack_hash: object) -> str:
    if (
        not isinstance(compiled_pack_hash, str)
        or _COMPILED_PACK_HASH.fullmatch(compiled_pack_hash) is None
    ):
        raise _invalid(
            "INVALID_COMPILED_PACK_HASH", "Compiled pack hash is invalid."
        )
    return compiled_pack_hash


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _created_by_is_valid(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"component", "version"}
        and value["component"] == "kokoroarc"
        and isinstance(value["version"], str)
        and 1 <= len(value["version"]) <= 64
    )


def _validate_event(event: object) -> dict[str, Any]:
    """Return an isolated, closed interaction event or raise a safe error."""
    if not isinstance(event, dict) or find_json_incompatibility(event) is not None:
        raise _invalid_event()
    keys = frozenset(event)
    if keys not in {_MINIMAL_EVENT_KEYS, _FULL_EVENT_KEYS}:
        raise _invalid_event()

    event_id = event.get("event_id")
    novelty_key = event.get("novelty_key")
    expected_revision = event.get("expected_state_revision")
    confidence = event.get("confidence")
    effects = event.get("effects")
    if (
        not isinstance(event_id, str)
        or len(event_id) > 128
        or _SESSION_ID.fullmatch(event_id) is None
        or not isinstance(novelty_key, str)
        or len(novelty_key) > 128
        or _SESSION_ID.fullmatch(novelty_key) is None
        or not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 0
        or not _is_number(confidence)
        or not 0 <= confidence <= 1
        or not isinstance(effects, dict)
        or not effects
        or not set(effects).issubset(_DIMENSIONS)
        or any(
            not _is_number(delta) or not -4 <= delta <= 4
            for delta in effects.values()
        )
    ):
        raise _invalid_event()

    if keys == _FULL_EVENT_KEYS:
        created_by = event.get("created_by")
        evidence = event.get("evidence")
        turn_id = event.get("turn_id")
        evaluator_version = event.get("evaluator_version")
        if (
            event.get("schema_version") != "1.0"
            or event.get("artifact_id") != f"event/{event_id}"
            or not _created_by_is_valid(created_by)
            or not isinstance(turn_id, str)
            or len(turn_id) > 128
            or _SESSION_ID.fullmatch(turn_id) is None
            or event.get("origin")
            not in {"verified_task_outcome", "explicit_user_feedback"}
            or not isinstance(evaluator_version, str)
            or not 1 <= len(evaluator_version) <= 128
            or not isinstance(evidence, dict)
            or set(evidence) != {"kind", "reference"}
            or evidence.get("kind")
            not in {
                "test_result", "user_feedback", "tool_result", "delivery_result"
            }
            or not isinstance(evidence.get("reference"), str)
            or not 1 <= len(evidence["reference"]) <= 512
        ):
            raise _invalid_event()
    return copy.deepcopy(event)


def _validate_transition_config(
    max_delta: object, repetition_window: object
) -> tuple[float, int]:
    if (
        not _is_number(max_delta)
        or not 0 <= max_delta <= 4
        or not isinstance(repetition_window, int)
        or isinstance(repetition_window, bool)
        or not 1 <= repetition_window <= MAX_APPLIED_EVENT_IDS
    ):
        raise _invalid_event()
    return float(max_delta), repetition_window


def _initial_state(
    session_id: str, created_by: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": f"state/{session_id}",
        "created_by": copy.deepcopy(created_by),
        "revision": 0,
        "turn_index": 0,
        "dimensions": {
            "familiarity": 0.0,
            "trust": 0.0,
            "collaboration": 0.0,
            "tension": 0.0,
        },
        "stage": "unknown",
        "applied_event_ids": [],
        "recent_novelty": {},
    }


def _state_is_valid(value: object, session_id: str) -> bool:
    if not isinstance(value, dict) or set(value) != _STATE_KEYS:
        return False
    revision = value.get("revision")
    turn_index = value.get("turn_index")
    dimensions = value.get("dimensions")
    event_ids = value.get("applied_event_ids")
    novelty = value.get("recent_novelty")
    return (
        value.get("schema_version") == "1.0"
        and value.get("artifact_id") == f"state/{session_id}"
        and _created_by_is_valid(value.get("created_by"))
        and isinstance(revision, int)
        and not isinstance(revision, bool)
        and revision >= 0
        and isinstance(turn_index, int)
        and not isinstance(turn_index, bool)
        and turn_index >= 0
        and isinstance(dimensions, dict)
        and set(dimensions) == _DIMENSIONS
        and all(
            _is_number(item) and 0 <= item <= 100
            for item in dimensions.values()
        )
        and value.get("stage") in _STAGES
        and isinstance(event_ids, list) and len(event_ids) <= MAX_APPLIED_EVENT_IDS
        and all(
            isinstance(item, str) and len(item) <= 128
            and _SESSION_ID.fullmatch(item) is not None for item in event_ids
        )
        and len(event_ids) == len(set(event_ids))
        and isinstance(novelty, dict) and len(novelty) <= MAX_APPLIED_EVENT_IDS
        and all(
            isinstance(key, str) and len(key) <= 128
            and _SESSION_ID.fullmatch(key) is not None
            and isinstance(item, int) and not isinstance(item, bool) and item >= 0
            for key, item in novelty.items()
        )
    )


def _read_bounded_json(target: Path, max_bytes: int, error_factory) -> Any:
    try:
        with target.open("rb") as handle:
            contents = handle.read(max_bytes + 1)
    except FileNotFoundError:
        raise
    except OSError as error:
        raise error_factory() from error
    if len(contents) > max_bytes:
        raise error_factory()
    try:
        value = json.loads(
            contents.decode("utf-8"),
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as error:
        raise error_factory() from error
    if find_json_incompatibility(value) is not None:
        raise error_factory()
    return value


class SessionStore:
    """Manage explicit on-disk session lifecycles."""

    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root).resolve(strict=False)

    def _storage_directory(self, name: str, *, create: bool) -> Path:
        directory = self.data_root / name
        if _path_is_redirect(directory):
            raise KokoroError(
                "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
            )
        try:
            resolved = directory.resolve(strict=False)
            if not resolved.is_relative_to(self.data_root):
                raise KokoroError(
                    "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
                )
            if create:
                directory.mkdir(parents=True, exist_ok=True)
        except KokoroError:
            raise
        except OSError as error:
            raise KokoroError(
                "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
            ) from error

        if _path_is_redirect(directory):
            raise KokoroError(
                "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
            )
        try:
            resolved = directory.resolve(strict=False)
        except OSError as error:
            raise KokoroError(
                "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
            ) from error
        if not resolved.is_relative_to(self.data_root):
            raise KokoroError(
                "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
            )
        return directory

    def _target_path(
        self,
        area: str,
        session_id: str,
        *,
        create: bool,
        suffix: str = ".json",
    ) -> Path:
        directory = self._storage_directory(area, create=create)
        target = directory / f"{session_id}{suffix}"
        if _path_is_redirect(target):
            raise KokoroError(
                "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
            )
        try:
            resolved = target.resolve(strict=False)
        except OSError as error:
            raise KokoroError(
                "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
            ) from error
        if not resolved.is_relative_to(self.data_root):
            raise KokoroError(
                "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
            )
        if _path_is_redirect(target):
            raise KokoroError(
                "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
            )
        return target

    def _nested_directory(
        self, area: str, name: str, *, create: bool
    ) -> Path:
        parent = self._storage_directory(area, create=create)
        directory = parent / name
        if _path_is_redirect(directory):
            raise KokoroError(
                "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
            )
        try:
            resolved = directory.resolve(strict=False)
            if not resolved.is_relative_to(self.data_root):
                raise KokoroError(
                    "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
                )
            if create:
                directory.mkdir(exist_ok=True)
        except KokoroError:
            raise
        except OSError as error:
            raise KokoroError(
                "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
            ) from error
        if _path_is_redirect(directory):
            raise KokoroError(
                "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
            )
        if directory.exists() and not directory.is_dir():
            raise _invalid_journal()
        return directory

    def _event_directory(self, session_id: str, *, create: bool) -> Path:
        return self._nested_directory("events", session_id, create=create)

    def _event_path(
        self, session_id: str, revision: int, event_id: str
    ) -> Path:
        directory = self._event_directory(session_id, create=True)
        target = directory / f"{revision}-{event_id}.json"
        if _path_is_redirect(target):
            raise KokoroError(
                "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
            )
        try:
            resolved = target.resolve(strict=False)
        except OSError as error:
            raise KokoroError(
                "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
            ) from error
        if not resolved.is_relative_to(self.data_root):
            raise KokoroError(
                "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
            )
        if _path_is_redirect(target):
            raise KokoroError(
                "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
            )
        return target

    def _journal_entries(self, session_id: str) -> list[tuple[int, str, Path]]:
        directory = self._event_directory(session_id, create=False)
        if not directory.exists():
            return []
        candidates: list[Path] = []
        try:
            for candidate in directory.iterdir():
                if len(candidates) >= MAX_APPLIED_EVENT_IDS:
                    raise _invalid_journal()
                candidates.append(candidate)
        except KokoroError:
            raise
        except OSError as error:
            raise _invalid_journal() from error

        entries: list[tuple[int, str, Path]] = []
        for candidate in candidates:
            if _path_is_redirect(candidate):
                raise KokoroError(
                    "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
                )
            match = _EVENT_FILENAME.fullmatch(candidate.name)
            try:
                is_file = candidate.is_file()
                contained = candidate.resolve(strict=False).is_relative_to(
                    self.data_root
                )
            except OSError as error:
                raise _invalid_journal() from error
            if match is None or not is_file or not contained:
                raise _invalid_journal()
            entries.append((int(match.group(1)), match.group(2), candidate))

        entries.sort(key=lambda item: (item[0], item[1]))
        seen_ids: set[str] = set()
        for expected_revision, (revision, event_id, _path) in enumerate(
            entries, start=1
        ):
            if revision != expected_revision or event_id in seen_ids:
                raise _invalid_journal()
            seen_ids.add(event_id)
        return entries

    def _read_event_record(
        self, revision: int, filename_event_id: str, path: Path
    ) -> tuple[dict[str, Any], float, int]:
        value = _read_bounded_json(path, EVENT_RECORD_MAX_BYTES, _invalid_journal)
        if (
            not isinstance(value, dict)
            or set(value) != {"schema_version", "event", "transition"}
            or value.get("schema_version") != "1.0"
            or not isinstance(value.get("transition"), dict)
            or set(value["transition"]) != {"max_delta", "repetition_window"}
        ):
            raise _invalid_journal()
        try:
            committed_event = _validate_event(value["event"])
            max_delta, repetition_window = _validate_transition_config(
                value["transition"]["max_delta"],
                value["transition"]["repetition_window"],
            )
        except KokoroError as error:
            raise _invalid_journal() from error
        if (
            committed_event["event_id"] != filename_event_id
            or committed_event["expected_state_revision"] != revision - 1
        ):
            raise _invalid_journal()
        return committed_event, max_delta, repetition_window

    def _replay_locked(
        self, session_id: str, manifest: dict[str, Any]
    ) -> dict[str, Any]:
        state = _initial_state(session_id, manifest["created_by"])
        for revision, event_id, path in self._journal_entries(session_id):
            committed_event, max_delta, repetition_window = self._read_event_record(
                revision, event_id, path
            )
            state = apply_event(
                state,
                committed_event,
                max_delta=max_delta,
                repetition_window=repetition_window,
            )
            if state["revision"] != revision:
                raise _invalid_journal()
        if not _state_is_valid(state, session_id):
            raise _invalid_journal()
        return state

    def _read_cached_state(self, session_id: str) -> dict[str, Any] | None:
        target = self._target_path("state", session_id, create=False)
        try:
            state = _read_bounded_json(
                target, RELATIONSHIP_STATE_MAX_BYTES, _invalid_session_data
            )
        except FileNotFoundError:
            return None
        except KokoroError as error:
            if error.code == "SESSION_DATA_INVALID":
                return None
            raise
        if not _state_is_valid(state, session_id):
            return None
        return state

    def _repair_projection_locked(
        self,
        session_id: str,
        manifest: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        cached_state = self._read_cached_state(session_id)
        if cached_state != state:
            state_path = self._target_path("state", session_id, create=True)
            _atomic_write_json(state, state_path)

        if manifest["state_revision"] == state["revision"]:
            return manifest
        repaired = copy.deepcopy(manifest)
        repaired["state_revision"] = state["revision"]
        manifest_path = self._target_path("sessions", session_id, create=False)
        _atomic_write_json(repaired, manifest_path)
        return repaired

    def _archive_event_history_locked(
        self, session_id: str, manifest: dict[str, Any]
    ) -> None:
        source = self._event_directory(session_id, create=False)
        if not source.exists():
            return
        self._replay_locked(session_id, manifest)
        archive_root = self._storage_directory("event-archives", create=True)
        target: Path | None = None
        for index in range(1, MAX_APPLIED_EVENT_IDS + 1):
            candidate = archive_root / f"{session_id}-{index}"
            if _path_is_redirect(candidate):
                raise KokoroError(
                    "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
                )
            try:
                contained = candidate.resolve(strict=False).is_relative_to(
                    self.data_root
                )
            except OSError as error:
                raise KokoroError(
                    "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
                ) from error
            if not contained:
                raise KokoroError(
                    "SESSION_PATH_UNSAFE", "Session storage path is unsafe."
                )
            if not candidate.exists():
                target = candidate
                break
        if target is None:
            raise KokoroError(
                "STATE_CAPACITY_EXCEEDED",
                "Relationship state capacity was exceeded.",
                details={"field": "event_archives", "limit": MAX_APPLIED_EVENT_IDS},
            )
        try:
            os.replace(source, target)
        except OSError as error:
            raise KokoroError(
                "SESSION_WRITE_FAILED", "Session data could not be written."
            ) from error

    @contextmanager
    def _session_lock(self, session_id: str) -> Iterator[None]:
        thread_lock = _thread_lock_for(self.data_root, session_id)
        if not thread_lock.acquire(timeout=_SESSION_LOCK_TIMEOUT_SECONDS):
            raise KokoroError(
                "SESSION_LOCK_TIMEOUT",
                "Session lock acquisition timed out.",
                retryable=True,
            )
        try:
            lock_path = self._target_path(
                "session-locks",
                session_id,
                create=True,
                suffix=".lock",
            )
            handle: BinaryIO | None = None
            try:
                handle = lock_path.open("a+b")
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                _acquire_os_file_lock(handle)
            except KokoroError:
                if handle is not None:
                    try:
                        handle.close()
                    except OSError:
                        pass
                raise
            except OSError as error:
                if handle is not None:
                    try:
                        handle.close()
                    except OSError:
                        pass
                raise _session_lock_failed() from error

            assert handle is not None
            body_failed = True
            cleanup_error: OSError | None = None
            try:
                yield
                body_failed = False
            finally:
                try:
                    _release_os_file_lock(handle)
                except OSError as error:
                    cleanup_error = error
                try:
                    handle.close()
                except OSError as error:
                    if cleanup_error is None:
                        cleanup_error = error
                if cleanup_error is not None and not body_failed:
                    raise _session_lock_failed() from cleanup_error
        finally:
            thread_lock.release()

    def _read_manifest(self, session_id: str) -> dict[str, Any]:
        target = self._target_path("sessions", session_id, create=False)
        try:
            with target.open("rb") as handle:
                contents = handle.read(SESSION_MANIFEST_MAX_BYTES + 1)
        except FileNotFoundError as error:
            raise KokoroError(
                "SESSION_NOT_FOUND", "Session was not found."
            ) from error
        except OSError as error:
            raise KokoroError(
                "SESSION_READ_FAILED", "Session data could not be read."
            ) from error
        if len(contents) > SESSION_MANIFEST_MAX_BYTES:
            raise _invalid_session_data()
        try:
            manifest = json.loads(
                contents.decode("utf-8"),
                object_pairs_hook=_strict_json_object,
                parse_constant=_reject_json_constant,
            )
            compatible = find_json_incompatibility(manifest) is None
            valid = self._manifest_is_valid(manifest, session_id)
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
            ValueError,
        ) as error:
            raise _invalid_session_data() from error
        if not compatible or not valid:
            raise _invalid_session_data()
        return manifest

    @staticmethod
    def _manifest_is_valid(manifest: Any, session_id: str) -> bool:
        if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
            return False
        created_by = manifest["created_by"]
        if not isinstance(created_by, dict) or set(created_by) != {
            "component",
            "version",
        }:
            return False
        creator_version = created_by["version"]
        state_revision = manifest["state_revision"]
        return (
            manifest["schema_version"] == "1.0"
            and manifest["artifact_id"] == f"session/{session_id}"
            and created_by["component"] == "kokoroarc"
            and isinstance(creator_version, str)
            and 1 <= len(creator_version) <= 64
            and manifest["session_id"] == session_id
            and _SESSION_ID.fullmatch(session_id) is not None
            and isinstance(manifest["character_id"], str)
            and len(manifest["character_id"]) <= 64
            and _CHARACTER_ID.fullmatch(manifest["character_id"]) is not None
            and isinstance(manifest["character_version"], str)
            and 1 <= len(manifest["character_version"]) <= 64
            and _SEMVER.fullmatch(manifest["character_version"]) is not None
            and isinstance(manifest["compiled_pack_hash"], str)
            and _COMPILED_PACK_HASH.fullmatch(manifest["compiled_pack_hash"])
            is not None
            and manifest["scope"] == "session"
            and isinstance(state_revision, int)
            and not isinstance(state_revision, bool)
            and state_revision >= 0
            and isinstance(manifest["active"], bool)
        )

    def start(
        self,
        session_id: str,
        character_id: str,
        character_version: str,
        compiled_pack_hash: str,
    ) -> dict[str, Any]:
        session_id = _validate_session_id(session_id)
        character_id = _validate_character_id(character_id)
        character_version = _validate_character_version(character_version)
        compiled_pack_hash = _validate_compiled_pack_hash(compiled_pack_hash)

        with self._session_lock(session_id):
            existing: dict[str, Any] | None = None
            try:
                existing = self._read_manifest(session_id)
            except KokoroError as error:
                if error.code != "SESSION_NOT_FOUND":
                    raise
            else:
                if existing["active"]:
                    raise KokoroError(
                        "SESSION_ALREADY_ACTIVE", "Session is already active."
                    )

            if existing is not None:
                self._archive_event_history_locked(session_id, existing)

            manifest = {
                "schema_version": "1.0",
                "artifact_id": f"session/{session_id}",
                "created_by": {"component": "kokoroarc", "version": __version__},
                "session_id": session_id,
                "character_id": character_id,
                "character_version": character_version,
                "compiled_pack_hash": compiled_pack_hash,
                "scope": "session",
                "state_revision": 0,
                "active": True,
            }
            state = _initial_state(session_id, manifest["created_by"])
            state_path = self._target_path("state", session_id, create=True)
            manifest_path = self._target_path("sessions", session_id, create=True)
            _atomic_write_json(state, state_path)
            _atomic_write_json(manifest, manifest_path)
            return manifest

    def load(self, session_id: str) -> dict[str, Any]:
        """Load an existing session manifest as a fresh object."""
        session_id = _validate_session_id(session_id)
        return self._read_manifest(session_id)

    def replay(self, session_id: str) -> dict[str, Any]:
        """Read and replay the authoritative append-only event journal."""
        session_id = _validate_session_id(session_id)
        with self._session_lock(session_id):
            manifest = self._read_manifest(session_id)
            return self._replay_locked(session_id, manifest)

    def apply(
        self,
        session_id: str,
        event: dict[str, Any],
        max_delta: float = 4.0,
        *,
        repetition_window: int = 3,
    ) -> dict[str, Any]:
        """Commit one revision-checked event and refresh derived projections."""
        session_id = _validate_session_id(session_id)
        committed_event = _validate_event(event)
        max_delta, repetition_window = _validate_transition_config(
            max_delta, repetition_window
        )
        try:
            with self._session_lock(session_id):
                manifest = self._read_manifest(session_id)
                if not manifest["active"]:
                    raise KokoroError(
                        "SESSION_NOT_ACTIVE", "Session is not active."
                    )

                state = self._replay_locked(session_id, manifest)
                manifest = self._repair_projection_locked(
                    session_id, manifest, state
                )
                event_id = committed_event["event_id"]
                if event_id in state["applied_event_ids"]:
                    return state

                expected_revision = committed_event["expected_state_revision"]
                actual_revision = state["revision"]
                if expected_revision != actual_revision:
                    raise KokoroError(
                        "STATE_REVISION_CONFLICT",
                        "Relationship state revision conflicted.",
                        retryable=True,
                        details={
                            "expected": expected_revision,
                            "actual": actual_revision,
                        },
                    )

                next_state = apply_event(
                    state,
                    committed_event,
                    max_delta=max_delta,
                    repetition_window=repetition_window,
                )
                next_revision = next_state["revision"]
                event_path = self._event_path(
                    session_id, next_revision, event_id
                )
                if event_path.exists():
                    raise _invalid_journal()
                record = {
                    "schema_version": "1.0",
                    "event": committed_event,
                    "transition": {
                        "max_delta": max_delta,
                        "repetition_window": repetition_window,
                    },
                }

                # Publishing this append-only record is the transaction commit point.
                _atomic_write_json(record, event_path)
                state_path = self._target_path("state", session_id, create=True)
                _atomic_write_json(next_state, state_path)
                updated_manifest = copy.deepcopy(manifest)
                updated_manifest["state_revision"] = next_revision
                manifest_path = self._target_path(
                    "sessions", session_id, create=False
                )
                _atomic_write_json(updated_manifest, manifest_path)
                return next_state
        except KokoroError as error:
            if error.code == "SESSION_LOCK_TIMEOUT":
                raise KokoroError(
                    "STATE_BUSY",
                    "Relationship state is busy.",
                    retryable=True,
                ) from error
            raise

    def end(self, session_id: str) -> dict[str, Any]:
        """End a session without altering its relationship state."""
        session_id = _validate_session_id(session_id)
        with self._session_lock(session_id):
            manifest = self._read_manifest(session_id)
            if not manifest["active"]:
                return manifest

            ended = dict(manifest)
            ended["active"] = False
            target = self._target_path("sessions", session_id, create=False)
            _atomic_write_json(ended, target)
            return ended
