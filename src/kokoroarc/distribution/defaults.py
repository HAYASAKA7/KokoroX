"""Scoped character defaults with explicit-only activation semantics."""

from __future__ import annotations

from dataclasses import dataclass
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from typing import Any, Callable, Literal, Mapping, Protocol, cast

from kokoroarc import __version__
from kokoroarc.distribution.archive import (
    KarcLimits,
    inspect_karc_container,
    load_karc_archive,
)
from kokoroarc.distribution.registry import (
    InstallScope,
    load_installed_registry,
    resolve_install_scope,
)
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes


SelectionSource = Literal[
    "explicit",
    "active_session",
    "workspace_default",
    "global_default",
    "none",
]
_MAX_CONFIG_BYTES = 64 * 1024
_MAX_REGISTRY_BYTES = 2 * 1024 * 1024
_MAX_INSTALLED_ENTRIES = 32
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_SEMANTIC_VERSION = re.compile(
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
)
_LOCK_DELAYS = (0.0, 0.01, 0.02, 0.04, 0.08)
_LOCK_ERRNOS = frozenset(
    value
    for value in (
        getattr(errno, "EACCES", None),
        getattr(errno, "EAGAIN", None),
        getattr(errno, "EWOULDBLOCK", None),
        getattr(errno, "EDEADLK", None),
    )
    if value is not None
)
_LOCK_WINERRORS = frozenset({33, 36})
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
    """The schema capability required by the defaults domain."""

    def validate(self, name: str, instance: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class CharacterSelection:
    """One detached character-selection result without host paths."""

    source: SelectionSource
    installation_id: str | None = None
    namespace: str | None = None
    character_id: str | None = None
    character_version: str | None = None
    archive_sha256: str | None = None
    compiled_sha256: str | None = None

    @property
    def binding(self) -> dict[str, str] | None:
        """Return a fresh detached exact installation binding."""

        if self.source == "none":
            return None
        values = (
            self.installation_id,
            self.namespace,
            self.character_id,
            self.character_version,
            self.archive_sha256,
            self.compiled_sha256,
        )
        if not all(isinstance(value, str) for value in values):
            raise KokoroError(
                "KARC_DEFAULT_BINDING_INVALID",
                "Character default binding is invalid.",
            )
        return {
            "installation_id": cast(str, self.installation_id),
            "namespace": cast(str, self.namespace),
            "character_id": cast(str, self.character_id),
            "character_version": cast(str, self.character_version),
            "archive_sha256": cast(str, self.archive_sha256),
            "compiled_sha256": cast(str, self.compiled_sha256),
        }


@dataclass(frozen=True, slots=True)
class _DirectoryIdentity:
    path: Path
    device: int
    inode: int
    file_type: int


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    path: Path
    payload: bytes | None
    identity: tuple[int, int, int, int, int, int] | None


@dataclass(frozen=True, slots=True)
class _DefaultReadBoundary:
    root: Path
    root_existed: bool
    ancestry: tuple[_DirectoryIdentity, ...]
    file: _FileSnapshot
    workspace: tuple[_DirectoryIdentity, ...] | None
    workspace_path: Path | None
    workspace_canonical: str | None


@dataclass(frozen=True, slots=True)
class _InstalledTreeSnapshot:
    root: Path
    directories: tuple[_DirectoryIdentity, ...]
    files: tuple[_FileSnapshot, ...]


@dataclass(frozen=True, slots=True)
class _SelectedCompiledSnapshot:
    payload: bytes
    audits: tuple[Callable[[], None], ...]

    @property
    def compiled(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.payload))

    def audit(self) -> None:
        for audit in self.audits:
            audit()


@dataclass(slots=True)
class _ConfigLock:
    path: Path
    descriptor: int
    ancestry: tuple[_DirectoryIdentity, ...]
    identity: tuple[int, int, int, int, int, int]
    held: bool = True

    def __enter__(self) -> _ConfigLock:
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
        return (
            not _is_redirect(self.path, linked)
            and _file_identity(linked) == self.identity
            and _file_identity(opened) == self.identity
        )

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


