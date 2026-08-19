"""Consent-bound append-only persistent relationship state."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Callable, Iterator, Literal, Mapping, cast

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
    _absolute_path,
    _absent_file_audit,
    _acquire_character_lock,
    _assert_directory_chain,
    _capture_directory_identity,
    _capture_directory_chain,
    _decode_canonical_object,
    _file_audit,
    _fsync_directory,
    _is_redirect,
    _lstat,
    _publish_new_file,
    _read_regular_file,
    _remove_transaction_marker,
    _replace_file,
    _require_safe_regular_file,
    _snapshot_canonical_file,
    _write_transaction_marker,
    open_persistence_scope,
    read_canonical_object,
    scan_canonical_directory,
    validate_and_finalize,
)
from kokoroarc.persistence.consent import (
    ActiveConsent,
    _load_consent_state,
    _require_active_consent,
)
from kokoroarc.persistence.memory import (
    _cleanup_memory_reset,
    _cutover_memory_reset,
    _memory_collection_sha256,
    _memory_root,
    _memory_reset_cleanup_path,
    _scan_memory_references,
)
from kokoroarc.state.transitions import apply_event_v1


_STATE_CONTRACT_VERSION = "1.0.0"
_TRANSITION_ALGORITHM = "relationship-v1"
_GENERATION_PATTERN = re.compile(r"generation-[a-f0-9]{32}\Z")
_STABLE_ID_PATTERN = re.compile(
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*\Z"
)
_MOODS = frozenset(
    {
        "neutral",
        "focused",
        "curious",
        "pleased",
        "amused",
        "concerned",
        "embarrassed",
        "irritated",
        "disappointed",
        "relieved",
        "proud",
        "tired",
    }
)
_MOOD_UPDATE_KEYS = frozenset(
    {
        "event_id",
        "expected_mood_revision",
        "primary",
        "secondary",
        "arousal",
        "valence",
        "intensity",
        "expires_after_turns",
        "triggering_interaction_event_id",
        "trigger_strength",
    }
)
_MOOD_ADVANCE_KEYS = frozenset(
    {"event_id", "expected_mood_revision", "turns"}
)
_RESET_TARGETS = frozenset({"relationship", "mood", "memory", "all"})
_RESET_PREVIEW_KEYS = frozenset(
    {
        "schema_version",
        "artifact_id",
        "created_by",
        "reset_id",
        "target",
        "scope",
        "workspace_id",
        "namespace",
        "character_id",
        "consent_id",
        "installation",
        "state_generation_id",
        "state_sha256",
        "event_log_sha256",
        "expected_state_revision",
        "expected_relationship_revision",
        "expected_mood_revision",
        "memory_root_present",
        "memory_reference_ids",
        "memory_references_sha256",
        "preview_sha256",
    }
)


@dataclass(frozen=True, slots=True)
class _ReplayResult:
    state: dict[str, Any]
    events: tuple[ArtifactSnapshot, ...]
    boundary: PersistenceBoundary
    projection_present: bool
    projection_matches: bool


@dataclass(frozen=True, slots=True)
class PersistentResetPreview:
    """Detached canonical preview required by an explicit reset."""

    payload: bytes

    @property
    def document(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.payload))


@dataclass(frozen=True, slots=True)
class _PersistenceCapture:
    scope: PersistenceScope
    consent_state: Any
    state_result: _ReplayResult | None
    memories: tuple[ArtifactSnapshot, ...]
    memory_root_present: bool
    schemas: SchemaValidator
    workspace_root: Path | None

    def assert_clean(self) -> None:
        self.scope.boundary.assert_clean()
        if self.state_result is not None:
            self.state_result.boundary.assert_clean()


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


def load_persistent_state(
    data_root: Path,
    character_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any] | None:
    """Load and replay current persistent state without creating storage."""

    return _state_domain(
        lambda: _load_or_replay(
            data_root,
            character_id,
            schemas,
            namespace=namespace,
            workspace_root=workspace_root,
            limits=limits,
            repair=False,
        )
    )


def replay_persistent_state(
    data_root: Path,
    character_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any] | None:
    """Replay the authoritative current journal without writing projections."""

    return _state_domain(
        lambda: _replay_read_only(
            data_root,
            character_id,
            schemas,
            namespace=namespace,
            workspace_root=workspace_root,
            limits=limits,
        )
    )


def apply_persistent_relationship_event(
    data_root: Path,
    character_id: str,
    event: Mapping[str, Any],
    consent_id: str,
    consent_revision: int,
    schemas: SchemaValidator,
    *,
    expected_state_revision: int,
    operation_id: str,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    """Apply one explicit relationship event to durable state."""

    return _state_domain(
        lambda: _apply_state_operation(
            data_root=data_root,
            character_id=character_id,
            operation_kind="relationship",
            operation_payload=event,
            consent_id=consent_id,
            consent_revision=consent_revision,
            schemas=schemas,
            expected_state_revision=expected_state_revision,
            operation_id=operation_id,
            namespace=namespace,
            workspace_root=workspace_root,
            limits=limits,
        )
    )


def apply_persistent_mood_event(
    data_root: Path,
    character_id: str,
    event: Mapping[str, Any],
    consent_id: str,
    consent_revision: int,
    schemas: SchemaValidator,
    *,
    expected_state_revision: int,
    operation_id: str,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    """Apply one explicit bounded mood event to durable state."""

    return _state_domain(
        lambda: _apply_state_operation(
            data_root=data_root,
            character_id=character_id,
            operation_kind="mood_update",
            operation_payload=event,
            consent_id=consent_id,
            consent_revision=consent_revision,
            schemas=schemas,
            expected_state_revision=expected_state_revision,
            operation_id=operation_id,
            namespace=namespace,
            workspace_root=workspace_root,
            limits=limits,
        )
    )


def advance_persistent_mood_turn(
    data_root: Path,
    character_id: str,
    consent_id: str,
    consent_revision: int,
    schemas: SchemaValidator,
    *,
    expected_state_revision: int,
    expected_mood_revision: int,
    operation_id: str,
    turns: int = 1,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    """Advance a durable mood by an explicit number of turns."""

    return _state_domain(
        lambda: _apply_state_operation(
            data_root=data_root,
            character_id=character_id,
            operation_kind="mood_advance",
            operation_payload={
                "event_id": operation_id,
                "expected_mood_revision": expected_mood_revision,
                "turns": turns,
            },
            consent_id=consent_id,
            consent_revision=consent_revision,
            schemas=schemas,
            expected_state_revision=expected_state_revision,
            operation_id=operation_id,
            namespace=namespace,
            workspace_root=workspace_root,
            limits=limits,
        )
    )


def export_persistent_data(
    data_root: Path,
    character_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    """Return one canonical path-free snapshot of retained persistence."""

    return _state_domain(
        lambda: _export_persistent_data(
            data_root,
            character_id,
            schemas,
            namespace=namespace,
            workspace_root=workspace_root,
            limits=limits,
        )
    )


def preview_persistent_reset(
    data_root: Path,
    character_id: str,
    consent_id: str,
    schemas: SchemaValidator,
    *,
    target: Literal["relationship", "mood", "memory", "all"],
    reset_id: str,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> PersistentResetPreview:
    """Capture the exact state and membership an explicit reset would alter."""

    return _state_domain(
        lambda: _preview_persistent_reset(
            data_root,
            character_id,
            consent_id,
            schemas,
            target=target,
            reset_id=reset_id,
            namespace=namespace,
            workspace_root=workspace_root,
            limits=limits,
        )
    )


def reset_persistent_data(
    data_root: Path,
    character_id: str,
    preview: PersistentResetPreview,
    consent_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    workspace_root: Path | None = None,
    limits: PersistenceLimits = PersistenceLimits(),
) -> dict[str, Any]:
    """Apply one exact previewed scoped reset under a transaction marker."""

    return _state_domain(
        lambda: _reset_persistent_data(
            data_root,
            character_id,
            preview,
            consent_id,
            schemas,
            namespace=namespace,
            workspace_root=workspace_root,
            limits=limits,
        )
    )


def _export_persistent_data(
    data_root: Path,
    character_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str,
    workspace_root: Path | None,
    limits: PersistenceLimits,
) -> dict[str, Any]:
    captured = _capture_persistence_data(
        data_root,
        character_id,
        schemas,
        namespace=namespace,
        workspace_root=workspace_root,
        limits=limits,
    )
    consent = captured.consent_state.current.value
    state = (
        None
        if captured.state_result is None
        else captured.state_result.state
    )
    event_digest = (
        None
        if captured.state_result is None
        else _event_log_sha256(captured.state_result.events)
    )
    memories = [snapshot.value for snapshot in captured.memories]
    exported: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact_id": (
            f"persistence-exports/{captured.scope.key.scope}/"
            f"{captured.scope.key.namespace}/"
            f"{captured.scope.key.character_id}"
        ),
        "created_by": {"component": "kokoroarc", "version": __version__},
        "scope": captured.scope.key.scope,
        "workspace_id": captured.scope.key.workspace_id,
        "namespace": captured.scope.key.namespace,
        "character_id": captured.scope.key.character_id,
        "consent": _detached(consent),
        "state": None if state is None else _detached(state),
        "event_log_sha256": event_digest,
        "memory_references": [_detached(item) for item in memories],
        "memory_count": len(memories),
        "export_sha256": None,
    }
    exported["export_sha256"] = sha256(canonical_bytes(exported)).hexdigest()
    payload = canonical_bytes(exported)
    _validate_captured_payload(captured, "persistence-export", payload)
    captured.assert_clean()
    return cast(dict[str, Any], json.loads(payload))


def _preview_persistent_reset(
    data_root: Path,
    character_id: str,
    consent_id: str,
    schemas: SchemaValidator,
    *,
    target: str,
    reset_id: str,
    namespace: str,
    workspace_root: Path | None,
    limits: PersistenceLimits,
) -> PersistentResetPreview:
    _require_reset_request(target, reset_id, consent_id)
    captured = _capture_persistence_data(
        data_root,
        character_id,
        schemas,
        namespace=namespace,
        workspace_root=workspace_root,
        limits=limits,
    )
    document = _assemble_reset_preview(
        captured,
        target=target,
        reset_id=reset_id,
        consent_id=consent_id,
    )
    payload = canonical_bytes(document)
    captured.assert_clean()
    return PersistentResetPreview(payload)


def _capture_persistence_data(
    data_root: Path,
    character_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str,
    workspace_root: Path | None,
    limits: PersistenceLimits,
) -> _PersistenceCapture:
    captured_workspace = _capture_workspace_root(workspace_root)
    scope = open_persistence_scope(
        data_root,
        _NoCallbackSchemas(),
        namespace=namespace,
        character_id=character_id,
        workspace_root=captured_workspace,
        limits=limits,
    )
    return _capture_persistence_scope(
        scope,
        schemas,
        captured_workspace,
    )


def _capture_persistence_scope(
    scope: PersistenceScope,
    schemas: SchemaValidator,
    workspace_root: Path | None,
) -> _PersistenceCapture:
    consent_state = _load_consent_state(scope)
    if consent_state is None:
        raise _journal_invalid("consent_absent")
    state_result = _read_current(scope, workspace_root)
    memories = _scan_memory_references(scope)
    memory_root_present = _lstat(_memory_root(scope)) is not None
    captured = _PersistenceCapture(
        scope=scope,
        consent_state=consent_state,
        state_result=state_result,
        memories=memories,
        memory_root_present=memory_root_present,
        schemas=schemas,
        workspace_root=workspace_root,
    )
    captured.assert_clean()
    _validate_captured_payload(
        captured,
        "persistence-consent",
        consent_state.current.payload,
    )
    for history in consent_state.history:
        _validate_captured_payload(
            captured,
            "persistence-consent",
            history.payload,
        )
    if state_result is not None:
        for event in state_result.events:
            _validate_captured_payload(
                captured,
                "persistent-state-event",
                event.payload,
            )
        _validate_captured_payload(
            captured,
            "persistent-character-state",
            canonical_bytes(state_result.state),
        )
    for memory in memories:
        _validate_captured_payload(
            captured,
            "memory-reference",
            memory.payload,
        )
    captured.assert_clean()
    return captured


def _validate_captured_payload(
    captured: _PersistenceCapture,
    schema_name: str,
    payload: bytes,
) -> None:
    probe = _decode_canonical_object(payload)
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
        raise _journal_invalid("stored_schema") from schema_error


def _assemble_reset_preview(
    captured: _PersistenceCapture,
    *,
    target: str,
    reset_id: str,
    consent_id: str,
) -> dict[str, Any]:
    consent = captured.consent_state.current.value
    if consent["consent_id"] != consent_id:
        raise _reset_stale("consent_id")
    state = (
        None
        if captured.state_result is None
        else captured.state_result.state
    )
    memory_values = [item.value for item in captured.memories]
    if any(item["consent_id"] != consent_id for item in memory_values):
        raise _reset_stale("memory_consent")
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact_id": (
            f"persistence-resets/{captured.scope.key.scope}/"
            + sha256(canonical_bytes(reset_id)).hexdigest()[:32]
        ),
        "created_by": {"component": "kokoroarc", "version": __version__},
        "reset_id": reset_id,
        "target": target,
        "scope": captured.scope.key.scope,
        "workspace_id": captured.scope.key.workspace_id,
        "namespace": captured.scope.key.namespace,
        "character_id": captured.scope.key.character_id,
        "consent_id": consent_id,
        "installation": _detached(consent["installation"]),
        "state_generation_id": (
            None if state is None else state["generation_id"]
        ),
        "state_sha256": (
            None if state is None else _state_sha256(state)
        ),
        "event_log_sha256": (
            None
            if captured.state_result is None
            else _event_log_sha256(captured.state_result.events)
        ),
        "expected_state_revision": 0 if state is None else state["revision"],
        "expected_relationship_revision": (
            0 if state is None else state["relationship"]["revision"]
        ),
        "expected_mood_revision": (
            0 if state is None else state["mood"]["revision"]
        ),
        "memory_root_present": captured.memory_root_present,
        "memory_reference_ids": [
            item["memory_reference_id"] for item in memory_values
        ],
        "memory_references_sha256": _memory_references_sha256(
            captured.memories
        ),
        "preview_sha256": None,
    }
    document["preview_sha256"] = sha256(
        canonical_bytes(document)
    ).hexdigest()
    return document


def _event_log_sha256(events: tuple[ArtifactSnapshot, ...]) -> str:
    event_hashes = [sha256(event.payload).hexdigest() for event in events]
    return sha256(canonical_bytes(event_hashes)).hexdigest()


def _memory_references_sha256(
    memories: tuple[ArtifactSnapshot, ...],
) -> str:
    return _memory_collection_sha256(memories)


def _require_reset_request(
    target: Any,
    reset_id: Any,
    consent_id: Any,
) -> None:
    if target not in _RESET_TARGETS:
        raise _reset_stale("target")
    try:
        _require_stable_id(reset_id, "reset_id")
    except KokoroError as error:
        raise _reset_stale("reset_id") from error
    if not isinstance(consent_id, str):
        raise _reset_stale("consent_id")


def _reset_persistent_data(
    data_root: Path,
    character_id: str,
    preview: PersistentResetPreview,
    consent_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str,
    workspace_root: Path | None,
    limits: PersistenceLimits,
) -> dict[str, Any]:
    if not isinstance(preview, PersistentResetPreview):
        raise _reset_stale("preview_type")
    preview_payload = preview.payload
    if not isinstance(preview_payload, bytes):
        raise _reset_stale("preview_type")
    document = _decode_reset_preview(preview_payload)
    _require_reset_request(
        document["target"],
        document["reset_id"],
        consent_id,
    )
    if document["consent_id"] != consent_id:
        raise _reset_stale("consent_id")
    captured_workspace = _capture_workspace_root(workspace_root)
    scope = open_persistence_scope(
        data_root,
        _NoCallbackSchemas(),
        namespace=namespace,
        character_id=character_id,
        workspace_root=captured_workspace,
        limits=limits,
    )
    _require_reset_scope(scope, document)
    _audit_preview(scope.boundary, preview, preview_payload)

    with _acquire_character_lock(scope) as lock, _audit_failures(
        scope.boundary
    ):
        receipt = _read_reset_receipt(scope, document["reset_id"])
        marker = _read_reset_marker(scope)
        _confirm_reset_durability(scope, receipt, marker)
        if receipt is not None:
            result = _validate_reset_receipt(
                receipt,
                document,
                preview_payload,
            )
            if marker is not None:
                _require_reset_marker(marker.value, document, preview_payload)
                _remove_reset_marker(scope, marker, lock)
            scope.boundary.assert_clean()
            return result

        if marker is None:
            captured = _capture_persistence_scope(
                scope,
                schemas,
                captured_workspace,
            )
            expected = _assemble_reset_preview(
                captured,
                target=cast(str, document["target"]),
                reset_id=cast(str, document["reset_id"]),
                consent_id=consent_id,
            )
            if canonical_bytes(expected) != preview_payload:
                raise _reset_stale("preview_changed")
            captured.assert_clean()
            marker_value = _reset_marker_document(
                document,
                phase="prepared",
                memory_directory_identity=_reset_memory_directory_identity(
                    scope,
                    document,
                ),
                memory_reference_sha256s=_reset_memory_reference_sha256s(
                    captured,
                    document,
                ),
            )
            captured.assert_clean()
            marker = _write_transaction_marker(
                scope,
                canonical_bytes(marker_value),
                lock,
            )
            _retain_reset_marker(scope, marker)
        else:
            _require_reset_marker(marker.value, document, preview_payload)
            _recover_locked_state(scope, lock, captured_workspace)
            _confirm_reset_state_durability(scope, document)
            captured = _capture_persistence_scope(
                scope,
                schemas,
                captured_workspace,
            )
            _require_reset_resume_binding(captured, document)

        result, marker = _complete_reset_transaction(
            captured,
            document,
            marker,
            preview_payload,
            lock,
        )
        captured.assert_clean()
        return result


def _decode_reset_preview(payload: bytes) -> dict[str, Any]:
    try:
        document = _decode_canonical_object(payload)
    except KokoroError as error:
        raise _reset_stale("preview_bytes") from error
    if set(document) != _RESET_PREVIEW_KEYS:
        raise _reset_stale("preview_shape")
    if document.get("schema_version") != "1.0":
        raise _reset_stale("preview_version")
    expected_hash = document.get("preview_sha256")
    unhashed = _detached(document)
    unhashed["preview_sha256"] = None
    if (
        not isinstance(expected_hash, str)
        or re.fullmatch(r"[a-f0-9]{64}", expected_hash) is None
        or sha256(canonical_bytes(unhashed)).hexdigest() != expected_hash
    ):
        raise _reset_stale("preview_hash")
    _require_reset_request(
        document.get("target"),
        document.get("reset_id"),
        document.get("consent_id"),
    )
    if (
        not isinstance(document.get("expected_state_revision"), int)
        or isinstance(document["expected_state_revision"], bool)
        or document["expected_state_revision"] < 0
        or not isinstance(document.get("expected_relationship_revision"), int)
        or isinstance(document["expected_relationship_revision"], bool)
        or document["expected_relationship_revision"] < 0
        or not isinstance(document.get("expected_mood_revision"), int)
        or isinstance(document["expected_mood_revision"], bool)
        or document["expected_mood_revision"] < 0
    ):
        raise _reset_stale("preview_revision")
    memory_ids = document.get("memory_reference_ids")
    if (
        not isinstance(memory_ids, list)
        or len(memory_ids) > 1024
        or memory_ids != sorted(memory_ids)
        or len(set(memory_ids)) != len(memory_ids)
        or any(
            not isinstance(item, str)
            or re.fullmatch(r"memory-[a-f0-9]{32}", item) is None
            for item in memory_ids
        )
        or not isinstance(document.get("memory_root_present"), bool)
    ):
        raise _reset_stale("preview_memory")
    for field in (
        "state_sha256",
        "event_log_sha256",
        "memory_references_sha256",
    ):
        value = document.get(field)
        if (
            value is not None
            and (
                not isinstance(value, str)
                or re.fullmatch(r"[a-f0-9]{64}", value) is None
            )
        ):
            raise _reset_stale("preview_hash_field")
    return document


def _require_reset_scope(
    scope: PersistenceScope,
    document: dict[str, Any],
) -> None:
    actual = {
        "scope": scope.key.scope,
        "workspace_id": scope.key.workspace_id,
        "namespace": scope.key.namespace,
        "character_id": scope.key.character_id,
    }
    expected = {field: document.get(field) for field in actual}
    if actual != expected:
        raise _reset_stale("scope")


def _audit_preview(
    boundary: PersistenceBoundary,
    preview: PersistentResetPreview,
    payload: bytes,
) -> None:
    def audit() -> None:
        if preview.payload != payload:
            boundary.fail("reset_preview")

    boundary.audits["input:reset_preview"] = audit


def _reset_receipt_path(scope: PersistenceScope, reset_id: str) -> Path:
    digest = sha256(canonical_bytes(reset_id)).hexdigest()
    return _state_root(scope) / "resets" / f"{digest}.json"


def _read_reset_receipt(
    scope: PersistenceScope,
    reset_id: str,
) -> ArtifactSnapshot | None:
    path = _reset_receipt_path(scope, reset_id)
    if _lstat(path) is None:
        return None
    snapshot = _snapshot_canonical_file(
        path,
        scope.limits.max_transaction_bytes,
    )
    scope.boundary.audits[f"reset-receipt:{path}"] = _file_audit(
        path,
        snapshot.payload,
        snapshot.identity,
    )
    return snapshot


def _read_reset_marker(scope: PersistenceScope) -> ArtifactSnapshot | None:
    if _lstat(scope.transaction_path) is None:
        return None
    snapshot = _snapshot_canonical_file(
        scope.transaction_path,
        scope.limits.max_transaction_bytes,
    )
    _retain_reset_marker(scope, snapshot)
    return snapshot


def _retain_reset_marker(
    scope: PersistenceScope,
    snapshot: ArtifactSnapshot,
) -> None:
    scope.boundary.audits["reset-transaction-marker"] = _file_audit(
        snapshot.path,
        snapshot.payload,
        snapshot.identity,
    )


def _release_reset_marker(scope: PersistenceScope) -> None:
    scope.boundary.assert_clean()
    scope.boundary.audits.pop("reset-transaction-marker", None)


def _remove_reset_marker(
    scope: PersistenceScope,
    marker: ArtifactSnapshot,
    lock: PersistenceLock,
) -> None:
    _release_reset_marker(scope)
    _remove_transaction_marker(scope, marker, lock)


def _confirm_reset_durability(
    scope: PersistenceScope,
    receipt: ArtifactSnapshot | None,
    marker: ArtifactSnapshot | None,
) -> None:
    directories = {
        snapshot.path.parent
        for snapshot in (receipt, marker)
        if snapshot is not None
    }
    transaction_parent = scope.transaction_path.parent
    if _lstat(transaction_parent) is not None:
        directories.add(transaction_parent)
    try:
        for directory in sorted(directories, key=os.fspath):
            _fsync_directory(directory)
    except (KokoroError, OSError) as error:
        raise _reset_durability_failed("recovery_fsync") from error


def _confirm_reset_state_durability(
    scope: PersistenceScope,
    preview: dict[str, Any],
) -> None:
    generation_id = preview["state_generation_id"]
    if generation_id is None:
        return
    if (
        not isinstance(generation_id, str)
        or _GENERATION_PATTERN.fullmatch(generation_id) is None
    ):
        raise _reset_stale("state_generation")
    generation_root = _generation_root(scope, generation_id)
    directories = (
        generation_root / "events",
        generation_root,
        _state_root(scope),
    )
    try:
        for directory in directories:
            if _lstat(directory) is not None:
                _fsync_directory(directory)
    except (KokoroError, OSError) as error:
        raise _reset_durability_failed("state_recovery_fsync") from error


def _reset_memory_directory_identity(
    scope: PersistenceScope,
    preview: dict[str, Any],
) -> dict[str, int] | None:
    if preview["target"] not in {"memory", "all"}:
        return None
    root = _memory_root(scope)
    if not preview["memory_root_present"]:
        if _lstat(root) is not None:
            raise _reset_stale("memory_membership")
        return None
    identity = _capture_directory_identity(root)
    return {
        "device": identity.device,
        "inode": identity.inode,
        "file_type": identity.file_type,
    }


def _reset_memory_reference_sha256s(
    captured: _PersistenceCapture,
    preview: dict[str, Any],
) -> list[str]:
    if preview["target"] not in {"memory", "all"}:
        return []
    reference_ids = [
        cast(str, snapshot.value["memory_reference_id"])
        for snapshot in captured.memories
    ]
    if reference_ids != preview["memory_reference_ids"]:
        raise _reset_stale("memory_membership")
    return [sha256(snapshot.payload).hexdigest() for snapshot in captured.memories]


def _reset_marker_document(
    preview: dict[str, Any],
    *,
    phase: str,
    memory_directory_identity: dict[str, int] | None,
    memory_reference_sha256s: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "kind": "persistent_reset",
        "reset_id": preview["reset_id"],
        "target": preview["target"],
        "scope": preview["scope"],
        "workspace_id": preview["workspace_id"],
        "namespace": preview["namespace"],
        "character_id": preview["character_id"],
        "consent_id": preview["consent_id"],
        "preview": _detached(preview),
        "phase": phase,
        "memory_directory_identity": (
            None
            if memory_directory_identity is None
            else _detached(memory_directory_identity)
        ),
        "memory_reference_sha256s": list(memory_reference_sha256s),
    }


def _require_reset_marker(
    marker: dict[str, Any],
    preview: dict[str, Any],
    preview_payload: bytes,
) -> None:
    expected_keys = {
        "schema_version",
        "kind",
        "reset_id",
        "target",
        "scope",
        "workspace_id",
        "namespace",
        "character_id",
        "consent_id",
        "preview",
        "phase",
        "memory_directory_identity",
        "memory_reference_sha256s",
    }
    if (
        set(marker) != expected_keys
        or marker.get("schema_version") != "1.0"
        or marker.get("kind") != "persistent_reset"
        or marker.get("phase") not in {"prepared", "memory_committed"}
        or canonical_bytes(marker.get("preview")) != preview_payload
    ):
        raise _reset_stale("transaction_marker")
    for field in (
        "reset_id",
        "target",
        "scope",
        "workspace_id",
        "namespace",
        "character_id",
        "consent_id",
    ):
        if marker.get(field) != preview.get(field):
            raise _reset_stale("transaction_binding")
    identity = marker.get("memory_directory_identity")
    reference_sha256s = marker.get("memory_reference_sha256s")
    if identity is not None and (
        not isinstance(identity, dict)
        or set(identity) != {"device", "inode", "file_type"}
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in identity.values()
        )
    ):
        raise _reset_stale("transaction_memory_identity")
    if not isinstance(reference_sha256s, list) or any(
        not isinstance(value, str)
        or re.fullmatch(r"[a-f0-9]{64}", value) is None
        for value in reference_sha256s
    ):
        raise _reset_stale("transaction_memory_references")
    expected_ids = (
        preview["memory_reference_ids"]
        if preview["target"] in {"memory", "all"}
        else []
    )
    identity_required = (
        preview["target"] in {"memory", "all"}
        and preview["memory_root_present"]
    )
    if (
        len(reference_sha256s) != len(expected_ids)
        or (identity is not None) != identity_required
        or (
            marker["phase"] == "memory_committed"
            and preview["target"] not in {"memory", "all"}
        )
    ):
        raise _reset_stale("transaction_memory_binding")


def _validate_reset_receipt(
    snapshot: ArtifactSnapshot,
    preview: dict[str, Any],
    preview_payload: bytes,
) -> dict[str, Any]:
    receipt = snapshot.value
    expected_state_revision = _expected_reset_state_revision(preview)
    expected_removed_ids = (
        preview["memory_reference_ids"]
        if preview["target"] in {"memory", "all"}
        else []
    )
    expected_artifact_id = (
        f"persistence-reset-receipts/{preview['scope']}/"
        + sha256(canonical_bytes(preview["reset_id"])).hexdigest()[:32]
    )
    created_by = receipt.get("created_by")
    expected_keys = {
        "schema_version",
        "artifact_id",
        "created_by",
        "reset_id",
        "target",
        "scope",
        "workspace_id",
        "namespace",
        "character_id",
        "consent_id",
        "preview_sha256",
        "preview_payload_sha256",
        "record_state",
        "state_revision",
        "removed_memory_reference_ids",
    }
    if (
        set(receipt) != expected_keys
        or receipt.get("schema_version") != "1.0"
        or receipt.get("record_state") != "committed"
        or receipt.get("artifact_id") != expected_artifact_id
        or not isinstance(created_by, dict)
        or set(created_by) != {"component", "version"}
        or created_by.get("component") != "kokoroarc"
        or not isinstance(created_by.get("version"), str)
        or not 1 <= len(created_by["version"]) <= 64
        or receipt.get("preview_sha256") != preview["preview_sha256"]
        or receipt.get("preview_payload_sha256")
        != sha256(preview_payload).hexdigest()
        or receipt.get("state_revision") != expected_state_revision
        or receipt.get("removed_memory_reference_ids")
        != expected_removed_ids
    ):
        raise _reset_stale("reset_receipt")
    for field in (
        "reset_id",
        "target",
        "scope",
        "workspace_id",
        "namespace",
        "character_id",
        "consent_id",
    ):
        if receipt.get(field) != preview.get(field):
            raise _reset_stale("reset_receipt_binding")
    return _detached(receipt)


def _expected_reset_state_revision(preview: dict[str, Any]) -> int | None:
    if preview["state_generation_id"] is None:
        return None
    target = preview["target"]
    increments = int(target in {"relationship", "all"}) + int(
        target in {"mood", "all"}
    )
    return cast(int, preview["expected_state_revision"]) + increments


def _require_reset_resume_binding(
    captured: _PersistenceCapture,
    preview: dict[str, Any],
) -> None:
    current = captured.consent_state.current.value
    if (
        current["consent_id"] != preview["consent_id"]
        or current["installation"] != preview["installation"]
    ):
        raise _reset_stale("consent_changed")
    state = (
        None
        if captured.state_result is None
        else captured.state_result.state
    )
    expected_generation = preview["state_generation_id"]
    if (
        (state is None) != (expected_generation is None)
        or (
            state is not None
            and state["generation_id"] != expected_generation
        )
    ):
        raise _reset_stale("state_generation")


def _complete_reset_transaction(
    captured: _PersistenceCapture,
    preview: dict[str, Any],
    marker: ArtifactSnapshot,
    preview_payload: bytes,
    lock: PersistenceLock,
) -> tuple[dict[str, Any], ArtifactSnapshot]:
    scope = captured.scope
    target = cast(str, preview["target"])
    state = (
        None
        if captured.state_result is None
        else captured.state_result.state
    )
    state_reset_count = 0
    if state is not None and target in {"relationship", "all"}:
        _drop_capture_store_audits(captured, _state_root(scope))
        state = _append_reset_state_event(
            captured,
            operation_kind="relationship_reset",
            reset_id=cast(str, preview["reset_id"]),
            expected_outer_revision=cast(
                int,
                preview["expected_state_revision"],
            ),
            expected_component_revision=cast(
                int,
                preview["expected_relationship_revision"],
            ),
            lock=lock,
        )
        state_reset_count += 1
    if state is not None and target in {"mood", "all"}:
        _drop_capture_store_audits(captured, _state_root(scope))
        state = _append_reset_state_event(
            captured,
            operation_kind="mood_reset",
            reset_id=cast(str, preview["reset_id"]),
            expected_outer_revision=(
                cast(int, preview["expected_state_revision"])
                + state_reset_count
            ),
            expected_component_revision=cast(
                int,
                preview["expected_mood_revision"],
            ),
            lock=lock,
        )
        state_reset_count += 1

    if state is not None:
        expected_final_revision = (
            cast(int, preview["expected_state_revision"])
            + state_reset_count
        )
        if state["revision"] != expected_final_revision:
            raise _reset_stale("state_revision")
    elif preview["state_generation_id"] is not None:
        raise _reset_stale("state_missing")

    if target in {"memory", "all"}:
        _drop_capture_store_audits(captured, _memory_root(scope))
        directory_identity = cast(
            dict[str, int] | None,
            marker.value["memory_directory_identity"],
        )
        reference_bindings = tuple(
            zip(
                preview["memory_reference_ids"],
                marker.value["memory_reference_sha256s"],
                strict=True,
            )
        )
        memory_scope = PersistenceScope(
            root=scope.root,
            key=scope.key,
            boundary=PersistenceBoundary(
                _AuditedSchemas(captured.schemas, scope.boundary)
            ),
            limits=scope.limits,
        )
        if marker.value["phase"] == "prepared":
            cleanup = _cutover_memory_reset(
                memory_scope,
                reset_id=cast(str, preview["reset_id"]),
                expected_root_present=cast(
                    bool,
                    preview["memory_root_present"],
                ),
                expected_ids=tuple(preview["memory_reference_ids"]),
                expected_sha256=cast(
                    str,
                    preview["memory_references_sha256"],
                ),
                expected_directory_identity=directory_identity,
                expected_references=reference_bindings,
                lock=lock,
            )
            marker = _update_reset_marker(
                scope,
                marker,
                preview,
                phase="memory_committed",
                lock=lock,
            )
        else:
            cleanup = _memory_reset_cleanup_path(
                memory_scope,
                cast(str, preview["reset_id"]),
            )
        if cleanup is not None:
            _cleanup_memory_reset(
                memory_scope,
                reset_id=cast(str, preview["reset_id"]),
                expected_ids=tuple(preview["memory_reference_ids"]),
                expected_sha256=cast(
                    str,
                    preview["memory_references_sha256"],
                ),
                expected_directory_identity=directory_identity,
                expected_references=reference_bindings,
                lock=lock,
            )

    confirmed = _read_current(scope, captured.workspace_root)
    confirmed_state = None if confirmed is None else confirmed.state
    if confirmed_state is not None and state is not None:
        if canonical_bytes(confirmed_state) != canonical_bytes(state):
            raise _reset_stale("state_confirmation")
    result = _reset_receipt_document(
        scope,
        preview,
        preview_payload,
        confirmed_state,
    )
    receipt_payload = canonical_bytes(result)
    existing = _read_reset_receipt(scope, cast(str, preview["reset_id"]))
    if existing is None:
        receipt = _publish_new_file(
            scope,
            _reset_receipt_path(scope, cast(str, preview["reset_id"])),
            receipt_payload,
            lock,
        )
        scope.boundary.audits[f"reset-receipt:{receipt.path}"] = _file_audit(
            receipt.path,
            receipt.payload,
            receipt.identity,
        )
    else:
        if existing.payload != receipt_payload:
            raise _reset_stale("reset_id_reused")
        receipt = existing
    _remove_reset_marker(scope, marker, lock)
    lock.assert_owned()
    scope.boundary.assert_clean()
    return _detached(result), marker


def _append_reset_state_event(
    captured: _PersistenceCapture,
    *,
    operation_kind: str,
    reset_id: str,
    expected_outer_revision: int,
    expected_component_revision: int,
    lock: PersistenceLock,
) -> dict[str, Any]:
    scope = captured.scope
    current = _read_current(scope, captured.workspace_root)
    if current is None:
        raise _reset_stale("state_missing")
    operation_id = _reset_operation_id(reset_id, operation_kind)
    existing = _find_operation(current.events, operation_id)
    payload_key = (
        "expected_relationship_revision"
        if operation_kind == "relationship_reset"
        else "expected_mood_revision"
    )
    payload = {
        "reset_id": reset_id,
        payload_key: expected_component_revision,
    }
    if existing is not None:
        if (
            existing.value["operation_kind"] != operation_kind
            or existing.value["payload"] != payload
        ):
            raise _reset_stale("reset_id_reused")
        current.boundary.assert_clean()
        return _detached(current.state)
    if current.state["revision"] != expected_outer_revision:
        raise _reset_stale("state_revision")
    if len(current.events) >= scope.limits.max_state_events:
        raise _event_limit(scope.limits.max_state_events)
    if operation_kind == "relationship_reset":
        successor = _relationship_reset_successor(
            current.state,
            payload,
            operation_id,
        )
    elif operation_kind == "mood_reset":
        successor = _mood_reset_successor(
            current.state,
            payload,
            operation_id,
        )
    else:
        raise _reset_stale("operation_kind")
    record = _reset_operation_record(
        scope,
        current.state,
        successor,
        operation_kind,
        payload,
        operation_id,
    )
    record_payload = canonical_bytes(record)
    if len(record_payload) > scope.limits.max_event_bytes:
        raise _event_limit(scope.limits.max_event_bytes, reason="event_bytes")
    _validate_reset_generated_payload(
        captured,
        current.boundary,
        "persistent-state-event",
        record_payload,
    )
    successor["last_event_sha256"] = sha256(record_payload).hexdigest()
    state_payload = canonical_bytes(successor)
    if len(state_payload) > scope.limits.max_state_bytes:
        raise _event_limit(scope.limits.max_state_bytes, reason="state_bytes")
    _validate_reset_generated_payload(
        captured,
        current.boundary,
        "persistent-character-state",
        state_payload,
    )
    current.boundary.assert_clean()
    captured.assert_clean()
    lock.assert_owned()
    _publish_new_file(
        scope,
        _event_path(
            scope,
            cast(str, current.state["generation_id"]),
            cast(int, record["revision"]),
            operation_id,
        ),
        record_payload,
        lock,
    )
    try:
        _write_projection(
            scope,
            cast(str, current.state["generation_id"]),
            successor,
            lock,
        )
        _write_pointer(
            scope,
            cast(str, current.state["generation_id"]),
            lock,
        )
    except KokoroError as error:
        raise _state_write_failed("reset_projection", error) from error
    confirmed = _read_current(scope, captured.workspace_root)
    if (
        confirmed is None
        or canonical_bytes(confirmed.state) != state_payload
    ):
        raise _state_write_failed(
            "reset_confirmation",
            _journal_invalid("publication_confirmation"),
        )
    confirmed.boundary.assert_clean()
    lock.assert_owned()
    return _detached(successor)


def _drop_capture_store_audits(
    captured: _PersistenceCapture,
    store_root: Path,
) -> None:
    root_text = os.path.normcase(os.fspath(_absolute_path(store_root)))
    boundaries = [captured.scope.boundary]
    if captured.state_result is not None:
        boundaries.append(captured.state_result.boundary)
    for boundary in boundaries:
        for name in tuple(boundary.audits):
            normalized = os.path.normcase(name)
            if root_text in normalized or (
                store_root == _state_root(captured.scope)
                and name.startswith("generation:")
            ):
                boundary.audits.pop(name, None)


def _reset_operation_id(reset_id: str, operation_kind: str) -> str:
    identity = {
        "operation_kind": operation_kind,
        "reset_id": reset_id,
    }
    return "reset-" + sha256(canonical_bytes(identity)).hexdigest()[:32]


def _reset_operation_record(
    scope: PersistenceScope,
    state: dict[str, Any],
    successor: dict[str, Any],
    operation_kind: str,
    payload: dict[str, Any],
    operation_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": _event_artifact_id(
            scope,
            state["revision"] + 1,
            operation_id,
        ),
        "created_by": {"component": "kokoroarc", "version": __version__},
        "scope": scope.key.scope,
        "workspace_id": scope.key.workspace_id,
        "installation": _detached(state["installation"]),
        "consent": _detached(state["consent"]),
        "generation_id": state["generation_id"],
        "state_contract_version": _STATE_CONTRACT_VERSION,
        "transition_algorithm": _TRANSITION_ALGORITHM,
        "revision": state["revision"] + 1,
        "operation_id": operation_id,
        "operation_kind": operation_kind,
        "predecessor_event_sha256": state["last_event_sha256"],
        "predecessor_state_sha256": _state_sha256(state),
        "successor_state_sha256": _state_sha256(successor),
        "payload": _detached(payload),
    }


def _validate_reset_generated_payload(
    captured: _PersistenceCapture,
    current_boundary: PersistenceBoundary,
    schema_name: str,
    payload: bytes,
) -> None:
    probe = _decode_canonical_object(payload)
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
            current_boundary.assert_clean()
            captured.assert_clean()
    if schema_error is not None:
        raise _journal_invalid("generated_schema") from schema_error


def _update_reset_marker(
    scope: PersistenceScope,
    current: ArtifactSnapshot,
    preview: dict[str, Any],
    *,
    phase: str,
    lock: PersistenceLock,
) -> ArtifactSnapshot:
    observed = _snapshot_canonical_file(
        scope.transaction_path,
        scope.limits.max_transaction_bytes,
    )
    if observed.payload != current.payload or observed.identity != current.identity:
        raise _reset_stale("transaction_changed")
    payload = canonical_bytes(
        _reset_marker_document(
            preview,
            phase=phase,
            memory_directory_identity=cast(
                dict[str, int] | None,
                current.value["memory_directory_identity"],
            ),
            memory_reference_sha256s=cast(
                list[str],
                current.value["memory_reference_sha256s"],
            ),
        )
    )
    _release_reset_marker(scope)
    updated = _replace_file(scope, scope.transaction_path, payload, lock)
    _retain_reset_marker(scope, updated)
    return updated


def _reset_receipt_document(
    scope: PersistenceScope,
    preview: dict[str, Any],
    preview_payload: bytes,
    state: dict[str, Any] | None,
) -> dict[str, Any]:
    target = cast(str, preview["target"])
    removed = (
        list(preview["memory_reference_ids"])
        if target in {"memory", "all"}
        else []
    )
    return {
        "schema_version": "1.0",
        "artifact_id": (
            f"persistence-reset-receipts/{scope.key.scope}/"
            + sha256(canonical_bytes(preview["reset_id"])).hexdigest()[:32]
        ),
        "created_by": {"component": "kokoroarc", "version": __version__},
        "reset_id": preview["reset_id"],
        "target": target,
        "scope": scope.key.scope,
        "workspace_id": scope.key.workspace_id,
        "namespace": scope.key.namespace,
        "character_id": scope.key.character_id,
        "consent_id": preview["consent_id"],
        "preview_sha256": preview["preview_sha256"],
        "preview_payload_sha256": sha256(preview_payload).hexdigest(),
        "record_state": "committed",
        "state_revision": None if state is None else state["revision"],
        "removed_memory_reference_ids": removed,
    }


def _load_or_replay(
    data_root: Path,
    character_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str,
    workspace_root: Path | None,
    limits: PersistenceLimits,
    repair: bool,
) -> dict[str, Any] | None:
    if repair:
        raise _journal_invalid("read_only_repair")
    return _replay_read_only(
        data_root,
        character_id,
        schemas,
        namespace=namespace,
        workspace_root=workspace_root,
        limits=limits,
    )


def _replay_read_only(
    data_root: Path,
    character_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str,
    workspace_root: Path | None,
    limits: PersistenceLimits,
) -> dict[str, Any] | None:
    captured_workspace = _capture_workspace_root(workspace_root)
    scope = open_persistence_scope(
        data_root,
        schemas,
        namespace=namespace,
        character_id=character_id,
        workspace_root=captured_workspace,
        limits=limits,
    )
    pointer = _read_pointer(scope, optional=True)
    if pointer is None:
        scope.boundary.assert_clean()
        return None
    result = _replay_generation(
        scope,
        cast(str, pointer.value["generation_id"]),
        allow_projection_mismatch=False,
    )
    result.boundary.assert_clean()
    return _detached(result.state)


def _apply_state_operation(
    *,
    data_root: Path,
    character_id: str,
    operation_kind: str,
    operation_payload: Mapping[str, Any],
    consent_id: str,
    consent_revision: int,
    schemas: SchemaValidator,
    expected_state_revision: int,
    operation_id: str,
    namespace: str,
    workspace_root: Path | None,
    limits: PersistenceLimits,
) -> dict[str, Any]:
    if operation_kind not in {"relationship", "mood_update", "mood_advance"}:
        raise _contract_unsupported("operation_kind")
    _require_revision(expected_state_revision, "expected_state_revision")
    _require_revision(consent_revision, "consent_revision", minimum=1)
    _require_stable_id(operation_id, "operation_id")
    if not isinstance(consent_id, str):
        raise _journal_invalid("consent_id")

    captured_workspace = _capture_workspace_root(workspace_root)
    scope = open_persistence_scope(
        data_root,
        schemas,
        namespace=namespace,
        character_id=character_id,
        workspace_root=captured_workspace,
        limits=limits,
    )
    operation_payload_bytes = _capture_mapping(
        scope.boundary,
        "operation_payload",
        operation_payload,
    )
    event = _decode_mapping(operation_payload_bytes, "operation_payload")
    _validate_operation_payload(
        scope.boundary,
        operation_kind,
        operation_payload_bytes,
        event,
    )
    permission = (
        "relationship_state"
        if operation_kind == "relationship"
        else "mood_state"
    )

    with _acquire_character_lock(scope) as lock, _audit_failures(
        scope.boundary
    ):
        _recover_locked_state(scope, lock, captured_workspace)
        active = _require_active_consent(
            scope.root,
            character_id,
            consent_id,
            consent_revision,
            permission,
            _AuditedSchemas(schemas, scope.boundary),
            namespace=namespace,
            workspace_root=captured_workspace,
            limits=limits,
        )
        active.assert_clean()
        scope.boundary.assert_clean()
        current = _read_current(scope, captured_workspace)
        if current is None:
            generation_id = _generation_id(
                scope,
                active,
                operation_id,
                operation_kind,
                event,
            )
            _require_generation_capacity(
                scope,
                generation_id,
                captured_workspace,
            )
            state = _initial_state(scope, active, generation_id)
            records: tuple[ArtifactSnapshot, ...] = ()
            replay_boundary: PersistenceBoundary | None = None
        else:
            state = current.state
            records = current.events
            replay_boundary = current.boundary
            generation_id = cast(str, state["generation_id"])
            _require_active_generation(state, active)

        growth = (
            _growth_config(active.compiled)
            if operation_kind == "relationship"
            else None
        )
        duplicate = _find_operation(records, operation_id)
        if duplicate is not None:
            if not _exact_operation_retry(
                duplicate.value,
                operation_kind,
                event,
                growth,
                expected_state_revision,
            ):
                raise _revision_conflict("operation_id_reused")
            _finish_read_only_apply(
                lock,
                scope,
                active,
                replay_boundary,
            )
            return _detached(state)
        if _find_operation_event(
            records,
            operation_kind,
            cast(str, event["event_id"]),
        ):
            raise _revision_conflict("event_id_reused")
        if state["revision"] != expected_state_revision:
            raise _revision_conflict("outer_revision")
        _require_operation_revision(state, operation_kind, event)
        if len(records) >= limits.max_state_events:
            raise _event_limit(limits.max_state_events)
        if len(state["applied_operation_ids"]) >= limits.max_state_events:
            raise _event_limit(limits.max_state_events)

        successor = _operation_successor(
            state,
            operation_kind,
            event,
            growth,
            operation_id,
            scope.boundary,
        )
        record = _operation_record(
            scope,
            active,
            generation_id,
            state,
            successor,
            operation_kind,
            event,
            growth,
            operation_id,
        )
        record_payload = canonical_bytes(record)
        if len(record_payload) > limits.max_event_bytes:
            raise _event_limit(limits.max_event_bytes, reason="event_bytes")
        record = validate_and_finalize(
            "persistent-state-event",
            record,
            scope.boundary,
        )
        record_payload = canonical_bytes(record)
        event_sha256 = sha256(record_payload).hexdigest()
        successor["last_event_sha256"] = event_sha256
        successor_payload = canonical_bytes(successor)
        if len(successor_payload) > limits.max_state_bytes:
            raise _event_limit(limits.max_state_bytes, reason="state_bytes")
        successor = validate_and_finalize(
            "persistent-character-state",
            successor,
            scope.boundary,
        )
        successor_payload = canonical_bytes(successor)

        if replay_boundary is not None:
            replay_boundary.assert_clean()
        active.assert_clean()
        lock.assert_owned()
        event_path = _event_path(
            scope,
            generation_id,
            cast(int, record["revision"]),
            operation_id,
        )
        _publish_new_file(scope, event_path, record_payload, lock)
        try:
            _write_projection(scope, generation_id, successor, lock)
        except KokoroError as error:
            raise _state_write_failed("projection", error) from error
        try:
            _write_pointer(scope, generation_id, lock)
        except KokoroError as error:
            raise _state_write_failed("pointer", error) from error

        confirmed = _read_current(scope, captured_workspace)
        if confirmed is None or canonical_bytes(confirmed.state) != successor_payload:
            raise _state_write_failed(
                "confirmation",
                _journal_invalid("publication_confirmation"),
            )
        confirmed.boundary.assert_clean()
        active.assert_clean()
        lock.assert_owned()
        return _detached(successor)


def _recover_locked_state(
    scope: PersistenceScope,
    lock: PersistenceLock,
    workspace_root: Path | None,
) -> None:
    read_scope = _fresh_scope(scope, workspace_root)
    pointer = _read_pointer(read_scope, optional=True)
    if pointer is None:
        generation_ids = _scan_generation_ids(read_scope)
        if not generation_ids:
            return
        if len(generation_ids) != 1:
            raise _journal_invalid("current_generation_missing")
        generation_id = generation_ids[0]
    else:
        generation_id = cast(str, pointer.value["generation_id"])
    replayed = _replay_generation(
        read_scope,
        generation_id,
        allow_projection_mismatch=True,
    )
    if not replayed.projection_matches:
        _write_projection(scope, generation_id, replayed.state, lock)
    if pointer is None:
        _write_pointer(scope, generation_id, lock)


def _read_current(
    scope: PersistenceScope,
    workspace_root: Path | None,
) -> _ReplayResult | None:
    read_scope = _fresh_scope(scope, workspace_root)
    pointer = _read_pointer(read_scope, optional=True)
    if pointer is None:
        read_scope.boundary.assert_clean()
        return None
    return _replay_generation(
        read_scope,
        cast(str, pointer.value["generation_id"]),
        allow_projection_mismatch=False,
    )


def _replay_generation(
    scope: PersistenceScope,
    generation_id: str,
    *,
    allow_projection_mismatch: bool,
) -> _ReplayResult:
    if _GENERATION_PATTERN.fullmatch(generation_id) is None:
        raise _journal_invalid("generation_id")
    generation_root = _generation_root(scope, generation_id)
    ancestry = _capture_directory_chain(generation_root)
    scope.boundary.audits[f"generation:{generation_id}"] = (
        lambda: _assert_directory_chain(ancestry, "generation_changed")
    )
    events = tuple(
        scan_canonical_directory(
            generation_root / "events",
            entry_limit=scope.limits.max_state_events,
            aggregate_limit=scope.limits.max_journal_bytes,
            file_limit=scope.limits.max_event_bytes,
            schema_name="persistent-state-event",
            boundary=scope.boundary,
        )
    )
    if not events:
        raise _journal_invalid("empty_journal")

    first = events[0].value
    _require_event_contract(first, scope, generation_id)
    state = _initial_state_from_event(scope, first)
    operation_ids: set[str] = set()
    interaction_ids: set[str] = set()
    mood_event_ids: set[str] = set()
    predecessor_event_sha256: str | None = None
    for expected_revision, snapshot in enumerate(events, start=1):
        record = snapshot.value
        _require_event_contract(record, scope, generation_id)
        operation_id = cast(str, record["operation_id"])
        if record["installation"] != state["installation"]:
            raise _journal_invalid("installation_binding")
        if record["consent"] != state["consent"]:
            raise _journal_invalid("consent_binding")
        expected_name = _event_name(expected_revision, operation_id)
        if snapshot.path.name != expected_name:
            raise _journal_invalid("event_name")
        if record["revision"] != expected_revision:
            raise _journal_invalid("revision_sequence")
        if operation_id in operation_ids:
            raise _journal_invalid("duplicate_operation_id")
        if record["predecessor_event_sha256"] != predecessor_event_sha256:
            raise _journal_invalid("predecessor_event")
        if record["predecessor_state_sha256"] != _state_sha256(state):
            raise _journal_invalid("predecessor_state")
        operation_kind = cast(str, record["operation_kind"])
        payload = cast(dict[str, Any], record["payload"])
        if operation_kind == "relationship":
            interaction = cast(dict[str, Any], payload["interaction_event"])
            interaction_id = cast(str, interaction["event_id"])
            if interaction_id in interaction_ids:
                raise _journal_invalid("duplicate_event_id")
            if (
                interaction["expected_state_revision"]
                != state["relationship"]["revision"]
            ):
                raise _journal_invalid("relationship_revision")
            growth = _recorded_growth(payload)
            successor = _relationship_successor(
                state,
                interaction,
                growth,
                operation_id,
                scope.boundary,
            )
            interaction_ids.add(interaction_id)
        elif operation_kind in {"mood_update", "mood_advance"}:
            mood_event_id = cast(str, payload["event_id"])
            if mood_event_id in mood_event_ids:
                raise _journal_invalid("duplicate_mood_event_id")
            try:
                successor = _mood_successor(
                    state,
                    operation_kind,
                    payload,
                    operation_id,
                )
            except KokoroError as error:
                if error.code in {
                    "PERSISTENCE_MOOD_INVALID",
                    "PERSISTENCE_STATE_REVISION_CONFLICT",
                }:
                    raise _journal_invalid("mood_event") from error
                raise
            mood_event_ids.add(mood_event_id)
        elif operation_kind == "relationship_reset":
            successor = _relationship_reset_successor(
                state,
                payload,
                operation_id,
            )
        elif operation_kind == "mood_reset":
            successor = _mood_reset_successor(
                state,
                payload,
                operation_id,
            )
        elif operation_kind == "migration_marker":
            successor = _migration_marker_successor(
                state,
                payload,
                operation_id,
            )
        else:
            raise _contract_unsupported("operation_kind")
        if record["successor_state_sha256"] != _state_sha256(successor):
            raise _journal_invalid("successor_state")
        event_sha256 = sha256(snapshot.payload).hexdigest()
        successor["last_event_sha256"] = event_sha256
        scope.boundary.validate(
            "persistent-character-state",
            canonical_bytes(successor),
        )
        state = successor
        predecessor_event_sha256 = event_sha256
        operation_ids.add(operation_id)

    projection_present = True
    projection_matches = False
    try:
        projection = read_canonical_object(
            generation_root / "state.json",
            limit=scope.limits.max_state_bytes,
            schema_name="persistent-character-state",
            boundary=scope.boundary,
            optional=True,
        )
    except KokoroError as error:
        if not allow_projection_mismatch or error.code != "PERSISTENCE_CHANGED":
            raise
        projection = None
    if projection is None:
        projection_present = False
    else:
        projection_matches = projection.payload == canonical_bytes(state)
        if not projection_matches and not allow_projection_mismatch:
            raise _journal_invalid("projection_mismatch")
    replay_state = _detached(state)
    scope.boundary.capture("replay_output", replay_state)
    scope.boundary.assert_clean()
    return _ReplayResult(
        state=replay_state,
        events=events,
        boundary=scope.boundary,
        projection_present=projection_present,
        projection_matches=projection_matches,
    )


def _initial_state(
    scope: PersistenceScope,
    active: ActiveConsent,
    generation_id: str,
) -> dict[str, Any]:
    consent = active.consent
    return _initial_state_values(
        scope,
        installation=active.binding,
        consent={
            "consent_id": consent["consent_id"],
            "grant_revision": consent["grant_revision"],
        },
        generation_id=generation_id,
        created_by={"component": "kokoroarc", "version": __version__},
    )


def _initial_state_from_event(
    scope: PersistenceScope,
    event: dict[str, Any],
) -> dict[str, Any]:
    return _initial_state_values(
        scope,
        installation=cast(dict[str, Any], event["installation"]),
        consent=cast(dict[str, Any], event["consent"]),
        generation_id=cast(str, event["generation_id"]),
        created_by=cast(dict[str, Any], event["created_by"]),
    )


def _initial_state_values(
    scope: PersistenceScope,
    *,
    installation: dict[str, Any],
    consent: dict[str, Any],
    generation_id: str,
    created_by: dict[str, Any],
) -> dict[str, Any]:
    character_id = scope.key.character_id
    return {
        "schema_version": "1.0",
        "artifact_id": (
            f"persistent-state/{scope.key.scope}/{character_id}/{generation_id}"
        ),
        "created_by": deepcopy(created_by),
        "scope": scope.key.scope,
        "workspace_id": scope.key.workspace_id,
        "installation": deepcopy(installation),
        "consent": deepcopy(consent),
        "generation_id": generation_id,
        "state_contract_version": _STATE_CONTRACT_VERSION,
        "transition_algorithm": _TRANSITION_ALGORITHM,
        "revision": 0,
        "relationship": {
            "schema_version": "1.0",
            "artifact_id": f"state/{character_id}/relationship",
            "created_by": deepcopy(created_by),
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
        },
        "mood": {
            "revision": 0,
            "primary": "neutral",
            "secondary": None,
            "arousal": 0.0,
            "valence": 0.0,
            "intensity": 0.0,
            "remaining_turns": 0,
            "expires_after_turns": 0,
            "triggering_event_id": None,
            "applied_event_ids": [],
        },
        "applied_operation_ids": [],
        "last_event_sha256": None,
    }


def _operation_successor(
    state: dict[str, Any],
    operation_kind: str,
    event: dict[str, Any],
    growth: tuple[float, int] | None,
    operation_id: str,
    boundary: PersistenceBoundary,
) -> dict[str, Any]:
    if operation_kind == "relationship":
        if growth is None:
            raise _contract_unsupported("growth")
        return _relationship_successor(
            state,
            event,
            growth,
            operation_id,
            boundary,
        )
    return _mood_successor(state, operation_kind, event, operation_id)


def _relationship_successor(
    state: dict[str, Any],
    event: dict[str, Any],
    growth: tuple[float, int],
    operation_id: str,
    boundary: PersistenceBoundary,
) -> dict[str, Any]:
    transition_state = _detached(cast(dict[str, Any], state["relationship"]))
    transition_event = _detached(event)
    boundary.capture("transition_state_input", transition_state)
    boundary.capture("transition_event_input", transition_event)
    try:
        relationship = apply_event_v1(
            transition_state,
            transition_event,
            max_delta=growth[0],
            repetition_window=growth[1],
        )
    except KokoroError as error:
        boundary.assert_clean()
        if error.code == "STATE_CAPACITY_EXCEEDED":
            raise _event_limit(10_000) from error
        raise _journal_invalid("relationship_event") from error
    boundary.assert_clean()
    relationship_payload = boundary.capture("transition_output", relationship)
    relationship_value = cast(dict[str, Any], json.loads(relationship_payload))
    successor = _detached(state)
    successor["revision"] += 1
    successor["relationship"] = relationship_value
    successor["applied_operation_ids"].append(operation_id)
    return successor


def _mood_successor(
    state: dict[str, Any],
    operation_kind: str,
    event: dict[str, Any],
    operation_id: str,
) -> dict[str, Any]:
    mood = cast(dict[str, Any], state["mood"])
    if operation_kind == "mood_update":
        _validate_mood_update(event, mood)
    elif operation_kind == "mood_advance":
        _validate_mood_advance(event)
    else:
        raise _contract_unsupported("operation_kind")
    if event["expected_mood_revision"] != mood["revision"]:
        raise _revision_conflict("mood_revision")
    if len(mood["applied_event_ids"]) >= 10_000:
        raise _event_limit(10_000)

    successor = _detached(state)
    successor["revision"] += 1
    next_mood = _detached(mood)
    next_mood["revision"] += 1
    next_mood["applied_event_ids"].append(event["event_id"])
    if operation_kind == "mood_update":
        if event["primary"] == "neutral":
            _set_neutral_mood(next_mood)
        else:
            next_mood.update(
                primary=event["primary"],
                secondary=event["secondary"],
                arousal=event["arousal"],
                valence=event["valence"],
                intensity=event["intensity"],
                remaining_turns=event["expires_after_turns"],
                expires_after_turns=event["expires_after_turns"],
                triggering_event_id=event[
                    "triggering_interaction_event_id"
                ],
            )
    else:
        remaining = cast(int, next_mood["remaining_turns"])
        turns = cast(int, event["turns"])
        if remaining == 0 or turns > remaining:
            raise _mood_invalid("advance_past_expiry")
        if turns == remaining:
            _set_neutral_mood(next_mood)
        else:
            next_mood["remaining_turns"] = remaining - turns
    successor["mood"] = next_mood
    successor["applied_operation_ids"].append(operation_id)
    return successor


def _relationship_reset_successor(
    state: dict[str, Any],
    payload: dict[str, Any],
    operation_id: str,
) -> dict[str, Any]:
    if set(payload) != {"reset_id", "expected_relationship_revision"}:
        raise _journal_invalid("relationship_reset_payload")
    _require_stable_id(payload.get("reset_id"), "reset_id")
    relationship = cast(dict[str, Any], state["relationship"])
    if payload["expected_relationship_revision"] != relationship["revision"]:
        raise _revision_conflict("relationship_revision")
    if len(state["applied_operation_ids"]) >= 10_000:
        raise _event_limit(10_000)
    successor = _detached(state)
    successor["revision"] += 1
    successor["relationship"] = {
        "schema_version": relationship["schema_version"],
        "artifact_id": relationship["artifact_id"],
        "created_by": _detached(relationship["created_by"]),
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
    successor["applied_operation_ids"].append(operation_id)
    return successor


def _mood_reset_successor(
    state: dict[str, Any],
    payload: dict[str, Any],
    operation_id: str,
) -> dict[str, Any]:
    if set(payload) != {"reset_id", "expected_mood_revision"}:
        raise _journal_invalid("mood_reset_payload")
    _require_stable_id(payload.get("reset_id"), "reset_id")
    mood = cast(dict[str, Any], state["mood"])
    if payload["expected_mood_revision"] != mood["revision"]:
        raise _revision_conflict("mood_revision")
    if len(state["applied_operation_ids"]) >= 10_000:
        raise _event_limit(10_000)
    successor = _detached(state)
    successor["revision"] += 1
    successor["mood"] = {
        "revision": 0,
        "primary": "neutral",
        "secondary": None,
        "arousal": 0.0,
        "valence": 0.0,
        "intensity": 0.0,
        "remaining_turns": 0,
        "expires_after_turns": 0,
        "triggering_event_id": None,
        "applied_event_ids": [],
    }
    successor["applied_operation_ids"].append(operation_id)
    return successor


def _migration_marker_successor(
    state: dict[str, Any],
    payload: dict[str, Any],
    operation_id: str,
) -> dict[str, Any]:
    expected_keys = {
        "plan_sha256",
        "source_generation_id",
        "source_state_sha256",
        "source_event_log_sha256",
        "mood_strategy",
    }
    if set(payload) != expected_keys:
        raise _journal_invalid("migration_marker_payload")
    if (
        not isinstance(payload.get("plan_sha256"), str)
        or re.fullmatch(r"[a-f0-9]{64}", payload["plan_sha256"]) is None
        or not isinstance(payload.get("source_generation_id"), str)
        or _GENERATION_PATTERN.fullmatch(payload["source_generation_id"])
        is None
        or not isinstance(payload.get("source_state_sha256"), str)
        or re.fullmatch(r"[a-f0-9]{64}", payload["source_state_sha256"])
        is None
        or not isinstance(payload.get("source_event_log_sha256"), str)
        or re.fullmatch(
            r"[a-f0-9]{64}",
            payload["source_event_log_sha256"],
        )
        is None
        or payload.get("mood_strategy")
        not in {"preserve_identical_contract", "reset_neutral"}
    ):
        raise _journal_invalid("migration_marker_payload")
    if len(state["applied_operation_ids"]) >= 10_000:
        raise _event_limit(10_000)
    successor = _detached(state)
    successor["revision"] += 1
    successor["applied_operation_ids"].append(operation_id)
    return successor


def _set_neutral_mood(mood: dict[str, Any]) -> None:
    mood.update(
        primary="neutral",
        secondary=None,
        arousal=0.0,
        valence=0.0,
        intensity=0.0,
        remaining_turns=0,
        expires_after_turns=0,
        triggering_event_id=None,
    )


def _operation_record(
    scope: PersistenceScope,
    active: ActiveConsent,
    generation_id: str,
    state: dict[str, Any],
    successor: dict[str, Any],
    operation_kind: str,
    event: dict[str, Any],
    growth: tuple[float, int] | None,
    operation_id: str,
) -> dict[str, Any]:
    consent = active.consent
    if operation_kind == "relationship":
        if growth is None:
            raise _contract_unsupported("growth")
        payload = {
            "interaction_event": _detached(event),
            "max_delta": growth[0],
            "repetition_window": growth[1],
        }
    else:
        payload = _detached(event)
    return {
        "schema_version": "1.0",
        "artifact_id": _event_artifact_id(
            scope,
            state["revision"] + 1,
            operation_id,
        ),
        "created_by": {"component": "kokoroarc", "version": __version__},
        "scope": scope.key.scope,
        "workspace_id": scope.key.workspace_id,
        "installation": active.binding,
        "consent": {
            "consent_id": consent["consent_id"],
            "grant_revision": consent["grant_revision"],
        },
        "generation_id": generation_id,
        "state_contract_version": _STATE_CONTRACT_VERSION,
        "transition_algorithm": _TRANSITION_ALGORITHM,
        "revision": state["revision"] + 1,
        "operation_id": operation_id,
        "operation_kind": operation_kind,
        "predecessor_event_sha256": state["last_event_sha256"],
        "predecessor_state_sha256": _state_sha256(state),
        # The successor is hashed before its event hash is linked, avoiding a
        # circular event/state digest while retaining the predecessor link.
        "successor_state_sha256": _state_sha256(successor),
        "payload": payload,
    }


def _write_projection(
    scope: PersistenceScope,
    generation_id: str,
    state: dict[str, Any],
    lock: PersistenceLock,
) -> ArtifactSnapshot:
    payload = canonical_bytes(state)
    target = _generation_root(scope, generation_id) / "state.json"
    if _lstat(target) is None:
        return _publish_new_file(scope, target, payload, lock)
    return _replace_file(scope, target, payload, lock)


def _write_pointer(
    scope: PersistenceScope,
    generation_id: str,
    lock: PersistenceLock,
) -> ArtifactSnapshot:
    payload = canonical_bytes({"generation_id": generation_id})
    target = _state_root(scope) / "current.json"
    if _lstat(target) is None:
        return _publish_new_file(scope, target, payload, lock)
    current = _read_json_snapshot(
        target,
        scope.limits.max_transaction_bytes,
        scope.boundary,
        optional=False,
    )
    assert current is not None
    if current.payload == payload:
        return current
    return _replace_file(scope, target, payload, lock)


def _read_pointer(
    scope: PersistenceScope,
    *,
    optional: bool,
) -> ArtifactSnapshot | None:
    snapshot = _read_json_snapshot(
        _state_root(scope) / "current.json",
        scope.limits.max_transaction_bytes,
        scope.boundary,
        optional=optional,
    )
    if snapshot is None:
        return None
    value = snapshot.value
    if (
        set(value) != {"generation_id"}
        or not isinstance(value.get("generation_id"), str)
        or _GENERATION_PATTERN.fullmatch(value["generation_id"]) is None
    ):
        raise _journal_invalid("current_pointer")
    return snapshot


def _read_json_snapshot(
    path: Path,
    limit: int,
    boundary: PersistenceBoundary,
    *,
    optional: bool,
) -> ArtifactSnapshot | None:
    canonical_path = _absolute_path(path)
    parent_chain = None
    if _lstat(canonical_path.parent) is not None:
        parent_chain = _capture_directory_chain(canonical_path.parent)
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
    if parent_chain is None:
        raise _journal_invalid("artifact_parent")
    boundary.audits[f"ancestry:{canonical_path}"] = (
        lambda: _assert_directory_chain(parent_chain, "artifact_parent_changed")
    )
    boundary.audits[f"file:{canonical_path}"] = _file_audit(
        canonical_path,
        payload,
        identity,
    )
    return ArtifactSnapshot(
        canonical_path,
        payload,
        _decode_canonical_object(payload),
        identity,
    )


def _scan_generation_ids(scope: PersistenceScope) -> tuple[str, ...]:
    root = _state_root(scope) / "generations"
    root_stat = _lstat(root)
    if root_stat is None:
        return ()
    if _is_redirect(root, root_stat) or not stat.S_ISDIR(root_stat.st_mode):
        raise _journal_invalid("generations_layout")
    ancestry = _capture_directory_chain(root)
    names: list[str] = []
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                names.append(entry.name)
                if len(names) > scope.limits.max_state_generations:
                    raise _generation_limit(scope.limits.max_state_generations)
                entry_stat = entry.stat(follow_symlinks=False)
                path = root / entry.name
                if (
                    _GENERATION_PATTERN.fullmatch(entry.name) is None
                    or _is_redirect(path, entry_stat)
                    or not stat.S_ISDIR(entry_stat.st_mode)
                ):
                    raise _journal_invalid("generations_layout")
    except KokoroError:
        raise
    except OSError as error:
        raise _journal_invalid("generations_scan") from error
    _assert_directory_chain(ancestry, "generations_changed")
    return tuple(sorted(names))


def _require_generation_capacity(
    scope: PersistenceScope,
    generation_id: str,
    workspace_root: Path | None,
) -> None:
    generation_ids = _scan_generation_ids(_fresh_scope(scope, workspace_root))
    if (
        generation_id not in generation_ids
        and len(generation_ids) >= scope.limits.max_state_generations
    ):
        raise _generation_limit(scope.limits.max_state_generations)


def _require_event_contract(
    event: dict[str, Any],
    scope: PersistenceScope,
    generation_id: str,
) -> None:
    if event["state_contract_version"] != _STATE_CONTRACT_VERSION:
        raise _contract_unsupported("state_contract")
    if event["transition_algorithm"] != _TRANSITION_ALGORITHM:
        raise _contract_unsupported("transition_algorithm")
    operation_id = event["operation_id"]
    expected = {
        "scope": scope.key.scope,
        "workspace_id": scope.key.workspace_id,
        "namespace": scope.key.namespace,
        "character_id": scope.key.character_id,
        "generation_id": generation_id,
    }
    installation = event["installation"]
    actual = {
        "scope": event["scope"],
        "workspace_id": event["workspace_id"],
        "namespace": installation["namespace"],
        "character_id": installation["character_id"],
        "generation_id": event["generation_id"],
    }
    if actual != expected:
        raise _journal_invalid("event_binding")
    expected_artifact_id = _event_artifact_id(
        scope,
        cast(int, event["revision"]),
        cast(str, operation_id),
    )
    if event["artifact_id"] != expected_artifact_id:
        raise _journal_invalid("event_artifact_id")


def _require_active_generation(
    state: dict[str, Any],
    active: ActiveConsent,
) -> None:
    consent = active.consent
    expected_consent = {
        "consent_id": consent["consent_id"],
        "grant_revision": consent["grant_revision"],
    }
    if state["installation"] != active.binding:
        raise _migration_required("installation")
    if state["consent"] != expected_consent:
        raise _migration_required("consent")


def _growth_config(compiled: dict[str, Any]) -> tuple[float, int]:
    try:
        growth = compiled["growth"]
        max_delta = growth["max_delta_per_event"]
        repetition_window = growth["repetition_window_turns"]
    except (KeyError, TypeError) as error:
        raise _contract_unsupported("growth") from error
    if (
        isinstance(max_delta, bool)
        or not isinstance(max_delta, (int, float))
        or not 0 <= max_delta <= 4
        or isinstance(repetition_window, bool)
        or not isinstance(repetition_window, int)
        or not 1 <= repetition_window <= 10_000
    ):
        raise _contract_unsupported("growth")
    return float(max_delta), repetition_window


def _recorded_growth(payload: dict[str, Any]) -> tuple[float, int]:
    max_delta = payload.get("max_delta")
    repetition_window = payload.get("repetition_window")
    if (
        isinstance(max_delta, bool)
        or not isinstance(max_delta, (int, float))
        or not 0 <= max_delta <= 4
        or isinstance(repetition_window, bool)
        or not isinstance(repetition_window, int)
        or not 1 <= repetition_window <= 10_000
    ):
        raise _contract_unsupported("recorded_growth")
    return float(max_delta), repetition_window


def _validate_operation_payload(
    boundary: PersistenceBoundary,
    operation_kind: str,
    payload: bytes,
    event: dict[str, Any],
) -> None:
    if operation_kind == "relationship":
        boundary.validate("interaction-event", payload)
        _require_stable_id(event.get("event_id"), "event_id")
    elif operation_kind == "mood_update":
        _validate_mood_update(event)
    elif operation_kind == "mood_advance":
        _validate_mood_advance(event)
    else:
        raise _contract_unsupported("operation_kind")


def _validate_mood_update(
    event: dict[str, Any],
    current: dict[str, Any] | None = None,
) -> None:
    if set(event) != _MOOD_UPDATE_KEYS:
        raise _mood_invalid("event_shape")
    if not _is_stable_id(event.get("event_id")):
        raise _mood_invalid("event_id")
    if not _is_revision(event.get("expected_mood_revision")):
        raise _mood_invalid("expected_mood_revision")
    primary = event.get("primary")
    secondary = event.get("secondary")
    if not isinstance(primary, str) or primary not in _MOODS:
        raise _mood_invalid("primary")
    if (
        secondary is not None
        and (not isinstance(secondary, str) or secondary not in _MOODS)
    ):
        raise _mood_invalid("secondary")
    if secondary == primary:
        raise _mood_invalid("secondary_equals_primary")
    if not _bounded_number(event.get("arousal"), -1.0, 1.0):
        raise _mood_invalid("arousal")
    if not _bounded_number(event.get("valence"), -1.0, 1.0):
        raise _mood_invalid("valence")
    if not _bounded_number(event.get("intensity"), 0.0, 1.0):
        raise _mood_invalid("intensity")
    expiry = event.get("expires_after_turns")
    if (
        isinstance(expiry, bool)
        or not isinstance(expiry, int)
        or not 0 <= expiry <= 1_000
    ):
        raise _mood_invalid("expires_after_turns")
    if not _is_stable_id(event.get("triggering_interaction_event_id")):
        raise _mood_invalid("triggering_interaction_event_id")
    trigger_strength = event.get("trigger_strength")
    if (
        not isinstance(trigger_strength, str)
        or trigger_strength not in {"ordinary", "strong"}
    ):
        raise _mood_invalid("trigger_strength")
    if primary == "neutral":
        if (
            secondary is not None
            or event["arousal"] != 0
            or event["valence"] != 0
            or event["intensity"] != 0
            or expiry != 0
        ):
            raise _mood_invalid("neutral_values")
    elif expiry == 0:
        raise _mood_invalid("non_neutral_expiry")
    if current is None or event["trigger_strength"] == "strong":
        return
    old_intensity = float(current["intensity"])
    target_intensity = float(event["intensity"])
    if abs(target_intensity - old_intensity) > 0.35:
        raise _mood_invalid("ordinary_intensity_delta")
    old_valence = float(current["valence"])
    target_valence = float(event["valence"])
    if (
        old_valence * target_valence < 0
        and abs(old_valence) >= 0.5
        and abs(target_valence) >= 0.5
    ):
        raise _mood_invalid("ordinary_valence_reversal")


def _validate_mood_advance(event: dict[str, Any]) -> None:
    if set(event) != _MOOD_ADVANCE_KEYS:
        raise _mood_invalid("advance_shape")
    if not _is_stable_id(event.get("event_id")):
        raise _mood_invalid("event_id")
    if not _is_revision(event.get("expected_mood_revision")):
        raise _mood_invalid("expected_mood_revision")
    turns = event.get("turns")
    if (
        isinstance(turns, bool)
        or not isinstance(turns, int)
        or not 1 <= turns <= 1_000
    ):
        raise _mood_invalid("turns")


def _bounded_number(value: Any, minimum: float, maximum: float) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and minimum <= value <= maximum
    )


def _is_revision(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int)
        and 0 <= value <= 10_000
    )


def _is_stable_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and _STABLE_ID_PATTERN.fullmatch(value) is not None
    )


def _exact_operation_retry(
    record: dict[str, Any],
    operation_kind: str,
    event: dict[str, Any],
    growth: tuple[float, int] | None,
    expected_state_revision: int,
) -> bool:
    if operation_kind == "relationship":
        return growth is not None and _exact_relationship_retry(
            record,
            event,
            growth,
            expected_state_revision,
        )
    return (
        record.get("operation_kind") == operation_kind
        and record.get("revision") == expected_state_revision + 1
        and record.get("payload") == event
    )


def _exact_relationship_retry(
    record: dict[str, Any],
    event: dict[str, Any],
    growth: tuple[float, int],
    expected_state_revision: int,
) -> bool:
    payload = record.get("payload")
    return (
        record.get("operation_kind") == "relationship"
        and record.get("revision") == expected_state_revision + 1
        and isinstance(payload, dict)
        and payload.get("interaction_event") == event
        and payload.get("max_delta") == growth[0]
        and payload.get("repetition_window") == growth[1]
    )


def _find_operation(
    records: tuple[ArtifactSnapshot, ...],
    operation_id: str,
) -> ArtifactSnapshot | None:
    return next(
        (
            record
            for record in records
            if record.value["operation_id"] == operation_id
        ),
        None,
    )


def _find_relationship_event(
    records: tuple[ArtifactSnapshot, ...],
    event_id: str,
) -> bool:
    return any(
        record.value["operation_kind"] == "relationship"
        and record.value["payload"]["interaction_event"]["event_id"]
        == event_id
        for record in records
    )


def _find_operation_event(
    records: tuple[ArtifactSnapshot, ...],
    operation_kind: str,
    event_id: str,
) -> bool:
    if operation_kind == "relationship":
        return _find_relationship_event(records, event_id)
    return any(
        record.value["operation_kind"] in {"mood_update", "mood_advance"}
        and record.value["payload"]["event_id"] == event_id
        for record in records
    )


def _require_operation_revision(
    state: dict[str, Any],
    operation_kind: str,
    event: dict[str, Any],
) -> None:
    if operation_kind == "relationship":
        if (
            event["expected_state_revision"]
            != state["relationship"]["revision"]
        ):
            raise _revision_conflict("relationship_revision")
        return
    if event["expected_mood_revision"] != state["mood"]["revision"]:
        raise _revision_conflict("mood_revision")


def _generation_id(
    scope: PersistenceScope,
    active: ActiveConsent,
    operation_id: str,
    operation_kind: str,
    operation_payload: dict[str, Any],
) -> str:
    operation_sha256 = sha256(
        canonical_bytes(
            {
                "operation_id": operation_id,
                "operation_kind": operation_kind,
                "payload": operation_payload,
            }
        )
    ).hexdigest()
    consent = active.consent
    identity = {
        "scope": scope.key.scope,
        "workspace_id": scope.key.workspace_id,
        "namespace": scope.key.namespace,
        "character_id": scope.key.character_id,
        "installation": active.binding,
        "consent_revision": consent["grant_revision"],
        "creation_operation_sha256": operation_sha256,
    }
    return "generation-" + sha256(canonical_bytes(identity)).hexdigest()[:32]


def _state_sha256(state: dict[str, Any]) -> str:
    return sha256(canonical_bytes(state)).hexdigest()


def _event_name(revision: int, operation_id: str) -> str:
    digest = sha256(canonical_bytes(operation_id)).hexdigest()[:32]
    return f"{revision:010d}-{digest}.json"


def _event_artifact_id(
    scope: PersistenceScope,
    revision: int,
    operation_id: str,
) -> str:
    stem = _event_name(revision, operation_id).removesuffix(".json")
    return (
        f"persistent-events/{scope.key.scope}/{scope.key.character_id}/{stem}"
    )


def _event_path(
    scope: PersistenceScope,
    generation_id: str,
    revision: int,
    operation_id: str,
) -> Path:
    return _generation_root(scope, generation_id) / "events" / _event_name(
        revision,
        operation_id,
    )


def _state_root(scope: PersistenceScope) -> Path:
    return scope.character_root("persistent-state")


def _generation_root(scope: PersistenceScope, generation_id: str) -> Path:
    return _state_root(scope) / "generations" / generation_id


def _fresh_scope(
    scope: PersistenceScope,
    workspace_root: Path | None,
) -> PersistenceScope:
    return open_persistence_scope(
        scope.root,
        _AuditedSchemas(scope.boundary.schemas, scope.boundary),
        namespace=scope.key.namespace,
        character_id=scope.key.character_id,
        workspace_root=workspace_root,
        limits=scope.limits,
    )


def _capture_workspace_root(workspace_root: Path | None) -> Path | None:
    return None if workspace_root is None else _absolute_path(workspace_root)


def _finish_read_only_apply(
    lock: PersistenceLock,
    scope: PersistenceScope,
    active: ActiveConsent,
    replay_boundary: PersistenceBoundary | None,
) -> None:
    if replay_boundary is not None:
        replay_boundary.assert_clean()
    active.assert_clean()
    lock.assert_owned()
    scope.boundary.assert_clean()


@contextmanager
def _audit_failures(boundary: PersistenceBoundary) -> Iterator[None]:
    try:
        yield
    except BaseException:
        boundary.assert_clean()
        raise


def _decode_mapping(payload: bytes, reason: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise _journal_invalid(reason) from error
    if not isinstance(value, dict):
        raise _journal_invalid(reason)
    return cast(dict[str, Any], value)


def _capture_mapping(
    boundary: PersistenceBoundary,
    name: str,
    value: Mapping[str, Any],
) -> bytes:
    try:
        payload = canonical_bytes(dict(value))
    except (KokoroError, TypeError, ValueError, UnicodeError) as error:
        raise _journal_invalid(name) from error

    def audit() -> None:
        try:
            matches = canonical_bytes(dict(value)) == payload
        except (KokoroError, TypeError, ValueError, UnicodeError):
            matches = False
        if not matches:
            boundary.fail(name)

    boundary.audits[f"input:{name}"] = audit
    return payload


def _detached(value: Mapping[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(canonical_bytes(value)))


def _require_revision(value: Any, reason: str, *, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _journal_invalid(reason)


def _require_stable_id(value: Any, reason: str) -> None:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 128
        or _STABLE_ID_PATTERN.fullmatch(value) is None
    ):
        raise _journal_invalid(reason)


def _state_domain(action: Callable[[], Any]) -> Any:
    try:
        return action()
    except KokoroError as error:
        if error.code == "PERSISTENCE_CHANGED":
            raise _journal_invalid("stored_artifact") from error
        if error.code == "STATE_CAPACITY_EXCEEDED":
            raise _event_limit(10_000) from error
        if error.code == "INVALID_EVENT":
            raise _journal_invalid("relationship_event") from error
        raise
    except (OSError, TypeError, ValueError, UnicodeError) as error:
        raise _journal_invalid("invalid_input") from error
    except Exception as error:
        raise _journal_invalid("callback_failure") from error


def _revision_conflict(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_STATE_REVISION_CONFLICT",
        "Persistent state revision conflicts with the request.",
        retryable=True,
        details={"reason": reason},
    )


def _reset_stale(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_RESET_STALE",
        "Persistent reset preview is stale.",
        retryable=True,
        details={"reason": reason},
    )


def _reset_durability_failed(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_DURABILITY_FAILED",
        "Persistent reset durability could not be confirmed.",
        details={
            "operation": "reset_recovery",
            "reason": reason,
            "record_state": "unknown",
        },
    )


def _journal_invalid(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_STATE_JOURNAL_INVALID",
        "Persistent state journal is invalid.",
        details={"reason": reason},
    )


def _mood_invalid(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_MOOD_INVALID",
        "Persistent mood event is invalid.",
        details={"reason": reason},
    )


def _contract_unsupported(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_STATE_CONTRACT_UNSUPPORTED",
        "Persistent state contract is unsupported.",
        details={"reason": reason},
    )


def _migration_required(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_STATE_MIGRATION_REQUIRED",
        "Persistent state requires an explicit migration.",
        details={"reason": reason},
    )


def _event_limit(limit: int, *, reason: str = "state_events") -> KokoroError:
    return KokoroError(
        "PERSISTENCE_LIMIT_EXCEEDED",
        "Persistent storage limit was exceeded.",
        details={"reason": reason, "limit": limit},
    )


def _generation_limit(limit: int) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_LIMIT_EXCEEDED",
        "Persistent storage limit was exceeded.",
        details={"reason": "state_generations", "limit": limit},
    )


def _state_write_failed(phase: str, error: KokoroError) -> KokoroError:
    reason = cast(str, error.details.get("reason", "write_failed"))
    return KokoroError(
        "PERSISTENCE_STATE_WRITE_FAILED",
        "Persistent state publication was committed but incomplete.",
        details={
            "phase": phase,
            "reason": reason,
            "record_state": "committed",
        },
    )


__all__ = [
    "PersistentResetPreview",
    "advance_persistent_mood_turn",
    "apply_persistent_mood_event",
    "apply_persistent_relationship_event",
    "export_persistent_data",
    "load_persistent_state",
    "preview_persistent_reset",
    "replay_persistent_state",
    "reset_persistent_data",
]
