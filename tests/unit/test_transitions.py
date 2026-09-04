from copy import deepcopy
from pathlib import Path

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.schemas import SchemaRegistry
from kokoroarc.state import transitions as transitions_module
from kokoroarc.state.transitions import apply_event, derive_stage
from kokoroarc import __version__


SCHEMAS = SchemaRegistry(Path(__file__).parents[2] / "schemas" / "v1")


def state(
    trust: float = 0.0,
    familiarity: float = 0.0,
    collaboration: float = 0.0,
    tension: float = 0.0,
    stage: str = "unknown",
) -> dict:
    return {
        "revision": 0,
        "turn_index": 0,
        "dimensions": {
            "familiarity": familiarity,
            "trust": trust,
            "collaboration": collaboration,
            "tension": tension,
        },
        "stage": stage,
        "applied_event_ids": [],
        "recent_novelty": {},
        "metadata": {"nested": ["preserved"]},
    }


def event(
    event_id: str,
    novelty_key: str,
    effects: dict[str, float],
    confidence: float = 1.0,
) -> dict:
    return {
        "event_id": event_id,
        "novelty_key": novelty_key,
        "confidence": confidence,
        "effects": effects,
    }


def test_event_delta_is_capped_and_idempotent() -> None:
    interaction = event("e1", "kept-commitment", {"trust": 9.0})

    first = apply_event(state(), interaction, max_delta=4.0)
    second = apply_event(first, interaction, max_delta=4.0)

    assert first["dimensions"]["trust"] == 4.0
    assert second == first
    assert second is not first
    assert second["dimensions"] is not first["dimensions"]


def test_public_apply_event_delegates_to_frozen_v1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = {"sentinel": True}

    def fake_v1(*_args, **_kwargs) -> dict:
        return sentinel

    monkeypatch.setattr(transitions_module, "apply_event_v1", fake_v1)

    assert apply_event(state(), event("e1", "n1", {"trust": 1.0}), 4.0) is sentinel


def test_frozen_v1_does_not_follow_current_capacity_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(transitions_module, "MAX_APPLIED_EVENT_IDS", 0)
    monkeypatch.setattr(transitions_module, "MAX_RECENT_NOVELTY_KEYS", 0)

    result = transitions_module.apply_event_v1(
        state(), event("e1", "n1", {"trust": 1.0}), max_delta=4.0
    )

    assert result["revision"] == 1
    assert result["dimensions"]["trust"] == 1.0


def test_familiar_stage_uses_exit_hysteresis() -> None:
    interaction = event("e2", "specific-conflict", {"familiarity": -2.0})

    result = apply_event(
        state(trust=22, familiarity=30, stage="familiar"),
        interaction,
        max_delta=4.0,
    )

    assert result["stage"] == "familiar"


def test_repeated_novelty_key_does_not_grind_score() -> None:
    first_event = event("e3", "repeated-compliment", {"trust": 2.0})
    second_event = event("e4", "repeated-compliment", {"trust": 2.0})

    first = apply_event(state(), first_event, max_delta=4.0, repetition_window=3)
    second = apply_event(
        first,
        second_event,
        max_delta=4.0,
        repetition_window=3,
    )

    assert first["dimensions"]["trust"] == 2.0
    assert second["dimensions"]["trust"] == 2.0
    assert second["applied_event_ids"] == ["e3", "e4"]
    assert second["revision"] == 2
    assert second["turn_index"] == 2
    assert second["recent_novelty"]["repeated-compliment"] == 2


