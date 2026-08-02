"""Explicit lifecycle storage for KokoroArc sessions."""

from __future__ import annotations

import errno
import json
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
            state = {
                "schema_version": "1.0",
                "artifact_id": f"state/{session_id}",
                "created_by": {"component": "kokoroarc", "version": __version__},
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
            state_path = self._target_path("state", session_id, create=True)
            manifest_path = self._target_path("sessions", session_id, create=True)
            _atomic_write_json(state, state_path)
            _atomic_write_json(manifest, manifest_path)
            return manifest

    def load(self, session_id: str) -> dict[str, Any]:
        """Load an existing session manifest as a fresh object."""
        session_id = _validate_session_id(session_id)
        return self._read_manifest(session_id)

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
