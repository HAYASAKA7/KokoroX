"""Transactional installation of verified ``.karc`` character packs."""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import secrets
import stat
import sys
from typing import TYPE_CHECKING, Any, Callable, Protocol, cast

from kokoroarc.distribution.archive import (
    KarcLimits,
    InspectedKarcContainer,
    inspect_karc_container,
    load_karc_archive,
)
from kokoroarc.distribution.compatibility import inspect_karc_compatibility
from kokoroarc.distribution.registry import (
    InstallScope,
    _RegistryLock,
    _acquire_registry_lock,
    _capture_directory_chain,
    _directory_chain_matches,
    _ensure_directory,
    _fsync_directory,
    _read_optional_regular_file,
    _registry_state,
    _write_installed_registry_cas_locked,
    empty_installed_registry,
    load_installed_registry,
    resolve_install_scope,
)
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes

if TYPE_CHECKING:
    from kokoroarc.persistence._storage import PersistenceLock


_STABLE_VERSION_TOKEN = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
_SLUG_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_SEMANTIC_VERSION = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
_MAX_INSTALLED_ENTRIES = 32
_MAX_JOURNAL_BYTES = 256 * 1024
_MAX_REFERENCE_BYTES = 2 * 1024 * 1024
_MAX_SESSION_REFERENCES = 1024
_MAX_MIGRATION_REFERENCES = 256
_MAX_WORKSPACE_REGISTRIES = 1024
_JOURNAL_VERSION = "1.0"
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}")
_INSTALL_PHASES = {
    "prepared",
    "archive_published",
    "installation_published",
    "registry_published",
}
_REMOVAL_PHASES = {
    "prepared",
    "registry_published",
    "installation_removed",
}
_PORTABLE_DEVICE_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)


