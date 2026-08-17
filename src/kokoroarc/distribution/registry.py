"""Canonical scoped registries for installed ``.karc`` character packs."""

from __future__ import annotations

from dataclasses import dataclass
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import tempfile
import time
from typing import Any, Callable, Literal, Protocol, cast

from kokoroarc import __version__
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes


_MAX_REGISTRY_BYTES = 2 * 1024 * 1024
_LOCK_RETRY_DELAYS = (0.0, 0.01, 0.02, 0.04, 0.08)
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


class _SchemaValidator(Protocol):
    def validate(self, name: str, instance: Any) -> None: ...


class _RegistryBoundarySchemas:
    def __init__(
        self,
        delegate: _SchemaValidator,
        audit: Callable[[], None],
    ) -> None:
        self._delegate = delegate
        self._audit = audit
        self._violation: KokoroError | None = None

    def validate(self, name: str, instance: Any) -> None:
        try:
            self._delegate.validate(name, instance)
        finally:
            try:
                self._audit()
            except KokoroError as error:
                if self._violation is None:
                    self._violation = error
                raise

    def raise_if_failed(self) -> None:
        if self._violation is not None:
            raise self._violation


@dataclass(frozen=True, slots=True)
class InstallScope:
    """One global or explicitly derived workspace installation scope."""

    kind: Literal["global", "workspace"]
    workspace_id: str | None
    installed_relative_root: str
    registry_relative_path: str


@dataclass(frozen=True, slots=True)
class _DirectoryIdentity:
    path: Path
    device: int
    inode: int
    file_type: int


@dataclass(frozen=True, slots=True)
class _RegistryReadBoundary:
    root: Path
    root_existed: bool
    ancestry: tuple[_DirectoryIdentity, ...]
    path: Path
    payload: bytes | None
    file_identity: tuple[int, int, int] | None


@dataclass(frozen=True, slots=True)
class _WorkspaceReadBoundary:
    path: Path
    ancestry: tuple[_DirectoryIdentity, ...]
    canonical_path: str


@dataclass(frozen=True, slots=True)
class _RegistryWriteBoundary:
    lock: _RegistryLock
    path: Path
    payload: bytes | None
    file_identity: tuple[int, int, int] | None


@dataclass(slots=True)
class _RegistryLock:
    root: Path
    scope: InstallScope
    path: Path
    descriptor: int
    ancestors: tuple[_DirectoryIdentity, ...]
    held: bool = True

    def __enter__(self) -> _RegistryLock:
        return self

    def __exit__(
        self,
        _exception_type: object,
        _exception: object,
        _traceback: object,
    ) -> None:
        self.release()

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

    def owns(self) -> bool:
        if not self.held or not _directory_chain_matches(self.ancestors):
            return False
        try:
            linked = self.path.lstat()
            opened = os.fstat(self.descriptor)
        except OSError:
            return False
        return (
            stat.S_ISREG(linked.st_mode)
            and not _is_redirect(self.path, linked)
            and _lock_identity(linked) == _lock_identity(opened)
        )


def resolve_install_scope(workspace_root: Path | None = None) -> InstallScope:
    """Return global scope, or hash one explicit canonical workspace root."""

    if workspace_root is None:
        return InstallScope(
            kind="global",
            workspace_id=None,
            installed_relative_root="global",
            registry_relative_path="registry/global.json",
        )
    try:
        supplied = Path(os.path.abspath(os.fspath(workspace_root)))
        supplied_stat = supplied.lstat()
    except (OSError, TypeError, ValueError) as error:
        raise _error(
            "KARC_SCOPE_INVALID",
            "Workspace scope requires an existing directory.",
        ) from error
    if not stat.S_ISDIR(supplied_stat.st_mode) or _is_redirect(supplied, supplied_stat):
        raise _error(
            "KARC_SCOPE_INVALID",
            "Workspace scope requires a regular non-link directory.",
        )
    try:
        canonical = supplied.resolve(strict=True)
    except OSError as error:
        raise _error(
            "KARC_SCOPE_INVALID",
            "Workspace scope could not be canonicalized.",
        ) from error
    normalized = os.path.normcase(str(canonical))
    workspace_id = sha256(normalized.encode("utf-8")).hexdigest()
    return InstallScope(
        kind="workspace",
        workspace_id=workspace_id,
        installed_relative_root=f"workspaces/{workspace_id}",
        registry_relative_path=f"registry/workspaces/{workspace_id}.json",
    )


