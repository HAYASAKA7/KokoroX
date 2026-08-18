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
from typing import Any, Callable, Iterator, Mapping, cast

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
    _capture_directory_chain,
    _decode_canonical_object,
    _file_audit,
    _is_redirect,
    _lstat,
    _publish_new_file,
    _read_regular_file,
    _replace_file,
    open_persistence_scope,
    read_canonical_object,
    scan_canonical_directory,
)
from kokoroarc.persistence.consent import ActiveConsent, _require_active_consent
from kokoroarc.state.transitions import apply_event_v1


_STATE_CONTRACT_VERSION = "1.0.0"
_TRANSITION_ALGORITHM = "relationship-v1"
_GENERATION_PATTERN = re.compile(r"generation-[a-f0-9]{32}\Z")
_STABLE_ID_PATTERN = re.compile(
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*\Z"
)


@dataclass(frozen=True, slots=True)
class _ReplayResult:
    state: dict[str, Any]
    events: tuple[ArtifactSnapshot, ...]
    boundary: PersistenceBoundary
    projection_present: bool
    projection_matches: bool


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
    if operation_kind != "relationship":
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
    scope.boundary.validate("interaction-event", operation_payload_bytes)
    _require_stable_id(cast(str, event.get("event_id")), "event_id")

    with _acquire_character_lock(scope) as lock, _audit_failures(
        scope.boundary
    ):
        _recover_locked_state(scope, lock, captured_workspace)
        active = _require_active_consent(
            scope.root,
            character_id,
            consent_id,
            consent_revision,
            "relationship_state",
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

        growth = _growth_config(active.compiled)
        duplicate = _find_operation(records, operation_id)
        if duplicate is not None:
            if not _exact_relationship_retry(
                duplicate.value,
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
        if _find_relationship_event(records, cast(str, event["event_id"])):
            raise _revision_conflict("event_id_reused")
        if state["revision"] != expected_state_revision:
            raise _revision_conflict("outer_revision")
        if (
            event["expected_state_revision"]
            != state["relationship"]["revision"]
        ):
            raise _revision_conflict("relationship_revision")
        if len(records) >= limits.max_state_events:
            raise _event_limit(limits.max_state_events)
        if len(state["applied_operation_ids"]) >= limits.max_state_events:
            raise _event_limit(limits.max_state_events)

        successor = _relationship_successor(state, event, growth, operation_id)
        record = _relationship_record(
            scope,
            active,
            generation_id,
            state,
            successor,
            event,
            growth,
            operation_id,
        )
        record_payload = canonical_bytes(record)
        if len(record_payload) > limits.max_event_bytes:
            raise _event_limit(limits.max_event_bytes, reason="event_bytes")
        scope.boundary.validate("persistent-state-event", record_payload)
        event_sha256 = sha256(record_payload).hexdigest()
        successor["last_event_sha256"] = event_sha256
        successor_payload = canonical_bytes(successor)
        if len(successor_payload) > limits.max_state_bytes:
            raise _event_limit(limits.max_state_bytes, reason="state_bytes")
        scope.boundary.validate("persistent-character-state", successor_payload)

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
        if record["operation_kind"] != "relationship":
            raise _contract_unsupported("operation_kind")
        payload = cast(dict[str, Any], record["payload"])
        interaction = cast(dict[str, Any], payload["interaction_event"])
        interaction_id = cast(str, interaction["event_id"])
        if interaction_id in interaction_ids:
            raise _journal_invalid("duplicate_event_id")
        if interaction["expected_state_revision"] != state["relationship"]["revision"]:
            raise _journal_invalid("relationship_revision")
        growth = _recorded_growth(payload)
        successor = _relationship_successor(
            state,
            interaction,
            growth,
            operation_id,
        )
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
        interaction_ids.add(interaction_id)

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
    scope.boundary.assert_clean()
    return _ReplayResult(
        state=state,
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


def _relationship_successor(
    state: dict[str, Any],
    event: dict[str, Any],
    growth: tuple[float, int],
    operation_id: str,
) -> dict[str, Any]:
    try:
        relationship = apply_event_v1(
            cast(dict[str, Any], state["relationship"]),
            event,
            max_delta=growth[0],
            repetition_window=growth[1],
        )
    except KokoroError as error:
        if error.code == "STATE_CAPACITY_EXCEEDED":
            raise _event_limit(10_000) from error
        raise _journal_invalid("relationship_event") from error
    successor = _detached(state)
    successor["revision"] += 1
    successor["relationship"] = relationship
    successor["applied_operation_ids"].append(operation_id)
    return successor


def _relationship_record(
    scope: PersistenceScope,
    active: ActiveConsent,
    generation_id: str,
    state: dict[str, Any],
    successor: dict[str, Any],
    event: dict[str, Any],
    growth: tuple[float, int],
    operation_id: str,
) -> dict[str, Any]:
    consent = active.consent
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
        "operation_kind": "relationship",
        "predecessor_event_sha256": state["last_event_sha256"],
        "predecessor_state_sha256": _state_sha256(state),
        # The successor is hashed before its event hash is linked, avoiding a
        # circular event/state digest while retaining the predecessor link.
        "successor_state_sha256": _state_sha256(successor),
        "payload": {
            "interaction_event": _detached(event),
            "max_delta": growth[0],
            "repetition_window": growth[1],
        },
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


def _journal_invalid(reason: str) -> KokoroError:
    return KokoroError(
        "PERSISTENCE_STATE_JOURNAL_INVALID",
        "Persistent state journal is invalid.",
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
    "apply_persistent_relationship_event",
    "load_persistent_state",
    "replay_persistent_state",
]
