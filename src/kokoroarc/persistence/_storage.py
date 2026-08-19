"""Bounded, no-follow storage primitives for consented persistence."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import errno
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import (
    Any,
    Callable,
    Iterator,
    Literal,
    Mapping,
    NoReturn,
    Protocol,
    Sequence,
    cast,
)

from kokoroarc.distribution.registry import InstallScope, resolve_install_scope
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes


_SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_JSON_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\.json\Z")
_SHA256_PATTERN = re.compile(r"[a-f0-9]{64}\Z")
_GENERATION_PATTERN = re.compile(r"generation-[a-f0-9]{32}\Z")
_MIGRATION_ID_PATTERN = re.compile(r"migration-[a-f0-9]{32}\Z")
_WINDOWS_RESERVED_DEVICE_BASENAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }
)
_STORE_NAMES = frozenset(
    {"consents", "persistent-state", "memory-references"}
)
_LOCK_CONTENTION_ERRNOS = frozenset(
    value
    for value in (
        getattr(errno, "EACCES", None),
        getattr(errno, "EAGAIN", None),
        getattr(errno, "EWOULDBLOCK", None),
        getattr(errno, "EDEADLK", None),
    )
    if value is not None
)
_LOCK_CONTENTION_WINERRORS = frozenset({33, 36})
_DIRECTORY_FSYNC_UNSUPPORTED = frozenset(
    value
    for value in (
        getattr(errno, "EINVAL", None),
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
        getattr(errno, "EBADF", None),
    )
    if value is not None
)


class SchemaValidator(Protocol):
    """The narrow schema callback needed by persistence storage."""

    def validate(self, name: str, instance: Any) -> None:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class _NoCallbackSchemas:
    def validate(self, _name: str, _instance: Any) -> None:
        return None


@dataclass(frozen=True, slots=True)
class PersistenceLimits:
    """Closed resource limits shared by all persistent stores."""

    max_consent_bytes: int = 64 * 1024
    max_state_bytes: int = 4 * 1024 * 1024
    max_event_bytes: int = 16 * 1024
    max_memory_bytes: int = 16 * 1024
    max_transaction_bytes: int = 128 * 1024
    max_consent_history: int = 1024
    max_state_generations: int = 64
    max_state_events: int = 10_000
    max_memory_references: int = 1024
    max_journal_bytes: int = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PersistenceKey:
    """One canonical global or workspace character persistence key."""

    scope: Literal["global", "workspace"]
    workspace_id: str | None
    namespace: str
    character_id: str

    @property
    def scope_parts(self) -> tuple[str] | tuple[str, str]:
        if self.scope == "global":
            return ("global",)
        return ("workspaces", cast(str, self.workspace_id))


@dataclass(frozen=True, slots=True)
class ArtifactSnapshot:
    """Canonical bytes, detached value, and retained file identity."""

    path: Path
    payload: bytes
    value: dict[str, Any]
    identity: tuple[int, int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class _DirectoryIdentity:
    path: Path
    device: int
    inode: int
    file_type: int


@dataclass(frozen=True, slots=True)
class _DirectorySnapshot:
    path: Path
    identity: _DirectoryIdentity
    entries: tuple[tuple[str, tuple[int, int, int, int, int, int]], ...]
    limit: int


@dataclass(frozen=True, slots=True)
class _ReferenceLayoutSnapshot:
    path: Path
    identity: _DirectoryIdentity
    entries: tuple[tuple[str, tuple[int, int, int, int, int, int]], ...]
    allowed: tuple[tuple[str, Literal["directory", "file"]], ...]


@dataclass(frozen=True, slots=True)
class _MutationProbe:
    name: str
    value: Any
    payload: bytes

    def audit(self) -> None:
        try:
            matches = canonical_bytes(self.value) == self.payload
        except (KokoroError, TypeError, ValueError, UnicodeError):
            matches = False
        if not matches:
            raise _mutation_error(self.name)


@dataclass(slots=True)
class PersistenceBoundary:
    """Sticky mutation and filesystem audit boundary."""

    schemas: SchemaValidator
    audits: dict[str, Callable[[], None]] = field(default_factory=dict)
    violation: KokoroError | None = None

    def capture(self, name: str, value: Any) -> bytes:
        try:
            payload = canonical_bytes(value)
        except (KokoroError, TypeError, ValueError, UnicodeError) as error:
            raise _changed("invalid_canonical_input") from error
        probe = _MutationProbe(name=name, value=value, payload=payload)
        self.audits[f"input:{name}"] = probe.audit
        return payload

    def validate(self, schema_name: str, payload: bytes) -> None:
        probe = _decode_canonical_object(payload)
        schema_error: BaseException | None = None
        try:
            self.schemas.validate(schema_name, probe)
        except (KokoroError, TypeError, ValueError, UnicodeError) as error:
            schema_error = error
        finally:
            try:
                if canonical_bytes(probe) != payload:
                    self.fail("schema_input")
            except KokoroError as error:
                if error.code == "PERSISTENCE_INPUT_MUTATION":
                    raise
                self.fail("schema_input")
            self.assert_clean()
        if schema_error is not None:
            raise _changed("schema_invalid") from schema_error

    def assert_clean(self) -> None:
        if self.violation is not None:
            raise self.violation
        def audit_order(name: str) -> tuple[int, str]:
            # An invalidated scope makes every descendant observation unsafe.
            # Report that boundary failure before a descendant merely appears
            # missing or byte-different as a consequence of the replacement.
            return (0 if name.startswith("scope:") else 1, name)

        for name in sorted(tuple(self.audits), key=audit_order):
            try:
                self.audits[name]()
            except KokoroError as error:
                if self.violation is None:
                    self.violation = error
                raise self.violation

    def fail(self, reason: str) -> NoReturn:
        error = _mutation_error(reason)
        if self.violation is None:
            self.violation = error
        raise self.violation

    def authorize_root_creation(self) -> None:
        self.assert_clean()
        self.audits.pop("scope:root_absent", None)


@dataclass(frozen=True, slots=True)
class PersistenceScope:
    """One read boundary and its canonical persistent storage roots."""

    root: Path
    key: PersistenceKey
    boundary: PersistenceBoundary
    limits: PersistenceLimits

    def character_root(self, store: str) -> Path:
        if store not in _STORE_NAMES:
            raise _path_unsafe("unknown_store")
        return self.root.joinpath(
            store,
            *self.key.scope_parts,
            self.key.namespace,
            self.key.character_id,
        )

    @property
    def transaction_path(self) -> Path:
        return self.root.joinpath(
            "persistence-transactions",
            *self.key.scope_parts,
            f"{self.key.namespace}.{self.key.character_id}.json",
        )

    @property
    def lock_path(self) -> Path:
        return self.root.joinpath(
            "persistence-locks",
            *self.key.scope_parts,
            f"{self.key.namespace}.{self.key.character_id}.lock",
        )


@dataclass(slots=True)
class PersistenceLock:
    """A retained cross-process per-character persistence lock."""

    scope: PersistenceScope
    path: Path
    descriptor: int
    ancestry: tuple[_DirectoryIdentity, ...]
    held: bool = True

    def __enter__(self) -> PersistenceLock:
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()

    def owns(self) -> bool:
        if not self.held or not _directory_chain_matches(self.ancestry):
            return False
        try:
            linked = self.path.lstat()
            opened = os.fstat(self.descriptor)
        except OSError:
            return False
        return _safe_lock_stats(self.path, linked, opened)

    def assert_owned(self) -> None:
        if not self.owns():
            raise _path_unsafe("lock_changed")
        self.scope.boundary.assert_clean()

    def release(self) -> None:
        if not self.held:
            return
        try:
            _unlock_descriptor(self.descriptor)
        finally:
            try:
                os.close(self.descriptor)
            except OSError:
                pass
            self.held = False


@dataclass(frozen=True, slots=True)
class _IdentifiedStaging:
    path: Path
    identity: _DirectoryIdentity
    ancestry: tuple[_DirectoryIdentity, ...]


def open_persistence_scope(
    data_root: Path,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    character_id: str,
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> PersistenceScope:
    """Capture one persistence scope without creating any filesystem node."""

    root = _absolute_path(data_root)
    _assert_safe_segment(namespace, "namespace")
    _assert_safe_segment(character_id, "character_id")
    try:
        install_scope = resolve_install_scope(workspace_root)
    except KokoroError as error:
        raise _path_unsafe("workspace_scope") from error
    key = PersistenceKey(
        scope=install_scope.kind,
        workspace_id=install_scope.workspace_id,
        namespace=namespace,
        character_id=character_id,
    )
    boundary = _capture_scope_boundary(root, workspace_root, schemas)
    return PersistenceScope(root, key, boundary, limits)


@contextmanager
def persistence_reference_lock(
    data_root: Path,
    scope: InstallScope,
    namespace: str,
    character_id: str,
) -> Iterator[PersistenceLock]:
    """Hold the exact persistence character lock during installation removal."""

    reference_scope = _reference_scope(
        data_root,
        scope,
        namespace,
        character_id,
        _NoCallbackSchemas(),
        PersistenceLimits(),
    )
    with _acquire_character_lock(reference_scope) as lock:
        yield lock


def persistence_reference_blockers(
    data_root: Path,
    scope: InstallScope,
    installation: Mapping[str, Any],
    schemas: SchemaValidator,
    *,
    limits: PersistenceLimits = PersistenceLimits(),
    _lock: PersistenceLock | None = None,
) -> list[str]:
    """Return exact current persistent references to one installation."""

    binding = _reference_installation_binding(scope, installation)
    reference_scope = _reference_scope(
        data_root,
        scope,
        cast(str, binding["namespace"]),
        cast(str, binding["character_id"]),
        schemas,
        limits,
    )
    if _lock is not None:
        _require_reference_lock(_lock, reference_scope)
    blockers = _scan_persistence_reference_blockers(
        reference_scope,
        binding,
    )
    reference_scope.boundary.assert_clean()
    if _lock is not None:
        _lock.scope.boundary.audits.update(
            reference_scope.boundary.audits
        )
        _lock.scope.boundary.assert_clean()
    return sorted(blockers)


def _reference_scope(
    data_root: Path,
    install_scope: InstallScope,
    namespace: str,
    character_id: str,
    schemas: SchemaValidator,
    limits: PersistenceLimits,
) -> PersistenceScope:
    root = _absolute_path(data_root)
    _assert_safe_segment(namespace, "namespace")
    _assert_safe_segment(character_id, "character_id")
    if install_scope.kind == "global":
        if install_scope.workspace_id is not None:
            raise _path_unsafe("scope_binding")
    elif (
        install_scope.kind != "workspace"
        or not isinstance(install_scope.workspace_id, str)
        or _SHA256_PATTERN.fullmatch(install_scope.workspace_id) is None
    ):
        raise _path_unsafe("scope_binding")
    key = PersistenceKey(
        scope=install_scope.kind,
        workspace_id=install_scope.workspace_id,
        namespace=namespace,
        character_id=character_id,
    )
    return PersistenceScope(
        root,
        key,
        _capture_scope_boundary(root, None, schemas),
        limits,
    )


def _reference_installation_binding(
    scope: InstallScope,
    installation: Mapping[str, Any],
) -> dict[str, Any]:
    required = {
        "installation_id",
        "compiled_artifact_id",
        "archive_sha256",
        "compiled_sha256",
        "relative_path",
    }
    if not required.issubset(installation):
        raise _changed("installation_binding")
    relative_path = installation.get("relative_path")
    compiled_artifact_id = installation.get("compiled_artifact_id")
    if not isinstance(relative_path, str) or not isinstance(
        compiled_artifact_id,
        str,
    ):
        raise _changed("installation_binding")
    relative_parts = relative_path.split("/")
    artifact_parts = compiled_artifact_id.split("/")
    if scope.kind == "global":
        expected_prefix = ["global"]
    else:
        expected_prefix = ["workspaces", cast(str, scope.workspace_id)]
    if (
        len(relative_parts) != len(expected_prefix) + 2
        or relative_parts[: len(expected_prefix)] != expected_prefix
        or len(artifact_parts) != 3
        or artifact_parts[2] != "compiled"
    ):
        raise _changed("installation_binding")
    namespace = artifact_parts[0]
    character_id, character_version = relative_parts[-2:]
    if artifact_parts[1] != character_id:
        raise _changed("installation_binding")
    _assert_safe_segment(namespace, "namespace")
    _assert_safe_segment(character_id, "character_id")
    installation_id = installation.get("installation_id")
    archive_sha256 = installation.get("archive_sha256")
    compiled_sha256 = installation.get("compiled_sha256")
    if (
        not isinstance(installation_id, str)
        or not installation_id
        or len(installation_id) > 256
        or not isinstance(character_version, str)
        or not character_version
        or len(character_version) > 64
        or not isinstance(archive_sha256, str)
        or _SHA256_PATTERN.fullmatch(archive_sha256) is None
        or not isinstance(compiled_sha256, str)
        or _SHA256_PATTERN.fullmatch(compiled_sha256) is None
    ):
        raise _changed("installation_binding")
    return {
        "installation_id": installation_id,
        "namespace": namespace,
        "character_id": character_id,
        "character_version": character_version,
        "archive_sha256": archive_sha256,
        "compiled_sha256": compiled_sha256,
    }


def _require_reference_lock(
    lock: PersistenceLock,
    scope: PersistenceScope,
) -> None:
    if (
        not lock.owns()
        or lock.scope.root != scope.root
        or lock.scope.key != scope.key
        or lock.path != scope.lock_path
    ):
        raise _path_unsafe("reference_lock")


def _scan_persistence_reference_blockers(
    scope: PersistenceScope,
    binding: dict[str, Any],
) -> set[str]:
    from kokoroarc.persistence import memory as memory_module
    from kokoroarc.persistence import state as state_module

    blockers: set[str] = set()
    consent_root = scope.character_root("consents")
    consent_layout = _retain_reference_layout(
        scope,
        consent_root,
        {"current.json": "file", "history": "directory"},
        "consent-layout",
    )
    current_consent = read_canonical_object(
        consent_root / "current.json",
        limit=scope.limits.max_consent_bytes,
        schema_name="persistence-consent",
        boundary=scope.boundary,
        optional=True,
    )
    if current_consent is None:
        if consent_layout is not None:
            raise _changed("current_consent_missing")
    else:
        consent_value = current_consent.value
        consent_binding = _stored_installation_binding(
            consent_value.get("installation")
        )
        if (
            consent_value.get("scope") != scope.key.scope
            or consent_value.get("workspace_id") != scope.key.workspace_id
            or consent_binding["namespace"] != scope.key.namespace
            or consent_binding["character_id"] != scope.key.character_id
        ):
            raise _changed("current_consent_scope")
        if (
            consent_value.get("status") == "active"
            and consent_binding == binding
        ):
            blockers.add("persistence_consent")

    state_root = scope.character_root("persistent-state")
    _retain_reference_layout(
        scope,
        state_root,
        {
            "current.json": "file",
            "generations": "directory",
            "resets": "directory",
        },
        "state-layout",
    )
    pointer = state_module._read_pointer(scope, optional=True)
    if pointer is not None:
        replayed = state_module._replay_generation(
            scope,
            cast(str, pointer.value["generation_id"]),
            allow_projection_mismatch=False,
        )
        relationship = replayed.state.get("relationship")
        mood = replayed.state.get("mood")
        retained = (
            isinstance(relationship, dict)
            and isinstance(relationship.get("revision"), int)
            and relationship["revision"] > 0
        ) or (
            isinstance(mood, dict)
            and isinstance(mood.get("revision"), int)
            and mood["revision"] > 0
        )
        if retained and replayed.state.get("installation") == binding:
            blockers.add("persistent_state")

    for snapshot in memory_module._scan_memory_references(scope):
        value = snapshot.value
        if all(value.get(field) == binding[field] for field in binding):
            blockers.add("memory_reference")

    _scan_migration_reference(scope, binding, blockers, state_module)
    scope.boundary.assert_clean()
    return blockers


def _scan_migration_reference(
    scope: PersistenceScope,
    binding: dict[str, Any],
    blockers: set[str],
    state_module: Any,
) -> None:
    marker_path = scope.transaction_path
    if _lstat(marker_path) is None:
        scope.boundary.audits[f"absent:{marker_path}"] = _absent_file_audit(
            marker_path
        )
        return
    marker = _snapshot_canonical_file(
        marker_path,
        scope.limits.max_transaction_bytes,
    )
    scope.boundary.audits[f"migration:{marker_path}"] = _file_audit(
        marker.path,
        marker.payload,
        marker.identity,
    )
    value = marker.value
    identity = value.get("target_directory_identity")
    target_installation = value.get("target_installation")
    if (
        set(value)
        != {
            "schema_version",
            "kind",
            "phase",
            "migration_id",
            "plan_sha256",
            "source_generation_id",
            "target_generation_id",
            "target_installation",
            "target_directory_identity",
        }
        or value.get("schema_version") != "1.0"
        or value.get("kind") != "state_migration"
        or value.get("phase") not in {"prepared", "committed"}
        or not isinstance(value.get("migration_id"), str)
        or _MIGRATION_ID_PATTERN.fullmatch(value["migration_id"]) is None
        or not isinstance(value.get("plan_sha256"), str)
        or _SHA256_PATTERN.fullmatch(value["plan_sha256"]) is None
        or not isinstance(value.get("source_generation_id"), str)
        or _GENERATION_PATTERN.fullmatch(value["source_generation_id"])
        is None
        or not isinstance(value.get("target_generation_id"), str)
        or _GENERATION_PATTERN.fullmatch(value["target_generation_id"])
        is None
        or value["source_generation_id"] == value["target_generation_id"]
        or (
            identity is not None
            and (
                not isinstance(identity, dict)
                or set(identity) != {"device", "inode", "file_type"}
                or any(
                    isinstance(item, bool)
                    or not isinstance(item, int)
                    or item < 0
                    for item in identity.values()
                )
            )
        )
        or (value["phase"] == "committed" and identity is None)
    ):
        raise _changed("migration_marker")
    target_binding = _stored_installation_binding(target_installation)
    if (
        target_binding["namespace"] != scope.key.namespace
        or target_binding["character_id"] != scope.key.character_id
    ):
        raise _changed("migration_target_binding")
    source = state_module._replay_generation(
        scope,
        cast(str, value["source_generation_id"]),
        allow_projection_mismatch=False,
    )
    if source.state.get("installation") == binding:
        blockers.add("state_migration")
    if target_binding == binding:
        blockers.add("state_migration")
    if identity is not None:
        target_root = state_module._generation_root(
            scope,
            cast(str, value["target_generation_id"]),
        )
        actual_identity = _capture_directory_identity(target_root)
        if (
            actual_identity.device != identity["device"]
            or actual_identity.inode != identity["inode"]
            or actual_identity.file_type != identity["file_type"]
        ):
            raise _changed("migration_target_identity")
        target = state_module._replay_generation(
            scope,
            cast(str, value["target_generation_id"]),
            allow_projection_mismatch=False,
        )
        if target.state.get("generation_id") != value["target_generation_id"]:
            raise _changed("migration_target")
        if target.state.get("installation") != target_binding:
            raise _changed("migration_target_binding")


def _stored_installation_binding(value: Any) -> dict[str, Any]:
    required = {
        "installation_id",
        "namespace",
        "character_id",
        "character_version",
        "archive_sha256",
        "compiled_sha256",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise _changed("installation_binding")
    installation_id = value.get("installation_id")
    namespace = value.get("namespace")
    character_id = value.get("character_id")
    character_version = value.get("character_version")
    archive_sha256 = value.get("archive_sha256")
    compiled_sha256 = value.get("compiled_sha256")
    if (
        not isinstance(installation_id, str)
        or not installation_id
        or len(installation_id) > 256
        or not isinstance(namespace, str)
        or not isinstance(character_id, str)
        or not isinstance(character_version, str)
        or not character_version
        or len(character_version) > 64
        or not isinstance(archive_sha256, str)
        or _SHA256_PATTERN.fullmatch(archive_sha256) is None
        or not isinstance(compiled_sha256, str)
        or _SHA256_PATTERN.fullmatch(compiled_sha256) is None
    ):
        raise _changed("installation_binding")
    _assert_safe_segment(namespace, "namespace")
    _assert_safe_segment(character_id, "character_id")
    return {
        "installation_id": installation_id,
        "namespace": namespace,
        "character_id": character_id,
        "character_version": character_version,
        "archive_sha256": archive_sha256,
        "compiled_sha256": compiled_sha256,
    }


def read_canonical_object(
    path: Path,
    *,
    limit: int,
    schema_name: str,
    boundary: PersistenceBoundary,
    optional: bool = False,
) -> ArtifactSnapshot | None:
    """Read one canonical, schema-valid, stable regular JSON object."""

    canonical_path = _absolute_path(path)
    captured = _read_regular_file(
        canonical_path,
        limit=limit,
        optional=optional,
    )
    if captured is None:
        boundary.audits[f"absent:{canonical_path}"] = _absent_file_audit(
            canonical_path
        )
        return None
    payload, identity = captured
    boundary.audits[f"file:{canonical_path}"] = _file_audit(
        canonical_path,
        payload,
        identity,
    )
    value = _decode_canonical_object(payload)
    boundary.validate(schema_name, payload)
    return ArtifactSnapshot(
        path=canonical_path,
        payload=payload,
        value=value,
        identity=identity,
    )


def scan_canonical_directory(
    path: Path,
    *,
    entry_limit: int,
    aggregate_limit: int,
    file_limit: int,
    schema_name: str,
    boundary: PersistenceBoundary,
) -> Sequence[ArtifactSnapshot]:
    """Return one stable sorted snapshot of a canonical JSON directory."""

    canonical_path = _absolute_path(path)
    snapshot = _capture_directory_snapshot(canonical_path, entry_limit)
    boundary.audits[f"directory:{canonical_path}"] = _directory_audit(snapshot)
    snapshots: list[ArtifactSnapshot] = []
    total = 0
    for name, _identity in snapshot.entries:
        item = read_canonical_object(
            canonical_path / name,
            limit=file_limit,
            schema_name=schema_name,
            boundary=boundary,
        )
        assert item is not None
        total += len(item.payload)
        if total > aggregate_limit:
            raise _limit_error("aggregate_bytes", aggregate_limit)
        snapshots.append(item)
    boundary.assert_clean()
    return tuple(snapshots)


def _capture_scope_boundary(
    root: Path,
    workspace_root: Path | None,
    schemas: SchemaValidator,
) -> PersistenceBoundary:
    boundary = PersistenceBoundary(schemas=schemas)
    root_stat = _lstat(root)
    if root_stat is None:
        boundary.audits["scope:root_absent"] = _absent_file_audit(root)
    else:
        _require_safe_directory(root, root_stat)
        root_chain = _capture_directory_chain(root)
        boundary.audits["scope:root"] = lambda: _assert_directory_chain(
            root_chain,
            "scope_root_changed",
        )
    if workspace_root is not None:
        workspace = Path(os.path.abspath(os.fspath(workspace_root)))
        workspace_chain = _capture_directory_chain(workspace)
        boundary.audits["scope:workspace"] = lambda: _assert_directory_chain(
            workspace_chain,
            "workspace_changed",
        )
    return boundary


def _read_regular_file(
    path: Path,
    *,
    limit: int,
    optional: bool,
) -> tuple[bytes, tuple[int, int, int, int, int, int]] | None:
    if limit < 0:
        raise _limit_error("file_bytes", limit)
    try:
        linked_before = path.lstat()
    except FileNotFoundError:
        if optional:
            return None
        raise _changed("missing_file") from None
    except OSError as error:
        raise _changed("inspect_file") from error
    _require_safe_regular_file(path, linked_before)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOINHERIT", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        opened_before = os.fstat(descriptor)
        if not _safe_opened_file(path, linked_before, opened_before):
            raise _path_unsafe("file_identity")
        payload = _read_bounded(descriptor, limit)
        opened_after = os.fstat(descriptor)
        linked_after = path.lstat()
        expected = _file_identity(linked_before)
        if (
            _file_identity(opened_before) != expected
            or _file_identity(opened_after) != expected
            or _file_identity(linked_after) != expected
            or len(payload) != expected[2]
            or not _safe_opened_file(path, linked_after, opened_after)
        ):
            raise _changed("file_changed")
        return payload, expected
    except KokoroError:
        raise
    except FileNotFoundError:
        raise _changed("file_changed") from None
    except OSError as error:
        raise _changed("read_file") from error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _read_bounded(descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    remaining = limit + 1
    while remaining > 0:
        chunk = os.read(descriptor, min(remaining, 64 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    payload = b"".join(chunks)
    if len(payload) > limit:
        raise _limit_error("file_bytes", limit)
    return payload


def _decode_canonical_object(payload: bytes) -> dict[str, Any]:
    try:
        text = payload.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise _changed("invalid_json") from error
    if not isinstance(value, dict):
        raise _changed("non_object_json")
    try:
        if canonical_bytes(value) != payload:
            raise _changed("noncanonical_json")
    except KokoroError as error:
        if error.code == "PERSISTENCE_CHANGED":
            raise
        raise _changed("invalid_json") from error
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> NoReturn:
    raise ValueError("non-finite JSON number")


def _bounded_regular_json_entries(path: Path, limit: int) -> tuple[Path, ...]:
    snapshot = _capture_directory_snapshot(path, limit)
    return tuple(path / name for name, _identity in snapshot.entries)


def _retain_reference_layout(
    scope: PersistenceScope,
    path: Path,
    allowed: Mapping[str, Literal["directory", "file"]],
    audit_name: str,
) -> _ReferenceLayoutSnapshot | None:
    canonical_path = _absolute_path(path)
    snapshot = _capture_reference_layout(canonical_path, allowed)
    if snapshot is None:
        scope.boundary.audits[f"layout:{audit_name}"] = _absent_file_audit(
            canonical_path
        )
        return None
    scope.boundary.audits[f"layout:{audit_name}"] = (
        lambda: _audit_reference_layout(snapshot)
    )
    return snapshot


def _capture_reference_layout(
    path: Path,
    allowed: Mapping[str, Literal["directory", "file"]],
) -> _ReferenceLayoutSnapshot | None:
    linked = _lstat(path)
    if linked is None:
        return None
    _require_safe_directory(path, linked)
    identity = _capture_directory_identity(path)
    allowed_items = tuple(sorted(allowed.items()))
    entries: list[Any] = []
    try:
        with os.scandir(path) as iterator:
            for entry in iterator:
                entries.append(entry)
                if len(entries) > len(allowed_items):
                    raise _path_unsafe("unexpected_reference_layout")
    except KokoroError:
        raise
    except OSError as error:
        raise _changed("scan_reference_layout") from error
    names = [entry.name for entry in entries]
    if len({name.casefold() for name in names}) != len(names):
        raise _path_unsafe("case_collision")
    if any(name not in allowed for name in names):
        raise _path_unsafe("unexpected_reference_layout")
    captured: list[tuple[str, tuple[int, int, int, int, int, int]]] = []
    for entry in entries:
        entry_path = path / entry.name
        try:
            entry_stat = entry_path.lstat()
        except OSError as error:
            raise _changed("reference_entry_changed") from error
        if allowed[entry.name] == "file":
            _require_safe_regular_file(entry_path, entry_stat)
        else:
            _require_safe_directory(entry_path, entry_stat)
        captured.append((entry.name, _file_identity(entry_stat)))
    if not _directory_identity_matches(identity):
        raise _changed("reference_layout_changed")
    return _ReferenceLayoutSnapshot(
        path=path,
        identity=identity,
        entries=tuple(sorted(captured)),
        allowed=allowed_items,
    )


def _audit_reference_layout(snapshot: _ReferenceLayoutSnapshot) -> None:
    current = _capture_reference_layout(
        snapshot.path,
        dict(snapshot.allowed),
    )
    if current != snapshot:
        raise _changed("reference_layout_changed")


def _capture_directory_snapshot(path: Path, limit: int) -> _DirectorySnapshot:
    if limit < 0:
        raise _limit_error("entry_count", limit)
    identity = _capture_directory_identity(path)
    entries: list[Any] = []
    try:
        with os.scandir(path) as iterator:
            for entry in iterator:
                entries.append(entry)
                if len(entries) > limit:
                    raise _limit_error("entry_count", limit)
    except KokoroError:
        raise
    except OSError as error:
        raise _changed("scan_directory") from error
    names = [entry.name for entry in entries]
    if len({name.casefold() for name in names}) != len(names):
        raise _path_unsafe("case_collision")
    if any(_JSON_NAME_PATTERN.fullmatch(name) is None for name in names):
        raise _path_unsafe("unsafe_entry_name")
    snapshots: list[tuple[str, tuple[int, int, int, int, int, int]]] = []
    for entry in entries:
        entry_path = path / entry.name
        try:
            # Python 3.14's Windows DirEntry stat may report st_nlink=0 even
            # for an ordinary file.  Re-stat the named node without following
            # redirects so hard-link and identity checks use authoritative
            # metadata on every supported platform.
            entry_stat = entry_path.lstat()
        except OSError as error:
            raise _changed("entry_changed") from error
        _require_safe_regular_file(entry_path, entry_stat)
        snapshots.append((entry.name, _file_identity(entry_stat)))
    if not _directory_identity_matches(identity):
        raise _changed("directory_changed")
    return _DirectorySnapshot(
        path=path,
        identity=identity,
        entries=tuple(sorted(snapshots, key=lambda item: item[0])),
        limit=limit,
    )


def _file_audit(
    path: Path,
    payload: bytes,
    identity: tuple[int, int, int, int, int, int],
) -> Callable[[], None]:
    def audit() -> None:
        try:
            captured = _read_regular_file(
                path,
                limit=len(payload),
                optional=False,
            )
        except KokoroError as error:
            if error.code == "PERSISTENCE_PATH_UNSAFE":
                raise
            raise _changed("file_changed") from error
        assert captured is not None
        current_payload, current_identity = captured
        if current_payload != payload or current_identity != identity:
            raise _changed("file_changed")

    return audit


def _directory_audit(snapshot: _DirectorySnapshot) -> Callable[[], None]:
    def audit() -> None:
        current = _capture_directory_snapshot(snapshot.path, snapshot.limit)
        if current != snapshot:
            raise _changed("directory_changed")

    return audit


def _absent_file_audit(path: Path) -> Callable[[], None]:
    ancestor = path
    missing: list[Path] = []
    while True:
        path_stat = _lstat(ancestor)
        if path_stat is not None:
            break
        missing.append(ancestor)
        if ancestor == ancestor.parent:
            raise _path_unsafe("missing_filesystem_root")
        ancestor = ancestor.parent
    _require_safe_directory(ancestor, path_stat)
    ancestry = _capture_directory_chain(ancestor)

    def audit() -> None:
        _assert_directory_chain(ancestry, "ancestor_changed")
        if any(_lstat(item) is not None for item in missing):
            raise _changed("absent_node_appeared")

    return audit


def _acquire_character_lock(scope: PersistenceScope) -> PersistenceLock:
    scope.boundary.authorize_root_creation()
    _create_secure_directories(scope.lock_path.parent)
    ancestry = _capture_directory_chain(scope.lock_path.parent)
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOINHERIT", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(scope.lock_path, flags, 0o600)
        linked = scope.lock_path.lstat()
        opened = os.fstat(descriptor)
        if not _safe_lock_stats(scope.lock_path, linked, opened):
            raise _path_unsafe("lock_unsafe")
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        if opened.st_size < 1:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.write(descriptor, b"\0") != 1:
                raise OSError(errno.EIO, "lock initialization failed")
            os.fsync(descriptor)
        try:
            _lock_descriptor(descriptor)
        except OSError as error:
            if _is_lock_contention(error):
                raise _locked() from error
            raise
        if (
            not _safe_lock_stats(
                scope.lock_path,
                scope.lock_path.lstat(),
                os.fstat(descriptor),
            )
            or not _directory_chain_matches(ancestry)
        ):
            raise _path_unsafe("lock_changed")
        lock = PersistenceLock(scope, scope.lock_path, descriptor, ancestry)
        descriptor = None
        return lock
    except KokoroError:
        raise
    except OSError as error:
        raise _write_failed("lock", _error_reason(error)) from error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _create_identified_staging(parent: Path, prefix: str) -> _IdentifiedStaging:
    _assert_safe_segment(prefix, "staging_prefix")
    parent = _absolute_path(parent)
    ancestry = _capture_directory_chain(parent)
    try:
        path = Path(tempfile.mkdtemp(prefix=f".{prefix}.staging-", dir=parent))
    except OSError as error:
        raise _write_failed("create_staging", _error_reason(error)) from error
    try:
        identity = _capture_directory_identity(path)
    except KokoroError as error:
        raise _cleanup_failed("staging_identity_unavailable") from error
    return _IdentifiedStaging(path, identity, ancestry)


def _cleanup_identified_staging(staging: _IdentifiedStaging) -> None:
    if (
        staging.path.parent != staging.ancestry[-1].path
        or not _directory_chain_matches(staging.ancestry)
        or not _directory_identity_matches(staging.identity)
    ):
        raise _cleanup_failed("staging_identity_changed")
    try:
        children = _bounded_cleanup_entries(staging.path, 32)
        for child in children:
            child_stat = child.lstat()
            _require_safe_regular_file(child, child_stat)
            if not _directory_identity_matches(staging.identity):
                raise _cleanup_failed("staging_identity_changed")
            child.unlink()
        if not _directory_identity_matches(staging.identity):
            raise _cleanup_failed("staging_identity_changed")
        staging.path.rmdir()
    except KokoroError:
        raise
    except OSError as error:
        raise _cleanup_failed(_error_reason(error)) from error


def _publish_new_file(
    scope: PersistenceScope,
    target: Path,
    payload: bytes,
    lock: PersistenceLock,
) -> ArtifactSnapshot:
    return _publish_file(scope, target, payload, lock, replace=False)


def _replace_file(
    scope: PersistenceScope,
    target: Path,
    payload: bytes,
    lock: PersistenceLock,
) -> ArtifactSnapshot:
    return _publish_file(scope, target, payload, lock, replace=True)


def _publish_file(
    scope: PersistenceScope,
    target: Path,
    payload: bytes,
    lock: PersistenceLock,
    *,
    replace: bool,
) -> ArtifactSnapshot:
    target = _absolute_path(target)
    _assert_target_within_scope(scope, target)
    _decode_canonical_object(payload)
    lock.assert_owned()
    _create_secure_directories(target.parent)
    parent_chain = _capture_directory_chain(target.parent)
    existing = _lstat(target)
    if existing is not None:
        _require_safe_regular_file(target, existing)
        if not replace:
            raise _write_failed("publish", "already_exists")
    descriptor: int | None = None
    staging_path: Path | None = None
    staging_identity: tuple[int, int, int, int, int, int] | None = None
    committed = False
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{target.name}.staging-",
            dir=target.parent,
        )
        staging_path = Path(raw_path)
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
        opened = os.fstat(descriptor)
        linked = staging_path.lstat()
        if not _safe_opened_file(staging_path, linked, opened):
            raise _path_unsafe("staging_file")
        staging_identity = _file_identity(linked)
        os.close(descriptor)
        descriptor = None
        lock.assert_owned()
        _assert_directory_chain(parent_chain, "publication_parent_changed")
        if replace:
            _atomic_replace(staging_path, target)
        else:
            _atomic_rename_noreplace(staging_path, target)
        committed = True
        staging_path = None
        snapshot = _snapshot_canonical_file(target, len(payload))
        if snapshot.payload != payload or snapshot.identity != staging_identity:
            raise _changed("published_file_changed")
        _fsync_directory(target.parent)
        lock.assert_owned()
        _assert_directory_chain(parent_chain, "publication_parent_changed")
        return snapshot
    except KokoroError:
        raise
    except FileExistsError as error:
        raise _write_failed("publish", "already_exists") from error
    except OSError as error:
        code = (
            "PERSISTENCE_DURABILITY_FAILED"
            if committed
            else "PERSISTENCE_WRITE_FAILED"
        )
        raise KokoroError(
            code,
            "Persistent storage publication failed.",
            details={
                "operation": "publish",
                "reason": _error_reason(error),
                "record_state": "committed" if committed else "not_visible",
            },
        ) from error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if staging_path is not None and staging_identity is not None:
            _cleanup_staged_file(staging_path, staging_identity, parent_chain)


def _write_transaction_marker(
    scope: PersistenceScope,
    payload: bytes,
    lock: PersistenceLock,
) -> ArtifactSnapshot:
    if len(payload) > scope.limits.max_transaction_bytes:
        raise _limit_error("transaction_bytes", scope.limits.max_transaction_bytes)
    _decode_canonical_object(payload)
    existing = _lstat(scope.transaction_path)
    if existing is not None:
        snapshot = _snapshot_canonical_file(
            scope.transaction_path,
            scope.limits.max_transaction_bytes,
        )
        if snapshot.payload == payload:
            return snapshot
        raise _write_failed("transaction", "already_exists")
    return _publish_new_file(scope, scope.transaction_path, payload, lock)


def _remove_transaction_marker(
    scope: PersistenceScope,
    snapshot: ArtifactSnapshot,
    lock: PersistenceLock,
) -> Literal["not_visible", "committed", "unknown"]:
    lock.assert_owned()
    if snapshot.path != scope.transaction_path:
        raise _path_unsafe("transaction_path")
    current = _snapshot_canonical_file(
        scope.transaction_path,
        scope.limits.max_transaction_bytes,
    )
    if current.payload != snapshot.payload or current.identity != snapshot.identity:
        raise _changed("transaction_changed")
    try:
        snapshot.path.unlink()
        _fsync_directory(snapshot.path.parent)
    except OSError as error:
        raise _cleanup_failed(
            _error_reason(error),
            record_state="unknown",
        ) from error
    if _lstat(snapshot.path) is not None:
        raise _cleanup_failed("transaction_visible", record_state="unknown")
    lock.assert_owned()
    return "not_visible"


def _snapshot_canonical_file(path: Path, limit: int) -> ArtifactSnapshot:
    captured = _read_regular_file(path, limit=limit, optional=False)
    assert captured is not None
    payload, identity = captured
    value = _decode_canonical_object(payload)
    return ArtifactSnapshot(path, payload, value, identity)


def _atomic_replace(staging: Path, target: Path) -> None:
    if staging.parent != target.parent:
        raise OSError(errno.EXDEV, "atomic replace requires one parent")
    os.replace(staging, target)


def _atomic_rename_noreplace(staging: Path, target: Path) -> None:
    if staging.parent != target.parent:
        raise OSError(errno.EXDEV, "atomic rename requires one parent")
    if os.name == "nt":
        os.rename(staging, target)
        return
    import ctypes

    library = ctypes.CDLL(None, use_errno=True)
    source = os.fsencode(staging.name)
    destination = os.fsencode(target.name)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(staging.parent, flags)
    try:
        if sys.platform.startswith("linux"):
            rename = getattr(library, "renameat2", None)
            rename_flag = 1
        elif sys.platform == "darwin":
            rename = getattr(library, "renameatx_np", None)
            rename_flag = 0x00000004
        else:
            rename = None
            rename_flag = 0
        if rename is None:
            raise OSError(errno.ENOTSUP, "atomic no-replace rename unavailable")
        rename.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename.restype = ctypes.c_int
        result = rename(
            descriptor,
            source,
            descriptor,
            destination,
            rename_flag,
        )
    finally:
        os.close(descriptor)
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError(error_number, os.strerror(error_number), target)
    raise OSError(error_number, os.strerror(error_number), target)


def _cleanup_staged_file(
    path: Path,
    identity: tuple[int, int, int, int, int, int],
    parent_chain: tuple[_DirectoryIdentity, ...],
) -> None:
    try:
        current = path.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise _cleanup_failed(_error_reason(error)) from error
    if (
        not _directory_chain_matches(parent_chain)
        or _file_identity(current) != identity
        or _is_redirect(path, current)
        or not stat.S_ISREG(current.st_mode)
        or current.st_nlink != 1
    ):
        raise _cleanup_failed("staging_identity_changed")
    try:
        path.unlink()
    except OSError as error:
        raise _cleanup_failed(_error_reason(error)) from error


def _bounded_cleanup_entries(path: Path, limit: int) -> tuple[Path, ...]:
    entries: list[Path] = []
    try:
        with os.scandir(path) as iterator:
            for entry in iterator:
                entries.append(path / entry.name)
                if len(entries) > limit:
                    raise _cleanup_failed("unexpected_layout")
    except KokoroError:
        raise
    except OSError as error:
        raise _cleanup_failed(_error_reason(error)) from error
    return tuple(sorted(entries, key=lambda item: item.name))


def _create_secure_directories(path: Path) -> tuple[Path, ...]:
    path = _absolute_path(path)
    missing: list[Path] = []
    current = path
    while _lstat(current) is None:
        missing.append(current)
        if current == current.parent:
            raise _path_unsafe("missing_filesystem_root")
        current = current.parent
    _capture_directory_chain(current)
    created: list[Path] = []
    for directory in reversed(missing):
        try:
            directory.mkdir()
            created.append(directory)
        except FileExistsError:
            pass
        except OSError as error:
            raise _write_failed("mkdir", _error_reason(error)) from error
        _require_safe_directory(directory)
        _fsync_directory(directory.parent)
    return tuple(created)


def _capture_directory_identity(path: Path) -> _DirectoryIdentity:
    path = _absolute_path(path)
    path_stat = _require_safe_directory(path)
    return _DirectoryIdentity(
        path=path,
        device=path_stat.st_dev,
        inode=path_stat.st_ino,
        file_type=stat.S_IFMT(path_stat.st_mode),
    )


def _capture_directory_chain(path: Path) -> tuple[_DirectoryIdentity, ...]:
    identities: list[_DirectoryIdentity] = []
    for component in reversed((path, *path.parents)):
        identities.append(_capture_directory_identity(component))
    return tuple(identities)


def _directory_identity_matches(identity: _DirectoryIdentity) -> bool:
    try:
        current = identity.path.lstat()
    except OSError:
        return False
    return (
        not _is_redirect(identity.path, current)
        and stat.S_ISDIR(current.st_mode)
        and current.st_dev == identity.device
        and current.st_ino == identity.inode
        and stat.S_IFMT(current.st_mode) == identity.file_type
    )


def _directory_chain_matches(
    identities: tuple[_DirectoryIdentity, ...],
) -> bool:
    return all(_directory_identity_matches(identity) for identity in identities)


def _assert_directory_chain(
    identities: tuple[_DirectoryIdentity, ...],
    reason: str,
) -> None:
    if not _directory_chain_matches(identities):
        raise _path_unsafe(reason)


def _require_safe_directory(
    path: Path,
    path_stat: os.stat_result | None = None,
) -> os.stat_result:
    try:
        current = path.lstat() if path_stat is None else path_stat
    except OSError as error:
        raise _path_unsafe("inspect_directory") from error
    if _is_redirect(path, current) or not stat.S_ISDIR(current.st_mode):
        raise _path_unsafe("unsafe_directory")
    return current


def _require_safe_regular_file(
    path: Path,
    path_stat: os.stat_result | None = None,
) -> os.stat_result:
    try:
        current = path.lstat() if path_stat is None else path_stat
    except OSError as error:
        raise _path_unsafe("inspect_file") from error
    if (
        _is_redirect(path, current)
        or not stat.S_ISREG(current.st_mode)
        or current.st_nlink != 1
        or (os.name != "nt" and current.st_mode & 0o111)
    ):
        raise _path_unsafe("unsafe_file")
    return current


def _safe_opened_file(
    path: Path,
    linked: os.stat_result,
    opened: os.stat_result,
) -> bool:
    return (
        not _is_redirect(path, linked)
        and stat.S_ISREG(linked.st_mode)
        and stat.S_ISREG(opened.st_mode)
        and linked.st_nlink == 1
        and opened.st_nlink == 1
        and (os.name == "nt" or not (linked.st_mode & 0o111))
        and os.path.samestat(linked, opened)
    )


def _safe_lock_stats(
    path: Path,
    linked: os.stat_result,
    opened: os.stat_result,
) -> bool:
    return (
        not _is_redirect(path, linked)
        and stat.S_ISREG(linked.st_mode)
        and stat.S_ISREG(opened.st_mode)
        and linked.st_nlink == 1
        and opened.st_nlink == 1
        and os.path.samestat(linked, opened)
    )


def _file_identity(
    path_stat: os.stat_result,
) -> tuple[int, int, int, int, int, int]:
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        path_stat.st_size,
        path_stat.st_mtime_ns,
        stat.S_IFMT(path_stat.st_mode),
        path_stat.st_nlink,
    )


def _is_redirect(path: Path, path_stat: os.stat_result) -> bool:
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    junction_probe = getattr(path, "is_junction", None)
    try:
        junction = bool(junction_probe()) if junction_probe is not None else False
    except OSError:
        return True
    return (
        stat.S_ISLNK(path_stat.st_mode)
        or junction
        or bool(attributes & reparse_flag)
    )


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise _path_unsafe("inspect_path") from error


def _absolute_path(path: Path) -> Path:
    try:
        return Path(os.path.abspath(os.fspath(path)))
    except (OSError, TypeError, ValueError) as error:
        raise _path_unsafe("path_cannot_be_canonicalized") from error


def _assert_safe_segment(value: Any, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or _SLUG_PATTERN.fullmatch(value) is None
        or value.split(".", 1)[0].lower() in _WINDOWS_RESERVED_DEVICE_BASENAMES
    ):
        raise _path_unsafe(f"unsafe_{field_name}")


def _assert_target_within_scope(scope: PersistenceScope, target: Path) -> None:
    if not target.is_relative_to(scope.root) or target == scope.root:
        raise _path_unsafe("target_outside_scope")


def _lock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_descriptor(descriptor: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError:
        pass


def _is_lock_contention(error: OSError) -> bool:
    return (
        error.errno in _LOCK_CONTENTION_ERRNOS
        or getattr(error, "winerror", None) in _LOCK_CONTENTION_WINERRORS
    )


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as error:
        if error.errno not in _DIRECTORY_FSYNC_UNSUPPORTED:
            raise _durability_failed("fsync_directory", _error_reason(error)) from error


def _error_reason(error: BaseException) -> str:
    if isinstance(error, KokoroError):
        return str(error.details.get("reason", error.code))
    return type(error).__name__


def _mutation_error(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_INPUT_MUTATION",
        "A persistence input changed during the operation.",
        details={"reason": reason},
    )


def _path_unsafe(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_PATH_UNSAFE",
        "Persistent storage path is unsafe.",
        details={"reason": reason},
    )


def _limit_error(reason: str, limit: int) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_LIMIT_EXCEEDED",
        "Persistent storage limit was exceeded.",
        details={"reason": reason, "limit": limit},
    )


def _changed(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_CHANGED",
        "Persistent storage changed or is invalid.",
        details={"reason": reason},
    )


def _locked() -> KokoroError:
    return KokoroError(
        "PERSISTENCE_LOCKED",
        "Persistent storage is busy.",
        details={"reason": "lock_contended"},
    )


def _write_failed(operation: str, reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_WRITE_FAILED",
        "Persistent storage write failed.",
        details={
            "operation": operation,
            "reason": reason,
            "record_state": "not_visible",
        },
    )


def _durability_failed(operation: str, reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_DURABILITY_FAILED",
        "Persistent storage durability confirmation failed.",
        details={"operation": operation, "reason": reason},
    )


def _cleanup_failed(
    reason: str,
    *,
    record_state: Literal["not_visible", "committed", "unknown"] = "not_visible",
) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_CLEANUP_FAILED",
        "Persistent storage cleanup failed.",
        details={"reason": reason, "record_state": record_state},
    )
