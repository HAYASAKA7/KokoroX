"""Safe, transactional publication of private character draft bundles."""

from __future__ import annotations

import errno
from hashlib import sha256
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import tempfile
import time
from dataclasses import dataclass
from typing import Any

from kokoroarc import __version__
from kokoroarc.authoring.validation import validate_authoring_pack
from kokoroarc.config import resolve_schema_dir
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.packs.loader import load_source_pack
from kokoroarc.packs.security import PackLimits, scan_pack
from kokoroarc.schemas import SchemaRegistry


_SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_HASH_PATTERN = re.compile(r"[a-f0-9]{64}\Z")
_SOURCE_HASH_ID_PREFIX_LENGTH = 16
_REPLACE_RETRY_DELAYS = (0.0, 0.001, 0.002, 0.004)
_CLEANUP_RETRY_DELAYS = (0.0, 0.001, 0.002, 0.004)
_TRANSIENT_REPLACE_WINERRORS = frozenset({5, 32})
_BACKUP_TOKEN_PATTERN = re.compile(r"[a-f0-9]{24}\Z")
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
_BUNDLE_REFERENCES = {
    "request": "request.json",
    "source_pack": "source-pack",
    "validation_report": "validation-report.json",
}
_DRAFT_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_id",
        "created_by",
        "build_status",
        "visibility",
        "activation_allowed",
        "mode",
        "namespace",
        "character_id",
        "display_name",
        "character_version",
        "request_hash",
        "source_pack_hash",
        "validation_report_hash",
        "bundle_references",
        "locale_coverage",
        "provenance_counts",
        "unresolved_warnings",
    }
)
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


@dataclass(frozen=True, slots=True)
class _SourceIdentity:
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


@dataclass(slots=True)
class _PublicationLock:
    target: Path
    path: Path
    descriptor: int
    ancestor_chain: tuple[_DirectoryIdentity, ...]
    held: bool = True

    def __enter__(self) -> _PublicationLock:
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
            _unlock_publication_descriptor(self.descriptor)
        finally:
            try:
                os.close(self.descriptor)
            except OSError:
                pass
            finally:
                self.held = False

    def owns(self, target: Path) -> bool:
        if not self.held or target != self.target:
            return False
        try:
            linked_stat = self.path.lstat()
            opened_stat = os.fstat(self.descriptor)
        except OSError:
            lock_matches = False
        else:
            lock_matches = _safe_lock_stats(self.path, linked_stat, opened_stat)
        ancestors_match = _lock_ancestor_chain_matches(self.ancestor_chain)
        return lock_matches and ancestors_match


def publish_draft_bundle(
    data_root: Path,
    source_root: Path,
    request: dict[str, Any],
    draft: dict[str, Any],
    report: dict[str, Any],
    research_bundle: dict[str, Any] | None = None,
) -> Path:
    """Publish one complete draft beneath ``data_root/drafts``.

    The source directory is treated as inert data. It is pre-scanned with the
    hardened pack scanner, and only the scanned regular files are copied.
    Existing directories are replaced transactionally using same-parent atomic
    renames and rollback because replacing a non-empty directory in one syscall
    is not portable to Windows.
    """
    schemas = SchemaRegistry(resolve_schema_dir())
    schemas.validate("character-build-request", request)
    schemas.validate("build-validation-report", report)
    schemas.validate("character-draft", draft)
    _validate_publish_inputs(request, draft, report)

    root = _absolute_without_resolution(data_root)
    final = root / "drafts" / Path(*draft["artifact_id"].split("/"))
    _validate_existing_chain(root)
    if _destination_lstat(final.parent) is None:
        _preflight_validate_source(
            source_root,
            request,
            draft,
            report,
            schemas,
            research_bundle,
        )
        _validate_existing_chain(root)
    created_directories = _create_secure_directories(final.parent)
    with _acquire_publication_lock(final) as publication_lock:
        if _destination_lstat(final) is None:
            _fsync_first_publication_directories(
                root,
                final.parent,
                created_directories,
            )
        return _publish_draft_bundle_locked(
            source_root,
            request,
            draft,
            report,
            schemas,
            final,
            publication_lock,
            research_bundle,
        )


