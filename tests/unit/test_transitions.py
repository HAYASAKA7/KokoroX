from copy import deepcopy

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.state.transitions import apply_event, derive_stage


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