@pytest.mark.parametrize(
    ("previous", "familiarity", "trust", "tension", "expected"),
    [
        ("trusted", 0.0, 42.0, 40.0, "trusted"),
        ("trusted", 35.0, 41.999, 35.0, "familiar"),
        ("trusted", 0.0, 42.0, 40.001, "unknown"),
        ("trusted", 0.0, 50.0, 35.0, "trusted"),
        ("unknown", 0.0, 50.0, 35.0, "trusted"),
        ("unknown", 30.0, 50.0, 35.001, "familiar"),
        ("familiar", 25.0, 15.0, 100.0, "familiar"),
        ("familiar", 24.999, 20.0, 100.0, "acquainted"),
        ("familiar", 30.0, 14.999, 100.0, "acquainted"),
        ("unknown", 30.0, 20.0, 100.0, "familiar"),
        ("unknown", 29.999, 20.0, 100.0, "acquainted"),
        ("unknown", 30.0, 19.999, 100.0, "acquainted"),
        ("acquainted", 7.0, 0.0, 100.0, "acquainted"),
        ("acquainted", 6.999, 0.0, 100.0, "unknown"),
        ("unknown", 10.0, 0.0, 100.0, "acquainted"),
        ("unknown", 9.999, 0.0, 100.0, "unknown"),
    ],
)
def test_derive_stage_thresholds(
    previous: str,
    familiarity: float,
    trust: float,
    tension: float,
    expected: str,
) -> None:
    dimensions = {
        "familiarity": familiarity,
        "trust": trust,
        "collaboration": 0.0,
        "tension": tension,
    }

    assert derive_stage(previous, dimensions) == expected


@pytest.mark.parametrize(
    ("confidence", "proposed", "current", "expected"),
    [
        (0.5, 6.0, 10.0, 13.0),
        (2.0, 3.0, 10.0, 13.0),
        (-1.0, 3.0, 10.0, 10.0),
        (1.0, -9.0, 10.0, 6.0),
        (1.0, -9.0, 2.0, 0.0),
        (1.0, 9.0, 98.0, 100.0),
    ],
)
def test_effects_apply_confidence_delta_and_dimension_bounds(
    confidence: float,
    proposed: float,
    current: float,
    expected: float,
) -> None:
    interaction = event(
        "bounded-event",
        "bounded-effect",
        {"trust": proposed},
        confidence,
    )

    result = apply_event(state(trust=current), interaction, max_delta=4.0)

    assert result["dimensions"]["trust"] == expected


def test_apply_event_returns_deep_copy_without_mutating_inputs() -> None:
    original_state = state(trust=10.0)
    interaction = event("copy-event", "copy-check", {"trust": 2.0})
    state_before = deepcopy(original_state)
    event_before = deepcopy(interaction)

    result = apply_event(original_state, interaction, max_delta=4.0)

    assert original_state == state_before
    assert interaction == event_before
    assert result is not original_state
    assert result["dimensions"] is not original_state["dimensions"]
    assert result["metadata"] is not original_state["metadata"]
    assert result["metadata"]["nested"] is not original_state["metadata"]["nested"]


def test_unknown_dimension_raises_without_mutating_inputs() -> None:
    original_state = state()
    interaction = event(
        "invalid-event",
        "invalid-dimension",
        {"trust": 2.0, "affection": 3.0},
    )
    state_before = deepcopy(original_state)
    event_before = deepcopy(interaction)

    with pytest.raises(KokoroError) as raised:
        apply_event(original_state, interaction, max_delta=4.0)

    assert raised.value.code == "INVALID_EVENT"
    assert str(raised.value) == "Unknown dimension: affection"
    assert original_state == state_before
    assert interaction == event_before


def test_non_idempotent_event_advances_bookkeeping_once() -> None:
    original_state = state()
    original_state["revision"] = 7
    original_state["turn_index"] = 12

    result = apply_event(
        original_state,
        event("bookkeeping-event", "bookkeeping", {"collaboration": 1.0}),
        max_delta=4.0,
    )

    assert result["revision"] == 8
    assert result["turn_index"] == 13
    assert result["applied_event_ids"] == ["bookkeeping-event"]
    assert result["recent_novelty"] == {"bookkeeping": 13}


def test_idempotent_event_does_not_change_revision_turn_or_novelty() -> None:
    original_state = state(trust=4.0)
    original_state["revision"] = 3
    original_state["turn_index"] = 5
    original_state["applied_event_ids"] = ["duplicate-event"]
    original_state["recent_novelty"] = {"other-novelty": 4}
    interaction = event(
        "duplicate-event",
        "replacement-novelty",
        {"trust": 4.0},
    )

    result = apply_event(original_state, interaction, max_delta=4.0)

    assert result == original_state
    assert result is not original_state
    assert result["revision"] == 3
    assert result["turn_index"] == 5
    assert result["recent_novelty"] == {"other-novelty": 4}