def _preflight_validate_source(
    source_root: Path,
    request: dict[str, Any],
    draft: dict[str, Any],
    report: dict[str, Any],
    schemas: SchemaRegistry,
    research_bundle: dict[str, Any] | None = None,
) -> None:
    scanned_files = scan_pack(source_root, PackLimits())
    resolved_source = _resolved_source_root(source_root)
    recorded = {
        path: _source_identity(path, path.relative_to(resolved_source))
        for path in scanned_files
    }
    recorded_hashes = {
        path: _hash_regular_file(
            path,
            recorded[path],
            path.relative_to(resolved_source),
        )
        for path in scanned_files
    }
    assembled_source = load_source_pack(source_root, schemas)
    _require_source_hash(assembled_source, draft["source_pack_hash"])
    _require_validation_report(
        request,
        assembled_source,
        report,
        schemas,
        research_bundle,
    )
    _revalidate_sources(
        source_root,
        resolved_source,
        scanned_files,
        recorded,
        recorded_hashes,
    )


def _publish_draft_bundle_locked(
    source_root: Path,
    request: dict[str, Any],
    draft: dict[str, Any],
    report: dict[str, Any],
    schemas: SchemaRegistry,
    final: Path,
    publication_lock: _PublicationLock,
    research_bundle: dict[str, Any] | None = None,
) -> Path:
    scanned_files = scan_pack(source_root, PackLimits())
    resolved_source = _resolved_source_root(source_root)
    recorded = {
        path: _source_identity(path, path.relative_to(resolved_source))
        for path in scanned_files
    }
    recorded_hashes = {
        path: _hash_regular_file(
            path,
            recorded[path],
            path.relative_to(resolved_source),
        )
        for path in scanned_files
    }
    assembled_source = load_source_pack(source_root, schemas)
    _require_source_hash(assembled_source, draft["source_pack_hash"])
    _require_validation_report(
        request,
        assembled_source,
        report,
        schemas,
        research_bundle,
    )
    _revalidate_sources(
        source_root,
        resolved_source,
        scanned_files,
        recorded,
        recorded_hashes,
    )

    final_stat = _destination_lstat(final)
    if final_stat is not None:
        _validate_destination_component(final)
        if not stat.S_ISDIR(final_stat.st_mode):
            raise _unsafe_draft_path(final, "target is not a directory")

    staging: Path | None = None
    try:
        try:
            staging = Path(
                tempfile.mkdtemp(
                    prefix=f".{final.name}.staging-",
                    dir=final.parent,
                )
            )
        except OSError as error:
            raise _publish_failed("create_staging", error) from error
        _validate_destination_component(staging)
        source_destination = staging / _BUNDLE_REFERENCES["source_pack"]
        source_destination.mkdir()
        copied_hashes: dict[Path, str] = {}
        for source_path in scanned_files:
            relative = source_path.relative_to(resolved_source)
            destination = source_destination.joinpath(*relative.parts)
            _create_staging_parent(source_destination, destination.parent)
            copied_hash = _copy_scanned_file(
                source_path, destination, recorded[source_path], relative
            )
            if copied_hash != recorded_hashes[source_path]:
                raise _source_changed(relative, "content")
            copied_hashes[source_path] = copied_hash

        _write_canonical_file(staging / "request.json", request)
        _write_canonical_file(staging / "validation-report.json", report)
        _write_canonical_file(staging / "draft.json", draft)
        _revalidate_sources(
            source_root,
            resolved_source,
            scanned_files,
            recorded,
            copied_hashes,
        )
        try:
            post_copy_source = load_source_pack(source_root, schemas)
        except KokoroError as error:
            raise _source_changed(Path("."), error.code) from error
        if _canonical_hash(post_copy_source) != draft["source_pack_hash"]:
            raise _source_changed(Path("."), "assembled_source")
        _require_validation_report(
            request,
            post_copy_source,
            report,
            schemas,
            research_bundle,
        )
        _revalidate_sources(
            source_root,
            resolved_source,
            scanned_files,
            recorded,
            copied_hashes,
        )
        expected_source_hashes = {
            path.relative_to(resolved_source): copied_hashes[path]
            for path in scanned_files
        }
        _validate_existing_chain(final.parent)
        final_stat = _destination_lstat(final)
        if final_stat is not None:
            _validate_destination_component(final)
            if not stat.S_ISDIR(final_stat.st_mode):
                raise _unsafe_draft_path(final, "target is not a directory")
        _fsync_tree_directories(staging)
        _verify_staged_bundle(
            staging,
            expected_source_hashes,
            request,
            report,
            draft,
        )
        if not publication_lock.owns(final):
            raise _unsafe_draft_path(final.parent, "publication lock ancestor changed")
        backup = _transactional_replace_directory(staging, final)
        try:
            _fsync_directory(final.parent)
        except KokoroError as error:
            raise _durability_failure(final, backup, error) from error
        if backup is not None:
            _cleanup_tree_best_effort(backup)
        _reap_stale_backups(final, publication_lock)
        return final
    except KokoroError:
        if staging is not None:
            _remove_staging(staging)
        raise
    except OSError as error:
        if staging is not None:
            _remove_staging(staging)
        raise _publish_failed("write", error) from error
    except BaseException:
        if staging is not None:
            _remove_staging(staging)
        raise


