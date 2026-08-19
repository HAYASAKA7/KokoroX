"""Declarative replay-verified migration of persistent character state."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Literal, Mapping, cast

from kokoroarc import __version__
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.persistence._storage import (
    ArtifactSnapshot,
    PersistenceBoundary,
    PersistenceLimits,
    PersistenceLock,
    PersistenceScope,
    SchemaValidator,
    _acquire_character_lock,
    _assert_directory_chain,
    _capture_directory_chain,
    _capture_directory_identity,
    _create_secure_directories,
    _file_audit,
    _fsync_directory,
    _lstat,
    _publish_new_file,
    _remove_transaction_marker,
    _replace_file,
    _snapshot_canonical_file,
    _write_transaction_marker,
    open_persistence_scope,
)
from kokoroarc.persistence.consent import (
    _ConsentState,
    _ResolvedInstallation,
    _load_consent_state,
    _resolve_installation,
)
import kokoroarc.persistence.state as persistent_state


_MOOD_STRATEGIES = frozenset(
    {"preserve_identical_contract", "reset_neutral"}
)
_GENERATION_PATTERN = re.compile(r"generation-[a-f0-9]{32}\Z")
_HASH_PATTERN = re.compile(r"[a-f0-9]{64}\Z")
_STATE_CONTRACT_VERSION = "1.0.0"
_TRANSITION_ALGORITHM = "relationship-v1"
_RETAIN_TARGET_IDENTITY = object()


@dataclass(frozen=True, slots=True)
class _NoCallbackSchemas:
    def validate(self, _name: str, _instance: Any) -> None:
        return None


@dataclass(frozen=True, slots=True)
class _AuditedSchemas:
    schemas: SchemaValidator
    boundary: PersistenceBoundary

    def validate(self, name: str, instance: Any) -> None:
        try:
            self.schemas.validate(name, instance)
        finally:
            self.boundary.assert_clean()


@dataclass(frozen=True, slots=True)
class _MigrationCapture:
    scope: PersistenceScope
    consent_state: _ConsentState
    source: Any
    current: Any
    source_consent: ArtifactSnapshot
    target_consent: ArtifactSnapshot
    source_installation: _ResolvedInstallation
    target_installation: _ResolvedInstallation
    schemas: SchemaValidator
    workspace_root: Path | None
    caller_boundary: PersistenceBoundary | None

    def assert_clean(self) -> None:
        if self.caller_boundary is not None:
            self.caller_boundary.assert_clean()
        self.scope.boundary.assert_clean()
        self.source.boundary.assert_clean()
        self.current.boundary.assert_clean()


@dataclass(frozen=True, slots=True)
class _BuiltMigration:
    plan: dict[str, Any]
    plan_payload: bytes
    generation_id: str
    event_payloads: tuple[bytes, ...]
    target_state: dict[str, Any]


def preview_state_migration(
    data_root: Path,
    character_id: str,
    target_consent_id: str,
    target_consent_revision: int,
    schemas: SchemaValidator,
    *,
    mood_strategy: Literal[
        "preserve_identical_contract",
        "reset_neutral",
    ],
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    """Preview one exact deterministic migration from the current generation."""

    return _migration_domain(
        lambda: _preview_state_migration(
            data_root,
            character_id,
            target_consent_id,
            target_consent_revision,
            schemas,
            mood_strategy=mood_strategy,
            namespace=namespace,
            workspace_root=workspace_root,
            limits=limits,
        )
    )


def apply_state_migration(
    data_root: Path,
    character_id: str,
    target_consent_id: str,
    target_consent_revision: int,
    plan: Mapping[str, Any],
    schemas: SchemaValidator,
    *,
    mood_strategy: Literal[
        "preserve_identical_contract",
        "reset_neutral",
    ],
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    """Apply one exact preview into a replay-verified target generation."""

    return _migration_domain(
        lambda: _apply_state_migration(
            data_root,
            character_id,
            target_consent_id,
            target_consent_revision,
            plan,
            schemas,
            mood_strategy=mood_strategy,
            namespace=namespace,
            workspace_root=workspace_root,
            limits=limits,
        )
    )


def _preview_state_migration(
    data_root: Path,
    character_id: str,
    target_consent_id: str,
    target_consent_revision: int,
    schemas: SchemaValidator,
    *,
    mood_strategy: str,
    namespace: str,
    workspace_root: Path | None,
    limits: PersistenceLimits,
) -> dict[str, Any]:
    _require_migration_request(
        target_consent_id,
        target_consent_revision,
        mood_strategy,
    )
    captured_workspace = _capture_workspace_root(workspace_root)
    captured = _capture_migration_inputs(
        data_root,
        character_id,
        target_consent_id,
        target_consent_revision,
        schemas,
        mood_strategy=mood_strategy,
        namespace=namespace,
        workspace_root=captured_workspace,
        limits=limits,
        source_generation_id=None,
        caller_boundary=None,
    )
    built = _build_migration(captured, mood_strategy)
    captured.assert_clean()
    return _detached(built.plan)


def _apply_state_migration(
    data_root: Path,
    character_id: str,
    target_consent_id: str,
    target_consent_revision: int,
    plan: Mapping[str, Any],
    schemas: SchemaValidator,
    *,
    mood_strategy: str,
    namespace: str,
    workspace_root: Path | None,
    limits: PersistenceLimits,
) -> dict[str, Any]:
    _require_migration_request(
        target_consent_id,
        target_consent_revision,
        mood_strategy,
    )
    captured_workspace = _capture_workspace_root(workspace_root)
    operation_scope = open_persistence_scope(
        data_root,
        _NoCallbackSchemas(),
        namespace=namespace,
        character_id=character_id,
        workspace_root=captured_workspace,
        limits=limits,
    )
    try:
        plan_payload = operation_scope.boundary.capture("migration_plan", plan)
        supplied_plan = _decode_plan(plan_payload)
        source_generation_id = cast(
            str,
            cast(dict[str, Any], supplied_plan["source"])["generation_id"],
        )
    except (KokoroError, KeyError, TypeError, ValueError) as error:
        raise _migration_invalid("plan") from error

    with _acquire_character_lock(operation_scope) as lock:
        captured = _capture_migration_inputs(
            data_root,
            character_id,
            target_consent_id,
            target_consent_revision,
            schemas,
            mood_strategy=mood_strategy,
            namespace=namespace,
            workspace_root=captured_workspace,
            limits=limits,
            source_generation_id=source_generation_id,
            caller_boundary=operation_scope.boundary,
        )
        _validate_payload(captured, "state-migration-plan", plan_payload)
        built = _build_migration(captured, mood_strategy)
        if built.plan_payload != plan_payload:
            raise _migration_stale("plan_changed")
        current_generation_id = cast(
            str,
            captured.current.state["generation_id"],
        )
        if current_generation_id not in {
            source_generation_id,
            built.generation_id,
        }:
            raise _migration_stale("current_generation")

        marker = _read_migration_marker(captured.scope)
        if marker is not None:
            _require_migration_marker(marker.value, built)
        if current_generation_id == built.generation_id:
            _require_target_state(captured.current.state, built)
            if marker is not None:
                _require_marker_target_directory(captured, built, marker)
                _confirm_directory_durability(
                    persistent_state._state_root(captured.scope),
                    "pointer_fsync",
                    record_state="committed",
                )
                if marker.value["phase"] != "committed":
                    marker = _update_migration_marker(
                        captured.scope,
                        marker,
                        built,
                        phase="committed",
                        lock=lock,
                    )
                captured.assert_clean()
                _remove_migration_marker(captured.scope, marker, lock)
            operation_scope.boundary.assert_clean()
            if marker is None:
                captured.assert_clean()
            return _detached(captured.current.state)

        persistent_state._require_generation_capacity(
            captured.scope,
            built.generation_id,
            captured_workspace,
        )
        if marker is None:
            marker_value = _migration_marker_document(
                built,
                phase="prepared",
                target_directory_identity=None,
            )
            marker = _write_transaction_marker(
                captured.scope,
                canonical_bytes(marker_value),
                lock,
            )
        try:
            marker = _prepare_target_generation(
                captured,
                built,
                marker,
                lock,
            )
            _publish_target_generation(captured, built, lock)
            staged = persistent_state._replay_generation(
                captured.scope,
                built.generation_id,
                allow_projection_mismatch=False,
            )
            _require_target_state(staged.state, built)
            staged.boundary.assert_clean()
        except BaseException:
            if isinstance(
                marker.value.get("target_directory_identity"),
                dict,
            ):
                _cleanup_target_generation(captured, built, marker, lock)
                marker = _update_migration_marker(
                    captured.scope,
                    marker,
                    built,
                    phase="prepared",
                    target_directory_identity=None,
                    lock=lock,
                )
            raise
        captured.assert_clean()
        _drop_pointer_audits(captured)
        try:
            pointer = _replace_current_generation_pointer(
                captured.scope,
                built.generation_id,
                lock,
            )
        except BaseException as error:
            record_state = _pointer_failure_record_state(error)
            if record_state == "not_visible":
                _cleanup_target_generation(captured, built, marker, lock)
                marker = _update_migration_marker(
                    captured.scope,
                    marker,
                    built,
                    phase="prepared",
                    target_directory_identity=None,
                    lock=lock,
                )
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            raise _migration_write_failed(
                "pointer_cutover",
                record_state,
            ) from error
        captured.scope.boundary.audits[f"file:{pointer.path}"] = _file_audit(
            pointer.path,
            pointer.payload,
            pointer.identity,
        )
        _confirm_directory_durability(
            persistent_state._state_root(captured.scope),
            "pointer_fsync",
            record_state="committed",
        )
        marker = _update_migration_marker(
            captured.scope,
            marker,
            built,
            phase="committed",
            lock=lock,
        )
        confirmed = persistent_state._read_current(
            captured.scope,
            captured_workspace,
        )
        if confirmed is None:
            raise _migration_write_failed("confirmation", "unknown")
        _require_target_state(confirmed.state, built)
        confirmed.boundary.assert_clean()
        captured.assert_clean()
        operation_scope.boundary.assert_clean()
        _remove_migration_marker(captured.scope, marker, lock)
        lock.assert_owned()
        return _detached(confirmed.state)


def _drop_pointer_audits(captured: _MigrationCapture) -> None:
    pointer = persistent_state._state_root(captured.scope) / "current.json"
    names = {f"file:{pointer}", f"absent:{pointer}"}
    boundaries = {
        id(boundary): boundary
        for boundary in (
            captured.scope.boundary,
            captured.source.boundary,
            captured.current.boundary,
        )
    }
    for boundary in boundaries.values():
        for name in names:
            boundary.audits.pop(name, None)


def _replace_current_generation_pointer(
    scope: PersistenceScope,
    generation_id: str,
    lock: PersistenceLock,
) -> ArtifactSnapshot:
    return persistent_state._write_pointer(scope, generation_id, lock)


def _pointer_failure_record_state(error: BaseException) -> str:
    if isinstance(error, KokoroError):
        record_state = error.details.get("record_state")
        if record_state in {"committed", "unknown"}:
            return cast(str, record_state)
    return "not_visible"


def _capture_migration_inputs(
    data_root: Path,
    character_id: str,
    target_consent_id: str,
    target_consent_revision: int,
    schemas: SchemaValidator,
    *,
    mood_strategy: str,
    namespace: str,
    workspace_root: Path | None,
    limits: PersistenceLimits,
    source_generation_id: str | None,
    caller_boundary: PersistenceBoundary | None,
) -> _MigrationCapture:
    scope = open_persistence_scope(
        data_root,
        _NoCallbackSchemas(),
        namespace=namespace,
        character_id=character_id,
        workspace_root=workspace_root,
        limits=limits,
    )
    consent_state = _load_consent_state(scope)
    if consent_state is None:
        raise _migration_invalid("consent_missing")
    current = persistent_state._read_current(scope, workspace_root)
    if current is None:
        raise _migration_invalid("source_state_missing")
    if source_generation_id is None:
        source = current
    else:
        if _GENERATION_PATTERN.fullmatch(source_generation_id) is None:
            raise _migration_invalid("source_generation")
        source = persistent_state._replay_generation(
            scope,
            source_generation_id,
            allow_projection_mismatch=False,
        )
    target_consent = consent_state.current
    _require_target_consent(
        target_consent.value,
        target_consent_id,
        target_consent_revision,
    )
    source_consent = _find_source_consent(
        consent_state,
        source.state,
    )
    source_version = cast(
        str,
        source.state["installation"]["character_version"],
    )
    target_version = cast(
        str,
        target_consent.value["installation"]["character_version"],
    )
    source_installation = _resolve_installation(
        scope,
        version=source_version,
        schemas=_NoCallbackSchemas(),
        workspace_root=workspace_root,
    )
    target_installation = _resolve_installation(
        scope,
        version=target_version,
        schemas=_NoCallbackSchemas(),
        workspace_root=workspace_root,
    )
    if source_installation.binding != source.state["installation"]:
        raise _migration_stale("source_installation")
    if target_installation.binding != target_consent.value["installation"]:
        raise _migration_stale("target_installation")
    if source_installation.binding == target_installation.binding:
        raise _migration_invalid("same_installation")
    captured = _MigrationCapture(
        scope=scope,
        consent_state=consent_state,
        source=source,
        current=current,
        source_consent=source_consent,
        target_consent=target_consent,
        source_installation=source_installation,
        target_installation=target_installation,
        schemas=schemas,
        workspace_root=workspace_root,
        caller_boundary=caller_boundary,
    )
    captured.assert_clean()
    for consent in consent_state.history:
        _validate_payload(captured, "persistence-consent", consent.payload)
    for event in source.events:
        _validate_payload(
            captured,
            "persistent-state-event",
            event.payload,
        )
    _validate_payload(
        captured,
        "persistent-character-state",
        canonical_bytes(source.state),
    )
    checked_source = _resolve_installation(
        scope,
        version=source_version,
        schemas=_AuditedSchemas(schemas, scope.boundary),
        workspace_root=workspace_root,
    )
    checked_target = _resolve_installation(
        scope,
        version=target_version,
        schemas=_AuditedSchemas(schemas, scope.boundary),
        workspace_root=workspace_root,
    )
    if (
        checked_source.binding_payload
        != source_installation.binding_payload
        or checked_source.compiled_payload
        != source_installation.compiled_payload
        or checked_target.binding_payload
        != target_installation.binding_payload
        or checked_target.compiled_payload
        != target_installation.compiled_payload
    ):
        raise _migration_stale("installation_changed")
    _require_permission_ceiling(captured, mood_strategy)
    captured.assert_clean()
    return captured


def _build_migration(
    captured: _MigrationCapture,
    mood_strategy: str,
) -> _BuiltMigration:
    source = captured.source.state
    target_consent = captured.target_consent.value
    source_digest = persistent_state._state_sha256(source)
    source_event_digest = persistent_state._event_log_sha256(
        captured.source.events
    )
    target_consent_binding = {
        "consent_id": target_consent["consent_id"],
        "grant_revision": target_consent["grant_revision"],
    }
    identity = {
        "scope": captured.scope.key.scope,
        "workspace_id": captured.scope.key.workspace_id,
        "namespace": captured.scope.key.namespace,
        "character_id": captured.scope.key.character_id,
        "source_generation_id": source["generation_id"],
        "source_state_sha256": source_digest,
        "source_event_log_sha256": source_event_digest,
        "target_installation": captured.target_installation.binding,
        "target_consent": target_consent_binding,
        "mood_strategy": mood_strategy,
    }
    identity_hash = sha256(canonical_bytes(identity)).hexdigest()
    migration_id = f"migration-{identity_hash[:32]}"
    generation_id = f"generation-{identity_hash[32:64]}"
    plan: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact_id": (
            f"state-migrations/{captured.scope.key.scope}/"
            f"{captured.scope.key.character_id}/{identity_hash[:32]}"
        ),
        "created_by": {"component": "kokoroarc", "version": __version__},
        "migration_id": migration_id,
        "scope": captured.scope.key.scope,
        "workspace_id": captured.scope.key.workspace_id,
        "namespace": captured.scope.key.namespace,
        "character_id": captured.scope.key.character_id,
        "source": {
            "installation": _detached(source["installation"]),
            "consent": _detached(source["consent"]),
            "generation_id": source["generation_id"],
            "state_sha256": source_digest,
            "event_log_sha256": source_event_digest,
            "state_contract_version": source["state_contract_version"],
            "transition_algorithm": source["transition_algorithm"],
        },
        "target": {
            "installation": _detached(captured.target_installation.binding),
            "consent": target_consent_binding,
            "state_contract_version": _STATE_CONTRACT_VERSION,
            "transition_algorithm": _TRANSITION_ALGORITHM,
        },
        "relationship_strategy": "replay_relationship_v1",
        "mood_strategy": mood_strategy,
        "target_replay_hash": None,
        "expected_target_state_hash": None,
        "mode": "preview",
        "executable_code_accepted": False,
    }
    plan_binding_hash = sha256(canonical_bytes(plan)).hexdigest()
    target_state = persistent_state._initial_state_values(
        captured.scope,
        installation=captured.target_installation.binding,
        consent=target_consent_binding,
        generation_id=generation_id,
        created_by={"component": "kokoroarc", "version": __version__},
    )
    payloads: list[bytes] = []
    target_growth = persistent_state._growth_config(
        captured.target_installation.compiled
    )
    target_permissions = frozenset(target_consent["permissions"])
    for snapshot in captured.source.events:
        source_record = snapshot.value
        operation_kind = cast(str, source_record["operation_kind"])
        if operation_kind in {"relationship", "relationship_reset"}:
            if "relationship_state" not in target_permissions:
                continue
        elif operation_kind in {
            "mood_update",
            "mood_advance",
            "mood_reset",
        }:
            if (
                mood_strategy == "reset_neutral"
                or "mood_state" not in target_permissions
            ):
                continue
        elif operation_kind == "migration_marker":
            continue
        else:
            raise _migration_unreplayable("operation_kind")
        payload = _detached(source_record["payload"])
        if operation_kind == "relationship":
            payload["max_delta"] = target_growth[0]
            payload["repetition_window"] = target_growth[1]
        target_state, record_payload = _append_target_event(
            captured,
            generation_id,
            target_state,
            operation_kind,
            cast(str, source_record["operation_id"]),
            payload,
        )
        payloads.append(record_payload)
    marker_payload = {
        "plan_sha256": plan_binding_hash,
        "source_generation_id": source["generation_id"],
        "source_state_sha256": source_digest,
        "source_event_log_sha256": source_event_digest,
        "mood_strategy": mood_strategy,
    }
    target_state, record_payload = _append_target_event(
        captured,
        generation_id,
        target_state,
        "migration_marker",
        migration_id,
        marker_payload,
    )
    payloads.append(record_payload)
    plan["target_replay_hash"] = _event_payloads_sha256(payloads)
    plan["expected_target_state_hash"] = persistent_state._state_sha256(
        target_state
    )
    plan_payload = canonical_bytes(plan)
    _validate_payload(captured, "state-migration-plan", plan_payload)
    captured.assert_clean()
    return _BuiltMigration(
        plan=_detached(plan),
        plan_payload=plan_payload,
        generation_id=generation_id,
        event_payloads=tuple(payloads),
        target_state=_detached(target_state),
    )


def _append_target_event(
    captured: _MigrationCapture,
    generation_id: str,
    state: dict[str, Any],
    operation_kind: str,
    operation_id: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], bytes]:
    if operation_kind == "relationship":
        successor = persistent_state._relationship_successor(
            state,
            cast(dict[str, Any], payload["interaction_event"]),
            (
                cast(float, payload["max_delta"]),
                cast(int, payload["repetition_window"]),
            ),
            operation_id,
        )
    elif operation_kind in {"mood_update", "mood_advance"}:
        successor = persistent_state._mood_successor(
            state,
            operation_kind,
            payload,
            operation_id,
        )
    elif operation_kind == "relationship_reset":
        successor = persistent_state._relationship_reset_successor(
            state,
            payload,
            operation_id,
        )
    elif operation_kind == "mood_reset":
        successor = persistent_state._mood_reset_successor(
            state,
            payload,
            operation_id,
        )
    elif operation_kind == "migration_marker":
        successor = persistent_state._migration_marker_successor(
            state,
            payload,
            operation_id,
        )
    else:
        raise _migration_unreplayable("operation_kind")
    revision = cast(int, successor["revision"])
    record = {
        "schema_version": "1.0",
        "artifact_id": persistent_state._event_artifact_id(
            captured.scope,
            revision,
            operation_id,
        ),
        "created_by": {"component": "kokoroarc", "version": __version__},
        "scope": captured.scope.key.scope,
        "workspace_id": captured.scope.key.workspace_id,
        "installation": _detached(captured.target_installation.binding),
        "consent": _detached(successor["consent"]),
        "generation_id": generation_id,
        "state_contract_version": _STATE_CONTRACT_VERSION,
        "transition_algorithm": _TRANSITION_ALGORITHM,
        "revision": revision,
        "operation_id": operation_id,
        "operation_kind": operation_kind,
        "predecessor_event_sha256": state["last_event_sha256"],
        "predecessor_state_sha256": persistent_state._state_sha256(state),
        "successor_state_sha256": persistent_state._state_sha256(successor),
        "payload": _detached(payload),
    }
    record_payload = canonical_bytes(record)
    if len(record_payload) > captured.scope.limits.max_event_bytes:
        raise _migration_unreplayable("event_bytes")
    _validate_payload(captured, "persistent-state-event", record_payload)
    successor["last_event_sha256"] = sha256(record_payload).hexdigest()
    state_payload = canonical_bytes(successor)
    if len(state_payload) > captured.scope.limits.max_state_bytes:
        raise _migration_unreplayable("state_bytes")
    _validate_payload(
        captured,
        "persistent-character-state",
        state_payload,
    )
    return successor, record_payload


def _find_source_consent(
    consent_state: _ConsentState,
    source_state: dict[str, Any],
) -> ArtifactSnapshot:
    binding = source_state["consent"]
    matches = [
        snapshot
        for snapshot in consent_state.history
        if snapshot.value["status"] == "active"
        and snapshot.value["consent_id"] == binding["consent_id"]
        and snapshot.value["grant_revision"] == binding["grant_revision"]
    ]
    if len(matches) != 1:
        raise _migration_invalid("source_consent_history")
    source_consent = matches[0]
    if source_consent.value["installation"] != source_state["installation"]:
        raise _migration_stale("source_consent_installation")
    return source_consent


def _require_target_consent(
    consent: dict[str, Any],
    consent_id: str,
    consent_revision: int,
) -> None:
    if consent.get("consent_id") != consent_id:
        raise _migration_stale("target_consent_id")
    if consent.get("status") != "active":
        raise _migration_stale("target_consent_status")
    if consent.get("grant_revision") != consent_revision:
        raise _migration_stale("target_consent_revision")


def _require_permission_ceiling(
    captured: _MigrationCapture,
    mood_strategy: str,
) -> None:
    permissions = frozenset(captured.target_consent.value["permissions"])
    relationship = captured.source.state["relationship"]
    if (
        relationship["revision"] > 0
        and "relationship_state" not in permissions
    ):
        raise _migration_invalid("relationship_permission")
    mood = captured.source.state["mood"]
    if (
        mood_strategy == "preserve_identical_contract"
        and not _mood_is_neutral(mood)
        and "mood_state" not in permissions
    ):
        raise _migration_invalid("mood_permission")


def _mood_is_neutral(mood: Mapping[str, Any]) -> bool:
    return (
        mood.get("primary") == "neutral"
        and mood.get("secondary") is None
        and mood.get("arousal") == 0
        and mood.get("valence") == 0
        and mood.get("intensity") == 0
        and mood.get("remaining_turns") == 0
        and mood.get("expires_after_turns") == 0
        and mood.get("triggering_event_id") is None
    )


def _prepare_target_generation(
    captured: _MigrationCapture,
    built: _BuiltMigration,
    marker: ArtifactSnapshot,
    lock: PersistenceLock,
) -> ArtifactSnapshot:
    target = persistent_state._generation_root(
        captured.scope,
        built.generation_id,
    )
    expected_identity = marker.value["target_directory_identity"]
    if expected_identity is not None:
        _require_directory_identity(target, expected_identity)
        return marker
    if _lstat(target) is not None:
        raise _migration_conflict("target_generation_collision")
    generations = target.parent
    _create_secure_directories(generations)
    ancestry = _capture_directory_chain(generations)
    lock.assert_owned()
    try:
        os.mkdir(target, 0o700)
    except OSError as error:
        raise _migration_write_failed("target_generation", "not_visible") from error
    try:
        identity = _capture_directory_identity(target)
    except (KokoroError, OSError) as error:
        raise _migration_cleanup_failed(
            "target_identity_unavailable"
        ) from error
    identity_value = {
        "device": identity.device,
        "inode": identity.inode,
        "file_type": identity.file_type,
    }
    try:
        _assert_directory_chain(ancestry, "generation_parent_changed")
        _confirm_directory_durability(
            generations,
            "generation_create_fsync",
            record_state="not_visible",
        )
    except BaseException:
        _cleanup_unrecorded_target_generation(
            target,
            identity_value,
            lock,
        )
        raise
    try:
        updated = _update_migration_marker(
            captured.scope,
            marker,
            built,
            phase="prepared",
            target_directory_identity=identity_value,
            lock=lock,
        )
    except BaseException as error:
        _recover_target_after_marker_update_failure(
            captured,
            built,
            marker,
            target,
            identity_value,
            lock,
            error,
        )
        raise
    lock.assert_owned()
    return updated


def _publish_target_generation(
    captured: _MigrationCapture,
    built: _BuiltMigration,
    lock: PersistenceLock,
) -> None:
    generation = persistent_state._generation_root(
        captured.scope,
        built.generation_id,
    )
    events = generation / "events"
    if _lstat(events) is None:
        try:
            os.mkdir(events, 0o700)
        except OSError as error:
            raise _migration_write_failed("events_directory", "not_visible") from error
        _confirm_directory_durability(
            generation,
            "events_directory_fsync",
            record_state="not_visible",
        )
    for revision, payload in enumerate(built.event_payloads, start=1):
        record = cast(dict[str, Any], json.loads(payload))
        target = persistent_state._event_path(
            captured.scope,
            built.generation_id,
            revision,
            cast(str, record["operation_id"]),
        )
        _publish_exact_file(captured.scope, target, payload, lock)
    projection = generation / "state.json"
    _publish_exact_file(
        captured.scope,
        projection,
        canonical_bytes(built.target_state),
        lock,
    )


def _publish_exact_file(
    scope: PersistenceScope,
    path: Path,
    payload: bytes,
    lock: PersistenceLock,
) -> ArtifactSnapshot:
    if _lstat(path) is None:
        return _publish_new_file(scope, path, payload, lock)
    existing = _snapshot_canonical_file(path, max(len(payload), 1))
    if existing.payload != payload:
        raise _migration_conflict("target_generation_collision")
    return existing


def _read_migration_marker(
    scope: PersistenceScope,
) -> ArtifactSnapshot | None:
    if _lstat(scope.transaction_path) is None:
        return None
    marker = _snapshot_canonical_file(
        scope.transaction_path,
        scope.limits.max_transaction_bytes,
    )
    scope.boundary.audits["migration-transaction-marker"] = _file_audit(
        marker.path,
        marker.payload,
        marker.identity,
    )
    if marker.value.get("kind") != "state_migration":
        raise _migration_conflict("transaction_kind")
    return marker


def _migration_marker_document(
    built: _BuiltMigration,
    *,
    phase: str,
    target_directory_identity: dict[str, int] | None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "kind": "state_migration",
        "phase": phase,
        "migration_id": built.plan["migration_id"],
        "plan_sha256": sha256(built.plan_payload).hexdigest(),
        "source_generation_id": built.plan["source"]["generation_id"],
        "target_generation_id": built.generation_id,
        "target_installation": _detached(
            cast(dict[str, Any], built.plan["target"])["installation"]
        ),
        "target_directory_identity": (
            None
            if target_directory_identity is None
            else _detached(target_directory_identity)
        ),
    }


def _require_migration_marker(
    marker: dict[str, Any],
    built: _BuiltMigration,
) -> None:
    expected = _migration_marker_document(
        built,
        phase=cast(str, marker.get("phase")),
        target_directory_identity=cast(
            dict[str, int] | None,
            marker.get("target_directory_identity"),
        ),
    )
    identity = marker.get("target_directory_identity")
    if (
        marker.get("phase") not in {"prepared", "committed"}
        or (
            identity is not None
            and (
                not isinstance(identity, dict)
                or set(identity) != {"device", "inode", "file_type"}
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or value < 0
                    for value in identity.values()
                )
            )
        )
        or canonical_bytes(marker) != canonical_bytes(expected)
    ):
        raise _migration_stale("transaction_marker")


def _update_migration_marker(
    scope: PersistenceScope,
    marker: ArtifactSnapshot,
    built: _BuiltMigration,
    *,
    phase: str,
    lock: PersistenceLock,
    target_directory_identity: (
        dict[str, int] | None | object
    ) = _RETAIN_TARGET_IDENTITY,
) -> ArtifactSnapshot:
    observed = _snapshot_canonical_file(
        scope.transaction_path,
        scope.limits.max_transaction_bytes,
    )
    if observed.payload != marker.payload or observed.identity != marker.identity:
        raise _migration_stale("transaction_changed")
    retained_identity = marker.value["target_directory_identity"]
    if target_directory_identity is not _RETAIN_TARGET_IDENTITY:
        retained_identity = target_directory_identity
    scope.boundary.audits.pop("migration-transaction-marker", None)
    updated = _replace_file(
        scope,
        scope.transaction_path,
        canonical_bytes(
            _migration_marker_document(
                built,
                phase=phase,
                target_directory_identity=retained_identity,
            )
        ),
        lock,
    )
    scope.boundary.audits["migration-transaction-marker"] = _file_audit(
        updated.path,
        updated.payload,
        updated.identity,
    )
    return updated


def _remove_migration_marker(
    scope: PersistenceScope,
    marker: ArtifactSnapshot,
    lock: PersistenceLock,
) -> None:
    scope.boundary.audits.pop("migration-transaction-marker", None)
    _remove_transaction_marker(scope, marker, lock)


def _require_marker_target_directory(
    captured: _MigrationCapture,
    built: _BuiltMigration,
    marker: ArtifactSnapshot,
) -> None:
    expected = marker.value["target_directory_identity"]
    if not isinstance(expected, dict):
        raise _migration_stale("target_generation_identity")
    target = persistent_state._generation_root(
        captured.scope,
        built.generation_id,
    )
    _require_directory_identity(target, expected)


def _cleanup_target_generation(
    captured: _MigrationCapture,
    built: _BuiltMigration,
    marker: ArtifactSnapshot,
    lock: PersistenceLock,
) -> None:
    try:
        _cleanup_exact_target_generation(captured, built, marker, lock)
    except KokoroError as error:
        if error.code == "PERSISTENCE_CLEANUP_FAILED":
            raise
        raise _migration_cleanup_failed("target_changed") from error


def _cleanup_exact_target_generation(
    captured: _MigrationCapture,
    built: _BuiltMigration,
    marker: ArtifactSnapshot,
    lock: PersistenceLock,
) -> None:
    expected_identity = marker.value["target_directory_identity"]
    if not isinstance(expected_identity, dict):
        raise _migration_cleanup_failed("target_identity_unavailable")
    target = persistent_state._generation_root(
        captured.scope,
        built.generation_id,
    )
    _require_directory_identity(target, expected_identity)
    lock.assert_owned()

    expected_events: dict[str, bytes] = {}
    for payload in built.event_payloads:
        record = cast(dict[str, Any], json.loads(payload))
        path = persistent_state._event_path(
            captured.scope,
            built.generation_id,
            cast(int, record["revision"]),
            cast(str, record["operation_id"]),
        )
        expected_events[path.name] = payload
    try:
        names = _bounded_directory_names(target, 2)
        if not set(names).issubset({"events", "state.json"}):
            raise _migration_cleanup_failed("unexpected_target_entry")
        events = target / "events"
        if "events" in names:
            events_identity = _capture_directory_identity(events)
            event_names = _bounded_directory_names(
                events,
                captured.scope.limits.max_state_events,
            )
            if not set(event_names).issubset(expected_events):
                raise _migration_cleanup_failed("unexpected_event_entry")
            for name in event_names:
                _require_directory_identity(target, expected_identity)
                _require_directory_identity(
                    events,
                    {
                        "device": events_identity.device,
                        "inode": events_identity.inode,
                        "file_type": events_identity.file_type,
                    },
                )
                path = events / name
                snapshot = _snapshot_canonical_file(
                    path,
                    captured.scope.limits.max_event_bytes,
                )
                if snapshot.payload != expected_events[name]:
                    raise _migration_cleanup_failed("event_changed")
                path.unlink()
            _require_directory_identity(target, expected_identity)
            _require_directory_identity(
                events,
                {
                    "device": events_identity.device,
                    "inode": events_identity.inode,
                    "file_type": events_identity.file_type,
                },
            )
            events.rmdir()
        projection = target / "state.json"
        if "state.json" in names:
            _require_directory_identity(target, expected_identity)
            snapshot = _snapshot_canonical_file(
                projection,
                captured.scope.limits.max_state_bytes,
            )
            if snapshot.payload != canonical_bytes(built.target_state):
                raise _migration_cleanup_failed("projection_changed")
            projection.unlink()
        _require_directory_identity(target, expected_identity)
        target.rmdir()
        _confirm_directory_durability(
            target.parent,
            "generation_cleanup_fsync",
            record_state="not_visible",
        )
    except KokoroError:
        raise
    except OSError as error:
        raise _migration_cleanup_failed("filesystem") from error


def _cleanup_unrecorded_target_generation(
    target: Path,
    expected_identity: Mapping[str, Any],
    lock: PersistenceLock,
) -> None:
    try:
        _require_directory_identity(target, expected_identity)
        lock.assert_owned()
        _bounded_directory_names(target, 0)
        target.rmdir()
        _confirm_directory_durability(
            target.parent,
            "generation_cleanup_fsync",
            record_state="not_visible",
        )
    except KokoroError as error:
        if error.code == "PERSISTENCE_CLEANUP_FAILED":
            raise
        raise _migration_cleanup_failed("target_changed") from error
    except OSError as error:
        raise _migration_cleanup_failed("filesystem") from error


def _recover_target_after_marker_update_failure(
    captured: _MigrationCapture,
    built: _BuiltMigration,
    marker: ArtifactSnapshot,
    target: Path,
    target_identity: Mapping[str, Any],
    lock: PersistenceLock,
    error: BaseException,
) -> None:
    expected_payload = canonical_bytes(
        _migration_marker_document(
            built,
            phase="prepared",
            target_directory_identity=cast(
                dict[str, int],
                _detached(target_identity),
            ),
        )
    )
    try:
        observed = _snapshot_canonical_file(
            captured.scope.transaction_path,
            captured.scope.limits.max_transaction_bytes,
        )
    except (KokoroError, OSError) as observation_error:
        raise _migration_cleanup_failed(
            "transaction_state_unknown"
        ) from observation_error
    if observed.payload == expected_payload:
        return
    if observed.payload != marker.payload or observed.identity != marker.identity:
        raise _migration_cleanup_failed(
            "transaction_state_unknown"
        ) from error
    _cleanup_unrecorded_target_generation(
        target,
        target_identity,
        lock,
    )


def _bounded_directory_names(path: Path, limit: int) -> tuple[str, ...]:
    names: list[str] = []
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                names.append(entry.name)
                if len(names) > limit:
                    raise _migration_cleanup_failed("entry_limit")
    except KokoroError:
        raise
    except OSError as error:
        raise _migration_cleanup_failed("directory_scan") from error
    return tuple(sorted(names))


def _require_directory_identity(
    path: Path,
    expected: Mapping[str, Any],
) -> None:
    actual = _capture_directory_identity(path)
    if (
        actual.device != expected.get("device")
        or actual.inode != expected.get("inode")
        or actual.file_type != expected.get("file_type")
    ):
        raise _migration_stale("target_generation_identity")


def _require_target_state(
    state: dict[str, Any],
    built: _BuiltMigration,
) -> None:
    if (
        state.get("generation_id") != built.generation_id
        or canonical_bytes(state) != canonical_bytes(built.target_state)
        or persistent_state._state_sha256(state)
        != built.plan["expected_target_state_hash"]
    ):
        raise _migration_unreplayable("target_state_hash")


def _validate_payload(
    captured: _MigrationCapture,
    schema_name: str,
    payload: bytes,
) -> None:
    probe = cast(dict[str, Any], json.loads(payload))
    schema_error: Exception | None = None
    try:
        captured.schemas.validate(schema_name, probe)
    except Exception as error:
        schema_error = error
    finally:
        try:
            if canonical_bytes(probe) != payload:
                captured.scope.boundary.fail("schema_input")
        finally:
            captured.assert_clean()
    if schema_error is not None:
        raise _migration_unreplayable("schema_validation") from schema_error


def _decode_plan(payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (TypeError, ValueError, UnicodeError) as error:
        raise _migration_invalid("plan") from error
    if not isinstance(value, dict) or canonical_bytes(value) != payload:
        raise _migration_invalid("plan")
    source = value.get("source")
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("generation_id"), str)
        or _GENERATION_PATTERN.fullmatch(source["generation_id"]) is None
    ):
        raise _migration_invalid("plan")
    return cast(dict[str, Any], value)


def _require_migration_request(
    consent_id: Any,
    consent_revision: Any,
    mood_strategy: Any,
) -> None:
    if not isinstance(consent_id, str) or not consent_id:
        raise _migration_invalid("target_consent_id")
    if (
        isinstance(consent_revision, bool)
        or not isinstance(consent_revision, int)
        or consent_revision < 1
    ):
        raise _migration_invalid("target_consent_revision")
    if mood_strategy not in _MOOD_STRATEGIES:
        raise _migration_invalid("mood_strategy")


def _event_payloads_sha256(payloads: list[bytes]) -> str:
    hashes = [sha256(payload).hexdigest() for payload in payloads]
    return sha256(canonical_bytes(hashes)).hexdigest()


def _capture_workspace_root(workspace_root: Path | None) -> Path | None:
    return (
        None
        if workspace_root is None
        else persistent_state._capture_workspace_root(workspace_root)
    )


def _confirm_directory_durability(
    path: Path,
    reason: str,
    *,
    record_state: str,
) -> None:
    try:
        _fsync_directory(path)
    except (KokoroError, OSError) as error:
        raise _migration_write_failed(reason, record_state) from error


def _detached(value: Any) -> Any:
    return json.loads(canonical_bytes(value))


def _migration_domain(action: Callable[[], Any]) -> Any:
    try:
        return action()
    except KokoroError as error:
        if error.code in {
            "PERSISTENCE_CHANGED",
            "PERSISTENCE_INPUT_MUTATION",
        }:
            raise _migration_stale("stored_artifact") from error
        if error.code == "PERSISTENCE_CONSENT_INVALID":
            raise _migration_invalid("consent_history") from error
        if error.code == "PERSISTENCE_INSTALLATION_STALE":
            raise _migration_stale("installation_changed") from error
        if error.code in {
            "PERSISTENCE_STATE_CONTRACT_UNSUPPORTED",
            "PERSISTENCE_STATE_JOURNAL_INVALID",
        }:
            raise _migration_unreplayable("source_replay") from error
        raise
    except (OSError, TypeError, ValueError, UnicodeError) as error:
        raise _migration_invalid("invalid_input") from error
    except Exception as error:
        raise _migration_invalid("callback_failure") from error


def _migration_invalid(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_MIGRATION_INVALID",
        "Persistent state migration is invalid.",
        details={"reason": reason},
    )


def _migration_stale(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_MIGRATION_STALE",
        "Persistent state migration inputs changed.",
        retryable=True,
        details={"reason": reason},
    )


def _migration_unreplayable(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_MIGRATION_UNREPLAYABLE",
        "Persistent state migration cannot be replayed safely.",
        details={"reason": reason},
    )


def _migration_conflict(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_MIGRATION_CONFLICT",
        "Persistent state migration conflicts with retained data.",
        retryable=True,
        details={"reason": reason},
    )


def _migration_write_failed(phase: str, record_state: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_MIGRATION_WRITE_FAILED",
        "Persistent state migration publication failed.",
        retryable=True,
        details={"phase": phase, "record_state": record_state},
    )


def _migration_cleanup_failed(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_CLEANUP_FAILED",
        "Persistent state migration cleanup failed.",
        retryable=True,
        details={"reason": reason, "record_state": "not_visible"},
    )


__all__ = ["apply_state_migration", "preview_state_migration"]