def empty_installed_registry(scope: InstallScope) -> dict[str, Any]:
    """Return the schema-valid revision-zero registry for one scope."""

    artifact_id = (
        "registry/global/installed-packs"
        if scope.kind == "global"
        else f"registry/workspaces/{scope.workspace_id[:8]}/installed-packs"
    )
    return {
        "schema_version": "1.0",
        "artifact_id": artifact_id,
        "created_by": {"component": "kokoroarc", "version": __version__},
        "scope": scope.kind,
        "workspace_id": scope.workspace_id,
        "revision": 0,
        "entries": {},
    }


def load_installed_registry(
    data_root: Path,
    schemas: _SchemaValidator,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """Read one canonical registry without creating storage."""

    scope = resolve_install_scope(workspace_root)
    workspace_boundary = _capture_workspace_read_boundary(
        workspace_root,
        scope,
    )
    root = _absolute_path(data_root)
    path = root.joinpath(*scope.registry_relative_path.split("/"))
    payload, file_identity = _read_optional_regular_file_snapshot(path)
    boundary = _capture_registry_read_boundary(
        root,
        path,
        payload,
        file_identity,
    )
    if payload is None:
        registry = empty_installed_registry(scope)
    else:
        registry = _parse_registry(payload)
    _validate_registry(registry, scope, schemas)
    _require_workspace_read_boundary(workspace_boundary)
    _require_registry_read_boundary(boundary)
    return _detached(registry)


def list_installed_packs(
    data_root: Path,
    schemas: _SchemaValidator,
    *,
    workspace_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Return detached entries ordered by registry identity."""

    registry = load_installed_registry(
        data_root,
        schemas,
        workspace_root=workspace_root,
    )
    return [
        {"registry_identity": identity, **_detached(entry)}
        for identity, entry in sorted(registry["entries"].items())
    ]


def write_installed_registry_cas(
    data_root: Path,
    scope: InstallScope,
    expected_revision: int,
    expected_sha256: str | None,
    registry: dict[str, Any],
    schemas: _SchemaValidator,
) -> None:
    """Publish one exact next revision under a bounded scope lock."""

    root = _absolute_path(data_root)
    with _acquire_registry_lock(root, scope) as lock:
        path = _registry_path(root, scope)
        payload, file_identity = _read_optional_regular_file_snapshot(path)
        boundary = _RegistryWriteBoundary(
            lock=lock,
            path=path,
            payload=payload,
            file_identity=file_identity,
        )
        audited = _RegistryBoundarySchemas(
            schemas,
            lambda: _require_registry_write_boundary(boundary),
        )
        try:
            _write_installed_registry_cas_locked(
                lock,
                expected_revision,
                expected_sha256,
                registry,
                audited,
            )
        except Exception:
            audited.raise_if_failed()
            raise
        _require_registry_write_boundary(boundary, published=True)


def _write_installed_registry_cas_locked(
    lock: _RegistryLock,
    expected_revision: int,
    expected_sha256: str | None,
    registry: dict[str, Any],
    schemas: _SchemaValidator,
    *,
    failure_hook: Callable[[str], None] | None = None,
) -> None:
    current, current_sha256 = _registry_state(lock.root, lock.scope, schemas)
    if (
        current.get("revision") != expected_revision
        or current_sha256 != expected_sha256
    ):
        raise _error(
            "KARC_REGISTRY_CONFLICT",
            "Installed registry no longer matches the expected revision.",
        )
    try:
        candidate_payload = canonical_bytes(registry)
        candidate = cast(dict[str, Any], json.loads(candidate_payload))
    except (KokoroError, TypeError, ValueError) as error:
        raise _error(
            "KARC_REGISTRY_INVALID",
            "Replacement registry is not canonical JSON data.",
        ) from error
    _validate_registry(candidate, lock.scope, schemas)
    if canonical_bytes(registry) != candidate_payload:
        raise _error(
            "KARC_REGISTRY_CHANGED",
            "Replacement registry changed during validation.",
        )
    if candidate.get("revision") != expected_revision + 1:
        raise _error(
            "KARC_REGISTRY_CONFLICT",
            "Replacement registry revision is not the exact successor.",
        )
    repeated, repeated_sha256 = _registry_state(lock.root, lock.scope, schemas)
    if repeated != current or repeated_sha256 != current_sha256 or not lock.owns():
        raise _error(
            "KARC_REGISTRY_CONFLICT",
            "Installed registry changed before publication.",
        )
    path = _registry_path(lock.root, lock.scope)
    descriptor = -1
    staging: Path | None = None
    staging_identity: tuple[int, int, int, int, int] | None = None
    staging_node_identity: tuple[int, int, int] | None = None
    try:
        descriptor, raw_staging = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        staging = Path(raw_staging)
        staging_node_identity = _lock_identity(os.fstat(descriptor))
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(candidate_payload)
            handle.flush()
            os.fsync(handle.fileno())
            staging_identity = _file_identity(os.fstat(handle.fileno()))
        if failure_hook is not None:
            failure_hook("registry_staged")
        try:
            staged_payload = _read_optional_regular_file(staging)
            staged_stat = staging.lstat()
        except (KokoroError, OSError) as error:
            raise _error(
                "KARC_REGISTRY_CHANGED",
                "Registry staging changed before publication.",
            ) from error
        if (
            staged_payload != candidate_payload
            or _file_identity(staged_stat) != staging_identity
        ):
            raise _error(
                "KARC_REGISTRY_CHANGED",
                "Registry staging changed before publication.",
            )
        final, final_sha256 = _registry_state(lock.root, lock.scope, schemas)
        if final != current or final_sha256 != current_sha256 or not lock.owns():
            raise _error(
                "KARC_REGISTRY_CONFLICT",
                "Installed registry changed before atomic publication.",
            )
        if current_sha256 is None:
            os.link(staging, path)
            staging.unlink()
            staging = None
        else:
            os.replace(staging, path)
            staging = None
        _fsync_directory(path.parent)
        if _read_optional_regular_file(path) != candidate_payload:
            raise _error(
                "KARC_REGISTRY_CHANGED",
                "Published registry bytes could not be confirmed.",
            )
        if failure_hook is not None:
            failure_hook("registry_published")
    except FileExistsError as error:
        raise _error(
            "KARC_REGISTRY_CONFLICT",
            "Installed registry appeared before publication.",
        ) from error
    except KokoroError:
        raise
    except OSError as error:
        raise _error(
            "KARC_REGISTRY_WRITE_FAILED",
            "Installed registry could not be published atomically.",
            reason=type(error).__name__,
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if staging is not None:
            _remove_registry_staging(staging, staging_node_identity)


def _remove_registry_staging(
    path: Path,
    expected: tuple[int, int, int] | None,
) -> None:
    try:
        current = path.lstat()
    except FileNotFoundError as error:
        raise _error(
            "KARC_INSTALL_CLEANUP_FAILED",
            "Registry staging cleanup could not confirm the generated node.",
            phase="registry_staging",
            reason="missing",
        ) from error
    except OSError as error:
        raise _error(
            "KARC_INSTALL_CLEANUP_FAILED",
            "Registry staging cleanup could not inspect the generated node.",
            phase="registry_staging",
            reason=type(error).__name__,
        ) from error
    if (
        expected is None
        or not stat.S_ISREG(current.st_mode)
        or _is_redirect(path, current)
        or _lock_identity(current) != expected
    ):
        raise _error(
            "KARC_INSTALL_CLEANUP_FAILED",
            "Registry staging cleanup refused an unverified node.",
            phase="registry_staging",
            reason="identity_changed",
        )
    try:
        path.unlink()
    except OSError as error:
        raise _error(
            "KARC_INSTALL_CLEANUP_FAILED",
            "Registry staging cleanup could not remove the generated node.",
            phase="registry_staging",
            reason=type(error).__name__,
        ) from error


def _acquire_registry_lock(
    data_root: Path,
    scope: InstallScope,
) -> _RegistryLock:
    root = _absolute_path(data_root)
    parent = _ensure_registry_parent(root, scope)
    lock_name = (
        ".global.lock"
        if scope.kind == "global"
        else f".{scope.workspace_id}.lock"
    )
    path = parent / lock_name
    ancestors = _capture_directory_chain(parent)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags, 0o600)
        linked = path.lstat()
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(linked.st_mode)
            or _is_redirect(path, linked)
            or _lock_identity(linked) != _lock_identity(opened)
        ):
            raise _error(
                "KARC_REGISTRY_PATH_INVALID",
                "Registry lock is not a stable regular file.",
            )
        if opened.st_size == 0:
            os.write(descriptor, b"0")
            os.fsync(descriptor)
        for attempt, delay in enumerate((*_LOCK_RETRY_DELAYS, None)):
            try:
                _lock_descriptor(descriptor)
                break
            except OSError as error:
                if not _is_lock_contention(error) or delay is None:
                    if _is_lock_contention(error):
                        raise _error(
                            "KARC_REGISTRY_LOCKED",
                            "Installed registry scope is locked.",
                        ) from error
                    raise
                time.sleep(delay)
        if not _directory_chain_matches(ancestors):
            raise _error(
                "KARC_REGISTRY_PATH_INVALID",
                "Registry lock ancestry changed during acquisition.",
            )
        return _RegistryLock(root, scope, path, descriptor, ancestors)
    except KokoroError:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise
    except OSError as error:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise _error(
            "KARC_REGISTRY_LOCK_FAILED",
            "Installed registry lock could not be acquired.",
            reason=type(error).__name__,
        ) from error


def _absolute_path(path: Path) -> Path:
    try:
        return Path(os.path.abspath(os.fspath(path)))
    except (OSError, TypeError, ValueError) as error:
        raise _error(
            "KARC_REGISTRY_PATH_INVALID",
            "Registry path is invalid.",
        ) from error


def _registry_path(root: Path, scope: InstallScope) -> Path:
    return root.joinpath(*scope.registry_relative_path.split("/"))


def _registry_state(
    root: Path,
    scope: InstallScope,
    schemas: _SchemaValidator,
) -> tuple[dict[str, Any], str | None]:
    payload = _read_optional_regular_file(_registry_path(root, scope))
    registry = (
        empty_installed_registry(scope)
        if payload is None
        else _parse_registry(payload)
    )
    _validate_registry(registry, scope, schemas)
    return _detached(registry), None if payload is None else sha256(payload).hexdigest()


def _ensure_registry_parent(root: Path, scope: InstallScope) -> Path:
    _require_safe_existing_chain(root.parent)
    _ensure_directory(root)
    registry_root = root / "registry"
    _ensure_directory(registry_root)
    if scope.kind == "global":
        return registry_root
    workspaces = registry_root / "workspaces"
    _ensure_directory(workspaces)
    return workspaces


def _require_safe_existing_chain(path: Path) -> None:
    for directory in reversed((path, *path.parents)):
        try:
            directory_stat = directory.lstat()
        except OSError as error:
            raise _error(
                "KARC_REGISTRY_PATH_INVALID",
                "Registry ancestry must already exist.",
            ) from error
        if not stat.S_ISDIR(directory_stat.st_mode) or _is_redirect(
            directory, directory_stat
        ):
            raise _error(
                "KARC_REGISTRY_PATH_INVALID",
                "Registry ancestry must contain regular directories.",
            )


def _ensure_directory(path: Path) -> None:
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        try:
            os.mkdir(path, 0o700)
            _fsync_directory(path.parent)
            path_stat = path.lstat()
        except OSError as error:
            raise _error(
                "KARC_REGISTRY_PATH_INVALID",
                "Registry directory could not be created safely.",
            ) from error
    except OSError as error:
        raise _error(
            "KARC_REGISTRY_PATH_INVALID",
            "Registry directory could not be inspected.",
        ) from error
    if not stat.S_ISDIR(path_stat.st_mode) or _is_redirect(path, path_stat):
        raise _error(
            "KARC_REGISTRY_PATH_INVALID",
            "Registry path must contain regular directories.",
        )


def _capture_directory_chain(path: Path) -> tuple[_DirectoryIdentity, ...]:
    result: list[_DirectoryIdentity] = []
    for directory in reversed((path, *path.parents)):
        try:
            directory_stat = directory.lstat()
        except OSError as error:
            raise _error(
                "KARC_REGISTRY_PATH_INVALID",
                "Registry directory identity could not be captured.",
            ) from error
        if not stat.S_ISDIR(directory_stat.st_mode) or _is_redirect(
            directory, directory_stat
        ):
            raise _error(
                "KARC_REGISTRY_PATH_INVALID",
                "Registry path must contain regular directories.",
            )
        result.append(
            _DirectoryIdentity(
                path=directory,
                device=int(directory_stat.st_dev),
                inode=int(directory_stat.st_ino),
                file_type=stat.S_IFMT(directory_stat.st_mode),
            )
        )
    return tuple(result)


def _directory_chain_matches(chain: tuple[_DirectoryIdentity, ...]) -> bool:
    for identity in chain:
        try:
            current = identity.path.lstat()
        except OSError:
            return False
        if (
            not stat.S_ISDIR(current.st_mode)
            or _is_redirect(identity.path, current)
            or int(current.st_dev) != identity.device
            or int(current.st_ino) != identity.inode
            or stat.S_IFMT(current.st_mode) != identity.file_type
        ):
            return False
    return True


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


def _lock_identity(value: os.stat_result) -> tuple[int, int, int]:
    return (int(value.st_dev), int(value.st_ino), stat.S_IFMT(value.st_mode))


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
            raise


def _capture_workspace_read_boundary(
    workspace_root: Path | None,
    scope: InstallScope,
) -> _WorkspaceReadBoundary | None:
    if workspace_root is None:
        return None
    try:
        path = Path(os.path.abspath(os.fspath(workspace_root)))
        canonical_path = os.path.normcase(str(path.resolve(strict=True)))
    except (OSError, TypeError, ValueError) as error:
        raise _error(
            "KARC_SCOPE_CHANGED",
            "Workspace scope changed before registry validation.",
        ) from error
    if sha256(canonical_path.encode("utf-8")).hexdigest() != scope.workspace_id:
        raise _error(
            "KARC_SCOPE_CHANGED",
            "Workspace scope changed before registry validation.",
        )
    return _WorkspaceReadBoundary(
        path=path,
        ancestry=_capture_directory_chain(path),
        canonical_path=canonical_path,
    )


def _require_workspace_read_boundary(
    boundary: _WorkspaceReadBoundary | None,
) -> None:
    if boundary is None:
        return
    try:
        canonical_path = os.path.normcase(
            str(boundary.path.resolve(strict=True))
        )
    except OSError as error:
        raise _error(
            "KARC_SCOPE_CHANGED",
            "Workspace scope changed during registry validation.",
        ) from error
    if (
        canonical_path != boundary.canonical_path
        or not _directory_chain_matches(boundary.ancestry)
    ):
        raise _error(
            "KARC_SCOPE_CHANGED",
            "Workspace scope changed during registry validation.",
        )


def _require_registry_write_boundary(
    boundary: _RegistryWriteBoundary,
    *,
    published: bool = False,
) -> None:
    if not boundary.lock.owns():
        raise _error(
            "KARC_REGISTRY_CONFLICT",
            "Registry lock changed during validation.",
        )
    if published:
        return
    try:
        payload, file_identity = _read_optional_regular_file_snapshot(
            boundary.path
        )
    except KokoroError as error:
        raise _error(
            "KARC_REGISTRY_CONFLICT",
            "Installed registry changed during validation.",
        ) from error
    if (
        payload != boundary.payload
        or file_identity != boundary.file_identity
    ):
        raise _error(
            "KARC_REGISTRY_CONFLICT",
            "Installed registry changed during validation.",
        )


def _capture_registry_read_boundary(
    root: Path,
    path: Path,
    payload: bytes | None,
    file_identity: tuple[int, int, int] | None,
) -> _RegistryReadBoundary:
    try:
        root_stat = root.lstat()
    except FileNotFoundError:
        root_existed = False
        anchor = root.parent
        while True:
            try:
                anchor_stat = anchor.lstat()
                break
            except FileNotFoundError:
                if anchor == anchor.parent:
                    raise _error(
                        "KARC_REGISTRY_PATH_INVALID",
                        "Registry ancestry has no existing directory.",
                    )
                anchor = anchor.parent
            except OSError as error:
                raise _error(
                    "KARC_REGISTRY_PATH_INVALID",
                    "Registry ancestry could not be inspected.",
                ) from error
        if not stat.S_ISDIR(anchor_stat.st_mode) or _is_redirect(
            anchor,
            anchor_stat,
        ):
            raise _error(
                "KARC_REGISTRY_PATH_INVALID",
                "Registry ancestry must contain regular directories.",
            )
    except OSError as error:
        raise _error(
            "KARC_REGISTRY_PATH_INVALID",
            "Registry data root could not be inspected.",
        ) from error
    else:
        root_existed = True
        if not stat.S_ISDIR(root_stat.st_mode) or _is_redirect(root, root_stat):
            raise _error(
                "KARC_REGISTRY_PATH_INVALID",
                "Registry data root must be a regular directory.",
            )
        anchor = root
    return _RegistryReadBoundary(
        root=root,
        root_existed=root_existed,
        ancestry=_capture_directory_chain(anchor),
        path=path,
        payload=payload,
        file_identity=file_identity,
    )


def _require_registry_read_boundary(boundary: _RegistryReadBoundary) -> None:
    try:
        root_stat = boundary.root.lstat()
    except FileNotFoundError:
        root_exists = False
    except OSError as error:
        raise _error(
            "KARC_REGISTRY_CHANGED",
            "Registry data root changed during validation.",
        ) from error
    else:
        root_exists = True
        if not stat.S_ISDIR(root_stat.st_mode) or _is_redirect(
            boundary.root,
            root_stat,
        ):
            raise _error(
                "KARC_REGISTRY_CHANGED",
                "Registry data root changed during validation.",
            )
    if (
        root_exists != boundary.root_existed
        or not _directory_chain_matches(boundary.ancestry)
    ):
        raise _error(
            "KARC_REGISTRY_CHANGED",
            "Registry data root changed during validation.",
        )
    try:
        payload, file_identity = _read_optional_regular_file_snapshot(
            boundary.path
        )
    except KokoroError as error:
        raise _error(
            "KARC_REGISTRY_CHANGED",
            "Installed registry changed during validation.",
        ) from error
    if (
        payload != boundary.payload
        or file_identity != boundary.file_identity
    ):
        raise _error(
            "KARC_REGISTRY_CHANGED",
            "Installed registry changed during validation.",
        )


def _read_optional_regular_file(path: Path) -> bytes | None:
    return _read_optional_regular_file_snapshot(path)[0]


def _read_optional_regular_file_snapshot(
    path: Path,
) -> tuple[bytes | None, tuple[int, int, int] | None]:
    try:
        linked = path.lstat()
    except FileNotFoundError:
        return None, None
    except OSError as error:
        raise _error(
            "KARC_REGISTRY_INVALID",
            "Installed registry could not be inspected.",
        ) from error
    if (
        not stat.S_ISREG(linked.st_mode)
        or _is_redirect(path, linked)
        or int(linked.st_nlink) != 1
    ):
        raise _error(
            "KARC_REGISTRY_INVALID",
            "Installed registry must be a regular non-link file.",
        )
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            payload = handle.read(_MAX_REGISTRY_BYTES + 1)
            after = os.fstat(handle.fileno())
        final = path.lstat()
    except OSError as error:
        raise _error(
            "KARC_REGISTRY_INVALID",
            "Installed registry could not be read.",
        ) from error
    if len(payload) > _MAX_REGISTRY_BYTES:
        raise _error(
            "KARC_REGISTRY_LIMIT_EXCEEDED",
            "Installed registry exceeds the byte limit.",
        )
    identities = tuple(
        _file_identity(value) for value in (linked, opened, after, final)
    )
    if (
        len(set(identities)) != 1
        or any(
            int(value.st_nlink) != 1
            for value in (linked, opened, after, final)
        )
    ):
        raise _error(
            "KARC_REGISTRY_CHANGED",
            "Installed registry changed while it was read.",
        )
    return payload, _lock_identity(linked)


def _parse_registry(payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise _error(
            "KARC_REGISTRY_INVALID",
            "Installed registry is not strict JSON.",
        ) from error
    if not isinstance(value, dict):
        raise _error(
            "KARC_REGISTRY_INVALID",
            "Installed registry must contain an object.",
        )
    try:
        if canonical_bytes(value) != payload:
            raise _error(
                "KARC_REGISTRY_INVALID",
                "Installed registry is not canonical JSON.",
            )
    except KokoroError:
        raise
    return cast(dict[str, Any], value)


def _validate_registry(
    registry: dict[str, Any],
    scope: InstallScope,
    schemas: _SchemaValidator,
) -> None:
    entries = registry.get("entries")
    if isinstance(entries, dict) and len(entries) > 1_024:
        raise _error(
            "KARC_REGISTRY_LIMIT_EXCEEDED",
            "Installed registry contains too many entries.",
        )
    payload = canonical_bytes(registry)
    probe = json.loads(payload)
    try:
        schemas.validate("installed-pack-registry", probe)
    except Exception as error:
        raise _error(
            "KARC_REGISTRY_INVALID",
            "Installed registry failed schema validation.",
            reason=_reason(error),
        ) from error
    if canonical_bytes(probe) != payload:
        raise _error(
            "KARC_REGISTRY_CHANGED",
            "Registry schema validation mutated its detached input.",
        )
    expected = empty_installed_registry(scope)
    if any(
        registry.get(name) != expected[name]
        for name in ("artifact_id", "scope", "workspace_id")
    ):
        raise _error(
            "KARC_REGISTRY_SCOPE_MISMATCH",
            "Installed registry does not match the selected scope.",
        )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        stat.S_IFMT(value.st_mode),
        int(value.st_size),
        int(value.st_mtime_ns),
    )


def _is_redirect(path: Path, path_stat: os.stat_result) -> bool:
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    probe = getattr(path, "is_junction", None)
    if probe is None:
        return False
    try:
        return bool(probe())
    except OSError as error:
        raise _error(
            "KARC_REGISTRY_PATH_INVALID",
            "Registry path redirection could not be inspected.",
        ) from error


def _detached(value: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(canonical_bytes(value)))


def _reason(error: BaseException) -> str:
    return error.code if isinstance(error, KokoroError) else type(error).__name__


def _error(code: str, message: str, **details: Any) -> KokoroError:
    return KokoroError(code, message, details=details)


__all__ = [
    "InstallScope",
    "empty_installed_registry",
    "list_installed_packs",
    "load_installed_registry",
    "resolve_install_scope",
    "write_installed_registry_cas",
]