def _validate_publish_inputs(
    request: dict[str, Any], draft: dict[str, Any], report: dict[str, Any]
) -> None:
    if report.get("valid") is not True or report.get("hard_failures") != []:
        raise KokoroError(
            "AUTHORING_VALIDATION_FAILED",
            "A draft cannot be published while authoring validation has hard failures.",
            details={"reason": "hard_failures"},
        )

    if not isinstance(draft, dict) or set(draft) != _DRAFT_FIELDS:
        raise _invalid_draft("invalid_fields")
    namespace = request.get("namespace")
    character_id = request.get("character_id")
    for identity in (
        namespace,
        character_id,
        draft.get("namespace"),
        draft.get("character_id"),
    ):
        if _reserved_device_basename(identity):
            raise _unsafe_draft_path(Path(identity), "reserved device name")
    if not _valid_slug(namespace) or not _valid_slug(character_id):
        raise _invalid_draft("invalid_identity")
    source_hash = draft.get("source_pack_hash")
    if not isinstance(source_hash, str) or _HASH_PATTERN.fullmatch(source_hash) is None:
        raise _invalid_draft("invalid_source_hash")

    expected_artifact_id = (
        f"{namespace}/{character_id}/draft/"
        f"{source_hash[:_SOURCE_HASH_ID_PREFIX_LENGTH]}"
    )
    advisory = report.get("advisory_findings", [])
    if not isinstance(advisory, list):
        raise _invalid_draft("invalid_report")
    try:
        warning_codes = sorted({item["code"] for item in advisory})
    except (KeyError, TypeError):
        raise _invalid_draft("invalid_report") from None

    expected = {
        "schema_version": "1.0",
        "artifact_id": expected_artifact_id,
        "created_by": {"component": "kokoroarc", "version": __version__},
        "build_status": "draft",
        "visibility": "private",
        "activation_allowed": False,
        "mode": request.get("mode"),
        "namespace": namespace,
        "character_id": character_id,
        "display_name": request.get("display_name"),
        "character_version": request.get("character_version"),
        "request_hash": sha256(canonical_bytes(request)).hexdigest(),
        "source_pack_hash": source_hash,
        "validation_report_hash": sha256(canonical_bytes(report)).hexdigest(),
        "bundle_references": _BUNDLE_REFERENCES,
        "locale_coverage": report.get("locale_coverage"),
        "provenance_counts": report.get("provenance_counts"),
        "unresolved_warnings": warning_codes,
    }
    if draft != expected:
        raise _invalid_draft("metadata_mismatch")


def _valid_slug(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 64
        and _SLUG_PATTERN.fullmatch(value) is not None
        and not _reserved_device_basename(value)
    )


def _reserved_device_basename(value: Any) -> bool:
    return isinstance(value, str) and value in _WINDOWS_RESERVED_DEVICE_BASENAMES


