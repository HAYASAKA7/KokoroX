"""Confined, transactional publication of private Research Bundles."""

from __future__ import annotations

from dataclasses import dataclass
import errno
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import tempfile
import time
from typing import Any

from kokoroarc.config import resolve_schema_dir
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.research.bundles import build_research_bundle, canonical_hash
from kokoroarc.research.validation import validate_research_workspace
from kokoroarc.research.workspace import ResearchWorkspace, load_research_workspace
from kokoroarc.schemas import SchemaRegistry


_PUBLISHED_FILES = {
    "bundle.json": "research-bundle",
    "request.json": "research-request",
    "validation-report.json": "research-validation-report",
}
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
_REPLACE_RETRY_DELAYS = (0.0, 0.001, 0.002, 0.004)
_CLEANUP_RETRY_DELAYS = (0.0, 0.001, 0.002, 0.004)
_TRANSIENT_REPLACE_WINERRORS = frozenset({5, 32})
_BACKUP_TOKEN_PATTERN = re.compile(r"[a-f0-9]{24}\Z")
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


@dataclass(slots=True)
class _PublicationLock:
    target: Path
    path: Path
    descriptor: int
    ancestor_chain: tuple[_DirectoryIdentity, ...]
    held: bool = True

    def __enter__(self) -> _PublicationLock:
        return self

    def __exit__(self, *_exception: object) -> None:
        self.release()

    def release(self) -> None:
        if not self.held:
            return
        try:
            _unlock_descriptor(self.descriptor)
        finally:
            try:
                os.close(self.descriptor)
            finally:
                self.held = False

    def owns(self, target: Path) -> bool:
        if not self.held or target != self.target:
            return False
        try:
            linked = self.path.lstat()
            opened = os.fstat(self.descriptor)
        except OSError:
            return False
        lock_matches = _safe_lock_stats(self.path, linked, opened)
        ancestors_match = _lock_ancestor_chain_matches(self.ancestor_chain)
        return lock_matches and ancestors_match


@dataclass(frozen=True, slots=True)
class _FileIdentity:
    device: int
    inode: int
    size: int
    modified_ns: int


@dataclass(frozen=True, slots=True)
class _DirectoryIdentity:
    path: Path
    device: int
    inode: int
    file_type: int