@pytest.mark.parametrize(
    ("current_turn", "last_seen", "expected_trust"),
    [
        (4, 2, 0.0),
        (5, 2, 2.0),
    ],
)
def test_repetition_window_boundary(
    current_turn: int,
    last_seen: int,
    expected_trust: float,
) -> None:
    original_state = state()
    original_state["turn_index"] = current_turn
    original_state["recent_novelty"] = {"windowed-novelty": last_seen}

    result = apply_event(
        original_state,
        event("new-event", "windowed-novelty", {"trust": 2.0}),
        max_delta=4.0,
        repetition_window=3,
    )

    assert result["dimensions"]["trust"] == expected_trust
    assert result["recent_novelty"]["windowed-novelty"] == current_turn + 1


def schema_state(
    *,
    applied_event_ids: list[str] | None = None,
    recent_novelty: dict[str, int] | None = None,
    turn_index: int = 0,
) -> dict:
    return {
        "schema_version": "1.0",
        "artifact_id": "state/session-1",
        "created_by": {
            "component": "kokoroarc",
            "version": __version__,
        },
        "revision": 0,
        "turn_index": turn_index,
        "dimensions": {
            "familiarity": 0.0,
            "trust": 0.0,
            "collaboration": 0.0,
            "tension": 0.0,
        },
        "stage": "unknown",
        "applied_event_ids": applied_event_ids or [],
        "recent_novelty": recent_novelty or {},
    }


def schema_event(event_id: str, novelty_key: str) -> dict:
    return {
        "schema_version": "1.0",
        "artifact_id": f"event/{event_id}",
        "created_by": {
            "component": "kokoroarc",
            "version": __version__,
        },
        "event_id": event_id,
        "turn_id": "turn-1",
        "origin": "verified_task_outcome",
        "novelty_key": novelty_key,
        "expected_state_revision": 0,
        "evaluator_version": "interaction-v1",
        "evidence": {
            "kind": "test_result",
            "reference": "pytest-run-1",
        },
        "confidence": 1.0,
        "effects": {"trust": 1.0},
    }


def test_capacity_boundary_additions_preserve_schema_validity() -> None:
    original_state = schema_state(
        applied_event_ids=[f"event-{index}" for index in range(9_999)],
        recent_novelty={
            f"novelty-{index}": 0 for index in range(9_999)
        },
    )
    interaction = schema_event("event-9999", "novelty-9999")
    SCHEMAS.validate("relationship-state", original_state)
    SCHEMAS.validate("interaction-event", interaction)

    result = apply_event(original_state, interaction, max_delta=4.0)

    assert len(result["applied_event_ids"]) == 10_000
    assert len(result["recent_novelty"]) == 10_000
    SCHEMAS.validate("relationship-state", result)


def test_new_event_is_rejected_at_applied_event_id_capacity() -> None:
    original_state = schema_state(
        applied_event_ids=[f"event-{index}" for index in range(10_000)]
    )
    interaction = schema_event("event-overflow", "new-novelty")
    state_before = deepcopy(original_state)
    event_before = deepcopy(interaction)
    SCHEMAS.validate("relationship-state", original_state)
    SCHEMAS.validate("interaction-event", interaction)

    with pytest.raises(KokoroError) as raised:
        apply_event(original_state, interaction, max_delta=4.0)

    assert raised.value.code == "STATE_CAPACITY_EXCEEDED"
    assert raised.value.retryable is False
    assert raised.value.details == {
        "field": "applied_event_ids",
        "limit": 10_000,
    }
    assert original_state == state_before
    assert interaction == event_before