def _acquire_publication_lock(target: Path) -> _PublicationLock:
    lock_path = target.parent / f".{target.name}.publish.lock"
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
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as error:
            try:
                linked_stat = lock_path.lstat()
            except OSError:
                raise _publish_failed("open_lock", error) from error
            if (
                _stat_is_redirect(lock_path, linked_stat)
                or not stat.S_ISREG(linked_stat.st_mode)
                or linked_stat.st_nlink != 1
            ):
                unsafe = _unsafe_draft_path(lock_path, "unsafe publication lock")
                raise unsafe from error
            raise _publish_failed("open_lock", error) from error

        linked_stat = lock_path.lstat()
        opened_stat = os.fstat(descriptor)
        if not _safe_lock_stats(lock_path, linked_stat, opened_stat):
            raise _unsafe_draft_path(lock_path, "unsafe publication lock")
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)

        if os.name == "nt" and opened_stat.st_size < 1:
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                if os.write(descriptor, b"\0") != 1:
                    raise OSError(errno.EIO, "publication lock initialization failed")
                os.fsync(descriptor)
            except OSError as error:
                if _is_lock_contention(error):
                    raise _publication_busy() from error
                raise

        try:
            _lock_publication_descriptor(descriptor)
        except OSError as error:
            if _is_lock_contention(error):
                raise _publication_busy() from error
            raise _publish_failed("lock", error) from error

        linked_stat = lock_path.lstat()
        opened_stat = os.fstat(descriptor)
        if not _safe_lock_stats(lock_path, linked_stat, opened_stat):
            raise _unsafe_draft_path(lock_path, "publication lock identity changed")
        if not _lock_ancestor_chain_matches(ancestor_chain):
            raise _unsafe_draft_path(
                target.parent, "publication lock ancestor changed"
            )
        publication_lock = _PublicationLock(
            target, lock_path, descriptor, ancestor_chain
        )
        descriptor = None
        return publication_lock
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
    lock_path: Path,
    linked_stat: os.stat_result,
    opened_stat: os.stat_result,
) -> bool:
    return (
        not _stat_is_redirect(lock_path, linked_stat)
        and stat.S_ISREG(linked_stat.st_mode)
        and stat.S_ISREG(opened_stat.st_mode)
        and linked_stat.st_nlink == 1
        and opened_stat.st_nlink == 1
        and os.path.samestat(linked_stat, opened_stat)
    )


def _safe_lock_parent(path: Path, path_stat: os.stat_result) -> bool:
    return not _stat_is_redirect(path, path_stat) and stat.S_ISDIR(path_stat.st_mode)


def _capture_lock_ancestor_chain(path: Path) -> tuple[_DirectoryIdentity, ...]:
    identities: list[_DirectoryIdentity] = []
    for component in reversed((path, *path.parents)):
        try:
            component_stat = component.lstat()
        except OSError as error:
            raise _publish_failed("inspect_lock_ancestor", error) from error
        if not _safe_lock_parent(component, component_stat):
            raise _unsafe_draft_path(component, "unsafe publication lock ancestor")
        identities.append(
            _DirectoryIdentity(
                path=component,
                device=component_stat.st_dev,
                inode=component_stat.st_ino,
                file_type=stat.S_IFMT(component_stat.st_mode),
            )
        )
    return tuple(identities)


def _lock_ancestor_chain_matches(
    identities: tuple[_DirectoryIdentity, ...],
) -> bool:
    matches = True
    for identity in identities:
        try:
            component_stat = identity.path.lstat()
        except OSError:
            matches = False
            continue
        if (
            not _safe_lock_parent(identity.path, component_stat)
            or component_stat.st_dev != identity.device
            or component_stat.st_ino != identity.inode
            or stat.S_IFMT(component_stat.st_mode) != identity.file_type
        ):
            matches = False
    return matches