class _BoundarySchemas:
    def __init__(
        self,
        delegate: SchemaValidator,
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


def empty_character_default(scope: InstallScope) -> dict[str, Any]:
    """Return the canonical in-memory representation of an absent default."""

    workspace_id = scope.workspace_id
    if scope.kind == "workspace":
        if workspace_id is None:
            raise ValueError("workspace scope requires a workspace ID")
        suffix = workspace_id[:8]
    else:
        suffix = "global"
    return {
        "schema_version": "1.0",
        "artifact_id": f"config/{suffix}/character-default",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "scope": scope.kind,
        "workspace_id": workspace_id,
        "revision": 0,
        "binding": None,
        "activation_policy": "explicit_only",
    }


def resolve_character_selection(
    data_root: Path,
    schemas: SchemaValidator,
    *,
    explicit_binding: Mapping[str, Any] | None = None,
    active_session_binding: Mapping[str, Any] | None = None,
    workspace_root: Path | None = None,
) -> CharacterSelection:
    """Resolve the highest-precedence present character without activation."""

    for source, candidate in (
        ("explicit", explicit_binding),
        ("active_session", active_session_binding),
    ):
        if candidate is not None:
            return _selection_from_binding(source, candidate, schemas)
    if workspace_root is not None:
        workspace_config = load_character_default(
            data_root,
            schemas,
            workspace_root=workspace_root,
        )
        if workspace_config["binding"] is not None:
            return _selection_from_config(
                "workspace_default",
                data_root,
                workspace_config,
                schemas,
                workspace_root=workspace_root,
            )
    global_config = load_character_default(data_root, schemas)
    if global_config["binding"] is not None:
        return _selection_from_config(
            "global_default",
            data_root,
            global_config,
            schemas,
        )
    return CharacterSelection(source="none")


def load_selected_compiled(
    data_root: Path,
    selection: CharacterSelection,
    schemas: SchemaValidator,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """Load the exact installed compiled artifact for one default selection."""

    snapshot = _load_selected_compiled_snapshot(
        data_root,
        selection,
        schemas,
        workspace_root=workspace_root,
    )
    snapshot.audit()
    return snapshot.compiled


def _load_selected_compiled_snapshot(
    data_root: Path,
    selection: CharacterSelection,
    schemas: SchemaValidator,
    *,
    workspace_root: Path | None = None,
) -> _SelectedCompiledSnapshot:
    """Retain exact source identities for an installed compiled artifact."""

    if selection.source not in {"workspace_default", "global_default"}:
        raise KokoroError(
            "KARC_DEFAULT_SELECTION_INVALID",
            "Character selection cannot load an installed default.",
        )
    if selection.source == "workspace_default" and workspace_root is None:
        raise KokoroError(
            "KARC_DEFAULT_SELECTION_INVALID",
            "Character selection cannot load an installed default.",
        )
    expected = selection.binding
    current = resolve_character_selection(
        data_root,
        schemas,
        workspace_root=workspace_root,
    )
    if current.source != selection.source or current.binding != expected:
        raise KokoroError(
            "KARC_DEFAULT_STALE",
            "Character default binding became stale.",
        )
    selected_workspace = (
        workspace_root if selection.source == "workspace_default" else None
    )
    root = _absolute_path(data_root)
    scope = resolve_install_scope(selected_workspace)
    config_snapshot = _read_optional_config(_default_path(root, scope))
    if config_snapshot.payload is None:
        raise KokoroError(
            "KARC_DEFAULT_STALE",
            "Character default binding became stale.",
        )
    stored = _parse_config(config_snapshot.payload)
    if stored.get("binding") != expected:
        raise KokoroError(
            "KARC_DEFAULT_STALE",
            "Character default binding became stale.",
        )

    def audit_config() -> None:
        current_config = _read_optional_config(config_snapshot.path)
        if (
            current_config.payload != config_snapshot.payload
            or current_config.identity != config_snapshot.identity
        ):
            raise KokoroError(
                "KARC_DEFAULT_INPUT_MUTATION",
                "Character default changed during compiled loading.",
            )

    audited = _BoundarySchemas(schemas, audit_config)
    compiled_results: list[dict[str, Any]] = []
    source_audits: list[Callable[[], None]] = [audit_config]
    verified = _resolve_installed_binding(
        data_root,
        cast(str, selection.character_id),
        audited,
        namespace=cast(str, selection.namespace),
        version=cast(str, selection.character_version),
        workspace_root=selected_workspace,
        boundary_audits=source_audits,
        compiled_results=compiled_results,
    )
    audited.raise_if_failed()
    if verified != expected or len(compiled_results) != 1:
        raise KokoroError(
            "KARC_DEFAULT_STALE",
            "Character default binding became stale.",
        )
    payload = canonical_bytes(compiled_results[0])
    snapshot = _SelectedCompiledSnapshot(
        payload=payload,
        audits=tuple(source_audits),
    )
    snapshot.audit()
    return snapshot


def _selection_from_config(
    source: SelectionSource,
    data_root: Path,
    config: dict[str, Any],
    schemas: SchemaValidator,
    *,
    workspace_root: Path | None = None,
) -> CharacterSelection:
    config_bytes = canonical_bytes(config)
    binding = config.get("binding")
    if not isinstance(binding, dict):
        raise KokoroError(
            "KARC_DEFAULT_BINDING_INVALID",
            "Character default binding is invalid.",
        )
    verified = _resolve_installed_binding(
        data_root,
        binding.get("character_id"),
        schemas,
        namespace=binding.get("namespace"),
        version=binding.get("character_version"),
        workspace_root=workspace_root,
    )
    if verified != binding:
        raise KokoroError(
            "KARC_DEFAULT_STALE",
            "Character default binding is stale.",
        )
    current = load_character_default(
        data_root,
        schemas,
        workspace_root=workspace_root,
    )
    if canonical_bytes(current) != config_bytes:
        raise KokoroError(
            "KARC_DEFAULT_INPUT_MUTATION",
            "Character default changed during resolution.",
        )
    return _selection_from_binding(source, verified, schemas)


def load_character_default(
    data_root: Path,
    schemas: SchemaValidator,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """Load one scoped default without creating an absent data root."""

    try:
        root = Path(os.path.abspath(os.fspath(data_root)))
    except (TypeError, ValueError, OSError) as error:
        raise KokoroError(
            "KARC_DEFAULT_PATH_UNSAFE",
            "Character default path is unsafe.",
        ) from error
    scope = resolve_install_scope(workspace_root)
    path = _default_path(root, scope)
    file_snapshot = _read_optional_config(path)
    boundary = _capture_read_boundary(
        root,
        file_snapshot,
        workspace_root,
        scope,
    )
    value = (
        empty_character_default(scope)
        if file_snapshot.payload is None
        else _parse_config(file_snapshot.payload)
    )
    payload = canonical_bytes(value)
    probe = json.loads(payload)
    audited = _BoundarySchemas(
        schemas,
        lambda: _require_read_boundary(boundary),
    )
    try:
        audited.validate("character-default-config", probe)
    except Exception as error:
        audited.raise_if_failed()
        raise KokoroError(
            "KARC_DEFAULT_CONFIG_INVALID",
            "Character default configuration is invalid.",
        ) from error
    if canonical_bytes(probe) != payload:
        raise KokoroError(
            "KARC_DEFAULT_INPUT_MUTATION",
            "Character default input changed during validation.",
        )
    _require_scope_document(value, scope)
    _require_read_boundary(boundary)
    return cast(dict[str, Any], json.loads(payload))


def set_character_default(
    data_root: Path,
    character_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    version: str | None = None,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """Atomically bind one exact eligible same-scope installation."""

    return _change_character_default(
        data_root,
        schemas,
        workspace_root=workspace_root,
        requested_character=character_id,
        namespace=namespace,
        version=version,
    )


def clear_character_default(
    data_root: Path,
    schemas: SchemaValidator,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """Atomically clear one scoped binding without activating anything."""

    root = _absolute_path(data_root)
    if not root.exists():
        return load_character_default(
            root,
            schemas,
            workspace_root=workspace_root,
        )
    return _change_character_default(
        root,
        schemas,
        workspace_root=workspace_root,
        requested_character=None,
        namespace=None,
        version=None,
    )


def _change_character_default(
    data_root: Path,
    schemas: SchemaValidator,
    *,
    workspace_root: Path | None,
    requested_character: str | None,
    namespace: str | None,
    version: str | None,
) -> dict[str, Any]:
    root = _absolute_path(data_root)
    scope = resolve_install_scope(workspace_root)
    parent = _ensure_config_parent(root, scope)
    source_audits: list[Callable[[], None]] = []
    with _acquire_config_lock(parent, scope) as lock:
        path = _default_path(root, scope)
        initial = _read_optional_config(path)
        current = load_character_default(
            root,
            schemas,
            workspace_root=workspace_root,
        )
        _require_write_boundary(lock, initial)
        if requested_character is None:
            binding = None
        else:
            if namespace is None:
                raise KokoroError(
                    "KARC_DEFAULT_BINDING_INVALID",
                    "Character default selection is invalid.",
                )
            binding = _resolve_installed_binding(
                root,
                requested_character,
                schemas,
                namespace=namespace,
                version=version,
                workspace_root=workspace_root,
                boundary_audits=source_audits,
            )
            _require_write_boundary(lock, initial)
            _require_source_audits(source_audits)
        if current["binding"] == binding:
            _require_write_boundary(lock, initial)
            if initial.payload is not None:
                _fsync_directory(parent)
            return _detached_object(current)
        successor = _detached_object(current)
        successor["revision"] += 1
        successor["binding"] = binding
        successor_bytes = canonical_bytes(successor)
        probe = json.loads(successor_bytes)
        audited = _BoundarySchemas(
            schemas,
            lambda: _require_default_write_inputs(
                lock,
                initial,
                source_audits,
            ),
        )
        try:
            audited.validate("character-default-config", probe)
            if canonical_bytes(probe) != successor_bytes:
                raise KokoroError(
                    "KARC_DEFAULT_INPUT_MUTATION",
                    "Character default input changed during validation.",
                )
            if requested_character is not None:
                latest = _resolve_installed_binding(
                    root,
                    requested_character,
                    audited,
                    namespace=cast(str, namespace),
                    version=version,
                    workspace_root=workspace_root,
                    boundary_audits=source_audits,
                )
                if latest != binding:
                    raise KokoroError(
                        "KARC_DEFAULT_STALE",
                        "Character default binding became stale.",
                    )
            _require_write_boundary(lock, initial)
            _require_source_audits(source_audits)
            _publish_config(path, successor_bytes, lock, initial)
            _fsync_directory(parent)
            if not lock.owns():
                raise KokoroError(
                    "KARC_DEFAULT_CONFLICT",
                    "Character default lock changed during publication.",
                )
            _require_source_audits(source_audits)
            published = _read_required_file(path, _MAX_CONFIG_BYTES)
            if published.payload != successor_bytes:
                raise KokoroError(
                    "KARC_DEFAULT_WRITE_FAILED",
                    "Character default configuration could not be published.",
                )
            _require_source_audits(source_audits)
        except Exception:
            audited.raise_if_failed()
            raise
        return _detached_object(successor)


def _resolve_installed_binding(
    data_root: Path,
    character_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    version: str | None = None,
    workspace_root: Path | None = None,
    limits: KarcLimits | None = None,
    boundary_audits: list[Callable[[], None]] | None = None,
    compiled_results: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Resolve and revalidate one exact same-scope installed release."""

    _require_slug(character_id)
    _require_slug(namespace)
    if version is not None and not _SEMANTIC_VERSION.fullmatch(version):
        raise KokoroError(
            "KARC_DEFAULT_BINDING_INVALID",
            "Character default selection is invalid.",
        )
    effective_limits = KarcLimits() if limits is None else limits
    root = _absolute_path(data_root)
    scope = resolve_install_scope(workspace_root)
    registry_path = root.joinpath(*scope.registry_relative_path.split("/"))
    try:
        registry_path.lstat()
    except FileNotFoundError as error:
        raise KokoroError(
            "KARC_DEFAULT_NOT_INSTALLED",
            "Character is not installed in the selected scope.",
        ) from error
    except OSError as error:
        raise KokoroError(
            "KARC_DEFAULT_STALE",
            "Installed character metadata is unavailable.",
        ) from error
    registry_snapshot = _read_required_file(
        registry_path,
        _MAX_REGISTRY_BYTES,
    )
    registry = _parse_registry_object(cast(bytes, registry_snapshot.payload))
    entries = registry.get("entries")
    if not isinstance(entries, dict) or len(entries) > 1_024:
        raise KokoroError(
            "KARC_DEFAULT_STALE",
            "Installed character metadata is stale.",
        )
    matches: list[tuple[str, dict[str, Any]]] = []
    if not all(isinstance(key, str) for key in entries):
        raise KokoroError(
            "KARC_DEFAULT_STALE",
            "Installed character metadata is stale.",
        )
    for identity, raw_entry in sorted(entries.items()):
        parts = identity.split("/")
        if len(parts) != 3 or not isinstance(raw_entry, dict):
            raise KokoroError(
                "KARC_DEFAULT_STALE",
                "Installed character metadata is stale.",
            )
        entry_namespace, entry_character, entry_version = parts
        if (
            entry_namespace == namespace
            and entry_character == character_id
            and (version is None or entry_version == version)
        ):
            matches.append((identity, cast(dict[str, Any], raw_entry)))
    if not matches:
        raise KokoroError(
            "KARC_DEFAULT_NOT_INSTALLED",
            "Character is not installed in the selected scope.",
        )
    if len(matches) != 1:
        raise KokoroError(
            "KARC_DEFAULT_AMBIGUOUS",
            "Character selection matches multiple installed releases.",
        )
    identity, entry = matches[0]
    archive_digest = entry.get("archive_sha256")
    relative_path = entry.get("relative_path")
    if (
        not isinstance(archive_digest, str)
        or re.fullmatch(r"[a-f0-9]{64}", archive_digest) is None
        or not _safe_relative_path(relative_path)
    ):
        raise KokoroError(
            "KARC_DEFAULT_STALE",
            "Installed character metadata is stale.",
        )
    archive_path = root / "archives" / f"{archive_digest}.karc"
    archive_snapshot = _read_required_file(
        archive_path,
        effective_limits.max_archive_bytes,
    )
    archive_payload = cast(bytes, archive_snapshot.payload)
    try:
        container = inspect_karc_container(
            archive_payload,
            limits=effective_limits,
        )
    except KokoroError as error:
        if error.code == "KARC_ARCHIVE_LIMIT_EXCEEDED":
            raise KokoroError(
                "KARC_DEFAULT_LIMIT_EXCEEDED",
                "Installed character data exceeds its limit.",
            ) from error
        raise KokoroError(
            "KARC_DEFAULT_STALE",
            "Installed character data is stale.",
        ) from error
    installed_root = root / "installed" / Path(cast(str, relative_path))
    installed_snapshot = _capture_installed_tree(
        installed_root,
        container.member_payloads,
        effective_limits,
    )
    compiled_payload = _installed_payload(
        installed_snapshot,
        "pack/compiled.json",
    )
    compiled = _parse_canonical_object(compiled_payload)
    root_chain = _capture_directory_chain(root)
    workspace_chain, workspace_path, workspace_canonical = _workspace_boundary(
        workspace_root,
        scope,
    )

    def audit() -> None:
        _require_file_snapshot(registry_snapshot)
        _require_file_snapshot(archive_snapshot)
        if not _directory_chain_matches(root_chain):
            raise KokoroError(
                "KARC_DEFAULT_PATH_UNSAFE",
                "Installed character path changed during validation.",
            )
        _require_workspace_boundary(
            workspace_chain,
            workspace_path,
            workspace_canonical,
        )
        _require_installed_snapshot(installed_snapshot)

    audited = _BoundarySchemas(schemas, audit)
    try:
        validated_registry = load_installed_registry(
            root,
            audited,
            workspace_root=workspace_root,
        )
        if canonical_bytes(validated_registry) != registry_snapshot.payload:
            raise KokoroError(
                "KARC_DEFAULT_INPUT_MUTATION",
                "Installed character input changed during validation.",
            )
        loaded = load_karc_archive(
            archive_payload,
            audited,
            limits=effective_limits,
        )
        _require_manifest_entry(identity, entry, container.manifest)
        compiled_probe = json.loads(compiled_payload)
        audited.validate("compiled-pack", compiled_probe)
        if canonical_bytes(compiled_probe) != compiled_payload:
            raise KokoroError(
                "KARC_DEFAULT_INPUT_MUTATION",
                "Installed character input changed during validation.",
            )
        _require_compiled_binding(entry, container.manifest, compiled)
        if loaded.archive_sha256 != entry["archive_sha256"]:
            raise KokoroError(
                "KARC_DEFAULT_STALE",
                "Installed character metadata is stale.",
            )
        audit()
    except Exception as error:
        audited.raise_if_failed()
        if isinstance(error, KokoroError):
            if error.code.startswith("KARC_DEFAULT_"):
                raise
            if error.code == "KARC_ARCHIVE_LIMIT_EXCEEDED":
                raise KokoroError(
                    "KARC_DEFAULT_LIMIT_EXCEEDED",
                    "Installed character data exceeds its limit.",
                ) from error
            if error.code == "KARC_INPUT_MUTATION":
                raise KokoroError(
                    "KARC_DEFAULT_INPUT_MUTATION",
                    "Installed character input changed during validation.",
                ) from error
        raise KokoroError(
            "KARC_DEFAULT_STALE",
            "Installed character data is stale.",
        ) from error
    namespace_value, character_value, version_value = identity.split("/")
    if boundary_audits is not None:
        boundary_audits.append(audit)
    if compiled_results is not None:
        compiled_results.append(_detached_object(compiled))
    return {
        "installation_id": cast(str, entry["installation_id"]),
        "namespace": namespace_value,
        "character_id": character_value,
        "character_version": version_value,
        "archive_sha256": cast(str, entry["archive_sha256"]),
        "compiled_sha256": cast(str, entry["compiled_sha256"]),
    }


def _absolute_path(value: Path) -> Path:
    try:
        return Path(os.path.abspath(os.fspath(value)))
    except (OSError, TypeError, ValueError) as error:
        raise KokoroError(
            "KARC_DEFAULT_PATH_UNSAFE",
            "Character default path is unsafe.",
        ) from error


def _detached_object(value: Mapping[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(canonical_bytes(dict(value))))


def _ensure_config_parent(root: Path, scope: InstallScope) -> Path:
    _require_safe_directory(root)
    config = root / "config"
    _ensure_directory(config)
    if scope.kind == "global":
        return config
    workspaces = config / "workspaces"
    _ensure_directory(workspaces)
    return workspaces


def _require_safe_directory(path: Path) -> None:
    try:
        value = path.lstat()
    except OSError as error:
        raise KokoroError(
            "KARC_DEFAULT_PATH_UNSAFE",
            "Character default directory is unsafe.",
        ) from error
    if not stat.S_ISDIR(value.st_mode) or _is_redirect(path, value):
        raise KokoroError(
            "KARC_DEFAULT_PATH_UNSAFE",
            "Character default directory is unsafe.",
        )
    _capture_directory_chain(path)


def _ensure_directory(path: Path) -> None:
    try:
        value = path.lstat()
    except FileNotFoundError:
        try:
            os.mkdir(path, 0o700)
            _fsync_directory(path.parent)
            value = path.lstat()
        except OSError as error:
            raise KokoroError(
                "KARC_DEFAULT_PATH_UNSAFE",
                "Character default directory could not be created.",
            ) from error
    except OSError as error:
        raise KokoroError(
            "KARC_DEFAULT_PATH_UNSAFE",
            "Character default directory is unsafe.",
        ) from error
    if not stat.S_ISDIR(value.st_mode) or _is_redirect(path, value):
        raise KokoroError(
            "KARC_DEFAULT_PATH_UNSAFE",
            "Character default directory is unsafe.",
        )


def _lock_name(scope: InstallScope) -> str:
    return (
        ".global.lock"
        if scope.kind == "global"
        else f".{scope.workspace_id}.lock"
    )


def _acquire_config_lock(parent: Path, scope: InstallScope) -> _ConfigLock:
    path = parent / _lock_name(scope)
    ancestry = _capture_directory_chain(parent)
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as error:
        raise KokoroError(
            "KARC_DEFAULT_LOCK_UNSAFE",
            "Character default lock is unavailable.",
        ) from error
    try:
        linked = path.lstat()
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(linked.st_mode)
            or _is_redirect(path, linked)
            or int(linked.st_nlink) != 1
            or _file_identity(linked) != _file_identity(opened)
        ):
            raise KokoroError(
                "KARC_DEFAULT_LOCK_UNSAFE",
                "Character default lock is unsafe.",
            )
        acquired = False
        for delay in _LOCK_DELAYS:
            if delay:
                time.sleep(delay)
            try:
                _lock_descriptor(descriptor)
                acquired = True
                break
            except OSError as error:
                if not _is_lock_contention(error):
                    raise
        if not acquired:
            raise KokoroError(
                "KARC_DEFAULT_LOCKED",
                "Character default configuration is busy.",
                retryable=True,
            )
        return _ConfigLock(
            path=path,
            descriptor=descriptor,
            ancestry=ancestry,
            identity=_file_identity(opened),
        )
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _require_write_boundary(
    lock: _ConfigLock,
    initial: _FileSnapshot,
) -> None:
    if not lock.owns():
        raise KokoroError(
            "KARC_DEFAULT_CONFLICT",
            "Character default lock changed during validation.",
        )
    current = _read_optional_config(initial.path)
    if current.payload != initial.payload or current.identity != initial.identity:
        raise KokoroError(
            "KARC_DEFAULT_CONFLICT",
            "Character default configuration changed concurrently.",
        )


def _require_source_audits(
    audits: list[Callable[[], None]],
) -> None:
    for audit in audits:
        audit()


def _require_default_write_inputs(
    lock: _ConfigLock,
    initial: _FileSnapshot,
    source_audits: list[Callable[[], None]],
) -> None:
    _require_write_boundary(lock, initial)
    _require_source_audits(source_audits)


def _publish_config(
    path: Path,
    payload: bytes,
    lock: _ConfigLock,
    initial: _FileSnapshot,
) -> None:
    descriptor = -1
    staging: Path | None = None
    staging_identity: tuple[int, int, int, int, int, int] | None = None
    staging_node_identity: tuple[int, int, int] | None = None
    try:
        descriptor, raw_staging = tempfile.mkstemp(
            prefix=f".{path.name}.staging-",
            dir=path.parent,
        )
        staging = Path(raw_staging)
        opened = os.fstat(descriptor)
        staging_node_identity = _node_identity(opened)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            staging_identity = _file_identity(os.fstat(handle.fileno()))
        _require_staging_identity(staging, staging_identity)
        _require_write_boundary(lock, initial)
        _require_staging_identity(staging, staging_identity)
        _require_write_boundary(lock, initial)
        if initial.payload is None:
            os.link(staging, path)
            staging.unlink()
        else:
            os.replace(staging, path)
        staging = None
    except FileExistsError as error:
        raise KokoroError(
            "KARC_DEFAULT_CONFLICT",
            "Character default configuration appeared concurrently.",
        ) from error
    except KokoroError:
        raise
    except OSError as error:
        raise KokoroError(
            "KARC_DEFAULT_WRITE_FAILED",
            "Character default configuration could not be published.",
        ) from error
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if staging is not None:
            _remove_staging(staging, staging_node_identity)


def _require_staging_identity(
    path: Path,
    identity: tuple[int, int, int, int, int, int] | None,
) -> None:
    try:
        linked = path.lstat()
    except OSError as error:
        raise KokoroError(
            "KARC_DEFAULT_INPUT_MUTATION",
            "Character default staging input changed.",
        ) from error
    if (
        identity is None
        or not stat.S_ISREG(linked.st_mode)
        or _is_redirect(path, linked)
        or int(linked.st_nlink) != 1
        or _file_identity(linked) != identity
    ):
        raise KokoroError(
            "KARC_DEFAULT_INPUT_MUTATION",
            "Character default staging input changed.",
        )


def _remove_staging(
    path: Path,
    identity: tuple[int, int, int] | None,
) -> None:
    try:
        current = path.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise KokoroError(
            "KARC_DEFAULT_CLEANUP_FAILED",
            "Character default staging cleanup failed.",
        ) from error
    if identity is None or _node_identity(current) != identity:
        raise KokoroError(
            "KARC_DEFAULT_CLEANUP_FAILED",
            "Character default staging cleanup failed.",
        )
    try:
        path.unlink()
    except OSError as error:
        raise KokoroError(
            "KARC_DEFAULT_CLEANUP_FAILED",
            "Character default staging cleanup failed.",
        ) from error


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
        error.errno in _LOCK_ERRNOS
        or getattr(error, "winerror", None) in _LOCK_WINERRORS
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
            raise KokoroError(
                "KARC_DEFAULT_DURABILITY_FAILED",
                "Character default durability could not be confirmed.",
            ) from error


def _require_slug(value: Any) -> None:
    if (
        not isinstance(value, str)
        or len(value) > 64
        or _SLUG.fullmatch(value) is None
    ):
        raise KokoroError(
            "KARC_DEFAULT_BINDING_INVALID",
            "Character default selection is invalid.",
        )


def _parse_registry_object(payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        canonical = canonical_bytes(value)
    except Exception as error:
        raise KokoroError(
            "KARC_DEFAULT_STALE",
            "Installed character metadata is stale.",
        ) from error
    if not isinstance(value, dict) or canonical != payload:
        raise KokoroError(
            "KARC_DEFAULT_STALE",
            "Installed character metadata is stale.",
        )
    return cast(dict[str, Any], value)


def _safe_relative_path(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or value.startswith("/")
        or "\\" in value
        or "//" in value
    ):
        return False
    return all(part not in {"", ".", ".."} for part in value.split("/"))


def _read_required_file(path: Path, limit: int) -> _FileSnapshot:
    try:
        linked = path.lstat()
    except OSError as error:
        raise KokoroError(
            "KARC_DEFAULT_STALE",
            "Installed character data is unavailable.",
        ) from error
    if (
        not stat.S_ISREG(linked.st_mode)
        or _is_redirect(path, linked)
        or int(linked.st_nlink) != 1
    ):
        raise KokoroError(
            "KARC_DEFAULT_PATH_UNSAFE",
            "Installed character path is unsafe.",
        )
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            payload = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
        final = path.lstat()
    except OSError as error:
        raise KokoroError(
            "KARC_DEFAULT_STALE",
            "Installed character data is unavailable.",
        ) from error
    if len(payload) > limit:
        raise KokoroError(
            "KARC_DEFAULT_LIMIT_EXCEEDED",
            "Installed character data exceeds its limit.",
        )
    identities = tuple(
        _file_identity(value) for value in (linked, opened, after, final)
    )
    if len(set(identities)) != 1:
        raise KokoroError(
            "KARC_DEFAULT_INPUT_MUTATION",
            "Installed character input changed while it was read.",
        )
    return _FileSnapshot(path=path, payload=payload, identity=identities[0])


def _require_file_snapshot(snapshot: _FileSnapshot) -> None:
    current = _read_required_file(
        snapshot.path,
        max(len(cast(bytes, snapshot.payload)), 1),
    )
    if current.payload != snapshot.payload or current.identity != snapshot.identity:
        raise KokoroError(
            "KARC_DEFAULT_INPUT_MUTATION",
            "Installed character input changed during validation.",
        )


def _workspace_boundary(
    workspace_root: Path | None,
    scope: InstallScope,
) -> tuple[
    tuple[_DirectoryIdentity, ...] | None,
    Path | None,
    str | None,
]:
    if workspace_root is None:
        return None, None, None
    path = _absolute_path(workspace_root)
    try:
        canonical = os.path.normcase(str(path.resolve(strict=True)))
    except OSError as error:
        raise KokoroError(
            "KARC_DEFAULT_PATH_UNSAFE",
            "Workspace path is unsafe.",
        ) from error
    if scope.workspace_id is None:
        raise KokoroError(
            "KARC_DEFAULT_SCOPE_MISMATCH",
            "Character default scope is invalid.",
        )
    return _capture_directory_chain(path), path, canonical


def _require_workspace_boundary(
    chain: tuple[_DirectoryIdentity, ...] | None,
    path: Path | None,
    canonical: str | None,
) -> None:
    if path is None:
        return
    try:
        current = os.path.normcase(str(path.resolve(strict=True)))
    except OSError as error:
        raise KokoroError(
            "KARC_DEFAULT_PATH_UNSAFE",
            "Workspace path changed during validation.",
        ) from error
    if chain is None or current != canonical or not _directory_chain_matches(chain):
        raise KokoroError(
            "KARC_DEFAULT_PATH_UNSAFE",
            "Workspace path changed during validation.",
        )


def _require_manifest_entry(
    identity: str,
    entry: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    namespace, character_id, version = identity.split("/")
    manifest_payload = canonical_bytes(manifest)
    expected = {
        "namespace": namespace,
        "character_id": character_id,
        "character_version": version,
        "archive_sha256": manifest.get("archive_sha256"),
    }
    if (
        manifest.get("namespace") != expected["namespace"]
        or manifest.get("character_id") != expected["character_id"]
        or manifest.get("character_version") != expected["character_version"]
        or entry.get("manifest_sha256") != sha256(manifest_payload).hexdigest()
        or entry.get("compiled_artifact_id")
        != manifest.get("compiled_artifact_id")
        or entry.get("compiled_sha256") != manifest.get("compiled_hash")
        or entry.get("activation_allowed") is not True
        or entry.get("promotion_status") != "verified"
    ):
        raise KokoroError(
            "KARC_DEFAULT_STALE",
            "Installed character metadata is stale.",
        )


def _capture_installed_tree(
    installation: Path,
    expected_payloads: Mapping[str, bytes],
    limits: KarcLimits,
) -> _InstalledTreeSnapshot:
    expected_paths = set(expected_payloads)
    found_files: dict[str, _FileSnapshot] = {}
    directories: list[_DirectoryIdentity] = []
    pending = [(installation, "")]
    entries_seen = 0
    while pending:
        directory, prefix = pending.pop()
        directory_identity = _capture_directory_chain(directory)[-1]
        directories.append(directory_identity)
        try:
            iterator = os.scandir(directory)
        except OSError as error:
            raise KokoroError(
                "KARC_DEFAULT_STALE",
                "Installed character tree is unavailable.",
            ) from error
        with iterator:
            for item in iterator:
                entries_seen += 1
                if entries_seen > _MAX_INSTALLED_ENTRIES:
                    raise KokoroError(
                        "KARC_DEFAULT_LIMIT_EXCEEDED",
                        "Installed character tree exceeds its limit.",
                    )
                relative = f"{prefix}/{item.name}" if prefix else item.name
                relative = relative.replace("\\", "/")
                item_path = directory / item.name
                try:
                    if item.is_symlink():
                        raise KokoroError(
                            "KARC_DEFAULT_PATH_UNSAFE",
                            "Installed character tree is unsafe.",
                        )
                    if item.is_dir(follow_symlinks=False):
                        pending.append((item_path, relative))
                    elif item.is_file(follow_symlinks=False):
                        if relative not in expected_paths:
                            raise KokoroError(
                                "KARC_DEFAULT_STALE",
                                "Installed character tree has unknown members.",
                            )
                        expected = expected_payloads[relative]
                        snapshot = _read_required_file(
                            item_path,
                            min(limits.max_member_bytes, len(expected)),
                        )
                        if snapshot.payload != expected:
                            raise KokoroError(
                                "KARC_DEFAULT_STALE",
                                "Installed character member is stale.",
                            )
                        found_files[relative] = snapshot
                    else:
                        raise KokoroError(
                            "KARC_DEFAULT_PATH_UNSAFE",
                            "Installed character tree is unsafe.",
                        )
                except OSError as error:
                    raise KokoroError(
                        "KARC_DEFAULT_PATH_UNSAFE",
                        "Installed character tree is unsafe.",
                    ) from error
    if set(found_files) != expected_paths:
        raise KokoroError(
            "KARC_DEFAULT_STALE",
            "Installed character tree is incomplete.",
        )
    return _InstalledTreeSnapshot(
        root=installation,
        directories=tuple(directories),
        files=tuple(found_files[path] for path in sorted(found_files)),
    )


def _require_installed_snapshot(snapshot: _InstalledTreeSnapshot) -> None:
    if any(not _directory_chain_matches((value,)) for value in snapshot.directories):
        raise KokoroError(
            "KARC_DEFAULT_PATH_UNSAFE",
            "Installed character tree changed during validation.",
        )
    for file_snapshot in snapshot.files:
        _require_file_snapshot(file_snapshot)


def _installed_payload(snapshot: _InstalledTreeSnapshot, suffix: str) -> bytes:
    for file_snapshot in snapshot.files:
        if file_snapshot.path.as_posix().endswith(suffix):
            return cast(bytes, file_snapshot.payload)
    raise KokoroError(
        "KARC_DEFAULT_STALE",
        "Installed compiled artifact is missing.",
    )


def _parse_canonical_object(payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
        canonical = canonical_bytes(value)
    except Exception as error:
        raise KokoroError(
            "KARC_DEFAULT_STALE",
            "Installed compiled artifact is invalid.",
        ) from error
    if not isinstance(value, dict) or canonical != payload:
        raise KokoroError(
            "KARC_DEFAULT_STALE",
            "Installed compiled artifact is invalid.",
        )
    return cast(dict[str, Any], value)


def _require_compiled_binding(
    entry: dict[str, Any],
    manifest: dict[str, Any],
    compiled: dict[str, Any],
) -> None:
    compiled_payload = canonical_bytes(compiled)
    if (
        compiled.get("artifact_id") != entry.get("compiled_artifact_id")
        or sha256(compiled_payload).hexdigest() != entry.get("compiled_sha256")
        or compiled.get("character_id") != manifest.get("character_id")
        or compiled.get("character_version") != manifest.get("character_version")
        or compiled.get("source_hash") != manifest.get("source_hash")
    ):
        raise KokoroError(
            "KARC_DEFAULT_STALE",
            "Installed compiled artifact is stale.",
        )


def _default_path(root: Path, scope: InstallScope) -> Path:
    if scope.kind == "global":
        return root / "config" / "global.json"
    return root / "config" / "workspaces" / f"{scope.workspace_id}.json"


def _read_optional_config(path: Path) -> _FileSnapshot:
    try:
        linked = path.lstat()
    except FileNotFoundError:
        return _FileSnapshot(path=path, payload=None, identity=None)
    except OSError as error:
        raise KokoroError(
            "KARC_DEFAULT_CONFIG_INVALID",
            "Character default configuration is invalid.",
        ) from error
    if (
        not stat.S_ISREG(linked.st_mode)
        or _is_redirect(path, linked)
        or int(linked.st_nlink) != 1
    ):
        raise KokoroError(
            "KARC_DEFAULT_PATH_UNSAFE",
            "Character default path is unsafe.",
        )
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            payload = handle.read(_MAX_CONFIG_BYTES + 1)
            after = os.fstat(handle.fileno())
        final = path.lstat()
    except OSError as error:
        raise KokoroError(
            "KARC_DEFAULT_CONFIG_INVALID",
            "Character default configuration is invalid.",
        ) from error
    if len(payload) > _MAX_CONFIG_BYTES:
        raise KokoroError(
            "KARC_DEFAULT_LIMIT_EXCEEDED",
            "Character default configuration exceeds its limit.",
        )
    identities = tuple(
        _file_identity(value) for value in (linked, opened, after, final)
    )
    if (
        len(set(identities)) != 1
        or any(int(value.st_nlink) != 1 for value in (linked, opened, after, final))
    ):
        raise KokoroError(
            "KARC_DEFAULT_INPUT_MUTATION",
            "Character default input changed while it was read.",
        )
    return _FileSnapshot(path=path, payload=payload, identity=identities[0])


def _parse_config(payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        canonical = canonical_bytes(value)
    except (
        KokoroError,
        RecursionError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as error:
        raise KokoroError(
            "KARC_DEFAULT_CONFIG_INVALID",
            "Character default configuration is invalid.",
        ) from error
    if not isinstance(value, dict) or canonical != payload:
        raise KokoroError(
            "KARC_DEFAULT_CONFIG_INVALID",
            "Character default configuration is invalid.",
        )
    return cast(dict[str, Any], value)


def _capture_read_boundary(
    root: Path,
    file_snapshot: _FileSnapshot,
    workspace_root: Path | None,
    scope: InstallScope,
) -> _DefaultReadBoundary:
    root_existed = root.exists()
    if root_existed:
        anchor = root
    else:
        anchor = _nearest_existing_directory(root)
    ancestry = _capture_directory_chain(
        file_snapshot.path.parent if file_snapshot.payload is not None else anchor
    )
    if workspace_root is None:
        workspace_path = None
        workspace_canonical = None
        workspace = None
    else:
        workspace_path = Path(os.path.abspath(os.fspath(workspace_root)))
        workspace_canonical = os.path.normcase(
            str(workspace_path.resolve(strict=True))
        )
        if scope.workspace_id is None:
            raise KokoroError(
                "KARC_DEFAULT_PATH_UNSAFE",
                "Character default path is unsafe.",
            )
        workspace = _capture_directory_chain(workspace_path)
    return _DefaultReadBoundary(
        root=root,
        root_existed=root_existed,
        ancestry=ancestry,
        file=file_snapshot,
        workspace=workspace,
        workspace_path=workspace_path,
        workspace_canonical=workspace_canonical,
    )


def _require_read_boundary(boundary: _DefaultReadBoundary) -> None:
    if boundary.root.exists() != boundary.root_existed:
        raise KokoroError(
            "KARC_DEFAULT_INPUT_MUTATION",
            "Character default input changed during validation.",
        )
    if not _directory_chain_matches(boundary.ancestry):
        raise KokoroError(
            "KARC_DEFAULT_PATH_UNSAFE",
            "Character default path changed during validation.",
        )
    current = _read_optional_config(boundary.file.path)
    if (
        current.payload != boundary.file.payload
        or current.identity != boundary.file.identity
    ):
        raise KokoroError(
            "KARC_DEFAULT_INPUT_MUTATION",
            "Character default input changed during validation.",
        )
    if boundary.workspace_path is not None:
        try:
            canonical = os.path.normcase(
                str(boundary.workspace_path.resolve(strict=True))
            )
        except OSError as error:
            raise KokoroError(
                "KARC_DEFAULT_PATH_UNSAFE",
                "Workspace identity changed during validation.",
            ) from error
        if (
            canonical != boundary.workspace_canonical
            or boundary.workspace is None
            or not _directory_chain_matches(boundary.workspace)
        ):
            raise KokoroError(
                "KARC_DEFAULT_PATH_UNSAFE",
                "Workspace identity changed during validation.",
            )


def _require_scope_document(value: dict[str, Any], scope: InstallScope) -> None:
    expected = empty_character_default(scope)
    if any(
        value.get(name) != expected[name]
        for name in ("artifact_id", "scope", "workspace_id", "activation_policy")
    ):
        raise KokoroError(
            "KARC_DEFAULT_SCOPE_MISMATCH",
            "Character default configuration has the wrong scope.",
        )


def _nearest_existing_directory(path: Path) -> Path:
    candidate = path
    while True:
        try:
            value = candidate.lstat()
        except FileNotFoundError:
            if candidate == candidate.parent:
                raise KokoroError(
                    "KARC_DEFAULT_PATH_UNSAFE",
                    "Character default ancestry is unsafe.",
                )
            candidate = candidate.parent
            continue
        except OSError as error:
            raise KokoroError(
                "KARC_DEFAULT_PATH_UNSAFE",
                "Character default ancestry is unsafe.",
            ) from error
        if not stat.S_ISDIR(value.st_mode) or _is_redirect(candidate, value):
            raise KokoroError(
                "KARC_DEFAULT_PATH_UNSAFE",
                "Character default ancestry is unsafe.",
            )
        return candidate


def _capture_directory_chain(path: Path) -> tuple[_DirectoryIdentity, ...]:
    result: list[_DirectoryIdentity] = []
    for directory in reversed((path, *path.parents)):
        try:
            value = directory.lstat()
        except OSError as error:
            raise KokoroError(
                "KARC_DEFAULT_PATH_UNSAFE",
                "Character default ancestry is unsafe.",
            ) from error
        if not stat.S_ISDIR(value.st_mode) or _is_redirect(directory, value):
            raise KokoroError(
                "KARC_DEFAULT_PATH_UNSAFE",
                "Character default ancestry is unsafe.",
            )
        result.append(
            _DirectoryIdentity(
                path=directory,
                device=int(value.st_dev),
                inode=int(value.st_ino),
                file_type=stat.S_IFMT(value.st_mode),
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


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        stat.S_IFMT(value.st_mode),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_nlink),
    )


def _node_identity(value: os.stat_result) -> tuple[int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        stat.S_IFMT(value.st_mode),
    )


def _is_redirect(path: Path, value: os.stat_result) -> bool:
    if stat.S_ISLNK(value.st_mode):
        return True
    probe = getattr(path, "is_junction", None)
    if probe is None:
        return False
    try:
        return bool(probe())
    except OSError as error:
        raise KokoroError(
            "KARC_DEFAULT_PATH_UNSAFE",
            "Character default path is unsafe.",
        ) from error


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate object key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite number")


def _selection_from_binding(
    source: SelectionSource,
    candidate: Mapping[str, Any],
    schemas: SchemaValidator,
) -> CharacterSelection:
    try:
        caller_bytes = canonical_bytes(dict(candidate))
        binding = json.loads(caller_bytes)
    except Exception as error:
        raise KokoroError(
            "KARC_DEFAULT_BINDING_INVALID",
            "Character default binding is invalid.",
        ) from error
    probe = empty_character_default(
        InstallScope(
            kind="global",
            workspace_id=None,
            installed_relative_root="global",
            registry_relative_path="registry/global.json",
        )
    )
    probe["revision"] = 1
    probe["binding"] = binding
    probe_bytes = canonical_bytes(probe)
    detached_probe = json.loads(probe_bytes)
    try:
        schemas.validate("character-default-config", detached_probe)
        if canonical_bytes(detached_probe) != probe_bytes:
            raise KokoroError(
                "KARC_DEFAULT_INPUT_MUTATION",
                "Character default input changed during validation.",
            )
        if canonical_bytes(dict(candidate)) != caller_bytes:
            raise KokoroError(
                "KARC_DEFAULT_INPUT_MUTATION",
                "Character default input changed during validation.",
            )
    except KokoroError as error:
        if error.code == "KARC_DEFAULT_INPUT_MUTATION":
            raise
        raise KokoroError(
            "KARC_DEFAULT_BINDING_INVALID",
            "Character default binding is invalid.",
        ) from error
    assert isinstance(binding, dict)
    return CharacterSelection(
        source=source,
        installation_id=binding["installation_id"],
        namespace=binding["namespace"],
        character_id=binding["character_id"],
        character_version=binding["character_version"],
        archive_sha256=binding["archive_sha256"],
        compiled_sha256=binding["compiled_sha256"],
    )


__all__ = [
    "CharacterSelection",
    "clear_character_default",
    "empty_character_default",
    "load_character_default",
    "load_selected_compiled",
    "resolve_character_selection",
    "set_character_default",
]