class _SchemaValidator(Protocol):
    def validate(self, name: str, instance: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class _CapturedArchive:
    path: Path
    payload: bytes
    identity: tuple[int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class _NodeIdentity:
    device: int
    inode: int
    file_type: int


@dataclass(frozen=True, slots=True)
class _CapturedWorkspace:
    path: Path
    canonical_path: str
    identity: _NodeIdentity


@dataclass(frozen=True, slots=True)
class _CapturedDataRoot:
    path: Path
    existed: bool
    ancestry: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class _CapturedInstalledTree:
    path: Path
    identity: _NodeIdentity
    members: dict[str, bytes]


@dataclass(frozen=True, slots=True)
class _CapturedOptionalFile:
    path: Path
    payload: bytes | None


@dataclass(frozen=True, slots=True)
class _CapturedReferenceDirectory:
    path: Path
    limit: int
    identity: _NodeIdentity | None
    entries: dict[str, bytes]


@dataclass(frozen=True, slots=True)
class _CapturedWorkspaceRegistries:
    path: Path
    excluded_name: str | None
    identity: _NodeIdentity | None
    entries: dict[str, bytes]


class _BoundarySchemas:
    def __init__(self, delegate: _SchemaValidator) -> None:
        self._delegate = delegate
        self._audits: dict[str, Callable[[], None]] = {}
        self._violation: KokoroError | None = None

    def validate(self, name: str, instance: Any) -> None:
        try:
            self._delegate.validate(name, instance)
        finally:
            self.assert_clean()

    def set_audit(self, name: str, audit: Callable[[], None]) -> None:
        self._audits[name] = audit

    def remove_audit(self, name: str) -> None:
        self._audits.pop(name, None)

    def assert_clean(self) -> None:
        try:
            for name in sorted(self._audits):
                self._audits[name]()
        except KokoroError as error:
            if self._violation is None:
                self._violation = error
            raise

    def raise_if_failed(self) -> None:
        if self._violation is not None:
            raise self._violation


def install_karc_archive(
    archive_path: Path,
    data_root: Path,
    schemas: _SchemaValidator,
    *,
    workspace_root: Path | None = None,
    dry_run: bool = False,
    limits: KarcLimits = KarcLimits(),
) -> dict[str, Any]:
    """Preview or atomically install one current verified archive."""

    source_path = _absolute_path(archive_path)
    root = _absolute_path(data_root)
    scope = resolve_install_scope(workspace_root)
    workspace = _capture_workspace(workspace_root)
    data_boundary = _capture_data_root(root)
    source = _capture_archive(source_path, limits.max_archive_bytes)
    registry_path = root.joinpath(*scope.registry_relative_path.split("/"))
    registry_payload = _read_optional_regular_file(registry_path)
    audited = _BoundarySchemas(schemas)
    audited.set_audit(
        "archive_source",
        lambda: _require_archive_unchanged(source, limits.max_archive_bytes),
    )
    audited.set_audit(
        "data_root",
        lambda: _require_data_root_unchanged(data_boundary),
    )
    audited.set_audit(
        "registry",
        lambda: _require_registry_payload(
            registry_path,
            registry_payload,
            "KARC_INSTALL_CONFLICT",
        ),
    )
    if workspace is not None:
        audited.set_audit(
            "workspace",
            lambda: _require_workspace_unchanged(workspace),
        )
    try:
        preview = preview_karc_install(
            source.payload,
            root,
            audited,
            workspace_root=workspace_root,
            limits=limits,
        )
        _require_archive_unchanged(source, limits.max_archive_bytes)
        if dry_run:
            audited.assert_clean()
            return preview
        with _acquire_registry_lock(root, scope) as lock:
            data_boundary = _capture_data_root(root)
            result = _install_under_lock(
                source,
                root,
                scope,
                lock,
                audited,
                workspace_root=workspace_root,
                limits=limits,
            )
            audited.assert_clean()
        return result
    except Exception:
        audited.raise_if_failed()
        raise


def recover_karc_installations(
    data_root: Path,
    schemas: _SchemaValidator,
    *,
    workspace_root: Path | None = None,
    limits: KarcLimits = KarcLimits(),
) -> dict[str, Any]:
    """Recover at most one bounded transaction for the selected scope."""

    root = _absolute_path(data_root)
    scope = resolve_install_scope(workspace_root)
    workspace = _capture_workspace(workspace_root)
    journal_path = _journal_path(root, scope)
    if _lstat_optional(journal_path) is None:
        data_boundary = _capture_data_root(root)
        registry_path = root.joinpath(*scope.registry_relative_path.split("/"))
        registry_payload = _read_optional_regular_file(registry_path)
        audited = _BoundarySchemas(schemas)
        audited.set_audit(
            "data_root",
            lambda: _require_data_root_unchanged(data_boundary),
        )
        audited.set_audit(
            "registry",
            lambda: _require_registry_payload(
                registry_path,
                registry_payload,
                "KARC_INSTALL_CONFLICT",
            ),
        )
        if workspace is not None:
            audited.set_audit(
                "workspace",
                lambda: _require_workspace_unchanged(workspace),
            )
        try:
            registry = load_installed_registry(
                root,
                audited,
                workspace_root=workspace_root,
            )
            audited.assert_clean()
            return _recovery_result(scope, registry["revision"])
        except Exception:
            audited.raise_if_failed()
            raise
    with _acquire_registry_lock(root, scope) as lock:
        data_boundary = _capture_data_root(root)
        payload = _read_optional_recovery_file(journal_path, _MAX_JOURNAL_BYTES)
        registry_path = root.joinpath(*scope.registry_relative_path.split("/"))
        registry_payload = _read_optional_regular_file(registry_path)
        workspace_registries = _capture_workspace_registries(
            root / "registry" / "workspaces",
            _selected_workspace_registry_name(scope),
        )
        audited = _BoundarySchemas(schemas)
        audited.set_audit(
            "data_root",
            lambda: _require_data_root_unchanged(data_boundary),
        )
        audited.set_audit(
            "registry",
            lambda: _require_registry_payload(
                registry_path,
                registry_payload,
                "KARC_INSTALL_CONFLICT",
            ),
        )
        audited.set_audit(
            "recovery_lock",
            lambda: _require_recovery_lock(lock),
        )
        audited.set_audit(
            "workspace_registries",
            lambda: _require_workspace_registries(workspace_registries),
        )
        if workspace is not None:
            audited.set_audit(
                "workspace",
                lambda: _require_workspace_unchanged(workspace),
            )
        if payload is None:
            try:
                registry, _registry_sha256 = _registry_state(
                    root,
                    scope,
                    audited,
                )
                audited.assert_clean()
                return _recovery_result(scope, registry["revision"])
            except Exception:
                audited.raise_if_failed()
                raise
        journal_identity = _capture_node_identity(
            journal_path,
            regular_file=True,
        )
        journal = _parse_transaction_journal(payload, root, scope)
        audited.set_audit(
            "journal",
            lambda: _audit_journal(journal_path, journal_identity, journal),
        )
        try:
            if journal["operation"] == "remove":
                result = _recover_removal_under_lock(
                    root,
                    scope,
                    lock,
                    journal_path,
                    journal,
                    audited,
                    limits,
                )
            else:
                result = _recover_under_lock(
                    root,
                    scope,
                    lock,
                    journal_path,
                    journal,
                    audited,
                    limits,
                )
            audited.assert_clean()
            return result
        except Exception:
            audited.raise_if_failed()
            raise


def remove_installed_pack(
    data_root: Path,
    namespace: str,
    character_id: str,
    character_version: str,
    schemas: _SchemaValidator,
    *,
    workspace_root: Path | None = None,
    dry_run: bool = False,
    limits: KarcLimits = KarcLimits(),
) -> dict[str, Any]:
    """Preview or remove one exact inactive installation."""

    from kokoroarc.persistence._storage import (
        persistence_reference_blockers,
        persistence_reference_lock,
    )

    root = _absolute_path(data_root)
    scope = resolve_install_scope(workspace_root)
    identity = _removal_identity(namespace, character_id, character_version)
    workspace = _capture_workspace(workspace_root)
    data_boundary = _capture_data_root(root)
    registry_path = root.joinpath(*scope.registry_relative_path.split("/"))
    registry_payload = _read_optional_regular_file(registry_path)
    installation_path = (
        root
        / "installed"
        / Path(scope.installed_relative_root)
        / character_id
        / character_version
    )
    installation_boundary = _capture_installed_tree(
        installation_path,
        limits,
        optional=True,
    )
    config_path = (
        root / "config" / "global.json"
        if scope.kind == "global"
        else root / "config" / "workspaces" / f"{scope.workspace_id}.json"
    )
    config_boundary = _capture_optional_reference_file(config_path)
    session_boundary = _capture_reference_directory(
        root / "sessions",
        _MAX_SESSION_REFERENCES,
    )
    migration_boundary = _capture_reference_directory(
        root / "migrations",
        _MAX_MIGRATION_REFERENCES,
    )
    workspace_registries = _capture_workspace_registries(
        root / "registry" / "workspaces",
        _selected_workspace_registry_name(scope),
    )
    audited = _BoundarySchemas(schemas)
    audited.set_audit(
        "data_root",
        lambda: _require_data_root_unchanged(data_boundary),
    )
    audited.set_audit(
        "registry",
        lambda: _require_registry_payload(
            registry_path,
            registry_payload,
            "KARC_REMOVE_CONFLICT",
        ),
    )
    audited.set_audit(
        "reference_config",
        lambda: _require_optional_reference_file(config_boundary),
    )
    audited.set_audit(
        "reference_sessions",
        lambda: _require_reference_directory(session_boundary),
    )
    audited.set_audit(
        "reference_migrations",
        lambda: _require_reference_directory(migration_boundary),
    )
    audited.set_audit(
        "workspace_registries",
        lambda: _require_workspace_registries(workspace_registries),
    )
    if workspace is not None:
        audited.set_audit(
            "workspace",
            lambda: _require_workspace_unchanged(workspace),
        )
    if installation_boundary is not None:
        audited.set_audit(
            "removal_installation",
            lambda: _require_installed_tree_unchanged(installation_boundary),
        )
    try:
        if dry_run:
            registry = load_installed_registry(
                root,
                audited,
                workspace_root=workspace_root,
            )
            removal_archive = _capture_removal_archive(
                root,
                identity,
                registry,
                limits,
            )
            if removal_archive is not None:
                audited.set_audit(
                    "removal_archive",
                    lambda: _require_removal_archive_unchanged(
                        removal_archive,
                        limits.max_archive_bytes,
                    ),
                )
            result = _preview_removal(
                root,
                scope,
                identity,
                registry,
                audited,
                limits,
                dry_run=True,
            )[0]
            audited.assert_clean()
            return result
        with _acquire_registry_lock(root, scope) as lock:
            try:
                preflight_registry, _preflight_sha256 = _registry_state(
                    root,
                    scope,
                    audited,
                )
                preflight_entry = preflight_registry["entries"].get(identity)
                if not isinstance(preflight_entry, dict):
                    raise _error(
                        "KARC_REMOVE_NOT_FOUND",
                        "The selected installation identity is not installed.",
                    )
                preflight_blockers = _legacy_reference_blockers(
                    root,
                    scope,
                    preflight_entry,
                    audited,
                )
                if preflight_blockers:
                    try:
                        preflight_blockers = sorted(
                            set(preflight_blockers)
                            | set(
                                persistence_reference_blockers(
                                    root,
                                    scope,
                                    preflight_entry,
                                    audited,
                                )
                            )
                        )
                    except KokoroError as error:
                        raise _reference_scan_error(
                            "Persistent character references could not be "
                            "verified.",
                            reason=error.code,
                        ) from error
                    raise _error(
                        "KARC_REMOVE_REFERENCED",
                        "The selected installation is still referenced.",
                        references=preflight_blockers,
                    )
                with persistence_reference_lock(
                    root,
                    scope,
                    namespace,
                    character_id,
                ) as reference_lock:
                    data_boundary = _capture_data_root(root)
                    result = _remove_under_lock(
                        root,
                        scope,
                        lock,
                        reference_lock,
                        identity,
                        audited,
                        limits,
                    )
                    audited.assert_clean()
            except KokoroError as error:
                if error.code == "PERSISTENCE_LOCKED":
                    raise _error(
                        "KARC_REMOVE_CONFLICT",
                        "Persistent character storage is currently changing.",
                    ) from error
                if error.code.startswith("PERSISTENCE_"):
                    raise _reference_scan_error(
                        "Persistent character references could not be verified.",
                        reason=error.code,
                    ) from error
                raise
        return result
    except Exception:
        audited.raise_if_failed()
        raise


def preview_karc_install(
    payload: bytes,
    data_root: Path,
    schemas: _SchemaValidator,
    *,
    workspace_root: Path | None = None,
    limits: KarcLimits = KarcLimits(),
) -> dict[str, Any]:
    """Return a deterministic installation plan without writing storage."""

    if not isinstance(payload, bytes):
        raise _error(
            "KARC_INSTALL_ARCHIVE_INVALID",
            "Install preview requires archive bytes.",
        )
    scope = resolve_install_scope(workspace_root)
    root = _absolute_path(data_root)
    workspace = _capture_workspace(workspace_root)
    data_boundary = _capture_data_root(root)
    registry_path = root.joinpath(*scope.registry_relative_path.split("/"))
    registry_payload = _read_optional_regular_file(registry_path)
    audited = _BoundarySchemas(schemas)
    audited.set_audit(
        "data_root",
        lambda: _require_data_root_unchanged(data_boundary),
    )
    audited.set_audit(
        "registry",
        lambda: _require_registry_payload(
            registry_path,
            registry_payload,
            "KARC_INSTALL_CONFLICT",
        ),
    )
    if workspace is not None:
        audited.set_audit(
            "workspace",
            lambda: _require_workspace_unchanged(workspace),
        )
    try:
        result = _preview_karc_install(
            payload,
            root,
            audited,
            workspace_root=workspace_root,
            limits=limits,
        )
        audited.assert_clean()
        return result
    except Exception:
        audited.raise_if_failed()
        raise


def _preview_karc_install(
    payload: bytes,
    data_root: Path,
    schemas: _SchemaValidator,
    *,
    workspace_root: Path | None = None,
    limits: KarcLimits = KarcLimits(),
) -> dict[str, Any]:
    scope = resolve_install_scope(workspace_root)
    root = _absolute_path(data_root)
    compatibility = inspect_karc_compatibility(
        payload,
        schemas,
        limits=limits,
    )
    if compatibility.get("installation_allowed") is not True:
        raise _error(
            "KARC_INSTALL_ARCHIVE_INVALID",
            "Archive is not compatible with this runtime.",
            reasons=_compatibility_reasons(compatibility),
        )
    try:
        loaded = load_karc_archive(payload, schemas, limits=limits)
        container = inspect_karc_container(payload, limits=limits)
    except Exception as error:
        raise _error(
            "KARC_INSTALL_ARCHIVE_INVALID",
            "Archive failed current release validation.",
            reason=_reason(error),
        ) from error
    manifest = loaded.manifest
    if (
        manifest.get("promotion_status") != "verified"
        or manifest.get("activation_allowed") is not True
        or manifest.get("trust") != "unsigned_local"
    ):
        raise _error(
            "KARC_INSTALL_ARCHIVE_INVALID",
            "Archive is not eligible for local installation.",
        )
    registry = load_installed_registry(
        root,
        schemas,
        workspace_root=workspace_root,
    )
    plan, entry = _install_plan(container, scope, registry)
    existing = registry["entries"].get(plan["registry_identity"])
    if existing is not None:
        if existing != entry:
            raise _error(
                "KARC_INSTALL_CONFLICT",
                "A different archive already owns this installation identity.",
            )
        if not _existing_installation_matches(root, container, plan):
            raise _error(
                "KARC_INSTALL_RECOVERY_REQUIRED",
                "Registry and installed archive bytes are inconsistent.",
            )
        plan.update(
            {
                "registry_revision_after": registry["revision"],
                "idempotent": True,
                "will_write": False,
            }
        )
        return _detached(plan)
    install_root = root / "installed" / Path(plan["relative_path"])
    if _lstat_optional(install_root) is not None:
        raise _error(
            "KARC_INSTALL_RECOVERY_REQUIRED",
            "Unregistered installation bytes already occupy the target.",
        )
    archive_path = root / "archives" / f"{container.archive_sha256}.karc"
    archive_stat = _lstat_optional(archive_path)
    if archive_stat is not None and not _regular_file_matches(archive_path, payload):
        raise _error(
            "KARC_INSTALL_RECOVERY_REQUIRED",
            "Content-addressed archive bytes do not match their name.",
        )
    return _detached(plan)


def _install_under_lock(
    source: _CapturedArchive,
    root: Path,
    scope: InstallScope,
    lock: _RegistryLock,
    schemas: _SchemaValidator,
    *,
    workspace_root: Path | None,
    limits: KarcLimits,
) -> dict[str, Any]:
    if not lock.owns():
        raise _error(
            "KARC_INSTALL_LOCK_LOST",
            "Install scope lock changed before the transaction began.",
        )
    journal_path = _journal_path(root, scope)
    if _lstat_optional(journal_path) is not None:
        raise _error(
            "KARC_INSTALL_RECOVERY_REQUIRED",
            "An unfinished install journal must be recovered first.",
        )
    registry, registry_sha256 = _registry_state(root, scope, schemas)
    boundary = schemas if isinstance(schemas, _BoundarySchemas) else None
    if boundary is not None:
        boundary.set_audit(
            "registry",
            lambda: _require_registry_snapshot(
                root,
                scope,
                registry,
                registry_sha256,
            ),
        )
    plan = preview_karc_install(
        source.payload,
        root,
        schemas,
        workspace_root=workspace_root,
        limits=limits,
    )
    _require_archive_unchanged(source, limits.max_archive_bytes)
    _require_registry_current(lock, registry, registry_sha256, schemas)
    if plan["registry_revision_before"] != registry["revision"]:
        raise _error(
            "KARC_INSTALL_CONFLICT",
            "Install preview no longer matches the locked registry.",
        )
    if plan["idempotent"] is True:
        return plan

    container = inspect_karc_container(source.payload, limits=limits)
    load_karc_archive(source.payload, schemas, limits=limits)
    if _archive_bytes(container) != source.payload:
        raise _error(
            "KARC_INSTALL_ARCHIVE_INVALID",
            "Archive does not have the canonical standalone encoding.",
        )
    locked_plan, entry = _install_plan(container, scope, registry)
    if locked_plan != plan:
        raise _error(
            "KARC_INSTALL_CONFLICT",
            "Install plan changed while the scope lock was held.",
        )
    next_registry = _registry_successor(registry, plan, entry)

    paths = _prepare_storage_paths(root, scope, plan)
    ancestry = tuple(
        _capture_directory_chain(path)
        for path in (
            paths["archives"],
            paths["installation_parent"],
            paths["journals"],
        )
    )
    if boundary is not None:
        boundary.set_audit(
            "storage_ancestry",
            lambda: _require_storage_ancestry(lock, ancestry),
        )
    token = secrets.token_hex(8)
    archive_staging = paths["archive"].with_name(
        f".{paths['archive'].name}.{token}.staging"
    )
    installation_staging = paths["installation"].parent / (
        f".{paths['installation'].name}.{token}.staging"
    )
    journal = _new_install_journal(
        root,
        scope,
        plan,
        entry,
        registry_sha256,
        sha256(canonical_bytes(next_registry)).hexdigest(),
        archive_staging,
        installation_staging,
    )
    journal_identity = _write_journal(journal_path, journal, create=True)
    if boundary is not None:
        boundary.set_audit(
            "journal",
            lambda: _audit_journal(journal_path, journal_identity, journal),
        )
    _install_failure_point("journal_created")

    archive_identity = _write_staging_archive(archive_staging, source.payload)
    journal["archive_staging_identity"] = _identity_document(archive_identity)
    journal_identity = _write_journal(journal_path, journal)
    _install_failure_point("archive_staged")
    installation_identity = _create_staging_directory(installation_staging)
    journal["installation_staging_identity"] = _identity_document(
        installation_identity
    )
    journal_identity = _write_journal(journal_path, journal)
    _write_installed_members(
        installation_staging,
        container.member_payloads,
    )
    if boundary is not None:
        boundary.set_audit(
            "archive_staging",
            lambda: _audit_staging_archive(
                archive_staging,
                archive_identity,
                source.payload,
            ),
        )
        boundary.set_audit(
            "installation_staging",
            lambda: _audit_staging_installation(
                installation_staging,
                installation_identity,
                container.member_payloads,
            ),
        )
    _validate_staged_installation(installation_staging, container, schemas, limits)
    _install_failure_point("installation_staged")

    _require_transaction_current(
        source,
        limits,
        lock,
        registry,
        registry_sha256,
        schemas,
        ancestry,
    )
    _require_node_identity(archive_staging, archive_identity)
    _publish_archive(
        archive_staging,
        paths["archive"],
        source.payload,
    )
    published_archive_identity = _capture_node_identity(
        paths["archive"],
        regular_file=True,
    )
    if boundary is not None:
        boundary.remove_audit("archive_staging")
        boundary.set_audit(
            "published_archive",
            lambda: _audit_published_archive(
                paths["archive"],
                published_archive_identity,
                source.payload,
            ),
        )
    _install_failure_point("archive_published")
    journal["phase"] = "archive_published"
    journal_identity = _write_journal(journal_path, journal)
    _install_failure_point("archive_phase_recorded")

    _require_transaction_current(
        source,
        limits,
        lock,
        registry,
        registry_sha256,
        schemas,
        ancestry,
    )
    _require_node_identity(installation_staging, installation_identity)
    _validate_staged_installation(installation_staging, container, schemas, limits)
    _rename_directory_no_replace(
        installation_staging,
        paths["installation"],
    )
    _fsync_directory(paths["installation"].parent)
    _require_node_identity(paths["installation"], installation_identity)
    if boundary is not None:
        boundary.remove_audit("installation_staging")
        boundary.set_audit(
            "published_installation",
            lambda: _audit_published_installation(
                paths["installation"],
                installation_identity,
                container.member_payloads,
            ),
        )
    _install_failure_point("installation_published")
    journal["phase"] = "installation_published"
    journal_identity = _write_journal(journal_path, journal)
    _install_failure_point("installation_phase_recorded")

    _require_archive_unchanged(source, limits.max_archive_bytes)
    if not lock.owns() or not _existing_installation_matches(root, container, plan):
        raise _error(
            "KARC_INSTALL_RECOVERY_REQUIRED",
            "Published installation changed before registry commit.",
        )
    _write_installed_registry_cas_locked(
        lock,
        registry["revision"],
        registry_sha256,
        next_registry,
        schemas,
        failure_hook=_install_failure_point,
    )
    if boundary is not None:
        next_registry_sha256 = sha256(canonical_bytes(next_registry)).hexdigest()
        boundary.set_audit(
            "registry",
            lambda: _require_registry_snapshot(
                root,
                scope,
                next_registry,
                next_registry_sha256,
            ),
        )
    journal["phase"] = "registry_published"
    journal_identity = _write_journal(journal_path, journal)
    _install_failure_point("registry_phase_recorded")
    registry_path = root.joinpath(*scope.registry_relative_path.split("/"))
    if not _regular_file_matches(registry_path, canonical_bytes(next_registry)):
        raise _error(
            "KARC_INSTALL_RECOVERY_REQUIRED",
            "Published registry bytes could not be confirmed.",
        )
    if boundary is not None:
        boundary.remove_audit("journal")
    _remove_exact_journal(journal_path, journal)
    _install_failure_point("cleanup_complete")
    return _detached(plan)


def _recover_under_lock(
    root: Path,
    scope: InstallScope,
    lock: _RegistryLock,
    journal_path: Path,
    journal: dict[str, Any],
    schemas: _SchemaValidator,
    limits: KarcLimits,
) -> dict[str, Any]:
    if not lock.owns():
        raise _recovery_error("Install scope lock changed during recovery.")
    boundary = schemas if isinstance(schemas, _BoundarySchemas) else None
    prior_phase = cast(str, journal["phase"])
    registry, registry_sha256 = _registry_state(root, scope, schemas)
    if boundary is not None:
        boundary.set_audit(
            "registry",
            lambda: _require_registry_snapshot(
                root,
                scope,
                registry,
                registry_sha256,
            ),
        )
    expected_revision = cast(int, journal["expected_registry_revision"])
    identity = cast(str, journal["registry_identity"])
    entry = cast(dict[str, Any], journal["registry_entry"])
    expected_sha256 = cast(str | None, journal["expected_registry_sha256"])
    next_sha256 = cast(str, journal["next_registry_sha256"])
    committed = (
        registry["revision"] == expected_revision + 1
        and registry_sha256 == next_sha256
        and registry["entries"].get(identity) == entry
    )
    pending = (
        registry["revision"] == expected_revision
        and registry_sha256 == expected_sha256
        and identity not in registry["entries"]
    )
    if not committed and not pending:
        raise _recovery_error("Installed registry conflicts with the journal.")

    paths = _journal_paths(root, journal)
    archive_visible = _lstat_optional(paths["archive"]) is not None
    installation_visible = _lstat_optional(paths["installation"]) is not None
    if committed:
        container, plan = _load_recovery_archive(
            paths["archive"],
            scope,
            journal,
            schemas,
            limits,
        )
        _require_recovered_installation(
            paths["installation"],
            container,
            journal,
        )
        actions = _cleanup_recovery_staging(paths, journal)
        if boundary is not None:
            boundary.remove_audit("journal")
        _remove_exact_journal(journal_path, journal)
        actions.append("removed_journal")
        return _recovery_result(
            scope,
            registry["revision"],
            recovered=True,
            prior_phase=prior_phase,
            final_phase="registry_published",
            actions=actions,
        )

    if not archive_visible and not installation_visible:
        if prior_phase != "prepared":
            raise _recovery_error("Journal phase requires visible install bytes.")
        actions = _cleanup_recovery_staging(paths, journal)
        if boundary is not None:
            boundary.remove_audit("journal")
        _remove_exact_journal(journal_path, journal)
        actions.append("removed_journal")
        return _recovery_result(
            scope,
            registry["revision"],
            recovered=True,
            prior_phase=prior_phase,
            final_phase="rolled_back",
            actions=actions,
        )
    if installation_visible and not archive_visible:
        raise _recovery_error("Visible installation has no exact archive.")

    container, plan = _load_recovery_archive(
        paths["archive"],
        scope,
        journal,
        schemas,
        limits,
    )
    actions: list[str] = []
    if installation_visible:
        _require_recovered_installation(
            paths["installation"],
            container,
            journal,
        )
    else:
        expected_identity = _journal_identity(
            journal["installation_staging_identity"]
        )
        _require_recovery_node(paths["installation_staging"], expected_identity)
        _validate_staged_installation(
            paths["installation_staging"],
            container,
            schemas,
            limits,
        )
        _rename_directory_no_replace(
            paths["installation_staging"],
            paths["installation"],
        )
        _fsync_directory(paths["installation"].parent)
        _require_recovery_node(paths["installation"], expected_identity)
        journal["phase"] = "installation_published"
        journal_identity = _write_journal(journal_path, journal)
        if boundary is not None:
            boundary.set_audit(
                "journal",
                lambda: _audit_journal(
                    journal_path,
                    journal_identity,
                    journal,
                ),
            )
        actions.append("published_installation")

    successor = _registry_successor(registry, plan, entry)
    if sha256(canonical_bytes(successor)).hexdigest() != next_sha256:
        raise _recovery_error("Journal registry successor is not reproducible.")
    _write_installed_registry_cas_locked(
        lock,
        expected_revision,
        expected_sha256,
        successor,
        schemas,
    )
    if boundary is not None:
        boundary.set_audit(
            "registry",
            lambda: _require_registry_snapshot(
                root,
                scope,
                successor,
                next_sha256,
            ),
        )
    journal["phase"] = "registry_published"
    journal_identity = _write_journal(journal_path, journal)
    if boundary is not None:
        boundary.set_audit(
            "journal",
            lambda: _audit_journal(
                journal_path,
                journal_identity,
                journal,
            ),
        )
    actions.append("published_registry")
    actions.extend(_cleanup_recovery_staging(paths, journal))
    if boundary is not None:
        boundary.remove_audit("journal")
    _remove_exact_journal(journal_path, journal)
    actions.append("removed_journal")
    return _recovery_result(
        scope,
        successor["revision"],
        recovered=True,
        prior_phase=prior_phase,
        final_phase="registry_published",
        actions=actions,
    )


def _remove_under_lock(
    root: Path,
    scope: InstallScope,
    lock: _RegistryLock,
    reference_lock: PersistenceLock,
    identity: str,
    schemas: _SchemaValidator,
    limits: KarcLimits,
) -> dict[str, Any]:
    if not lock.owns():
        raise _error(
            "KARC_REMOVE_CONFLICT",
            "Removal scope lock changed before the transaction began.",
        )
    journal_path = _journal_path(root, scope)
    if _lstat_optional(journal_path) is not None:
        raise _error(
            "KARC_INSTALL_RECOVERY_REQUIRED",
            "An unfinished scope journal must be recovered first.",
        )
    registry, registry_sha256 = _registry_state(root, scope, schemas)
    boundary = schemas if isinstance(schemas, _BoundarySchemas) else None
    if boundary is not None:
        boundary.set_audit(
            "registry",
            lambda: _require_registry_snapshot(
                root,
                scope,
                registry,
                registry_sha256,
                code="KARC_REMOVE_CONFLICT",
            ),
        )
        boundary.set_audit(
            "removal_lock",
            lambda: _require_removal_lock(lock),
        )
    removal_archive = _capture_removal_archive(
        root,
        identity,
        registry,
        limits,
    )
    if boundary is not None and removal_archive is not None:
        boundary.set_audit(
            "removal_archive",
            lambda: _require_removal_archive_unchanged(
                removal_archive,
                limits.max_archive_bytes,
            ),
        )
    plan, container, entry = _preview_removal(
        root,
        scope,
        identity,
        registry,
        schemas,
        limits,
        dry_run=False,
        persistence_lock=reference_lock,
    )
    reference_lock.assert_owned()
    _require_registry_current(lock, registry, registry_sha256, schemas)
    installation = root / "installed" / Path(entry["relative_path"])
    installation_identity = _capture_node_identity(installation, directory=True)
    removal_staging = installation.parent / (
        f".{installation.name}.{secrets.token_hex(8)}.removing"
    )
    successor = _detached(registry)
    successor["revision"] = registry["revision"] + 1
    del successor["entries"][identity]
    next_sha256 = sha256(canonical_bytes(successor)).hexdigest()
    journals = root / "registry" / "journals"
    _ensure_directory(journals)
    journal = _new_removal_journal(
        root,
        scope,
        plan,
        entry,
        registry_sha256,
        next_sha256,
        installation,
        removal_staging,
        installation_identity,
    )
    journal_identity = _write_journal(journal_path, journal, create=True)
    if boundary is not None:
        boundary.set_audit(
            "journal",
            lambda: _audit_journal(journal_path, journal_identity, journal),
        )
    _install_failure_point("removal_journal_created")

    reference_lock.assert_owned()
    _write_installed_registry_cas_locked(
        lock,
        registry["revision"],
        registry_sha256,
        successor,
        schemas,
        failure_hook=lambda name: _install_failure_point(f"removal_{name}"),
    )
    if boundary is not None:
        boundary.set_audit(
            "registry",
            lambda: _require_registry_snapshot(
                root,
                scope,
                successor,
                next_sha256,
                code="KARC_REMOVE_CONFLICT",
            ),
        )
    journal["phase"] = "registry_published"
    journal_identity = _write_journal(journal_path, journal)
    _install_failure_point("removal_registry_phase_recorded")

    _require_node_identity(installation, installation_identity)
    if not _installation_tree_matches(installation, container.member_payloads):
        raise _error(
            "KARC_INSTALL_RECOVERY_REQUIRED",
            "Installation changed after registry removal.",
        )
    _rename_directory_no_replace(installation, removal_staging)
    _fsync_directory(installation.parent)
    _require_node_identity(removal_staging, installation_identity)
    if boundary is not None:
        boundary.remove_audit("removal_installation")
    _install_failure_point("removal_installation_renamed")
    journal["phase"] = "installation_removed"
    journal_identity = _write_journal(journal_path, journal)

    _remove_recovery_tree(
        removal_staging,
        _identity_document(installation_identity),
    )
    _install_failure_point("removal_tree_cleaned")
    archive_removed = False
    if not _archive_is_referenced(root, plan["archive_sha256"], schemas):
        archive_path = root / "archives" / f"{plan['archive_sha256']}.karc"
        if boundary is not None:
            boundary.remove_audit("removal_archive")
        _remove_exact_archive(archive_path, plan["archive_sha256"], limits)
        archive_removed = True
    _install_failure_point("removal_archive_cleaned")
    if boundary is not None:
        boundary.remove_audit("journal")
    _remove_exact_journal(journal_path, journal)
    _install_failure_point("removal_cleanup_complete")
    plan["archive_removed"] = archive_removed
    plan["archive_will_be_removed"] = archive_removed
    return _detached(plan)


def _recover_removal_under_lock(
    root: Path,
    scope: InstallScope,
    lock: _RegistryLock,
    journal_path: Path,
    journal: dict[str, Any],
    schemas: _SchemaValidator,
    limits: KarcLimits,
) -> dict[str, Any]:
    from kokoroarc.persistence._storage import persistence_reference_lock

    if not lock.owns():
        raise _recovery_error("Removal scope lock changed during recovery.")
    boundary = schemas if isinstance(schemas, _BoundarySchemas) else None
    prior_phase = cast(str, journal["phase"])
    identity = cast(str, journal["registry_identity"])
    entry = cast(dict[str, Any], journal["registry_entry"])
    expected_revision = cast(int, journal["expected_registry_revision"])
    expected_sha256 = cast(str | None, journal["expected_registry_sha256"])
    next_sha256 = cast(str, journal["next_registry_sha256"])
    registry, registry_sha256 = _registry_state(root, scope, schemas)
    if boundary is not None:
        boundary.set_audit(
            "registry",
            lambda: _require_registry_snapshot(
                root,
                scope,
                registry,
                registry_sha256,
            ),
        )
    predecessor = (
        registry["revision"] == expected_revision
        and registry_sha256 == expected_sha256
        and registry["entries"].get(identity) == entry
    )
    successor_visible = (
        registry["revision"] == expected_revision + 1
        and registry_sha256 == next_sha256
        and identity not in registry["entries"]
    )
    actions: list[str] = []
    if predecessor:
        binding = _entry_binding(entry)
        try:
            with persistence_reference_lock(
                root,
                scope,
                cast(str, binding["namespace"]),
                cast(str, binding["character_id"]),
            ) as reference_lock:
                blockers = _reference_blockers(
                    root,
                    scope,
                    entry,
                    schemas,
                    container=_load_removal_archive(
                        root / "archives" / f"{entry['archive_sha256']}.karc",
                        scope,
                        entry,
                        schemas,
                        limits,
                    ),
                    persistence_lock=reference_lock,
                )
                if blockers:
                    raise _recovery_error(
                        "New references appeared before registry removal.",
                        references=blockers,
                    )
                successor = _detached(registry)
                successor["revision"] = expected_revision + 1
                del successor["entries"][identity]
                if sha256(canonical_bytes(successor)).hexdigest() != next_sha256:
                    raise _recovery_error(
                        "Removal registry successor is not reproducible."
                    )
                reference_lock.assert_owned()
                _write_installed_registry_cas_locked(
                    lock,
                    expected_revision,
                    expected_sha256,
                    successor,
                    schemas,
                )
                registry = successor
                if boundary is not None:
                    boundary.set_audit(
                        "registry",
                        lambda: _require_registry_snapshot(
                            root,
                            scope,
                            successor,
                            next_sha256,
                        ),
                    )
                journal["phase"] = "registry_published"
                journal_identity = _write_journal(journal_path, journal)
                if boundary is not None:
                    boundary.set_audit(
                        "journal",
                        lambda: _audit_journal(
                            journal_path,
                            journal_identity,
                            journal,
                        ),
                    )
                actions.append("published_registry")
        except KokoroError as error:
            if error.code.startswith("PERSISTENCE_"):
                raise _recovery_error(
                    "Persistent references could not be verified during recovery.",
                    reason=error.code,
                ) from error
            raise
    elif not successor_visible:
        raise _recovery_error("Installed registry conflicts with removal journal.")

    paths = _removal_journal_paths(root, journal)
    expected_identity = _journal_identity(journal["installation_identity"])
    installation_visible = _lstat_optional(paths["installation"]) is not None
    staging_visible = _lstat_optional(paths["removal_staging"]) is not None
    if installation_visible and staging_visible:
        raise _recovery_error("Removal has two visible installation trees.")
    if installation_visible or staging_visible:
        archive_path = root / "archives" / f"{journal['archive_sha256']}.karc"
        container = _load_removal_archive(
            archive_path,
            scope,
            entry,
            schemas,
            limits,
        )
        visible_path = (
            paths["installation"] if installation_visible else paths["removal_staging"]
        )
        _require_recovery_node(visible_path, expected_identity)
        if not _installation_tree_matches(visible_path, container.member_payloads):
            raise _recovery_error("Removal installation tree changed.")
    if installation_visible:
        _rename_directory_no_replace(
            paths["installation"],
            paths["removal_staging"],
        )
        _fsync_directory(paths["installation"].parent)
        _require_recovery_node(paths["removal_staging"], expected_identity)
        staging_visible = True
        actions.append("renamed_installation")
    if staging_visible:
        _remove_recovery_tree(
            paths["removal_staging"],
            journal["installation_identity"],
        )
        actions.append("removed_installation")
    journal["phase"] = "installation_removed"
    journal_identity = _write_journal(journal_path, journal)
    if boundary is not None:
        boundary.set_audit(
            "journal",
            lambda: _audit_journal(
                journal_path,
                journal_identity,
                journal,
            ),
        )

    archive_path = root / "archives" / f"{journal['archive_sha256']}.karc"
    archive_visible = _lstat_optional(archive_path) is not None
    referenced = _archive_is_referenced(
        root,
        cast(str, journal["archive_sha256"]),
        schemas,
    )
    if referenced and not archive_visible:
        raise _recovery_error("Referenced archive bytes are missing.")
    if archive_visible and not referenced:
        _remove_exact_archive(
            archive_path,
            cast(str, journal["archive_sha256"]),
            limits,
        )
        actions.append("removed_archive")
    if boundary is not None:
        boundary.remove_audit("journal")
    _remove_exact_journal(journal_path, journal)
    actions.append("removed_journal")
    return _recovery_result(
        scope,
        registry["revision"],
        recovered=True,
        prior_phase=prior_phase,
        final_phase="installation_removed",
        actions=actions,
    )


def _load_removal_archive(
    path: Path,
    scope: InstallScope,
    entry: dict[str, Any],
    schemas: _SchemaValidator,
    limits: KarcLimits,
) -> InspectedKarcContainer:
    payload = _read_optional_recovery_file(path, limits.max_archive_bytes)
    if payload is None or sha256(payload).hexdigest() != entry["archive_sha256"]:
        raise _recovery_error("Removal archive bytes are missing or changed.")
    try:
        container = inspect_karc_container(payload, limits=limits)
        load_karc_archive(payload, schemas, limits=limits)
    except Exception as error:
        raise _recovery_error(
            "Removal archive is not a current verified release.",
            reason=_reason(error),
        ) from error
    base = empty_installed_registry(scope)
    plan, expected_entry = _install_plan(container, scope, base)
    if expected_entry != entry or plan["archive_sha256"] != entry["archive_sha256"]:
        raise _recovery_error("Removal journal does not bind the archive.")
    return container


def _preview_removal(
    root: Path,
    scope: InstallScope,
    identity: str,
    registry: dict[str, Any],
    schemas: _SchemaValidator,
    limits: KarcLimits,
    *,
    dry_run: bool,
    persistence_lock: PersistenceLock | None = None,
) -> tuple[dict[str, Any], InspectedKarcContainer, dict[str, Any]]:
    entry = registry["entries"].get(identity)
    if not isinstance(entry, dict):
        raise _error(
            "KARC_REMOVE_NOT_FOUND",
            "The selected installation identity is not installed.",
        )
    container = _validate_installed_entry(
        root,
        scope,
        identity,
        registry,
        entry,
        schemas,
        limits,
    )
    blockers = _reference_blockers(
        root,
        scope,
        entry,
        schemas,
        container=container,
        persistence_lock=persistence_lock,
    )
    if blockers:
        raise _error(
            "KARC_REMOVE_REFERENCED",
            "The selected installation is still referenced.",
            references=blockers,
        )
    shared = _archive_is_referenced(
        root,
        entry["archive_sha256"],
        schemas,
        exclude=(scope, identity),
    )
    plan = {
        "schema_version": "1.0",
        "operation": "remove",
        "scope": scope.kind,
        "workspace_id": scope.workspace_id,
        "registry_identity": identity,
        "installation_id": entry["installation_id"],
        "archive_sha256": entry["archive_sha256"],
        "compiled_sha256": entry["compiled_sha256"],
        "relative_path": entry["relative_path"],
        "registry_revision_before": registry["revision"],
        "registry_revision_after": registry["revision"] + 1,
        "archive_will_be_removed": not shared,
        "archive_removed": False,
        "will_write": not dry_run,
        "activates_character": False,
    }
    return _detached(plan), container, _detached(entry)


def _removal_identity(
    namespace: str,
    character_id: str,
    character_version: str,
) -> str:
    values = (namespace, character_id)
    if any(
        not isinstance(value, str)
        or len(value) > 64
        or _SLUG_TOKEN.fullmatch(value) is None
        or value.casefold() in _PORTABLE_DEVICE_NAMES
        for value in values
    ):
        raise _error("KARC_REMOVE_IDENTITY_INVALID", "Removal identity is invalid.")
    if (
        not isinstance(character_version, str)
        or len(character_version) > 64
        or _SEMANTIC_VERSION.fullmatch(character_version) is None
    ):
        raise _error("KARC_REMOVE_IDENTITY_INVALID", "Removal version is invalid.")
    return f"{namespace}/{character_id}/{character_version}"


def _validate_installed_entry(
    root: Path,
    scope: InstallScope,
    identity: str,
    registry: dict[str, Any],
    entry: dict[str, Any],
    schemas: _SchemaValidator,
    limits: KarcLimits,
) -> InspectedKarcContainer:
    archive_path = root / "archives" / f"{entry['archive_sha256']}.karc"
    payload = _read_removal_file(archive_path, limits.max_archive_bytes)
    if sha256(payload).hexdigest() != entry["archive_sha256"]:
        raise _error(
            "KARC_REMOVE_STORAGE_INVALID",
            "Installed archive does not match its registry binding.",
        )
    try:
        container = inspect_karc_container(payload, limits=limits)
        load_karc_archive(payload, schemas, limits=limits)
    except Exception as error:
        raise _error(
            "KARC_REMOVE_STORAGE_INVALID",
            "Installed archive is not a current verified release.",
            reason=_reason(error),
        ) from error
    plan, expected_entry = _install_plan(container, scope, registry)
    if plan["registry_identity"] != identity or expected_entry != entry:
        raise _error(
            "KARC_REMOVE_STORAGE_INVALID",
            "Installed registry binding does not match the archive.",
        )
    installation = root / "installed" / Path(entry["relative_path"])
    if not _installation_tree_matches(installation, container.member_payloads):
        raise _error(
            "KARC_REMOVE_STORAGE_INVALID",
            "Installed member tree does not match the archive.",
        )
    return container


def _reference_blockers(
    root: Path,
    scope: InstallScope,
    entry: dict[str, Any],
    schemas: _SchemaValidator,
    *,
    container: InspectedKarcContainer | None = None,
    persistence_lock: PersistenceLock | None = None,
) -> list[str]:
    from kokoroarc.persistence._storage import persistence_reference_blockers

    blockers = set(
        _legacy_reference_blockers(
            root,
            scope,
            entry,
            schemas,
            session_hashes=_session_reference_hashes(entry, container),
        )
    )
    try:
        blockers.update(
            persistence_reference_blockers(
                root,
                scope,
                entry,
                schemas,
                _lock=persistence_lock,
            )
        )
    except KokoroError as error:
        raise _reference_scan_error(
            "Persistent character references could not be verified.",
            reason=error.code,
        ) from error
    if persistence_lock is not None and isinstance(schemas, _BoundarySchemas):
        schemas.set_audit(
            "persistent_references",
            persistence_lock.scope.boundary.assert_clean,
        )
    return sorted(blockers)


def _legacy_reference_blockers(
    root: Path,
    scope: InstallScope,
    entry: dict[str, Any],
    schemas: _SchemaValidator,
    *,
    session_hashes: frozenset[str] | None = None,
) -> list[str]:
    blockers: set[str] = set()
    exact_session_hashes = session_hashes or frozenset(
        {cast(str, entry["compiled_sha256"])}
    )
    config_path = (
        root / "config" / "global.json"
        if scope.kind == "global"
        else root / "config" / "workspaces" / f"{scope.workspace_id}.json"
    )
    config = _read_reference_document(
        config_path,
        "character-default-config",
        schemas,
        optional=True,
    )
    if config is not None and config.get("binding") == _entry_binding(entry):
        blockers.add("default")
    for session in _read_reference_directory(
        root / "sessions",
        _MAX_SESSION_REFERENCES,
        "session-manifest",
        schemas,
    ):
        if (
            session.get("active") is True
            and session.get("character_id") == _entry_character_id(entry)
            and session.get("character_version") == _entry_character_version(entry)
            and session.get("compiled_pack_hash") in exact_session_hashes
        ):
            blockers.add("active_session")
    for migration in _read_reference_directory(
        root / "migrations",
        _MAX_MIGRATION_REFERENCES,
        "pack-migration-plan",
        schemas,
    ):
        if entry["archive_sha256"] in {
            migration.get("input_archive_sha256"),
            migration.get("output_archive_sha256"),
        }:
            blockers.add("migration")
    return sorted(blockers)


def _session_reference_hashes(
    entry: dict[str, Any],
    container: InspectedKarcContainer | None,
) -> frozenset[str]:
    hashes = {cast(str, entry["compiled_sha256"])}
    if container is not None:
        compiled = container.documents.get("pack/compiled.json")
        source_hash = compiled.get("source_hash") if compiled is not None else None
        if (
            not isinstance(source_hash, str)
            or _HEX_SHA256.fullmatch(source_hash) is None
        ):
            raise _reference_scan_error(
                "Installed session binding could not be verified."
            )
        hashes.add(source_hash)
    return frozenset(hashes)


def _entry_binding(entry: dict[str, Any]) -> dict[str, Any]:
    identity = entry["relative_path"].split("/")[-2:]
    registry_parts = entry["compiled_artifact_id"].split("/")
    return {
        "installation_id": entry["installation_id"],
        "namespace": registry_parts[0],
        "character_id": identity[0],
        "character_version": identity[1],
        "archive_sha256": entry["archive_sha256"],
        "compiled_sha256": entry["compiled_sha256"],
    }


def _entry_character_id(entry: dict[str, Any]) -> str:
    return cast(str, entry["relative_path"].split("/")[-2])


def _entry_character_version(entry: dict[str, Any]) -> str:
    return cast(str, entry["relative_path"].split("/")[-1])


def _read_reference_directory(
    directory: Path,
    limit: int,
    schema_name: str,
    schemas: _SchemaValidator,
) -> list[dict[str, Any]]:
    linked = _lstat_optional(directory)
    if linked is None:
        return []
    if not stat.S_ISDIR(linked.st_mode) or _is_redirect(directory, linked):
        raise _reference_scan_error("Reference directory is unsafe.")
    paths: list[Path] = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if len(paths) >= limit:
                    raise _reference_scan_error(
                        "Reference directory exceeds its entry limit."
                    )
                path = Path(entry.path)
                path_stat = path.lstat()
                if (
                    not stat.S_ISREG(path_stat.st_mode)
                    or _is_redirect(path, path_stat)
                    or path.suffix != ".json"
                ):
                    raise _reference_scan_error(
                        "Reference directory contains an unsafe entry."
                    )
                paths.append(path)
    except KokoroError:
        raise
    except OSError as error:
        raise _reference_scan_error(
            "Reference directory could not be enumerated.",
            reason=type(error).__name__,
        ) from error
    return [
        cast(
            dict[str, Any],
            _read_reference_document(path, schema_name, schemas),
        )
        for path in sorted(paths, key=lambda value: value.name)
    ]


def _read_reference_document(
    path: Path,
    schema_name: str,
    schemas: _SchemaValidator,
    *,
    optional: bool = False,
) -> dict[str, Any] | None:
    if optional and _lstat_optional(path) is None:
        return None
    payload = _read_removal_file(path, _MAX_REFERENCE_BYTES)
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        if not isinstance(value, dict):
            raise ValueError("noncanonical reference")
        normalized = canonical_bytes(value)
        terminator = b""
        if payload != normalized:
            if schema_name != "session-manifest" or payload != normalized + b"\n":
                raise ValueError("noncanonical reference")
            terminator = b"\n"
        detached = cast(dict[str, Any], json.loads(payload))
        schemas.validate(schema_name, detached)
        if canonical_bytes(detached) + terminator != payload:
            raise ValueError("schema callback mutated reference")
        repeated = _read_removal_file(path, _MAX_REFERENCE_BYTES)
        if repeated != payload:
            raise ValueError("reference changed during validation")
    except Exception as error:
        raise _reference_scan_error(
            "Reference artifact is invalid or changed.",
            reason=_reason(error),
        ) from error
    return cast(dict[str, Any], json.loads(payload))


def _read_removal_file(path: Path, limit: int) -> bytes:
    try:
        payload = _read_optional_recovery_file(path, limit)
    except KokoroError as error:
        raise _error(
            "KARC_REMOVE_REFERENCE_SCAN_INVALID",
            "Removal input could not be read safely.",
            reason=error.code,
        ) from error
    if payload is None:
        raise _error(
            "KARC_REMOVE_REFERENCE_SCAN_INVALID",
            "Required removal input is missing.",
        )
    return payload


def _archive_is_referenced(
    root: Path,
    archive_sha256: str,
    schemas: _SchemaValidator,
    *,
    exclude: tuple[InstallScope, str] | None = None,
) -> bool:
    documents: list[dict[str, Any]] = []
    global_path = root / "registry" / "global.json"
    if _lstat_optional(global_path) is not None:
        document = _read_reference_document(
            global_path,
            "installed-pack-registry",
            schemas,
        )
        documents.append(cast(dict[str, Any], document))
    workspace_root = root / "registry" / "workspaces"
    linked = _lstat_optional(workspace_root)
    if linked is not None:
        if not stat.S_ISDIR(linked.st_mode) or _is_redirect(workspace_root, linked):
            raise _reference_scan_error("Workspace registry directory is unsafe.")
        paths: list[Path] = []
        seen = 0
        try:
            with os.scandir(workspace_root) as entries:
                for entry in entries:
                    seen += 1
                    if seen > _MAX_WORKSPACE_REGISTRIES:
                        raise _reference_scan_error(
                            "Workspace registry count exceeds its limit."
                        )
                    path = Path(entry.path)
                    path_stat = path.lstat()
                    safe_regular = stat.S_ISREG(path_stat.st_mode) and not _is_redirect(
                        path,
                        path_stat,
                    )
                    lock_scope = path.name[1:-5]
                    known_lock = (
                        path.name.startswith(".")
                        and path.name.endswith(".lock")
                        and _HEX_SHA256.fullmatch(lock_scope) is not None
                    )
                    if safe_regular and known_lock:
                        continue
                    if not safe_regular or path.suffix != ".json":
                        raise _reference_scan_error(
                            "Workspace registry directory has an unsafe entry."
                        )
                    paths.append(path)
        except KokoroError:
            raise
        except OSError as error:
            raise _reference_scan_error(
                "Workspace registries could not be enumerated.",
                reason=type(error).__name__,
            ) from error
        for path in sorted(paths, key=lambda value: value.name):
            document = _read_reference_document(
                path,
                "installed-pack-registry",
                schemas,
            )
            registry = cast(dict[str, Any], document)
            if (
                registry.get("scope") != "workspace"
                or registry.get("workspace_id") != path.stem
                or _HEX_SHA256.fullmatch(path.stem) is None
            ):
                raise _reference_scan_error(
                    "Workspace registry filename does not match its scope."
                )
            documents.append(registry)
    for registry in documents:
        for identity, entry in registry["entries"].items():
            if exclude is not None and _registry_exclusion_matches(
                registry,
                identity,
                exclude,
            ):
                continue
            if entry["archive_sha256"] == archive_sha256:
                return True
    return False


def _registry_exclusion_matches(
    registry: dict[str, Any],
    identity: str,
    exclude: tuple[InstallScope, str],
) -> bool:
    scope, excluded_identity = exclude
    return (
        identity == excluded_identity
        and registry.get("scope") == scope.kind
        and registry.get("workspace_id") == scope.workspace_id
    )


def _new_removal_journal(
    root: Path,
    scope: InstallScope,
    plan: dict[str, Any],
    entry: dict[str, Any],
    registry_sha256: str | None,
    next_registry_sha256: str,
    installation: Path,
    removal_staging: Path,
    installation_identity: _NodeIdentity,
) -> dict[str, Any]:
    return {
        "schema_version": _JOURNAL_VERSION,
        "operation": "remove",
        "phase": "prepared",
        "scope": scope.kind,
        "workspace_id": scope.workspace_id,
        "registry_identity": plan["registry_identity"],
        "archive_sha256": plan["archive_sha256"],
        "expected_registry_revision": plan["registry_revision_before"],
        "expected_registry_sha256": registry_sha256,
        "next_registry_sha256": next_registry_sha256,
        "registry_entry": _detached(entry),
        "installation_relative_path": installation.relative_to(root).as_posix(),
        "removal_staging_relative_path": (
            removal_staging.relative_to(root).as_posix()
        ),
        "installation_identity": _identity_document(installation_identity),
    }


def _remove_exact_archive(path: Path, digest: str, limits: KarcLimits) -> None:
    payload = _read_removal_file(path, limits.max_archive_bytes)
    if sha256(payload).hexdigest() != digest:
        raise _error(
            "KARC_INSTALL_RECOVERY_REQUIRED",
            "Archive changed before unreferenced cleanup.",
        )
    try:
        path.unlink()
        _fsync_directory(path.parent)
    except OSError as error:
        raise _error(
            "KARC_INSTALL_CLEANUP_FAILED",
            "Unreferenced archive could not be removed.",
            reason=type(error).__name__,
        ) from error


def _reference_scan_error(message: str, **details: Any) -> KokoroError:
    return _error("KARC_REMOVE_REFERENCE_SCAN_INVALID", message, **details)


def _recovery_result(
    scope: InstallScope,
    registry_revision: int,
    *,
    recovered: bool = False,
    prior_phase: str | None = None,
    final_phase: str | None = None,
    actions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "operation": "recover",
        "scope": scope.kind,
        "workspace_id": scope.workspace_id,
        "recovered": recovered,
        "prior_phase": prior_phase,
        "final_phase": final_phase,
        "registry_revision": registry_revision,
        "actions": [] if actions is None else list(actions),
    }


def _load_recovery_archive(
    path: Path,
    scope: InstallScope,
    journal: dict[str, Any],
    schemas: _SchemaValidator,
    limits: KarcLimits,
) -> tuple[InspectedKarcContainer, dict[str, Any]]:
    payload = _read_optional_recovery_file(path, limits.max_archive_bytes)
    if payload is None or sha256(payload).hexdigest() != journal["archive_sha256"]:
        raise _recovery_error("Visible archive does not match the journal.")
    try:
        container = inspect_karc_container(payload, limits=limits)
        load_karc_archive(payload, schemas, limits=limits)
    except Exception as error:
        raise _recovery_error(
            "Visible archive is not a current verified release.",
            reason=_reason(error),
        ) from error
    base = empty_installed_registry(scope)
    base["revision"] = journal["expected_registry_revision"]
    plan, entry = _install_plan(container, scope, base)
    bindings = {
        "registry_identity": plan["registry_identity"],
        "archive_sha256": plan["archive_sha256"],
        "manifest_sha256": plan["manifest_sha256"],
        "compiled_sha256": plan["compiled_sha256"],
        "installation_relative_path": f"installed/{plan['relative_path']}",
        "archive_relative_path": f"archives/{plan['archive_sha256']}.karc",
    }
    if any(journal[key] != value for key, value in bindings.items()):
        raise _recovery_error("Install journal does not bind the archive.")
    if journal["registry_entry"] != entry:
        raise _recovery_error("Install journal registry entry is invalid.")
    return container, plan


def _require_recovered_installation(
    path: Path,
    container: InspectedKarcContainer,
    journal: dict[str, Any],
) -> None:
    expected_identity = _journal_identity(
        journal["installation_staging_identity"]
    )
    _require_recovery_node(path, expected_identity)
    if not _installation_tree_matches(path, container.member_payloads):
        raise _recovery_error("Visible installation does not match the archive.")


def _installation_tree_matches(root: Path, members: dict[str, bytes]) -> bool:
    actual = _installed_files(root)
    return actual is not None and set(actual) == set(members) and all(
        _regular_file_matches(actual[path], payload)
        for path, payload in members.items()
    )


def _cleanup_recovery_staging(
    paths: dict[str, Path],
    journal: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    if _remove_recovery_tree(
        paths["installation_staging"],
        journal["installation_staging_identity"],
    ):
        actions.append("removed_installation_staging")
    if _remove_recovery_file(
        paths["archive_staging"],
        journal["archive_staging_identity"],
    ):
        actions.append("removed_archive_staging")
    return actions


def _remove_recovery_file(path: Path, value: Any) -> bool:
    if _lstat_optional(path) is None:
        return False
    expected = _journal_identity(value)
    _require_recovery_node(path, expected)
    try:
        path.unlink()
        _fsync_directory(path.parent)
    except OSError as error:
        raise _error(
            "KARC_INSTALL_CLEANUP_FAILED",
            "Recovery could not remove archive staging.",
            phase="archive_staging",
            reason=type(error).__name__,
        ) from error
    return True


def _remove_recovery_tree(path: Path, value: Any) -> bool:
    if _lstat_optional(path) is None:
        return False
    expected = _journal_identity(value)
    _require_recovery_node(path, expected)
    nodes: list[tuple[Path, _NodeIdentity, bool]] = []
    pending = [path]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if len(nodes) >= _MAX_INSTALLED_ENTRIES:
                        raise _recovery_error(
                            "Recovery staging exceeds the entry limit."
                        )
                    child = Path(entry.path)
                    identity = _capture_node_identity(child)
                    is_directory = identity.file_type == stat.S_IFDIR
                    if identity.file_type not in {stat.S_IFDIR, stat.S_IFREG}:
                        raise _recovery_error(
                            "Recovery staging contains an unsafe entry."
                        )
                    nodes.append((child, identity, is_directory))
                    if is_directory:
                        pending.append(child)
        except KokoroError:
            raise
        except OSError as error:
            raise _recovery_error(
                "Recovery staging could not be scanned safely.",
                reason=type(error).__name__,
            ) from error
    for child, identity, _is_directory in nodes:
        _require_recovery_node(child, identity)
    try:
        for child, identity, is_directory in sorted(
            nodes,
            key=lambda item: len(item[0].parts),
            reverse=True,
        ):
            _require_recovery_node(child, identity)
            child.rmdir() if is_directory else child.unlink()
        _require_recovery_node(path, expected)
        path.rmdir()
        _fsync_directory(path.parent)
    except KokoroError:
        raise
    except OSError as error:
        raise _error(
            "KARC_INSTALL_CLEANUP_FAILED",
            "Recovery could not remove installation staging.",
            phase="installation_staging",
            reason=type(error).__name__,
        ) from error
    return True


def _capture_removal_archive(
    root: Path,
    identity: str,
    registry: dict[str, Any],
    limits: KarcLimits,
) -> _CapturedArchive | None:
    entry = registry["entries"].get(identity)
    if entry is None:
        return None
    path = root / "archives" / f"{entry['archive_sha256']}.karc"
    try:
        return _capture_archive(path, limits.max_archive_bytes)
    except KokoroError as error:
        raise _error(
            "KARC_REMOVE_STORAGE_INVALID",
            "Installed archive could not be captured safely.",
            reason=error.code,
        ) from error


def _require_removal_archive_unchanged(
    captured: _CapturedArchive,
    limit: int,
) -> None:
    try:
        _require_archive_unchanged(captured, limit)
    except KokoroError as error:
        raise _error(
            "KARC_REMOVE_PATH_CHANGED",
            "Installed archive changed across a validation callback.",
            reason=error.code,
        ) from error


def _capture_archive(path: Path, limit: int) -> _CapturedArchive:
    descriptor = -1
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        linked = path.lstat()
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(linked.st_mode)
            or _is_redirect(path, linked)
            or _file_identity(linked) != _file_identity(opened)
            or int(linked.st_nlink) != 1
            or int(opened.st_nlink) != 1
        ):
            raise _error(
                "KARC_INSTALL_SOURCE_INVALID",
                "Archive source must be a stable regular file.",
            )
        if opened.st_size > limit:
            raise _error(
                "KARC_INSTALL_ARCHIVE_INVALID",
                "Archive source exceeds the installation byte limit.",
                limit="max_archive_bytes",
            )
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            payload = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
        final = path.lstat()
    except KokoroError:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise _error(
            "KARC_INSTALL_SOURCE_INVALID",
            "Archive source could not be captured safely.",
            reason=type(error).__name__,
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(payload) > limit:
        raise _error(
            "KARC_INSTALL_ARCHIVE_INVALID",
            "Archive source exceeds the installation byte limit.",
            limit="max_archive_bytes",
        )
    identities = tuple(
        _file_identity(value) for value in (linked, opened, after, final)
    )
    if len(set(identities)) != 1 or len(payload) != opened.st_size:
        raise _error(
            "KARC_INSTALL_SOURCE_CHANGED",
            "Archive source changed while it was being captured.",
        )
    return _CapturedArchive(path, payload, identities[0])


def _require_archive_unchanged(source: _CapturedArchive, limit: int) -> None:
    repeated = _capture_archive(source.path, limit)
    if repeated.identity != source.identity or repeated.payload != source.payload:
        raise _error(
            "KARC_INSTALL_SOURCE_CHANGED",
            "Archive source changed during installation.",
        )


def _capture_workspace(workspace_root: Path | None) -> _CapturedWorkspace | None:
    if workspace_root is None:
        return None
    path = _absolute_path(workspace_root)
    try:
        identity = _capture_node_identity(path, directory=True)
        canonical = os.path.normcase(str(path.resolve(strict=True)))
    except (KokoroError, OSError) as error:
        raise _error(
            "KARC_SCOPE_INVALID",
            "Workspace scope could not be captured safely.",
        ) from error
    return _CapturedWorkspace(path, canonical, identity)


def _capture_data_root(path: Path) -> _CapturedDataRoot:
    linked = _lstat_optional(path)
    existed = linked is not None
    if linked is not None and (
        not stat.S_ISDIR(linked.st_mode) or _is_redirect(path, linked)
    ):
        raise _error(
            "KARC_INSTALL_PATH_INVALID",
            "Install data root must be a regular non-link directory.",
        )
    try:
        ancestry = _capture_directory_chain(path if existed else path.parent)
    except KokoroError as error:
        raise _error(
            "KARC_INSTALL_PATH_INVALID",
            "Install data-root ancestry is unsafe.",
        ) from error
    return _CapturedDataRoot(path, existed, ancestry)


def _require_data_root_unchanged(captured: _CapturedDataRoot) -> None:
    if not _directory_chain_matches(captured.ancestry):
        raise _error(
            "KARC_INSTALL_PATH_CHANGED",
            "Install data-root ancestry changed during installation.",
        )
    linked = _lstat_optional(captured.path)
    if captured.existed:
        valid = linked is not None and stat.S_ISDIR(linked.st_mode)
        valid = valid and not _is_redirect(captured.path, linked)
    else:
        valid = linked is None
    if not valid:
        raise _error(
            "KARC_INSTALL_PATH_CHANGED",
            "Install data root changed during installation.",
        )


def _require_workspace_unchanged(workspace: _CapturedWorkspace) -> None:
    try:
        identity = _capture_node_identity(workspace.path, directory=True)
        canonical = os.path.normcase(str(workspace.path.resolve(strict=True)))
    except (KokoroError, OSError) as error:
        raise _error(
            "KARC_SCOPE_CHANGED",
            "Workspace scope changed during installation.",
        ) from error
    if identity != workspace.identity or canonical != workspace.canonical_path:
        raise _error(
            "KARC_SCOPE_CHANGED",
            "Workspace scope changed during installation.",
        )


def _require_registry_snapshot(
    root: Path,
    scope: InstallScope,
    registry: dict[str, Any],
    registry_sha256: str | None,
    *,
    code: str = "KARC_INSTALL_CONFLICT",
) -> None:
    path = root.joinpath(*scope.registry_relative_path.split("/"))
    if registry_sha256 is None:
        matches = _lstat_optional(path) is None
    else:
        payload = canonical_bytes(registry)
        matches = (
            sha256(payload).hexdigest() == registry_sha256
            and _regular_file_matches(path, payload)
        )
    if not matches:
        raise _error(
            code,
            "Installed registry changed across a validation callback.",
        )


def _require_registry_payload(
    path: Path,
    expected: bytes | None,
    code: str,
) -> None:
    try:
        current = _read_optional_regular_file(path)
    except KokoroError as error:
        raise _error(
            code,
            "Installed registry changed across a validation callback.",
        ) from error
    if current != expected:
        raise _error(
            code,
            "Installed registry changed across a validation callback.",
        )


def _require_removal_lock(lock: _RegistryLock) -> None:
    if not lock.owns():
        raise _error(
            "KARC_REMOVE_CONFLICT",
            "Removal scope lock changed across a validation callback.",
        )


def _require_recovery_lock(lock: _RegistryLock) -> None:
    if not lock.owns():
        raise _error(
            "KARC_INSTALL_RECOVERY_REQUIRED",
            "Recovery scope lock changed across a validation callback.",
        )


def _capture_optional_reference_file(path: Path) -> _CapturedOptionalFile:
    try:
        payload = _read_optional_recovery_file(path, _MAX_REFERENCE_BYTES)
    except KokoroError as error:
        raise _reference_scan_error(
            "Reference artifact could not be captured safely.",
            reason=error.code,
        ) from error
    return _CapturedOptionalFile(path, payload)


def _require_optional_reference_file(
    captured: _CapturedOptionalFile,
) -> None:
    try:
        payload = _read_optional_recovery_file(
            captured.path,
            _MAX_REFERENCE_BYTES,
        )
    except KokoroError as error:
        raise _reference_scan_error(
            "Reference artifact changed across a validation callback.",
            reason=error.code,
        ) from error
    if payload != captured.payload:
        raise _reference_scan_error(
            "Reference artifact changed across a validation callback."
        )


def _capture_reference_directory(
    path: Path,
    limit: int,
) -> _CapturedReferenceDirectory:
    linked = _lstat_optional(path)
    if linked is None:
        return _CapturedReferenceDirectory(path, limit, None, {})
    try:
        identity = _capture_node_identity(path, directory=True)
        entries: dict[str, bytes] = {}
        with os.scandir(path) as scanned:
            for entry in scanned:
                if len(entries) >= limit:
                    raise _reference_scan_error(
                        "Reference directory exceeds its entry limit."
                    )
                member = Path(entry.path)
                if member.parent != path or member.suffix != ".json":
                    raise _reference_scan_error(
                        "Reference directory contains an unsafe entry."
                    )
                payload = _read_optional_recovery_file(
                    member,
                    _MAX_REFERENCE_BYTES,
                )
                if payload is None:
                    raise _reference_scan_error(
                        "Reference directory entry disappeared."
                    )
                entries[member.name] = payload
        _require_node_identity(path, identity)
    except KokoroError as error:
        if error.code == "KARC_REMOVE_REFERENCE_SCAN_INVALID":
            raise
        raise _reference_scan_error(
            "Reference directory could not be captured safely.",
            reason=error.code,
        ) from error
    except OSError as error:
        raise _reference_scan_error(
            "Reference directory could not be captured safely.",
            reason=type(error).__name__,
        ) from error
    return _CapturedReferenceDirectory(path, limit, identity, entries)


def _require_reference_directory(
    captured: _CapturedReferenceDirectory,
) -> None:
    try:
        current = _capture_reference_directory(
            captured.path,
            captured.limit,
        )
    except KokoroError as error:
        raise _reference_scan_error(
            "Reference directory changed across a validation callback.",
            reason=error.code,
        ) from error
    if current != captured:
        raise _reference_scan_error(
            "Reference directory changed across a validation callback."
        )


def _selected_workspace_registry_name(scope: InstallScope) -> str | None:
    if scope.kind != "workspace":
        return None
    return PurePosixPath(scope.registry_relative_path).name


def _capture_workspace_registries(
    path: Path,
    excluded_name: str | None,
) -> _CapturedWorkspaceRegistries:
    linked = _lstat_optional(path)
    if linked is None:
        return _CapturedWorkspaceRegistries(path, excluded_name, None, {})
    try:
        identity = _capture_node_identity(path, directory=True)
        entries: dict[str, bytes] = {}
        seen = 0
        with os.scandir(path) as scanned:
            for entry in scanned:
                seen += 1
                if seen > _MAX_WORKSPACE_REGISTRIES:
                    raise _reference_scan_error(
                        "Workspace registry count exceeds its limit."
                    )
                member = Path(entry.path)
                if member.parent != path:
                    raise _reference_scan_error(
                        "Workspace registry directory has an unsafe entry."
                    )
                member_stat = member.lstat()
                safe_regular = stat.S_ISREG(
                    member_stat.st_mode
                ) and not _is_redirect(member, member_stat)
                lock_scope = member.name[1:-5]
                known_lock = (
                    member.name.startswith(".")
                    and member.name.endswith(".lock")
                    and _HEX_SHA256.fullmatch(lock_scope) is not None
                )
                known_selected_staging = (
                    excluded_name is not None
                    and member.name.startswith(f".{excluded_name}.")
                    and member.name.endswith(".tmp")
                )
                if safe_regular and (known_lock or known_selected_staging):
                    continue
                if (
                    not safe_regular
                    or member.suffix != ".json"
                    or _HEX_SHA256.fullmatch(member.stem) is None
                ):
                    raise _reference_scan_error(
                        "Workspace registry directory has an unsafe entry."
                    )
                if member.name == excluded_name:
                    continue
                payload = _read_optional_recovery_file(
                    member,
                    _MAX_REFERENCE_BYTES,
                )
                if payload is None:
                    raise _reference_scan_error(
                        "Workspace registry disappeared during capture."
                    )
                entries[member.name] = payload
        _require_node_identity(path, identity)
    except KokoroError as error:
        if error.code == "KARC_REMOVE_REFERENCE_SCAN_INVALID":
            raise
        raise _reference_scan_error(
            "Workspace registries could not be captured safely.",
            reason=error.code,
        ) from error
    except OSError as error:
        raise _reference_scan_error(
            "Workspace registries could not be captured safely.",
            reason=type(error).__name__,
        ) from error
    return _CapturedWorkspaceRegistries(
        path,
        excluded_name,
        identity,
        entries,
    )


def _require_workspace_registries(
    captured: _CapturedWorkspaceRegistries,
) -> None:
    try:
        current = _capture_workspace_registries(
            captured.path,
            captured.excluded_name,
        )
    except KokoroError as error:
        raise _reference_scan_error(
            "Workspace registries changed across a validation callback.",
            reason=error.code,
        ) from error
    if current != captured:
        raise _reference_scan_error(
            "Workspace registries changed across a validation callback."
        )


def _capture_installed_tree(
    path: Path,
    limits: KarcLimits,
    *,
    optional: bool = False,
) -> _CapturedInstalledTree | None:
    linked = _lstat_optional(path)
    if linked is None and optional:
        return None
    try:
        identity = _capture_node_identity(path, directory=True)
        files = _installed_files(path)
        if files is None:
            raise ValueError("unsafe installed tree")
        members: dict[str, bytes] = {}
        total = 0
        for relative, member_path in sorted(files.items()):
            payload = _read_optional_recovery_file(
                member_path,
                limits.max_member_bytes,
            )
            if payload is None:
                raise ValueError("missing installed member")
            total += len(payload)
            if total > limits.max_total_bytes:
                raise ValueError("installed tree exceeds its byte limit")
            members[relative] = payload
    except (KokoroError, OSError, ValueError) as error:
        raise _error(
            "KARC_REMOVE_STORAGE_INVALID",
            "Installed member tree could not be captured safely.",
        ) from error
    return _CapturedInstalledTree(path, identity, members)


def _require_installed_tree_unchanged(
    captured: _CapturedInstalledTree,
) -> None:
    try:
        _require_node_identity(captured.path, captured.identity)
    except KokoroError as error:
        raise _error(
            "KARC_REMOVE_PATH_CHANGED",
            "Installed tree identity changed across a validation callback.",
        ) from error
    if not _installation_tree_matches(captured.path, captured.members):
        raise _error(
            "KARC_REMOVE_PATH_CHANGED",
            "Installed tree bytes changed across a validation callback.",
        )


def _require_storage_ancestry(
    lock: _RegistryLock,
    ancestry: tuple[tuple[Any, ...], ...],
) -> None:
    if not lock.owns() or not all(
        _directory_chain_matches(chain) for chain in ancestry
    ):
        raise _error(
            "KARC_INSTALL_PATH_CHANGED",
            "Install storage ancestry changed across a validation callback.",
        )


def _audit_staging_archive(
    path: Path,
    identity: _NodeIdentity,
    payload: bytes,
) -> None:
    try:
        _require_node_identity(path, identity)
    except KokoroError as error:
        raise _error(
            "KARC_INSTALL_STAGING_INVALID",
            "Archive staging identity changed during validation.",
        ) from error
    if not _regular_file_matches(path, payload):
        raise _error(
            "KARC_INSTALL_STAGING_INVALID",
            "Archive staging bytes changed during validation.",
        )


def _audit_journal(
    path: Path,
    identity: _NodeIdentity,
    journal: dict[str, Any],
) -> None:
    try:
        _require_node_identity(path, identity)
    except KokoroError as error:
        raise _error(
            "KARC_INSTALL_JOURNAL_CHANGED",
            "Install journal identity changed during validation.",
        ) from error
    if not _regular_file_matches(path, canonical_bytes(journal)):
        raise _error(
            "KARC_INSTALL_JOURNAL_CHANGED",
            "Install journal bytes changed during validation.",
        )


def _audit_staging_installation(
    path: Path,
    identity: _NodeIdentity,
    members: dict[str, bytes],
) -> None:
    try:
        _require_node_identity(path, identity)
    except KokoroError as error:
        raise _error(
            "KARC_INSTALL_STAGING_INVALID",
            "Installation staging identity changed during validation.",
        ) from error
    if not _installation_tree_matches(path, members):
        raise _error(
            "KARC_INSTALL_STAGING_INVALID",
            "Installation staging bytes changed during validation.",
        )


def _audit_published_archive(
    path: Path,
    identity: _NodeIdentity,
    payload: bytes,
) -> None:
    if (
        _capture_node_identity(path, regular_file=True) != identity
        or not _regular_file_matches(path, payload)
    ):
        raise _error(
            "KARC_INSTALL_PATH_CHANGED",
            "Published archive changed during validation.",
        )


def _audit_published_installation(
    path: Path,
    identity: _NodeIdentity,
    members: dict[str, bytes],
) -> None:
    try:
        _require_node_identity(path, identity)
    except KokoroError as error:
        raise _error(
            "KARC_INSTALL_PATH_CHANGED",
            "Published installation identity changed during validation.",
        ) from error
    if not _installation_tree_matches(path, members):
        raise _error(
            "KARC_INSTALL_PATH_CHANGED",
            "Published installation bytes changed during validation.",
        )


def _prepare_storage_paths(
    root: Path,
    scope: InstallScope,
    plan: dict[str, Any],
) -> dict[str, Path]:
    archives = root / "archives"
    _ensure_directory(archives)
    installed = root / "installed"
    _ensure_directory(installed)
    installation = installed.joinpath(*plan["relative_path"].split("/"))
    cursor = installed
    for part in plan["relative_path"].split("/")[:-1]:
        cursor = cursor / part
        _ensure_directory(cursor)
    journals = root / "registry" / "journals"
    _ensure_directory(journals)
    journal = journals / (
        "global.json" if scope.kind == "global" else f"{scope.workspace_id}.json"
    )
    archive = archives / f"{plan['archive_sha256']}.karc"
    return {
        "archives": archives,
        "archive": archive,
        "installation_parent": installation.parent,
        "installation": installation,
        "journals": journals,
        "journal": journal,
    }


def _journal_path(root: Path, scope: InstallScope) -> Path:
    name = "global.json" if scope.kind == "global" else f"{scope.workspace_id}.json"
    return root / "registry" / "journals" / name


def _registry_successor(
    registry: dict[str, Any],
    plan: dict[str, Any],
    entry: dict[str, Any],
) -> dict[str, Any]:
    successor = _detached(registry)
    successor["revision"] = registry["revision"] + 1
    successor["entries"][plan["registry_identity"]] = _detached(entry)
    return successor


def _new_install_journal(
    root: Path,
    scope: InstallScope,
    plan: dict[str, Any],
    entry: dict[str, Any],
    registry_sha256: str | None,
    next_registry_sha256: str,
    archive_staging: Path,
    installation_staging: Path,
) -> dict[str, Any]:
    return {
        "schema_version": _JOURNAL_VERSION,
        "operation": "install",
        "phase": "prepared",
        "scope": scope.kind,
        "workspace_id": scope.workspace_id,
        "registry_identity": plan["registry_identity"],
        "archive_sha256": plan["archive_sha256"],
        "manifest_sha256": plan["manifest_sha256"],
        "compiled_sha256": plan["compiled_sha256"],
        "expected_registry_revision": plan["registry_revision_before"],
        "expected_registry_sha256": registry_sha256,
        "next_registry_sha256": next_registry_sha256,
        "registry_entry": _detached(entry),
        "archive_relative_path": f"archives/{plan['archive_sha256']}.karc",
        "installation_relative_path": f"installed/{plan['relative_path']}",
        "archive_staging_relative_path": archive_staging.relative_to(root).as_posix(),
        "installation_staging_relative_path": (
            installation_staging.relative_to(root).as_posix()
        ),
        "archive_staging_identity": None,
        "installation_staging_identity": None,
    }


def _parse_transaction_journal(
    payload: bytes,
    root: Path,
    scope: InstallScope,
) -> dict[str, Any]:
    try:
        probe = json.loads(
            payload,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (RecursionError, TypeError, ValueError) as error:
        raise _recovery_error("Scope journal is not canonical JSON.") from error
    if isinstance(probe, dict) and probe.get("operation") == "remove":
        return _parse_removal_journal(payload, root, scope)
    return _parse_install_journal(payload, root, scope)


def _parse_removal_journal(
    payload: bytes,
    root: Path,
    scope: InstallScope,
) -> dict[str, Any]:
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (RecursionError, TypeError, ValueError) as error:
        raise _recovery_error("Removal journal is not canonical JSON.") from error
    required = {
        "schema_version",
        "operation",
        "phase",
        "scope",
        "workspace_id",
        "registry_identity",
        "archive_sha256",
        "expected_registry_revision",
        "expected_registry_sha256",
        "next_registry_sha256",
        "registry_entry",
        "installation_relative_path",
        "removal_staging_relative_path",
        "installation_identity",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise _recovery_error("Removal journal has an invalid closed shape.")
    journal = cast(dict[str, Any], value)
    if canonical_bytes(journal) != payload:
        raise _recovery_error("Removal journal is not canonically encoded.")
    if (
        journal["schema_version"] != _JOURNAL_VERSION
        or journal["operation"] != "remove"
        or journal["phase"] not in _REMOVAL_PHASES
        or journal["scope"] != scope.kind
        or journal["workspace_id"] != scope.workspace_id
    ):
        raise _recovery_error("Removal journal does not match the selected scope.")
    revision = journal["expected_registry_revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise _recovery_error("Removal journal registry revision is invalid.")
    for field in ("archive_sha256", "next_registry_sha256"):
        if not isinstance(journal[field], str) or _HEX_SHA256.fullmatch(
            journal[field]
        ) is None:
            raise _recovery_error("Removal journal contains an invalid digest.")
    expected_sha256 = journal["expected_registry_sha256"]
    if expected_sha256 is not None and (
        not isinstance(expected_sha256, str)
        or _HEX_SHA256.fullmatch(expected_sha256) is None
    ):
        raise _recovery_error("Removal journal registry digest is invalid.")
    if not isinstance(journal["registry_identity"], str) or not isinstance(
        journal["registry_entry"], dict
    ):
        raise _recovery_error("Removal journal registry binding is invalid.")
    _safe_journal_relative(journal["installation_relative_path"])
    _safe_journal_relative(journal["removal_staging_relative_path"])
    _validate_journal_identity(journal["installation_identity"])
    if journal["installation_identity"] is None:
        raise _recovery_error("Removal journal has no installation identity.")
    paths = _removal_journal_paths(root, journal)
    entry_path = journal["registry_entry"].get("relative_path")
    if (
        not isinstance(entry_path, str)
        or journal["installation_relative_path"] != f"installed/{entry_path}"
    ):
        raise _recovery_error("Removal journal installation path is invalid.")
    if (
        paths["removal_staging"].parent != paths["installation"].parent
        or not paths["removal_staging"].name.startswith(
            f".{paths['installation'].name}."
        )
        or not paths["removal_staging"].name.endswith(".removing")
    ):
        raise _recovery_error("Removal journal staging path is invalid.")
    return _detached(journal)


def _removal_journal_paths(
    root: Path,
    journal: dict[str, Any],
) -> dict[str, Path]:
    return {
        "installation": root.joinpath(
            *_safe_journal_relative(journal["installation_relative_path"])
        ),
        "removal_staging": root.joinpath(
            *_safe_journal_relative(journal["removal_staging_relative_path"])
        ),
    }


def _parse_install_journal(
    payload: bytes,
    root: Path,
    scope: InstallScope,
) -> dict[str, Any]:
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (RecursionError, TypeError, ValueError) as error:
        raise _recovery_error("Install journal is not canonical JSON.") from error
    required = {
        "schema_version",
        "operation",
        "phase",
        "scope",
        "workspace_id",
        "registry_identity",
        "archive_sha256",
        "manifest_sha256",
        "compiled_sha256",
        "expected_registry_revision",
        "expected_registry_sha256",
        "next_registry_sha256",
        "registry_entry",
        "archive_relative_path",
        "installation_relative_path",
        "archive_staging_relative_path",
        "installation_staging_relative_path",
        "archive_staging_identity",
        "installation_staging_identity",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise _recovery_error("Install journal has an invalid closed shape.")
    journal = cast(dict[str, Any], value)
    if canonical_bytes(journal) != payload:
        raise _recovery_error("Install journal is not canonically encoded.")
    if (
        journal["schema_version"] != _JOURNAL_VERSION
        or journal["operation"] != "install"
        or journal["phase"] not in _INSTALL_PHASES
        or journal["scope"] != scope.kind
        or journal["workspace_id"] != scope.workspace_id
    ):
        raise _recovery_error("Install journal does not match the selected scope.")
    revision = journal["expected_registry_revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise _recovery_error("Install journal registry revision is invalid.")
    for field in (
        "archive_sha256",
        "manifest_sha256",
        "compiled_sha256",
        "next_registry_sha256",
    ):
        if not isinstance(journal[field], str) or _HEX_SHA256.fullmatch(
            journal[field]
        ) is None:
            raise _recovery_error("Install journal contains an invalid digest.")
    expected_sha256 = journal["expected_registry_sha256"]
    if expected_sha256 is not None and (
        not isinstance(expected_sha256, str)
        or _HEX_SHA256.fullmatch(expected_sha256) is None
    ):
        raise _recovery_error("Install journal registry digest is invalid.")
    if not isinstance(journal["registry_identity"], str) or not isinstance(
        journal["registry_entry"], dict
    ):
        raise _recovery_error("Install journal registry binding is invalid.")
    for field in (
        "archive_relative_path",
        "installation_relative_path",
        "archive_staging_relative_path",
        "installation_staging_relative_path",
    ):
        _safe_journal_relative(journal[field])
    _validate_journal_identity(journal["archive_staging_identity"])
    _validate_journal_identity(journal["installation_staging_identity"])
    paths = _journal_paths(root, journal)
    archive_name = f"{journal['archive_sha256']}.karc"
    if journal["archive_relative_path"] != f"archives/{archive_name}":
        raise _recovery_error("Install journal archive path is invalid.")
    entry_path = journal["registry_entry"].get("relative_path")
    if (
        not isinstance(entry_path, str)
        or journal["installation_relative_path"] != f"installed/{entry_path}"
    ):
        raise _recovery_error("Install journal installation path is invalid.")
    if (
        paths["archive_staging"].parent != paths["archive"].parent
        or not paths["archive_staging"].name.startswith(f".{archive_name}.")
        or not paths["archive_staging"].name.endswith(".staging")
    ):
        raise _recovery_error("Install journal archive staging path is invalid.")
    installation_name = paths["installation"].name
    if (
        paths["installation_staging"].parent
        != paths["installation"].parent
        or not paths["installation_staging"].name.startswith(
            f".{installation_name}."
        )
        or not paths["installation_staging"].name.endswith(".staging")
    ):
        raise _recovery_error(
            "Install journal installation staging path is invalid."
        )
    return _detached(journal)


def _safe_journal_relative(value: Any) -> tuple[str, ...]:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or "\\" in value
    ):
        raise _recovery_error("Install journal contains an invalid path.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise _recovery_error("Install journal path escapes storage.")
    return path.parts


def _journal_paths(root: Path, journal: dict[str, Any]) -> dict[str, Path]:
    return {
        "archive": root.joinpath(
            *_safe_journal_relative(journal["archive_relative_path"])
        ),
        "installation": root.joinpath(
            *_safe_journal_relative(journal["installation_relative_path"])
        ),
        "archive_staging": root.joinpath(
            *_safe_journal_relative(journal["archive_staging_relative_path"])
        ),
        "installation_staging": root.joinpath(
            *_safe_journal_relative(
                journal["installation_staging_relative_path"]
            )
        ),
    }


def _validate_journal_identity(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict) or set(value) != {
        "device",
        "inode",
        "file_type",
    }:
        raise _recovery_error("Install journal staging identity is invalid.")
    for item in value.values():
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise _recovery_error("Install journal staging identity is invalid.")
    if value["file_type"] not in {stat.S_IFREG, stat.S_IFDIR}:
        raise _recovery_error("Install journal staging type is invalid.")


def _journal_identity(value: Any) -> _NodeIdentity:
    _validate_journal_identity(value)
    if value is None:
        raise _recovery_error("Install journal has no captured staging identity.")
    return _NodeIdentity(value["device"], value["inode"], value["file_type"])


def _read_optional_recovery_file(path: Path, limit: int) -> bytes | None:
    linked = _lstat_optional(path)
    if linked is None:
        return None
    if (
        not stat.S_ISREG(linked.st_mode)
        or _is_redirect(path, linked)
        or int(linked.st_nlink) != 1
    ):
        raise _recovery_error("Recovery input is not a regular file.")
    descriptor = -1
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if _file_identity(linked) != _file_identity(opened) or opened.st_size > limit:
            raise _recovery_error("Recovery input changed or exceeds its limit.")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            payload = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
        final = path.lstat()
    except KokoroError:
        raise
    except OSError as error:
        raise _recovery_error(
            "Recovery input could not be read safely.",
            reason=type(error).__name__,
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    identities = tuple(
        _file_identity(value) for value in (linked, opened, after, final)
    )
    if (
        len(payload) > limit
        or len(payload) != opened.st_size
        or len(set(identities)) != 1
        or any(
            int(value.st_nlink) != 1
            for value in (linked, opened, after, final)
        )
    ):
        raise _recovery_error("Recovery input changed while it was read.")
    return payload


def _require_recovery_node(path: Path, expected: _NodeIdentity) -> None:
    try:
        current = _capture_node_identity(
            path,
            regular_file=expected.file_type == stat.S_IFREG,
            directory=expected.file_type == stat.S_IFDIR,
        )
    except KokoroError as error:
        raise _recovery_error(
            "Recovery path identity could not be confirmed.",
            reason=error.code,
        ) from error
    if current != expected:
        raise _recovery_error("Recovery path identity changed.")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate object key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _write_journal(
    path: Path,
    journal: dict[str, Any],
    *,
    create: bool = False,
) -> _NodeIdentity:
    allowed_phases = (
        _INSTALL_PHASES if journal.get("operation") == "install" else _REMOVAL_PHASES
    )
    if journal.get("phase") not in allowed_phases:
        raise _error(
            "KARC_INSTALL_JOURNAL_INVALID",
            "Install journal phase is invalid.",
        )
    payload = canonical_bytes(journal)
    staging: Path | None = path.with_name(
        f".{path.name}.{secrets.token_hex(8)}.tmp"
    )
    descriptor = -1
    staging_identity: _NodeIdentity | None = None
    published_identity: _NodeIdentity | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(staging, flags, 0o600)
        opened = os.fstat(descriptor)
        staging_identity = _NodeIdentity(
            int(opened.st_dev),
            int(opened.st_ino),
            stat.S_IFMT(opened.st_mode),
        )
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if create:
            os.link(staging, path, follow_symlinks=False)
            if (
                _capture_node_identity(staging, regular_file=True)
                != staging_identity
                or _capture_node_identity(path, regular_file=True)
                != staging_identity
            ):
                raise _error(
                    "KARC_INSTALL_JOURNAL_CHANGED",
                    "Install journal staging changed during publication.",
                )
            staging.unlink()
            staging = None
        else:
            os.replace(staging, path)
            if (
                _capture_node_identity(path, regular_file=True)
                != staging_identity
            ):
                raise _error(
                    "KARC_INSTALL_JOURNAL_CHANGED",
                    "Install journal staging changed during publication.",
                )
            staging = None
        _fsync_directory(path.parent)
        if not _regular_file_matches(path, payload):
            raise _error(
                "KARC_INSTALL_JOURNAL_CHANGED",
                "Published install journal bytes could not be confirmed.",
            )
        published_identity = _capture_node_identity(path, regular_file=True)
    except FileExistsError as error:
        raise _error(
            "KARC_INSTALL_RECOVERY_REQUIRED",
            "An unfinished install journal already exists.",
        ) from error
    except KokoroError:
        raise
    except OSError as error:
        raise _error(
            "KARC_INSTALL_JOURNAL_WRITE_FAILED",
            "Install journal could not be persisted.",
            reason=type(error).__name__,
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if staging is not None:
            _remove_journal_staging(staging, staging_identity)
    if published_identity is None:
        raise _error(
            "KARC_INSTALL_JOURNAL_WRITE_FAILED",
            "Install journal publication did not produce an identity.",
        )
    return published_identity


def _remove_journal_staging(
    path: Path,
    expected: _NodeIdentity | None,
) -> None:
    linked = _lstat_optional(path)
    if linked is None:
        raise _error(
            "KARC_INSTALL_CLEANUP_FAILED",
            "Journal staging cleanup could not confirm the generated node.",
            phase="journal_staging",
            reason="missing",
        )
    current = _NodeIdentity(
        int(linked.st_dev),
        int(linked.st_ino),
        stat.S_IFMT(linked.st_mode),
    )
    if (
        expected is None
        or current != expected
        or not stat.S_ISREG(linked.st_mode)
        or _is_redirect(path, linked)
    ):
        raise _error(
            "KARC_INSTALL_CLEANUP_FAILED",
            "Journal staging cleanup refused an unverified node.",
            phase="journal_staging",
            reason="identity_changed",
        )
    try:
        path.unlink()
        _fsync_directory(path.parent)
    except OSError as error:
        raise _error(
            "KARC_INSTALL_CLEANUP_FAILED",
            "Journal staging cleanup could not remove the generated node.",
            phase="journal_staging",
            reason=type(error).__name__,
        ) from error


def _write_staging_archive(path: Path, payload: bytes) -> _NodeIdentity:
    descriptor = -1
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        identity = _capture_node_identity(path, regular_file=True)
    except FileExistsError as error:
        raise _error(
            "KARC_INSTALL_CONFLICT",
            "Archive staging path already exists.",
        ) from error
    except KokoroError:
        raise
    except OSError as error:
        raise _error(
            "KARC_INSTALL_WRITE_FAILED",
            "Archive staging bytes could not be written.",
            reason=type(error).__name__,
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not _regular_file_matches(path, payload):
        raise _error(
            "KARC_INSTALL_WRITE_FAILED",
            "Archive staging bytes could not be verified.",
        )
    return identity


def _create_staging_directory(path: Path) -> _NodeIdentity:
    try:
        os.mkdir(path, 0o700)
        _fsync_directory(path.parent)
    except FileExistsError as error:
        raise _error(
            "KARC_INSTALL_CONFLICT",
            "Installation staging path already exists.",
        ) from error
    except OSError as error:
        raise _error(
            "KARC_INSTALL_WRITE_FAILED",
            "Installation staging directory could not be created.",
            reason=type(error).__name__,
        ) from error
    return _capture_node_identity(path, directory=True)


def _write_installed_members(root: Path, members: dict[str, bytes]) -> None:
    directories: set[Path] = {root}
    for relative, payload in sorted(members.items()):
        target = root.joinpath(*PurePosixPath(relative).parts)
        cursor = root
        for part in PurePosixPath(relative).parts[:-1]:
            cursor = cursor / part
            if cursor not in directories:
                try:
                    os.mkdir(cursor, 0o700)
                except OSError as error:
                    raise _error(
                        "KARC_INSTALL_WRITE_FAILED",
                        "Installed member directory could not be created.",
                        reason=type(error).__name__,
                    ) from error
                directories.add(cursor)
        _write_exclusive_member(target, payload)
    ordered_directories = sorted(
        directories,
        key=lambda value: len(value.parts),
        reverse=True,
    )
    for directory in ordered_directories:
        _fsync_directory(directory)


def _write_exclusive_member(path: Path, payload: bytes) -> None:
    descriptor = -1
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise _error(
            "KARC_INSTALL_WRITE_FAILED",
            "Installed member could not be written.",
            reason=type(error).__name__,
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _validate_staged_installation(
    root: Path,
    container: InspectedKarcContainer,
    schemas: _SchemaValidator,
    limits: KarcLimits,
) -> None:
    actual = _installed_files(root)
    expected = container.member_payloads
    if actual is None or set(actual) != set(expected):
        raise _error(
            "KARC_INSTALL_STAGING_INVALID",
            "Installation staging layout is not closed.",
        )
    if not all(
        _regular_file_matches(actual[path], payload)
        for path, payload in expected.items()
    ):
        raise _error(
            "KARC_INSTALL_STAGING_INVALID",
            "Installation staging bytes do not match the archive.",
        )
    load_karc_archive(_archive_bytes(container), schemas, limits=limits)
    if not all(
        _regular_file_matches(actual[path], payload)
        for path, payload in expected.items()
    ):
        raise _error(
            "KARC_INSTALL_STAGING_INVALID",
            "Installation staging changed during validation.",
        )


def _require_registry_current(
    lock: _RegistryLock,
    expected: dict[str, Any],
    expected_sha256: str | None,
    schemas: _SchemaValidator,
) -> None:
    current, current_sha256 = _registry_state(lock.root, lock.scope, schemas)
    if (
        current != expected
        or current_sha256 != expected_sha256
        or not lock.owns()
    ):
        raise _error(
            "KARC_INSTALL_CONFLICT",
            "Installed registry changed during installation.",
        )


def _require_transaction_current(
    source: _CapturedArchive,
    limits: KarcLimits,
    lock: _RegistryLock,
    registry: dict[str, Any],
    registry_sha256: str | None,
    schemas: _SchemaValidator,
    ancestry: tuple[tuple[Any, ...], ...],
) -> None:
    _require_registry_current(lock, registry, registry_sha256, schemas)
    _require_archive_unchanged(source, limits.max_archive_bytes)
    if not all(_directory_chain_matches(chain) for chain in ancestry):
        raise _error(
            "KARC_INSTALL_PATH_CHANGED",
            "Install storage ancestry changed during installation.",
        )


def _publish_archive(staging: Path, final: Path, payload: bytes) -> None:
    expected = _capture_node_identity(staging, regular_file=True)
    if not _regular_file_matches(staging, payload):
        raise _error(
            "KARC_INSTALL_STAGING_INVALID",
            "Archive staging changed before publication.",
        )
    created = False
    try:
        os.link(staging, final, follow_symlinks=False)
        created = True
    except FileExistsError:
        if not _regular_file_matches(final, payload):
            raise _error(
                "KARC_INSTALL_CONFLICT",
                "Content-addressed archive path contains different bytes.",
            )
    except OSError as error:
        raise _error(
            "KARC_INSTALL_WRITE_FAILED",
            "Content-addressed archive could not be published.",
            reason=type(error).__name__,
        ) from error
    if created and (
        _capture_node_identity(staging, regular_file=True) != expected
        or _capture_node_identity(final, regular_file=True) != expected
    ):
        raise _error(
            "KARC_INSTALL_RECOVERY_REQUIRED",
            "Published archive identity could not be confirmed.",
        )
    _remove_exact_staging(staging)
    if not _regular_file_matches(final, payload):
        raise _error(
            "KARC_INSTALL_RECOVERY_REQUIRED",
            "Published archive bytes could not be confirmed.",
        )
    _fsync_directory(final.parent)


def _rename_directory_no_replace(staging: Path, final: Path) -> None:
    try:
        if os.name == "nt":
            os.rename(staging, final)
        elif sys.platform.startswith("linux"):
            _linux_rename_no_replace(staging, final)
        elif sys.platform == "darwin":
            _darwin_rename_no_replace(staging, final)
        else:
            raise _error(
                "KARC_INSTALL_ATOMIC_UNAVAILABLE",
                "Atomic no-replace installation is unavailable.",
            )
    except FileExistsError as error:
        raise _error(
            "KARC_INSTALL_CONFLICT",
            "Installation target appeared before atomic publication.",
        ) from error
    except KokoroError:
        raise
    except OSError as error:
        raise _error(
            "KARC_INSTALL_WRITE_FAILED",
            "Installation directory could not be published atomically.",
            reason=type(error).__name__,
        ) from error


def _linux_rename_no_replace(staging: Path, final: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise _error(
            "KARC_INSTALL_ATOMIC_UNAVAILABLE",
            "Linux renameat2 is unavailable.",
        )
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    result = rename(
        -100,
        os.fsencode(staging),
        -100,
        os.fsencode(final),
        1,
    )
    if result == 0:
        return
    code = ctypes.get_errno()
    if code == errno.EEXIST:
        raise FileExistsError(code, os.strerror(code), final)
    if code in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
        raise _error(
            "KARC_INSTALL_ATOMIC_UNAVAILABLE",
            "Linux atomic no-replace rename is unavailable.",
        )
    raise OSError(code, os.strerror(code), final)


def _darwin_rename_no_replace(staging: Path, final: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameatx_np", None)
    if rename is None:
        raise _error(
            "KARC_INSTALL_ATOMIC_UNAVAILABLE",
            "macOS exclusive rename is unavailable.",
        )
    rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    result = rename(os.fsencode(staging), os.fsencode(final), 0x00000004)
    if result == 0:
        return
    code = ctypes.get_errno()
    if code == errno.EEXIST:
        raise FileExistsError(code, os.strerror(code), final)
    if code in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
        raise _error(
            "KARC_INSTALL_ATOMIC_UNAVAILABLE",
            "macOS atomic no-replace rename is unavailable.",
        )
    raise OSError(code, os.strerror(code), final)


def _capture_node_identity(
    path: Path,
    *,
    regular_file: bool = False,
    directory: bool = False,
) -> _NodeIdentity:
    try:
        path_stat = path.lstat()
    except OSError as error:
        raise _error(
            "KARC_INSTALL_PATH_CHANGED",
            "Install staging identity could not be captured.",
        ) from error
    if _is_redirect(path, path_stat):
        raise _error(
            "KARC_INSTALL_PATH_CHANGED",
            "Install staging path became a redirect.",
        )
    if regular_file and not stat.S_ISREG(path_stat.st_mode):
        raise _error(
            "KARC_INSTALL_PATH_CHANGED",
            "Archive staging path is not a regular file.",
        )
    if directory and not stat.S_ISDIR(path_stat.st_mode):
        raise _error(
            "KARC_INSTALL_PATH_CHANGED",
            "Installation staging path is not a directory.",
        )
    return _NodeIdentity(
        int(path_stat.st_dev),
        int(path_stat.st_ino),
        stat.S_IFMT(path_stat.st_mode),
    )


def _identity_document(identity: _NodeIdentity) -> dict[str, int]:
    return {
        "device": identity.device,
        "inode": identity.inode,
        "file_type": identity.file_type,
    }


def _require_node_identity(path: Path, expected: _NodeIdentity) -> None:
    current = _capture_node_identity(
        path,
        regular_file=expected.file_type == stat.S_IFREG,
        directory=expected.file_type == stat.S_IFDIR,
    )
    if current != expected:
        raise _error(
            "KARC_INSTALL_PATH_CHANGED",
            "Install staging identity changed during installation.",
        )


def _remove_exact_staging(path: Path) -> None:
    try:
        path.unlink()
    except OSError as error:
        raise _error(
            "KARC_INSTALL_CLEANUP_FAILED",
            "Archive staging file could not be removed.",
            reason=type(error).__name__,
        ) from error


def _remove_exact_journal(path: Path, journal: dict[str, Any]) -> None:
    if not _regular_file_matches(path, canonical_bytes(journal)):
        raise _error(
            "KARC_INSTALL_RECOVERY_REQUIRED",
            "Install journal changed before cleanup.",
        )
    try:
        path.unlink()
        _fsync_directory(path.parent)
    except OSError as error:
        raise _error(
            "KARC_INSTALL_CLEANUP_FAILED",
            "Completed install journal could not be removed.",
            reason=type(error).__name__,
        ) from error


def _install_plan(
    container: InspectedKarcContainer,
    scope: InstallScope,
    registry: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = container.manifest
    namespace = cast(str, manifest["namespace"])
    character_id = cast(str, manifest["character_id"])
    character_version = cast(str, manifest["character_version"])
    version_token = _installation_version_token(character_version)
    registry_identity = f"{namespace}/{character_id}/{character_version}"
    relative_path = (
        f"{scope.installed_relative_root}/{character_id}/{character_version}"
    )
    installation_id = (
        f"{namespace}.{character_id}.{version_token}."
        f"{container.archive_sha256[:8]}"
    )
    manifest_sha256 = sha256(canonical_bytes(manifest)).hexdigest()
    entry = {
        "installation_id": installation_id,
        "archive_sha256": container.archive_sha256,
        "manifest_sha256": manifest_sha256,
        "compiled_artifact_id": manifest["compiled_artifact_id"],
        "compiled_sha256": manifest["compiled_hash"],
        "visibility": manifest["visibility"],
        "promotion_status": "verified",
        "activation_allowed": True,
        "trust": "unsigned_local",
        "relative_path": relative_path,
    }
    plan = {
        "schema_version": "1.0",
        "operation": "install",
        "scope": scope.kind,
        "workspace_id": scope.workspace_id,
        "registry_identity": registry_identity,
        "installation_id": installation_id,
        "archive_sha256": container.archive_sha256,
        "manifest_sha256": manifest_sha256,
        "compiled_artifact_id": manifest["compiled_artifact_id"],
        "compiled_sha256": manifest["compiled_hash"],
        "visibility": manifest["visibility"],
        "relative_path": relative_path,
        "registry_revision_before": registry["revision"],
        "registry_revision_after": registry["revision"] + 1,
        "idempotent": False,
        "will_write": True,
        "activates_character": False,
    }
    return plan, entry


def _existing_installation_matches(
    root: Path,
    container: InspectedKarcContainer,
    plan: dict[str, Any],
) -> bool:
    archive_path = root / "archives" / f"{container.archive_sha256}.karc"
    expected_archive = _archive_bytes(container)
    if not _regular_file_matches(archive_path, expected_archive):
        return False
    install_root = root / "installed" / Path(plan["relative_path"])
    root_stat = _lstat_optional(install_root)
    if (
        root_stat is None
        or not stat.S_ISDIR(root_stat.st_mode)
        or _is_redirect(install_root, root_stat)
    ):
        return False
    expected = dict(container.member_payloads)
    actual = _installed_files(install_root)
    if actual is None or set(actual) != set(expected):
        return False
    return all(
        _regular_file_matches(actual[path], payload)
        for path, payload in expected.items()
    )


def _archive_bytes(container: InspectedKarcContainer) -> bytes:
    from kokoroarc.distribution.archive import _write_archive

    return _write_archive(dict(container.member_payloads))


def _installed_files(root: Path) -> dict[str, Path] | None:
    files: dict[str, Path] = {}
    pending = [root]
    seen = 0
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    seen += 1
                    if seen > _MAX_INSTALLED_ENTRIES:
                        return None
                    path = Path(entry.path)
                    linked = path.lstat()
                    if _is_redirect(path, linked):
                        return None
                    if stat.S_ISDIR(linked.st_mode):
                        pending.append(path)
                    elif stat.S_ISREG(linked.st_mode):
                        files[path.relative_to(root).as_posix()] = path
                    else:
                        return None
        except OSError:
            return None
    return files


def _regular_file_matches(path: Path, expected: bytes) -> bool:
    linked = _lstat_optional(path)
    if (
        linked is None
        or not stat.S_ISREG(linked.st_mode)
        or _is_redirect(path, linked)
        or int(linked.st_nlink) != 1
    ):
        return False
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            payload = handle.read(len(expected) + 1)
            after = os.fstat(handle.fileno())
        final = path.lstat()
    except OSError:
        return False
    identities = tuple(
        _file_identity(value) for value in (linked, opened, after, final)
    )
    return (
        len(set(identities)) == 1
        and all(
            int(value.st_nlink) == 1
            for value in (linked, opened, after, final)
        )
        and payload == expected
    )


def _installation_version_token(value: str) -> str:
    token = value.lower().replace("+", ".")
    if _STABLE_VERSION_TOKEN.fullmatch(token) is None:
        return sha256(value.encode("utf-8")).hexdigest()[:16]
    return token


def _compatibility_reasons(report: dict[str, Any]) -> list[str]:
    return sorted(
        {
            finding["code"]
            for check in report.get("checks", {}).values()
            if isinstance(check, dict)
            for finding in check.get("findings", [])
            if isinstance(finding, dict) and isinstance(finding.get("code"), str)
        }
    )[:32]


def _absolute_path(path: Path) -> Path:
    try:
        return Path(os.path.abspath(os.fspath(path)))
    except (OSError, TypeError, ValueError) as error:
        raise _error("KARC_INSTALL_PATH_INVALID", "Install path is invalid.") from error


def _lstat_optional(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise _error(
            "KARC_INSTALL_PATH_INVALID",
            "Install path could not be inspected.",
        ) from error


def _is_redirect(path: Path, path_stat: os.stat_result) -> bool:
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    probe = getattr(path, "is_junction", None)
    if probe is None:
        return False
    try:
        return bool(probe())
    except OSError:
        return True


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        stat.S_IFMT(value.st_mode),
        int(value.st_size),
        int(value.st_mtime_ns),
    )


def _detached(value: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(canonical_bytes(value)))


def _reason(error: BaseException) -> str:
    return error.code if isinstance(error, KokoroError) else type(error).__name__


def _error(code: str, message: str, **details: Any) -> KokoroError:
    return KokoroError(code, message, details=details)


def _recovery_error(message: str, **details: Any) -> KokoroError:
    return _error("KARC_INSTALL_RECOVERY_REQUIRED", message, **details)


def _install_failure_point(_name: str) -> None:
    """Internal deterministic interruption seam used by recovery tests."""


__all__ = [
    "install_karc_archive",
    "preview_karc_install",
    "recover_karc_installations",
    "remove_installed_pack",
]