def _lock_publication_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_publication_descriptor(descriptor: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            return

        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError:
        # Closing the descriptor below is the authoritative auto-release path.
        pass


def _is_lock_contention(error: OSError) -> bool:
    return (
        error.errno in _LOCK_CONTENTION_ERRNOS
        or getattr(error, "winerror", None) in _LOCK_CONTENTION_WINERRORS
    )


def _publication_busy() -> KokoroError:
    return KokoroError(
        "DRAFT_PUBLISH_BUSY",
        "Character draft publication is already in progress.",
        retryable=True,
        details={"reason": "target_locked"},
    )


def _absolute_without_resolution(path: Path) -> Path:
    try:
        return path.absolute()
    except (OSError, RuntimeError, ValueError) as error:
        raise _unsafe_draft_path(path, "path cannot be canonicalized") from error


def _resolved_source_root(source_root: Path) -> Path:
    try:
        return source_root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise KokoroError(
            "PACK_SCAN_FAILED",
            "Character pack filesystem scan failed.",
            details={"path": str(source_root), "reason": type(error).__name__},
        ) from error


def _validate_existing_chain(path: Path) -> None:
    chain = [path, *path.parents]
    for component in reversed(chain):
        if _destination_lstat(component) is not None:
            _validate_destination_component(component)


def _create_secure_directories(path: Path) -> tuple[Path, ...]:
    created: list[Path] = []
    chain = [path, *path.parents]
    for component in reversed(chain):
        component_stat = _destination_lstat(component)
        if component_stat is not None:
            _validate_destination_component(component)
            if not stat.S_ISDIR(component_stat.st_mode):
                raise _unsafe_draft_path(component, "component is not a directory")
            continue
        try:
            component.mkdir()
            created.append(component)
        except FileExistsError:
            pass
        except OSError as error:
            raise _publish_failed("mkdir", error) from error
        component_stat = _destination_lstat(component)
        if component_stat is None:
            raise _unsafe_draft_path(component, "component disappeared")
        _validate_destination_component(component)
        if not stat.S_ISDIR(component_stat.st_mode):
            raise _unsafe_draft_path(component, "component is not a directory")
    return tuple(created)


def _destination_lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise _publish_failed("inspect_destination", error) from error


def _validate_destination_component(path: Path) -> None:
    try:
        path_stat = path.lstat()
        is_junction = getattr(path, "is_junction", None)
        junction = bool(is_junction()) if is_junction is not None else False
    except OSError as error:
        raise _publish_failed("inspect_destination", error) from error
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if stat.S_ISLNK(path_stat.st_mode):
        raise _unsafe_draft_path(path, "symlink")
    if junction:
        raise _unsafe_draft_path(path, "junction")
    if attributes & reparse_flag:
        raise _unsafe_draft_path(path, "reparse point")


def _create_staging_parent(root: Path, parent: Path) -> None:
    if not parent.is_relative_to(root):
        raise _unsafe_draft_path(parent, "copy path escapes staging")
    relative = parent.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        current_stat = _destination_lstat(current)
        if current_stat is not None:
            _validate_destination_component(current)
            if not stat.S_ISDIR(current_stat.st_mode):
                raise _unsafe_draft_path(current, "copy component is not a directory")
        else:
            try:
                current.mkdir()
            except FileExistsError:
                pass
            except OSError as error:
                raise _publish_failed("mkdir", error) from error
            current_stat = _destination_lstat(current)
            if current_stat is None:
                raise _unsafe_draft_path(current, "copy component disappeared")
            _validate_destination_component(current)
            if not stat.S_ISDIR(current_stat.st_mode):
                raise _unsafe_draft_path(current, "copy component is not a directory")


def _source_identity(path: Path, relative: Path) -> _SourceIdentity:
    try:
        path_stat = path.stat(follow_symlinks=False)
    except OSError as error:
        raise _source_changed(relative, type(error).__name__) from error
    if (
        not stat.S_ISREG(path_stat.st_mode)
        or stat.S_ISLNK(path_stat.st_mode)
        or path_stat.st_nlink != 1
    ):
        raise _source_changed(relative, "unsafe_entry")
    return _identity_from_stat(path_stat)


def _identity_from_stat(path_stat: os.stat_result) -> _SourceIdentity:
    return _SourceIdentity(
        device=path_stat.st_dev,
        inode=path_stat.st_ino,
        size=path_stat.st_size,
        modified_ns=path_stat.st_mtime_ns,
    )


def _copy_scanned_file(
    source: Path,
    destination: Path,
    expected: _SourceIdentity,
    relative: Path,
) -> str:
    digest = sha256()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        source_fd = os.open(source, flags)
        with os.fdopen(source_fd, "rb") as source_handle:
            if _identity_from_stat(os.fstat(source_handle.fileno())) != expected:
                raise _source_changed(relative, "identity")
            with destination.open("xb") as destination_handle:
                copied = 0
                while True:
                    chunk = source_handle.read(64 * 1024)
                    if not chunk:
                        break
                    destination_handle.write(chunk)
                    digest.update(chunk)
                    copied += len(chunk)
                destination_handle.flush()
                os.fsync(destination_handle.fileno())
            if copied != expected.size:
                raise _source_changed(relative, "size")
            if _identity_from_stat(os.fstat(source_handle.fileno())) != expected:
                raise _source_changed(relative, "identity")
    except KokoroError:
        raise
    except OSError as error:
        raise _publish_failed("copy", error) from error
    if _source_identity(source, relative) != expected:
        raise _source_changed(relative, "identity")
    return digest.hexdigest()


def _write_canonical_file(path: Path, value: Any) -> None:
    payload = canonical_bytes(value) + b"\n"
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise _publish_failed("write_metadata", error) from error


def _revalidate_sources(
    source_root: Path,
    resolved_source: Path,
    expected_files: list[Path],
    recorded: dict[Path, _SourceIdentity],
    copied_hashes: dict[Path, str],
) -> None:
    rescanned = scan_pack(source_root, PackLimits())
    if rescanned != expected_files:
        raise _source_changed(Path("."), "entry_set")
    for path in rescanned:
        relative = path.relative_to(resolved_source)
        if _source_identity(path, relative) != recorded[path]:
            raise _source_changed(relative, "identity")
        if _hash_regular_file(path, recorded[path], relative) != copied_hashes[path]:
            raise _source_changed(relative, "content")


def _hash_regular_file(
    path: Path, expected: _SourceIdentity, relative: Path
) -> str:
    digest = sha256()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            if _identity_from_stat(os.fstat(handle.fileno())) != expected:
                raise _source_changed(relative, "identity")
            while chunk := handle.read(64 * 1024):
                digest.update(chunk)
            if _identity_from_stat(os.fstat(handle.fileno())) != expected:
                raise _source_changed(relative, "identity")
    except KokoroError:
        raise
    except OSError as error:
        raise _source_changed(relative, type(error).__name__) from error
    return digest.hexdigest()


def _verify_staged_bundle(
    staging: Path,
    expected_source_hashes: dict[Path, str],
    request: dict[str, Any],
    report: dict[str, Any],
    draft: dict[str, Any],
) -> None:
    _require_staged_directory(staging, Path("."))
    source_root = staging / _BUNDLE_REFERENCES["source_pack"]
    _require_staged_directory(source_root, Path("source-pack"))

    expected_files = {
        Path("request.json"),
        Path("validation-report.json"),
        Path("draft.json"),
        *(Path("source-pack") / relative for relative in expected_source_hashes),
    }
    expected_directories = {Path("source-pack")}
    for relative in expected_source_hashes:
        parent = relative.parent
        while parent != Path("."):
            expected_directories.add(Path("source-pack") / parent)
            parent = parent.parent
    observed_directories, observed_files = _inspect_staged_layout(staging)
    if observed_files != expected_files or observed_directories != expected_directories:
        raise _staging_invalid("layout", Path("."))

    try:
        scanned = scan_pack(source_root, PackLimits())
    except KokoroError as error:
        raise _staging_invalid("source_scan", Path("source-pack")) from error
    try:
        resolved_source = source_root.resolve(strict=True)
        observed_source_files = {
            path.relative_to(resolved_source): path for path in scanned
        }
    except (OSError, RuntimeError, ValueError) as error:
        raise _staging_invalid("source_scan", Path("source-pack")) from error
    if set(observed_source_files) != set(expected_source_hashes):
        raise _staging_invalid("source_file_set", Path("source-pack"))
    for relative, expected_hash in expected_source_hashes.items():
        payload = _read_staged_regular_file(
            observed_source_files[relative], Path("source-pack") / relative
        )
        if sha256(payload).hexdigest() != expected_hash:
            raise _staging_invalid("source_content", Path("source-pack") / relative)

    expected_metadata = {
        Path("request.json"): canonical_bytes(request) + b"\n",
        Path("validation-report.json"): canonical_bytes(report) + b"\n",
        Path("draft.json"): canonical_bytes(draft) + b"\n",
    }
    for relative, expected_payload in expected_metadata.items():
        if _read_staged_regular_file(staging / relative, relative) != expected_payload:
            raise _staging_invalid("metadata_content", relative)

    _require_staged_directory(staging, Path("."))
    _require_staged_directory(source_root, Path("source-pack"))


def _require_staged_directory(path: Path, relative: Path) -> None:
    try:
        path_stat = path.lstat()
    except OSError as error:
        raise _staging_invalid("directory", relative) from error
    if _stat_is_redirect(path, path_stat) or not stat.S_ISDIR(path_stat.st_mode):
        raise _staging_invalid("directory", relative)


def _inspect_staged_layout(root: Path) -> tuple[set[Path], set[Path]]:
    directories: set[Path] = set()
    files: set[Path] = set()
    pending = [(root, Path("."))]
    try:
        while pending:
            directory, relative_directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    relative = relative_directory / entry.name
                    path_stat = path.stat(follow_symlinks=False)
                    if _stat_is_redirect(path, path_stat):
                        raise _staging_invalid("redirect", relative)
                    if stat.S_ISDIR(path_stat.st_mode):
                        directories.add(relative)
                        pending.append((path, relative))
                    elif stat.S_ISREG(path_stat.st_mode):
                        files.add(relative)
                    else:
                        raise _staging_invalid("entry_type", relative)
    except KokoroError:
        raise
    except OSError as error:
        raise _staging_invalid("layout_scan", Path(".")) from error
    return directories, files


def _read_staged_regular_file(path: Path, relative: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        initial_stat = path.lstat()
        if (
            _stat_is_redirect(path, initial_stat)
            or not stat.S_ISREG(initial_stat.st_mode)
            or initial_stat.st_nlink != 1
        ):
            raise _staging_invalid("unsafe_file", relative)
        expected_identity = _identity_from_stat(initial_stat)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            if (
                _identity_from_stat(os.fstat(handle.fileno())) != expected_identity
                or os.fstat(handle.fileno()).st_nlink != 1
            ):
                raise _staging_invalid("file_identity", relative)
            payload = handle.read()
            final_handle_stat = os.fstat(handle.fileno())
            if (
                _identity_from_stat(final_handle_stat) != expected_identity
                or final_handle_stat.st_nlink != 1
            ):
                raise _staging_invalid("file_identity", relative)
        final_stat = path.lstat()
        if (
            _stat_is_redirect(path, final_stat)
            or _identity_from_stat(final_stat) != expected_identity
            or final_stat.st_nlink != 1
        ):
            raise _staging_invalid("file_identity", relative)
    except KokoroError:
        raise
    except OSError as error:
        raise _staging_invalid("read", relative) from error
    return payload


def _fsync_tree_directories(root: Path) -> None:
    directories = [path for path in root.rglob("*") if path.is_dir()]
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        _fsync_directory(directory)
    _fsync_directory(root)


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
        raise _unsafe_draft_path(
            target_parent,
            "created directory escaped publication chain",
        )

    # Sync the complete chain on first publication, including directories that
    # another process may have created before this lock holder entered.
    for directory in directories:
        _fsync_directory(directory)
        _fsync_directory(directory.parent)


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
            raise _publish_failed("fsync_directory", error) from error


def _transactional_replace_directory(staging: Path, target: Path) -> Path | None:
    backup: Path | None = None
    try:
        target_stat = _destination_lstat(target)
        if target_stat is not None:
            _validate_destination_component(target)
            if not stat.S_ISDIR(target_stat.st_mode):
                raise _unsafe_draft_path(target, "target is not a directory")
            backup = target.parent / (
                f".{target.name}.backup-{secrets.token_hex(12)}"
            )
            _replace_with_retries(target, backup)
        try:
            _replace_with_retries(staging, target)
        except OSError as cutover_error:
            if backup is not None:
                try:
                    _replace_with_retries(backup, target)
                except OSError as restore_error:
                    raise KokoroError(
                        "DRAFT_RESTORE_FAILED",
                        "Character draft publication failed; the previous draft "
                        "remains in a recovery backup.",
                        details={
                            "operation": "rollback",
                            "reason": type(restore_error).__name__,
                            "backup_path": str(backup),
                        },
                    ) from restore_error
                backup = None
            raise cutover_error
    except OSError as error:
        raise _publish_failed("replace", error) from error
    return backup


def _durability_failure(
    target: Path, backup: Path | None, error: KokoroError
) -> KokoroError:
    details: dict[str, Any] = {
        "operation": "fsync_parent",
        "reason": str(error.details.get("reason", error.code)),
    }
    if backup is not None:
        failed_target = target.parent / (
            f".{target.name}.failed-{secrets.token_hex(12)}"
        )
        try:
            _replace_with_retries(target, failed_target)
            try:
                _replace_with_retries(backup, target)
            except OSError:
                try:
                    _replace_with_retries(failed_target, target)
                except OSError:
                    pass
                details["backup_path"] = str(backup)
            else:
                _cleanup_tree_best_effort(failed_target)
        except OSError:
            details["backup_path"] = str(backup)
    return KokoroError(
        "DRAFT_DURABILITY_FAILED",
        "Character draft publication could not be made durable.",
        details=details,
    )


def _replace_with_retries(source: Path, target: Path) -> None:
    attempts = len(_REPLACE_RETRY_DELAYS) + 1
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError as error:
            if not _is_transient_replace_error(error) or attempt == attempts - 1:
                raise
            time.sleep(_REPLACE_RETRY_DELAYS[attempt])


def _is_transient_replace_error(error: PermissionError) -> bool:
    return (
        os.name == "nt"
        and getattr(error, "winerror", None) in _TRANSIENT_REPLACE_WINERRORS
    )


def _backup_prefix(target: Path) -> str:
    return f".{target.name}.backup-"


def _is_same_scope_backup(path: Path, target: Path) -> bool:
    prefix = _backup_prefix(target)
    return (
        path.parent == target.parent
        and path.name.startswith(prefix)
        and _BACKUP_TOKEN_PATTERN.fullmatch(path.name[len(prefix) :]) is not None
    )


def _reap_stale_backups(
    target: Path, publication_lock: _PublicationLock
) -> None:
    if not publication_lock.owns(target):
        raise RuntimeError("stale backup reaping requires the target publication lock")
    try:
        target_stat = _destination_lstat(target)
        if target_stat is None:
            return
        _validate_destination_component(target)
    except KokoroError:
        return
    if not stat.S_ISDIR(target_stat.st_mode):
        return
    try:
        entries = list(os.scandir(target.parent))
    except OSError:
        return
    for entry in entries:
        candidate = Path(entry.path)
        if _is_same_scope_backup(candidate, target):
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


def _tree_is_redirect_free(root: Path) -> bool:
    try:
        root_stat = root.lstat()
        if _stat_is_redirect(root, root_stat) or not stat.S_ISDIR(root_stat.st_mode):
            return False
        pending = [root]
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    path = Path(entry.path)
                    path_stat = path.stat(follow_symlinks=False)
                    if _stat_is_redirect(path, path_stat):
                        return False
                    if stat.S_ISDIR(path_stat.st_mode):
                        pending.append(path)
                    elif not stat.S_ISREG(path_stat.st_mode):
                        return False
    except OSError:
        return False
    return True


def _stat_is_redirect(path: Path, path_stat: os.stat_result) -> bool:
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    is_junction = getattr(path, "is_junction", None)
    try:
        junction = bool(is_junction()) if is_junction is not None else False
    except OSError:
        return True
    return (
        stat.S_ISLNK(path_stat.st_mode)
        or junction
        or bool(attributes & reparse_flag)
    )


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
    if _stat_is_redirect(path, path_stat):
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


def _canonical_hash(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _require_source_hash(source: dict[str, Any], expected: str) -> None:
    if _canonical_hash(source) != expected:
        raise KokoroError(
            "AUTHORING_SOURCE_HASH_MISMATCH",
            "Character source pack does not match the draft metadata.",
            details={"reason": "assembled_source_hash"},
        )


def _require_validation_report(
    request: dict[str, Any],
    source: dict[str, Any],
    report: dict[str, Any],
    schemas: SchemaRegistry,
    research_bundle: dict[str, Any] | None = None,
) -> None:
    recomputed = (
        validate_authoring_pack(request, source, schemas)
        if research_bundle is None
        else validate_authoring_pack(
            request,
            source,
            schemas,
            research_bundle=research_bundle,
        )
    )
    if recomputed["hard_failures"] or canonical_bytes(recomputed) != canonical_bytes(
        report
    ):
        raise KokoroError(
            "AUTHORING_VALIDATION_FAILED",
            "Character authoring validation does not match the source pack.",
            details={"reason": "report_mismatch"},
        )


def _staging_invalid(reason: str, relative: Path) -> KokoroError:
    return KokoroError(
        "DRAFT_STAGING_INVALID",
        "Character draft staging bundle failed final verification.",
        details={"path": relative.as_posix(), "reason": reason},
    )


def _invalid_draft(reason: str) -> KokoroError:
    return KokoroError(
        "INVALID_DRAFT_DATA",
        "Character draft metadata is invalid.",
        details={"reason": reason},
    )


def _unsafe_draft_path(path: Path, reason: str) -> KokoroError:
    return KokoroError(
        "UNSAFE_DRAFT_PATH",
        "Character draft destination contains an unsafe filesystem path.",
        details={"path": str(path), "reason": reason},
    )


def _source_changed(relative: Path, reason: str) -> KokoroError:
    return KokoroError(
        "AUTHORING_SOURCE_CHANGED",
        "Character source pack changed while the draft was being published.",
        details={"path": relative.as_posix(), "reason": reason},
    )


def _publish_failed(operation: str, error: OSError) -> KokoroError:
    return KokoroError(
        "DRAFT_PUBLISH_FAILED",
        "Character draft publication failed.",
        details={"operation": operation, "reason": type(error).__name__},
    )