def load_published_research_bundle(
    path: Path,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    """Load one explicit, complete published bundle without following redirects."""
    root = Path(os.path.abspath(path))
    try:
        _validate_existing_chain(root)
        root_before = root.lstat()
        _require_safe_directory(root, root_before)
        entries = sorted(item.name for item in root.iterdir())
        expected_names = sorted((*_PUBLISHED_FILES, "workspace.json"))
        if entries != expected_names:
            raise _bundle_invalid("layout")
        root_identity = _file_identity(root_before)
        initial_layout = _published_layout_snapshot(root, expected_names)
        documents = {
            name: _read_published_document(root, root / name)
            for name in expected_names
        }
        request = documents["request.json"]
        report = documents["validation-report.json"]
        workspace = documents["workspace.json"]
        bundle = documents["bundle.json"]
        for name, schema_name in _PUBLISHED_FILES.items():
            schemas.validate(schema_name, documents[name])
        _verify_loaded_documents(request, workspace, report, bundle)
        root_after = root.lstat()
        if (
            not os.path.samestat(root_before, root_after)
            or _file_identity(root_after) != root_identity
        ):
            raise _bundle_invalid("directory_changed")
        if sorted(item.name for item in root.iterdir()) != expected_names:
            raise _bundle_invalid("layout_changed")
        if _published_layout_snapshot(root, expected_names) != initial_layout:
            raise _bundle_invalid("file_changed")
        return bundle
    except KokoroError as error:
        if error.code == "RESEARCH_BUNDLE_INVALID":
            raise
        raise _bundle_invalid("validation") from error
    except (OSError, ValueError):
        raise _bundle_invalid("path") from None


def _verify_loaded_documents(
    request: dict[str, Any],
    workspace: dict[str, Any],
    report: dict[str, Any],
    bundle: dict[str, Any],
) -> None:
    if set(workspace) != {"request", "sources", "claims", "conflicts", "coverage"}:
        raise _bundle_invalid("workspace_fields")
    if canonical_bytes(workspace["request"]) != canonical_bytes(request):
        raise _bundle_invalid("request_binding")
    bindings = {
        "request_hash": canonical_hash(request),
        "workspace_hash": canonical_hash(workspace),
        "validation_report_hash": canonical_hash(report),
    }
    if any(bundle.get(name) != value for name, value in bindings.items()):
        raise _bundle_invalid("hash_binding")
    for name in ("sources", "claims", "conflicts", "coverage"):
        if canonical_bytes(bundle.get(name)) != canonical_bytes(workspace[name]):
            raise _bundle_invalid("workspace_binding")
    request_bindings = (
        "namespace",
        "character_id",
        "display_name",
        "continuity",
        "timeline_cutoff",
        "spoiler_scope",
    )
    if any(bundle.get(name) != request.get(name) for name in request_bindings):
        raise _bundle_invalid("request_identity")
    if bundle.get("authoring_allowed") != report.get("authoring_allowed"):
        raise _bundle_invalid("report_binding")
    if bundle.get("blocking_reasons") != report.get("blocking_reasons"):
        raise _bundle_invalid("report_binding")
    unhashed = dict(bundle)
    bundle_hash = unhashed.pop("bundle_hash", None)
    if bundle_hash != canonical_hash(unhashed):
        raise _bundle_invalid("bundle_hash")


def _published_layout_snapshot(
    root: Path,
    names: list[str],
) -> dict[str, _FileIdentity]:
    snapshot: dict[str, _FileIdentity] = {}
    for name in names:
        path = root / name
        path_stat = path.lstat()
        if (
            _is_redirect(path, path_stat)
            or not stat.S_ISREG(path_stat.st_mode)
            or path_stat.st_nlink != 1
        ):
            raise _bundle_invalid("unsafe_file")
        snapshot[name] = _file_identity(path_stat)
    return snapshot


def _read_published_document(root: Path, path: Path) -> dict[str, Any]:
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or _is_redirect(path, before)
        ):
            raise _bundle_invalid("unsafe_file")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or not os.path.samestat(before, opened)
            ):
                raise _bundle_invalid("file_changed")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after_open = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = path.lstat()
        if (
            not os.path.samestat(before, after_open)
            or not os.path.samestat(before, after)
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            raise _bundle_invalid("file_changed")
        if path.parent != root:
            raise _bundle_invalid("path")
        contents = b"".join(chunks)
        value = json.loads(
            contents.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        if not isinstance(value, dict) or contents != canonical_bytes(value) + b"\n":
            raise _bundle_invalid("canonical_json")
        return value
    except KokoroError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise _bundle_invalid("file") from None


def _unique_object(items: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, member in items:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = member
    return value


def publish_research_bundle(
    data_root: Path,
    source_root: Path,
    workspace: ResearchWorkspace,
    report: dict[str, Any],
    bundle: dict[str, Any],
) -> Path:
    """Publish a validated bundle beneath the private ``research`` root."""
    schemas = SchemaRegistry(resolve_schema_dir())
    _require_bundle_inputs(source_root, workspace, report, bundle, schemas)
    root = Path(os.path.abspath(data_root))
    final = root / "research" / Path(*bundle["artifact_id"].split("/"))
    _validate_existing_chain(root)
    created_directories = _create_secure_directories(final.parent)
    _validate_existing_chain(final.parent)
    with _acquire_publication_lock(final) as publication_lock:
        if _lstat(final) is None:
            _fsync_first_publication_directories(
                root,
                final.parent,
                created_directories,
            )
        return _publish_staged(
            final,
            source_root,
            workspace,
            report,
            bundle,
            schemas,
            publication_lock,
        )


def _require_bundle_inputs(
    source_root: Path,
    workspace: ResearchWorkspace,
    report: dict[str, Any],
    bundle: dict[str, Any],
    schemas: SchemaRegistry,
) -> None:
    schemas.validate("research-request", workspace.request)
    schemas.validate("research-validation-report", report)
    schemas.validate("research-bundle", bundle)
    reloaded = load_research_workspace(source_root, schemas)
    if reloaded.workspace_hash != workspace.workspace_hash:
        raise _storage_error("RESEARCH_WORKSPACE_CHANGED", "workspace_hash")
    expected_report = validate_research_workspace(reloaded, schemas)
    if canonical_bytes(expected_report) != canonical_bytes(report):
        raise _storage_error("RESEARCH_REPORT_MISMATCH", "report")
    if report["valid"] is not True or report["hard_failures"]:
        raise _storage_error("RESEARCH_VALIDATION_FAILED", "hard_failures")
    expected_bundle = build_research_bundle(reloaded, expected_report)
    if canonical_bytes(expected_bundle) != canonical_bytes(bundle):
        raise _storage_error("RESEARCH_BUNDLE_MISMATCH", "bundle")


def _workspace_summary(workspace: ResearchWorkspace) -> dict[str, Any]:
    return {
        "request": workspace.request,
        "sources": list(workspace.sources),
        "claims": list(workspace.claims),
        "conflicts": list(workspace.conflicts),
        "coverage": workspace.coverage,
    }


def _publish_staged(
    final: Path,
    source_root: Path,
    workspace: ResearchWorkspace,
    report: dict[str, Any],
    bundle: dict[str, Any],
    schemas: SchemaRegistry,
    publication_lock: _PublicationLock,
) -> Path:
    current = _lstat(final)
    if current is not None:
        _require_safe_directory(final, current)
    staging: Path | None = None
    try:
        try:
            staging = Path(
                tempfile.mkdtemp(prefix=f".{final.name}.staging-", dir=final.parent)
            )
        except OSError as error:
            raise _publish_failed("create_staging", error) from error
        _require_safe_directory(staging, staging.lstat())
        documents = {
            "bundle.json": bundle,
            "request.json": workspace.request,
            "validation-report.json": report,
            "workspace.json": _workspace_summary(workspace),
        }
        for name, value in documents.items():
            _write_canonical_file(staging / name, value)
        staged_identities = _verify_staged(
            staging, workspace, report, bundle, schemas
        )
        try:
            _fsync_directory(staging)
        except OSError as error:
            raise _publish_failed("fsync_staging", error) from error
        _verify_staged(
            staging,
            workspace,
            report,
            bundle,
            schemas,
            expected_identities=staged_identities,
        )
        _require_source_unchanged(source_root, workspace, schemas)
        if not publication_lock.owns(final):
            raise _storage_error("UNSAFE_RESEARCH_PATH", "publication_lock_changed")
        backup = _replace_directory(staging, final)
        staging = None
        try:
            _fsync_directory(final.parent)
        except KokoroError as error:
            raise _durability_failure(final, backup, error) from error
        if backup is not None:
            _cleanup_tree_best_effort(backup)
        _reap_stale_backups(final, publication_lock)
        return final
    except KokoroError:
        raise
    except OSError as error:
        raise _publish_failed("write", error) from error
    finally:
        if staging is not None:
            _remove_staging(staging)


def _require_source_unchanged(
    source_root: Path,
    workspace: ResearchWorkspace,
    schemas: SchemaRegistry,
) -> None:
    try:
        reloaded = load_research_workspace(source_root, schemas)
    except KokoroError:
        raise _storage_error("RESEARCH_WORKSPACE_CHANGED", "source") from None
    if reloaded.workspace_hash != workspace.workspace_hash:
        raise _storage_error("RESEARCH_WORKSPACE_CHANGED", "workspace_hash")


def _verify_staged(
    staging: Path,
    workspace: ResearchWorkspace,
    report: dict[str, Any],
    bundle: dict[str, Any],
    schemas: SchemaRegistry,
    *,
    expected_identities: dict[str, _FileIdentity] | None = None,
) -> dict[str, _FileIdentity]:
    expected = {
        "bundle.json": bundle,
        "request.json": workspace.request,
        "validation-report.json": report,
        "workspace.json": _workspace_summary(workspace),
    }
    if {path.name for path in staging.iterdir()} != set(expected):
        raise _storage_error("RESEARCH_STAGING_INVALID", "layout")
    identities: dict[str, _FileIdentity] = {}
    staged_documents: dict[str, dict[str, Any]] = {}
    for name, value in expected.items():
        path = staging / name
        payload, identity = _read_staged_regular_file(path)
        if (
            expected_identities is not None
            and expected_identities.get(name) != identity
        ):
            raise _storage_error("RESEARCH_STAGING_INVALID", "file_identity")
        if payload != canonical_bytes(value) + b"\n":
            raise _storage_error("RESEARCH_STAGING_INVALID", "content")
        identities[name] = identity
        try:
            document = json.loads(
                payload.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise _storage_error("RESEARCH_STAGING_INVALID", "json") from None
        if not isinstance(document, dict):
            raise _storage_error("RESEARCH_STAGING_INVALID", "json")
        staged_documents[name] = document
    try:
        for name, schema_name in _PUBLISHED_FILES.items():
            schemas.validate(schema_name, staged_documents[name])
    except KokoroError:
        raise _storage_error("RESEARCH_STAGING_INVALID", "schema") from None
    hash_bindings = {
        "request_hash": canonical_hash(workspace.request),
        "workspace_hash": canonical_hash(_workspace_summary(workspace)),
        "validation_report_hash": canonical_hash(report),
    }
    if any(bundle.get(name) != value for name, value in hash_bindings.items()):
        raise _storage_error("RESEARCH_STAGING_INVALID", "hash_binding")
    if (
        bundle.get("authoring_allowed") != report.get("authoring_allowed")
        or bundle.get("blocking_reasons") != report.get("blocking_reasons")
    ):
        raise _storage_error("RESEARCH_STAGING_INVALID", "report_binding")
    unhashed = dict(bundle)
    actual_hash = unhashed.pop("bundle_hash")
    if canonical_hash(unhashed) != actual_hash:
        raise _storage_error("RESEARCH_BUNDLE_MISMATCH", "bundle_hash")
    return identities


def _read_staged_regular_file(path: Path) -> tuple[bytes, _FileIdentity]:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        initial = path.lstat()
        if (
            _is_redirect(path, initial)
            or not stat.S_ISREG(initial.st_mode)
            or initial.st_nlink != 1
        ):
            raise _storage_error("RESEARCH_STAGING_INVALID", "unsafe_file")
        identity = _file_identity(initial)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if _file_identity(opened) != identity or opened.st_nlink != 1:
                raise _storage_error("RESEARCH_STAGING_INVALID", "file_identity")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            final_opened = os.fstat(descriptor)
            if _file_identity(final_opened) != identity or final_opened.st_nlink != 1:
                raise _storage_error("RESEARCH_STAGING_INVALID", "file_identity")
        finally:
            os.close(descriptor)
        final = path.lstat()
        if (
            _is_redirect(path, final)
            or _file_identity(final) != identity
            or final.st_nlink != 1
        ):
            raise _storage_error("RESEARCH_STAGING_INVALID", "file_identity")
        return b"".join(chunks), identity
    except KokoroError:
        raise
    except OSError:
        raise _storage_error("RESEARCH_STAGING_INVALID", "read") from None


def _file_identity(path_stat: os.stat_result) -> _FileIdentity:
    return _FileIdentity(
        device=path_stat.st_dev,
        inode=path_stat.st_ino,
        size=path_stat.st_size,
        modified_ns=path_stat.st_mtime_ns,
    )


def _write_canonical_file(path: Path, value: Any) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, 0o600)
    try:
        contents = canonical_bytes(value) + b"\n"
        offset = 0
        while offset < len(contents):
            offset += os.write(descriptor, contents[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _replace_directory(staging: Path, final: Path) -> Path | None:
    try:
        if _lstat(final) is None:
            _replace_with_retries(staging, final)
            return None
        backup = final.parent / f".{final.name}.backup-{secrets.token_hex(12)}"
        _replace_with_retries(final, backup)
        try:
            _replace_with_retries(staging, final)
        except BaseException:
            try:
                _replace_with_retries(backup, final)
            except OSError as rollback_error:
                raise KokoroError(
                    "RESEARCH_RECOVERY_REQUIRED",
                    "Research publication retained a recoverable previous bundle.",
                    details={"recovery_path": str(backup)},
                ) from rollback_error
            raise
        return backup
    except KokoroError:
        raise
    except OSError as error:
        raise _publish_failed("replace", error) from error


def _replace_with_retries(source: Path, target: Path) -> None:
    attempts = len(_REPLACE_RETRY_DELAYS) + 1
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError as error:
            if not _transient_replace_error(error) or attempt == attempts - 1:
                raise
            time.sleep(_REPLACE_RETRY_DELAYS[attempt])


def _transient_replace_error(error: PermissionError) -> bool:
    return (
        os.name == "nt"
        and getattr(error, "winerror", None) in _TRANSIENT_REPLACE_WINERRORS
    )


def _durability_failure(
    final: Path,
    backup: Path | None,
    error: KokoroError,
) -> KokoroError:
    details: dict[str, Any] = {
        "operation": "fsync_parent",
        "reason": str(error.details.get("reason", error.code)),
    }
    if backup is not None:
        failed = final.parent / f".{final.name}.failed-{secrets.token_hex(12)}"
        try:
            _replace_with_retries(final, failed)
            try:
                _replace_with_retries(backup, final)
            except OSError:
                try:
                    _replace_with_retries(failed, final)
                except OSError:
                    pass
                details["recovery_path"] = str(backup)
            else:
                shutil.rmtree(failed, ignore_errors=True)
        except OSError:
            details["recovery_path"] = str(backup)
    return KokoroError(
        "RESEARCH_DURABILITY_FAILED",
        "Research bundle publication could not be made durable.",
        details=details,
    )


def _acquire_publication_lock(target: Path) -> _PublicationLock:
    path = target.parent / f".{target.name}.publish.lock"
    ancestor_chain = _capture_lock_ancestor_chain(target.parent)
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
        descriptor = os.open(path, flags, 0o600)
        linked = path.lstat()
        opened = os.fstat(descriptor)
        if not _safe_lock_stats(path, linked, opened):
            raise _storage_error("UNSAFE_RESEARCH_PATH", "publication_lock")
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        if os.name == "nt" and opened.st_size < 1:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.write(descriptor, b"\0") != 1:
                raise OSError(errno.EIO, "lock initialization failed")
            os.fsync(descriptor)
        try:
            _lock_descriptor(descriptor)
        except OSError as error:
            if _is_lock_contention(error):
                raise _publication_busy() from error
            raise
        linked = path.lstat()
        opened = os.fstat(descriptor)
        if not _safe_lock_stats(path, linked, opened):
            raise _storage_error("UNSAFE_RESEARCH_PATH", "publication_lock_changed")
        if not _lock_ancestor_chain_matches(ancestor_chain):
            raise _storage_error("UNSAFE_RESEARCH_PATH", "publication_lock_changed")
        lock = _PublicationLock(target, path, descriptor, ancestor_chain)
        descriptor = None
        return lock
    except KokoroError:
        raise
    except OSError as error:
        raise _publish_failed("lock", error) from error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


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


def _capture_lock_ancestor_chain(path: Path) -> tuple[_DirectoryIdentity, ...]:
    identities: list[_DirectoryIdentity] = []
    try:
        for component in reversed((path, *path.parents)):
            component_stat = component.lstat()
            if not _safe_lock_parent(component, component_stat):
                raise _storage_error(
                    "UNSAFE_RESEARCH_PATH", "publication_lock_ancestor"
                )
            identities.append(
                _DirectoryIdentity(
                    path=component,
                    device=component_stat.st_dev,
                    inode=component_stat.st_ino,
                    file_type=stat.S_IFMT(component_stat.st_mode),
                )
            )
    except KokoroError:
        raise
    except OSError as error:
        raise _publish_failed("inspect_lock_ancestor", error) from error
    return tuple(identities)


def _safe_lock_parent(path: Path, path_stat: os.stat_result) -> bool:
    return not _is_redirect(path, path_stat) and stat.S_ISDIR(path_stat.st_mode)


def _lock_ancestor_chain_matches(
    identities: tuple[_DirectoryIdentity, ...],
) -> bool:
    matches = True
    for identity in identities:
        try:
            path_stat = identity.path.lstat()
        except OSError:
            matches = False
            continue
        if (
            not _safe_lock_parent(identity.path, path_stat)
            or path_stat.st_dev != identity.device
            or path_stat.st_ino != identity.inode
            or stat.S_IFMT(path_stat.st_mode) != identity.file_type
        ):
            matches = False
    return matches


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


def _publication_busy() -> KokoroError:
    return KokoroError(
        "RESEARCH_PUBLISH_BUSY",
        "Research bundle publication is already in progress.",
        retryable=True,
        details={"reason": "target_locked"},
    )


def _reap_stale_backups(final: Path, publication_lock: _PublicationLock) -> None:
    if not publication_lock.owns(final):
        raise RuntimeError("stale backup reaping requires the publication lock")
    final_stat = _lstat(final)
    if final_stat is None:
        return
    try:
        _require_safe_directory(final, final_stat)
        entries = list(os.scandir(final.parent))
    except (KokoroError, OSError):
        return
    prefix = f".{final.name}.backup-"
    for entry in entries:
        candidate = Path(entry.path)
        token = (
            candidate.name[len(prefix) :]
            if candidate.name.startswith(prefix)
            else ""
        )
        if (
            candidate.parent == final.parent
            and _BACKUP_TOKEN_PATTERN.fullmatch(token) is not None
        ):
            _cleanup_tree_best_effort(candidate)


def _cleanup_tree_best_effort(path: Path) -> bool:
    if not _tree_is_redirect_free(path):
        return False
    attempts = len(_CLEANUP_RETRY_DELAYS) + 1
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            if attempt == attempts - 1:
                return False
            time.sleep(_CLEANUP_RETRY_DELAYS[attempt])
    return False


def _remove_staging(staging: Path) -> None:
    attempts = len(_CLEANUP_RETRY_DELAYS) + 1
    for attempt in range(attempts):
        try:
            _remove_staged_entry_no_follow(staging)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == attempts - 1:
                return
            time.sleep(_CLEANUP_RETRY_DELAYS[attempt])


def _remove_staged_entry_no_follow(path: Path) -> None:
    path_stat = path.lstat()
    if _is_redirect(path, path_stat):
        try:
            path.unlink()
        except (IsADirectoryError, PermissionError):
            path.rmdir()
        return
    if stat.S_ISDIR(path_stat.st_mode):
        with os.scandir(path) as entries:
            children = [Path(entry.path) for entry in entries]
        for child in children:
            _remove_staged_entry_no_follow(child)
        path.rmdir()
        return
    path.unlink()


def _tree_is_redirect_free(root: Path) -> bool:
    try:
        root_stat = root.lstat()
        if _is_redirect(root, root_stat) or not stat.S_ISDIR(root_stat.st_mode):
            return False
        pending = [root]
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    path_stat = path.stat(follow_symlinks=False)
                    if _is_redirect(path, path_stat):
                        return False
                    if stat.S_ISDIR(path_stat.st_mode):
                        pending.append(path)
                    elif not stat.S_ISREG(path_stat.st_mode):
                        return False
    except OSError:
        return False
    return True


def _create_secure_directories(path: Path) -> tuple[Path, ...]:
    missing: list[Path] = []
    current = path
    while _lstat(current) is None:
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    if _lstat(current) is not None:
        _require_safe_directory(current, current.lstat())
    created: list[Path] = []
    for directory in reversed(missing):
        try:
            directory.mkdir()
        except FileExistsError:
            pass
        _require_safe_directory(directory, directory.lstat())
        created.append(directory)
    return tuple(created)


def _fsync_first_publication_directories(
    root: Path,
    target_parent: Path,
    created_directories: tuple[Path, ...],
) -> None:
    directories = [root]
    current = root
    for part in target_parent.relative_to(root).parts:
        current /= part
        directories.append(current)
    directory_set = set(directories)
    if any(path not in directory_set for path in created_directories):
        raise _storage_error("UNSAFE_RESEARCH_PATH", "created_directory_escape")
    for directory in directories:
        _fsync_directory(directory)
        _fsync_directory(directory.parent)


def _validate_existing_chain(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        path_stat = _lstat(current)
        if path_stat is None:
            break
        _require_safe_directory(current, path_stat)


def _require_safe_directory(path: Path, path_stat: os.stat_result) -> None:
    if not stat.S_ISDIR(path_stat.st_mode) or _is_redirect(path, path_stat):
        raise _storage_error("UNSAFE_RESEARCH_PATH", "redirect")


def _is_redirect(path: Path, path_stat: os.stat_result) -> bool:
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    junction = getattr(path, "is_junction", None)
    return (
        stat.S_ISLNK(path_stat.st_mode)
        or bool(attributes & reparse)
        or bool(junction and junction())
    )


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as error:
        if error.errno not in _DIRECTORY_FSYNC_UNSUPPORTED:
            raise _publish_failed("fsync_directory", error) from error


def _storage_error(code: str, reason: str) -> KokoroError:
    return KokoroError(
        code,
        "Research bundle publication failed.",
        details={"reason": reason},
    )


def _publish_failed(operation: str, error: OSError) -> KokoroError:
    return KokoroError(
        "RESEARCH_PUBLISH_FAILED",
        "Research bundle publication failed.",
        details={"operation": operation, "reason": type(error).__name__},
    )


def _bundle_invalid(reason: str) -> KokoroError:
    return KokoroError(
        "RESEARCH_BUNDLE_INVALID",
        "Published Research Bundle validation failed.",
        details={"reason": reason},
    )