def test_duplicate_event_at_capacity_remains_idempotent() -> None:
    original_state = schema_state(
        applied_event_ids=[f"event-{index}" for index in range(10_000)],
        recent_novelty={
            f"novelty-{index}": 0 for index in range(10_000)
        },
    )
    interaction = schema_event("event-9999", "brand-new-novelty")
    SCHEMAS.validate("relationship-state", original_state)
    SCHEMAS.validate("interaction-event", interaction)

    result = apply_event(original_state, interaction, max_delta=4.0)

    assert result == original_state
    assert result is not original_state
    SCHEMAS.validate("relationship-state", result)


def test_duplicate_event_precedes_malformed_effect_validation_at_capacity() -> None:
    original_state = schema_state(
        applied_event_ids=[f"event-{index}" for index in range(10_000)],
        recent_novelty={
            f"novelty-{index}": 0 for index in range(10_000)
        },
    )
    interaction = schema_event("event-9999", "brand-new-novelty")
    interaction["effects"] = {"affection": 1.0}
    SCHEMAS.validate("relationship-state", original_state)

    result = apply_event(original_state, interaction, max_delta=4.0)

    assert result == original_state
    assert result is not original_state


def test_unknown_dimension_precedes_applied_event_id_capacity() -> None:
    original_state = schema_state(
        applied_event_ids=[f"event-{index}" for index in range(10_000)]
    )
    interaction = schema_event("event-overflow", "new-novelty")
    interaction["effects"] = {"affection": 1.0}
    state_before = deepcopy(original_state)
    event_before = deepcopy(interaction)
    SCHEMAS.validate("relationship-state", original_state)

    with pytest.raises(KokoroError) as raised:
        apply_event(original_state, interaction, max_delta=4.0)

    assert raised.value.code == "INVALID_EVENT"
    assert str(raised.value) == "Unknown dimension: affection"
    assert original_state == state_before
    assert interaction == event_before


def test_unknown_dimension_precedes_novelty_capacity() -> None:
    original_state = schema_state(
        recent_novelty={
            f"novelty-{index}": 0 for index in range(10_000)
        }
    )
    interaction = schema_event("new-event", "brand-new-novelty")
    interaction["effects"] = {"affection": 1.0}
    state_before = deepcopy(original_state)
    event_before = deepcopy(interaction)
    SCHEMAS.validate("relationship-state", original_state)

    with pytest.raises(KokoroError) as raised:
        apply_event(original_state, interaction, max_delta=4.0)

    assert raised.value.code == "INVALID_EVENT"
    assert str(raised.value) == "Unknown dimension: affection"
    assert original_state == state_before
    assert interaction == event_before


def test_new_novelty_key_is_rejected_at_novelty_capacity() -> None:
    original_state = schema_state(
        recent_novelty={
            f"novelty-{index}": 0 for index in range(10_000)
        }
    )
    interaction = schema_event("new-event", "brand-new-novelty")
    state_before = deepcopy(original_state)
    event_before = deepcopy(interaction)
    SCHEMAS.validate("relationship-state", original_state)
    SCHEMAS.validate("interaction-event", interaction)

    with pytest.raises(KokoroError) as raised:
        apply_event(original_state, interaction, max_delta=4.0)

    assert raised.value.code == "STATE_CAPACITY_EXCEEDED"
    assert raised.value.retryable is False
    assert raised.value.details == {
        "field": "recent_novelty",
        "limit": 10_000,
    }
    assert original_state == state_before
    assert interaction == event_before


def test_existing_novelty_key_can_refresh_at_novelty_capacity() -> None:
    original_state = schema_state(
        recent_novelty={
            f"novelty-{index}": 0 for index in range(10_000)
        },
        turn_index=3,
    )
    interaction = schema_event("new-event", "novelty-9999")
    SCHEMAS.validate("relationship-state", original_state)
    SCHEMAS.validate("interaction-event", interaction)

    result = apply_event(
        original_state,
        interaction,
        max_delta=4.0,
        repetition_window=3,
    )

    assert len(result["recent_novelty"]) == 10_000
    assert result["recent_novelty"]["novelty-9999"] == 4
    assert result["dimensions"]["trust"] == 1.0
    SCHEMAS.validate("relationship-state", result)
