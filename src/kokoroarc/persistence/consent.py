"""Explicit persistence consent lifecycle and active-write guards."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable, NoReturn, Sequence, cast

from kokoroarc import __version__
from kokoroarc.distribution.defaults import _resolve_installed_binding
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.persistence._storage import (
    ArtifactSnapshot,
    PersistenceBoundary,
    PersistenceLimits,
    PersistenceScope,
    SchemaValidator,
    _absolute_path,
    _acquire_character_lock,
    _limit_error,
    _lstat,
    _publish_new_file,
    _replace_file,
    open_persistence_scope,
    read_canonical_object,
    scan_canonical_directory,
    validate_and_finalize,
)


_PERMISSION_ORDER = (
    "relationship_state",
    "mood_state",
    "memory_references",
)
_PERMISSION_SET = frozenset(_PERMISSION_ORDER)


@dataclass(frozen=True, slots=True)
class ActiveConsent:
    """One exact active consent and its retained installation boundary."""

    consent_payload: bytes
    binding_payload: bytes
    compiled_payload: bytes
    permission: str
    _boundary: PersistenceBoundary

    @property
    def consent(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.consent_payload))

    @property
    def binding(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.binding_payload))

    @property
    def compiled(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.compiled_payload))

    def assert_clean(self) -> None:
        try:
            self._boundary.assert_clean()
        except KokoroError as error:
            _raise_active_audit_error(error)


@dataclass(frozen=True, slots=True)
class _ConsentState:
    current: ArtifactSnapshot
    history: tuple[ArtifactSnapshot, ...]


@dataclass(frozen=True, slots=True)
class _ResolvedInstallation:
    binding: dict[str, Any]
    binding_payload: bytes
    compiled: dict[str, Any]
    compiled_payload: bytes


@dataclass(frozen=True, slots=True)
class _AuditedSchemas:
    schemas: SchemaValidator
    boundary: PersistenceBoundary

    def validate(self, name: str, instance: Any) -> None:
        try:
            self.schemas.validate(name, instance)
        finally:
            self.boundary.assert_clean()


def grant_consent(
    data_root: Path,
    character_id: str,
    permissions: Sequence[str],
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    version: str | None = None,
    workspace_root: Path | None = None,
    expected_revision: int,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    """Grant or exactly replace persistent permissions for one installation."""

    return _consent_domain(
        lambda: _change_consent(
            data_root=data_root,
            character_id=character_id,
            permissions=permissions,
            schemas=schemas,
            namespace=namespace,
            version=version,
            workspace_root=workspace_root,
            expected_revision=expected_revision,
            revoke=False,
            consent_id=None,
            limits=limits,
        )
    )


def load_consent(
    data_root: Path,
    character_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any] | None:
    """Load one current consent without creating storage."""

    captured_workspace = _capture_workspace_root(workspace_root)

    def load() -> dict[str, Any] | None:
        scope = open_persistence_scope(
            data_root,
            schemas,
            namespace=namespace,
            character_id=character_id,
            workspace_root=captured_workspace,
            limits=limits,
        )
        state = _load_consent_state(scope)
        if state is None:
            scope.boundary.assert_clean()
            return None
        current = cast(dict[str, Any], json.loads(state.current.payload))
        resolved = _resolve_installation(
            scope,
            version=cast(str, current["installation"]["character_version"]),
            schemas=schemas,
            workspace_root=captured_workspace,
        )
        _require_exact_installation(current, resolved)
        scope.boundary.assert_clean()
        return cast(dict[str, Any], json.loads(state.current.payload))

    return _consent_domain(load)


def revoke_consent(
    data_root: Path,
    character_id: str,
    consent_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    workspace_root: Path | None = None,
    expected_revision: int,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    """Publish an idempotent revoked successor without erasing data."""

    return _consent_domain(
        lambda: _change_consent(
            data_root=data_root,
            character_id=character_id,
            permissions=(),
            schemas=schemas,
            namespace=namespace,
            version=None,
            workspace_root=workspace_root,
            expected_revision=expected_revision,
            revoke=True,
            consent_id=consent_id,
            limits=limits,
        )
    )


def _require_active_consent(
    data_root: Path,
    character_id: str,
    consent_id: str,
    consent_revision: int,
    permission: str,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> ActiveConsent:
    """Return an exact active-consent snapshot for one durable operation."""

    captured_workspace = _capture_workspace_root(workspace_root)

    def require() -> ActiveConsent:
        scope = open_persistence_scope(
            data_root,
            schemas,
            namespace=namespace,
            character_id=character_id,
            workspace_root=captured_workspace,
            limits=limits,
        )
        state = _load_consent_state(scope)
        if state is None:
            raise _consent_not_found()
        current = cast(dict[str, Any], json.loads(state.current.payload))
        if current["consent_id"] != consent_id:
            raise _consent_conflict("consent_id")
        if current["status"] != "active":
            raise _consent_revoked()
        if current["grant_revision"] != consent_revision:
            raise _consent_conflict("grant_revision")
        if permission not in current["permissions"]:
            raise _permission_denied()
        resolved = _resolve_installation(
            scope,
            version=cast(str, current["installation"]["character_version"]),
            schemas=schemas,
            workspace_root=captured_workspace,
        )
        _require_exact_installation(current, resolved)
        scope.boundary.assert_clean()
        return ActiveConsent(
            consent_payload=state.current.payload,
            binding_payload=resolved.binding_payload,
            compiled_payload=resolved.compiled_payload,
            permission=permission,
            _boundary=scope.boundary,
        )

    return _consent_domain(require)


def _change_consent(
    *,
    data_root: Path,
    character_id: str,
    permissions: Sequence[str],
    schemas: SchemaValidator,
    namespace: str,
    version: str | None,
    workspace_root: Path | None,
    expected_revision: int,
    revoke: bool,
    consent_id: str | None,
    limits: PersistenceLimits,
) -> dict[str, Any]:
    _require_expected_revision(expected_revision)
    workspace_root = _capture_workspace_root(workspace_root)
    scope = open_persistence_scope(
        data_root,
        schemas,
        namespace=namespace,
        character_id=character_id,
        workspace_root=workspace_root,
        limits=limits,
    )
    normalized_permissions: tuple[str, ...] = ()
    resolved: _ResolvedInstallation | None = None
    if revoke:
        if not isinstance(consent_id, str):
            raise _consent_invalid("consent_id")
        initial = _load_consent_state(scope)
        if initial is None:
            raise _consent_not_found()
        initial_value = initial.current.value
        resolved = _resolve_installation(
            scope,
            version=cast(
                str,
                initial_value["installation"]["character_version"],
            ),
            schemas=schemas,
            workspace_root=workspace_root,
        )
        _require_exact_installation(initial_value, resolved)
    else:
        normalized_permissions = _capture_permissions(scope, permissions)
        resolved = _resolve_installation(
            scope,
            version=version,
            schemas=schemas,
            workspace_root=workspace_root,
        )

    with _acquire_character_lock(scope) as lock:
        state = _load_consent_state(scope)
        if revoke and state is None:
            raise _consent_not_found()
        current = None if state is None else state.current.value
        lifecycle_revision = (
            0 if current is None else _lifecycle_revision(current)
        )
        if lifecycle_revision != expected_revision:
            raise _consent_conflict("expected_revision")
        if revoke:
            assert current is not None
            assert consent_id is not None
            assert resolved is not None
            _require_exact_installation(current, resolved)
            if current["consent_id"] != consent_id:
                raise _consent_conflict("consent_id")
            if current["status"] == "revoked":
                lock.assert_owned()
                scope.boundary.assert_clean()
                return _detached(current)
            if len(state.history) >= limits.max_consent_history:
                raise _limit_error(
                    "consent_history",
                    limits.max_consent_history,
                )
            successor = _revoked_successor(
                scope,
                current,
                lifecycle_revision + 1,
            )
        else:
            assert resolved is not None
            if current is not None and _same_grant_intent(
                current,
                normalized_permissions,
                resolved.binding,
            ):
                lock.assert_owned()
                scope.boundary.assert_clean()
                return _detached(current)
            if (
                state is not None
                and len(state.history) >= limits.max_consent_history
            ):
                raise _limit_error(
                    "consent_history",
                    limits.max_consent_history,
                )
            successor = _active_successor(
                scope,
                normalized_permissions,
                resolved.binding,
                lifecycle_revision + 1,
            )
        payload = canonical_bytes(successor)
        if len(payload) > limits.max_consent_bytes:
            raise _consent_invalid("consent_bytes")
        successor = validate_and_finalize(
            "persistence-consent",
            successor,
            scope.boundary,
        )
        payload = canonical_bytes(successor)
        lock.assert_owned()
        _drop_consent_audits(scope)
        consent_root = scope.character_root("consents")
        history_path = consent_root / "history" / _history_name(
            lifecycle_revision + 1
        )
        _publish_new_file(scope, history_path, payload, lock)
        _replace_file(scope, consent_root / "current.json", payload, lock)
        confirmed = _load_consent_state(scope)
        if (
            confirmed is None
            or confirmed.current.payload != payload
            or len(confirmed.history) != lifecycle_revision + 1
        ):
            raise _consent_invalid("publication_confirmation")
        lock.assert_owned()
        scope.boundary.assert_clean()
        return cast(dict[str, Any], json.loads(payload))


def _capture_permissions(
    scope: PersistenceScope,
    permissions: Sequence[str],
) -> tuple[str, ...]:
    try:
        payload = scope.boundary.capture("permissions", permissions)
        value = json.loads(payload)
    except (KokoroError, TypeError, ValueError, UnicodeError) as error:
        raise _consent_invalid("permissions") from error
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) for item in value)
        or len(set(value)) != len(value)
        or any(item not in _PERMISSION_SET for item in value)
    ):
        raise _consent_invalid("permissions")
    requested = frozenset(cast(list[str], value))
    return tuple(item for item in _PERMISSION_ORDER if item in requested)


def _load_consent_state(scope: PersistenceScope) -> _ConsentState | None:
    root = scope.character_root("consents")
    try:
        current = read_canonical_object(
            root / "current.json",
            limit=scope.limits.max_consent_bytes,
            schema_name="persistence-consent",
            boundary=scope.boundary,
            optional=True,
        )
        if current is None:
            if _lstat(root) is not None:
                raise _consent_invalid("current_missing")
            return None
        history = tuple(
            scan_canonical_directory(
                root / "history",
                entry_limit=scope.limits.max_consent_history,
                aggregate_limit=scope.limits.max_journal_bytes,
                file_limit=scope.limits.max_consent_bytes,
                schema_name="persistence-consent",
                boundary=scope.boundary,
            )
        )
        _validate_history(scope, current, history)
        scope.boundary.assert_clean()
        return _ConsentState(current, history)
    except KokoroError as error:
        if error.code == "PERSISTENCE_CHANGED":
            raise _consent_invalid("stored_consent") from error
        raise


def _validate_history(
    scope: PersistenceScope,
    current: ArtifactSnapshot,
    history: tuple[ArtifactSnapshot, ...],
) -> None:
    if not history or current.payload != history[-1].payload:
        raise _consent_invalid("history_membership")
    expected_consent_id = _consent_id(scope)
    previous: dict[str, Any] | None = None
    for revision, snapshot in enumerate(history, start=1):
        value = snapshot.value
        if snapshot.path.name != _history_name(revision):
            raise _consent_invalid("history_name")
        if _lifecycle_revision(value) != revision:
            raise _consent_invalid("history_revision")
        if value.get("artifact_id") != _artifact_id(scope, revision):
            raise _consent_invalid("artifact_id")
        if value.get("consent_id") != expected_consent_id:
            raise _consent_invalid("consent_id")
        _require_scope_binding(scope, value)
        if value["status"] == "active":
            if value["grant_revision"] != revision:
                raise _consent_invalid("grant_revision")
        elif (
            revision == 1
            or value["revoked_revision"] != revision
            or value["grant_revision"] >= revision
        ):
            raise _consent_invalid("revoked_revision")
        if previous is not None:
            if value["consent_id"] != previous["consent_id"]:
                raise _consent_invalid("consent_lineage")
            if value["status"] == "revoked" and any(
                value[field] != previous[field]
                for field in ("grant_revision", "installation", "permissions")
            ):
                raise _consent_invalid("revocation_lineage")
        previous = value


def _resolve_installation(
    scope: PersistenceScope,
    *,
    version: str | None,
    schemas: SchemaValidator,
    workspace_root: Path | None,
) -> _ResolvedInstallation:
    audits: list[Callable[[], None]] = []
    compiled_results: list[dict[str, Any]] = []
    try:
        binding = _resolve_installed_binding(
            scope.root,
            scope.key.character_id,
            _AuditedSchemas(schemas, scope.boundary),
            namespace=scope.key.namespace,
            version=version,
            workspace_root=workspace_root,
            boundary_audits=audits,
            compiled_results=compiled_results,
        )
    except Exception as error:
        try:
            scope.boundary.assert_clean()
        except KokoroError:
            raise
        raise _installation_stale("resolution") from error
    if len(audits) != 1 or len(compiled_results) != 1:
        raise _installation_stale("resolution")

    def installation_audit() -> None:
        try:
            audits[0]()
        except Exception as error:
            raise _installation_stale("installation_changed") from error

    scope.boundary.audits["installation:binding"] = installation_audit
    binding_payload = scope.boundary.capture(
        "installed_binding_output",
        binding,
    )
    compiled_payload = scope.boundary.capture(
        "compiled_installation_input",
        compiled_results[0],
    )
    binding_value = cast(dict[str, Any], json.loads(binding_payload))
    compiled_value = cast(dict[str, Any], json.loads(compiled_payload))
    resolved = _ResolvedInstallation(
        binding=binding_value,
        binding_payload=binding_payload,
        compiled=compiled_value,
        compiled_payload=compiled_payload,
    )
    scope.boundary.assert_clean()
    return resolved


def _active_successor(
    scope: PersistenceScope,
    permissions: tuple[str, ...],
    binding: dict[str, Any],
    revision: int,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": _artifact_id(scope, revision),
        "created_by": {"component": "kokoroarc", "version": __version__},
        "consent_id": _consent_id(scope),
        "scope": scope.key.scope,
        "workspace_id": scope.key.workspace_id,
        "installation": _detached(binding),
        "permissions": list(permissions),
        "status": "active",
        "grant_revision": revision,
        "revoked_revision": None,
        "persistence_policy": "explicit_consent_only",
    }


def _revoked_successor(
    scope: PersistenceScope,
    current: dict[str, Any],
    revision: int,
) -> dict[str, Any]:
    successor = _detached(current)
    successor["artifact_id"] = _artifact_id(scope, revision)
    successor["created_by"] = {
        "component": "kokoroarc",
        "version": __version__,
    }
    successor["status"] = "revoked"
    successor["revoked_revision"] = revision
    return successor


def _same_grant_intent(
    current: dict[str, Any],
    permissions: tuple[str, ...],
    binding: dict[str, Any],
) -> bool:
    return (
        current["status"] == "active"
        and current["permissions"] == list(permissions)
        and current["installation"] == binding
    )


def _require_scope_binding(
    scope: PersistenceScope,
    value: dict[str, Any],
) -> None:
    installation = value.get("installation")
    if (
        value.get("scope") != scope.key.scope
        or value.get("workspace_id") != scope.key.workspace_id
        or not isinstance(installation, dict)
        or installation.get("namespace") != scope.key.namespace
        or installation.get("character_id") != scope.key.character_id
    ):
        raise _consent_invalid("scope_binding")


def _require_exact_installation(
    consent: dict[str, Any],
    resolved: _ResolvedInstallation,
) -> None:
    try:
        matches = canonical_bytes(consent["installation"]) == (
            resolved.binding_payload
        )
    except (KokoroError, TypeError, ValueError, UnicodeError) as error:
        raise _installation_stale("binding") from error
    if not matches:
        raise _installation_stale("binding")


def _drop_consent_audits(scope: PersistenceScope) -> None:
    prefix = str(scope.character_root("consents")).casefold()
    for name in tuple(scope.boundary.audits):
        if prefix in name.casefold():
            scope.boundary.audits.pop(name, None)


def _consent_id(scope: PersistenceScope) -> str:
    identity = {
        "scope": scope.key.scope,
        "workspace_id": scope.key.workspace_id,
        "namespace": scope.key.namespace,
        "character_id": scope.key.character_id,
    }
    return f"consent-{sha256(canonical_bytes(identity)).hexdigest()[:32]}"


def _artifact_id(scope: PersistenceScope, revision: int) -> str:
    scope_root = "/".join(scope.key.scope_parts)
    return (
        f"consents/{scope_root}/{scope.key.namespace}/"
        f"{scope.key.character_id}/history/{revision:020d}"
    )


def _history_name(revision: int) -> str:
    return f"{revision:020d}.json"


def _capture_workspace_root(workspace_root: Path | None) -> Path | None:
    return None if workspace_root is None else _absolute_path(workspace_root)


def _lifecycle_revision(value: dict[str, Any]) -> int:
    revision = (
        value.get("revoked_revision")
        if value.get("status") == "revoked"
        else value.get("grant_revision")
    )
    if isinstance(revision, bool) or not isinstance(revision, int):
        raise _consent_invalid("lifecycle_revision")
    return revision


def _require_expected_revision(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _consent_invalid("expected_revision")


def _detached(value: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(canonical_bytes(value)))


def _consent_domain(action: Callable[[], Any]) -> Any:
    try:
        return action()
    except KokoroError as error:
        if error.code == "PERSISTENCE_CHANGED":
            raise _consent_invalid("stored_consent") from error
        if error.code.startswith("KARC_DEFAULT_"):
            raise _installation_stale("resolution") from error
        raise
    except (OSError, TypeError, ValueError, UnicodeError) as error:
        raise _consent_invalid("invalid_input") from error
    except Exception as error:
        raise _consent_invalid("callback_failure") from error


def _raise_active_audit_error(error: KokoroError) -> NoReturn:
    if error.code == "PERSISTENCE_CHANGED":
        raise _consent_invalid("consent_changed") from error
    if error.code.startswith("KARC_DEFAULT_"):
        raise _installation_stale("installation_changed") from error
    raise error


def _consent_invalid(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_CONSENT_INVALID",
        "Persistent consent is invalid.",
        details={"reason": reason},
    )


def _consent_not_found() -> KokoroError:
    return KokoroError(
        "PERSISTENCE_CONSENT_NOT_FOUND",
        "Persistent consent was not found.",
        details={"reason": "absent"},
    )


def _consent_conflict(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_CONSENT_CONFLICT",
        "Persistent consent revision conflicts with the request.",
        details={"reason": reason},
    )


def _consent_revoked() -> KokoroError:
    return KokoroError(
        "PERSISTENCE_CONSENT_REVOKED",
        "Persistent consent is revoked.",
        details={"reason": "revoked"},
    )


def _permission_denied() -> KokoroError:
    return KokoroError(
        "PERSISTENCE_PERMISSION_DENIED",
        "Persistent permission is not granted.",
        details={"reason": "permission_missing"},
    )


def _installation_stale(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_INSTALLATION_STALE",
        "Persistent consent installation is stale.",
        details={"reason": reason},
    )


__all__ = [
    "ActiveConsent",
    "grant_consent",
    "load_consent",
    "revoke_consent",
]
