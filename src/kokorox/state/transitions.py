"""Pure relationship-state transitions."""

from __future__ import annotations

from collections.abc import Mapping
import copy

from kokorox.errors import KokoroError


RELATIONSHIP_V1_MAX_APPLIED_EVENT_IDS = 10_000
RELATIONSHIP_V1_MAX_RECENT_NOVELTY_KEYS = 10_000
MAX_APPLIED_EVENT_IDS = RELATIONSHIP_V1_MAX_APPLIED_EVENT_IDS
MAX_RECENT_NOVELTY_KEYS = RELATIONSHIP_V1_MAX_RECENT_NOVELTY_KEYS


def _capacity_exceeded(field: str, limit: int) -> KokoroError:
    return KokoroError(
        "STATE_CAPACITY_EXCEEDED",
        "Relationship state capacity was exceeded.",
        details={"field": field, "limit": limit},
    )


def apply_event(
    state: dict,
    event: dict,
    max_delta: float,
    repetition_window: int = 3,
    stages: Mapping[str, Mapping[str, float]] | None = None,
) -> dict:
    """Delegate current relationship transitions to the v1 contract."""
    return apply_event_v1(
        state,
        event,
        max_delta=max_delta,
        repetition_window=repetition_window,
        stages=stages,
    )


def apply_event_v1(
    state: dict,
    event: dict,
    max_delta: float,
    repetition_window: int = 3,
    stages: Mapping[str, Mapping[str, float]] | None = None,
) -> dict:
    """Return a new state with one bounded interaction event applied."""
    result = copy.deepcopy(state)
    event_id = event["event_id"]
    if event_id in result["applied_event_ids"]:
        return result

    effects = event["effects"]
    for dimension in effects:
        if dimension not in result["dimensions"]:
            raise KokoroError(
                "INVALID_EVENT",
                f"Unknown dimension: {dimension}",
            )

    novelty_key = event["novelty_key"]
    if (
        len(result["applied_event_ids"])
        >= RELATIONSHIP_V1_MAX_APPLIED_EVENT_IDS
    ):
        raise _capacity_exceeded(
            "applied_event_ids",
            RELATIONSHIP_V1_MAX_APPLIED_EVENT_IDS,
        )
    if (
        novelty_key not in result["recent_novelty"]
        and len(result["recent_novelty"])
        >= RELATIONSHIP_V1_MAX_RECENT_NOVELTY_KEYS
    ):
        raise _capacity_exceeded(
            "recent_novelty",
            RELATIONSHIP_V1_MAX_RECENT_NOVELTY_KEYS,
        )

    confidence = min(max(float(event["confidence"]), 0.0), 1.0)
    last_seen = result["recent_novelty"].get(novelty_key)
    repeated = (
        last_seen is not None
        and result["turn_index"] - last_seen < repetition_window
    )

    for dimension, proposed in effects.items():
        delta = (
            0.0
            if repeated
            else min(
                max(float(proposed) * confidence, -max_delta),
                max_delta,
            )
        )
        current = result["dimensions"][dimension]
        result["dimensions"][dimension] = min(
            max(current + delta, 0.0),
            100.0,
        )

    result["applied_event_ids"].append(event_id)
    result["revision"] += 1
    result["turn_index"] += 1
    result["recent_novelty"][novelty_key] = result["turn_index"]
    result["stage"] = _derive_stage_v1(
        result["stage"], result["dimensions"], stages
    )
    return result


def derive_stage(
    previous: str,
    dimensions: dict[str, float],
    stages: Mapping[str, Mapping[str, float]] | None = None,
) -> str:
    """Derive the relationship stage using first-slice hysteresis."""
    return _derive_stage_v1(previous, dimensions, stages)


#: The reference character's curve, used when a pack declares no stages of its
#: own. Every value here is `characters/original/rin-aster/growth.yaml`; it is
#: a default, not the rule.
FROZEN_STAGES_V1: Mapping[str, Mapping[str, float]] = {
    "acquainted": {"enter_familiarity": 10, "exit_familiarity": 7},
    "familiar": {
        "enter_familiarity": 30,
        "enter_trust": 20,
        "exit_familiarity": 25,
        "exit_trust": 15,
    },
    "trusted": {"enter_trust": 50, "max_tension": 35, "exit_trust": 42},
}

#: Stages from the strongest down. `unknown` is the floor, not a gate.
_STAGE_ORDER = ("trusted", "familiar", "acquainted")

#: How much the tension ceiling relaxes while holding a stage. The schema has
#: no exit form for tension, and the reference curve's undeclared hold value
#: (40) is exactly its declared ceiling (35) plus this. A pack may state
#: `exit_max_tension` instead of accepting it.
_TENSION_HYSTERESIS = 5


def _holds(
    dimensions: dict[str, float], thresholds: Mapping[str, float]
) -> bool:
    """Return whether the relaxed bar for staying in a stage is met.

    Hysteresis needs a relaxed floor to hold on to. A stage that declares no
    exit floor has none, so it is entered and left on its enter bar alone.
    """

    if "exit_familiarity" not in thresholds and "exit_trust" not in thresholds:
        return False
    if (
        "exit_familiarity" in thresholds
        and dimensions["familiarity"] < thresholds["exit_familiarity"]
    ):
        return False
    if "exit_trust" in thresholds and dimensions["trust"] < thresholds["exit_trust"]:
        return False
    ceiling = thresholds.get("exit_max_tension")
    if ceiling is None and "max_tension" in thresholds:
        ceiling = thresholds["max_tension"] + _TENSION_HYSTERESIS
    if ceiling is not None and dimensions["tension"] > ceiling:
        return False
    return True


def _enters(
    dimensions: dict[str, float], thresholds: Mapping[str, float]
) -> bool:
    """Return whether the entry bar for a stage is met."""

    if (
        "enter_familiarity" not in thresholds
        and "enter_trust" not in thresholds
    ):
        return False
    if (
        "enter_familiarity" in thresholds
        and dimensions["familiarity"] < thresholds["enter_familiarity"]
    ):
        return False
    if "enter_trust" in thresholds and dimensions["trust"] < thresholds["enter_trust"]:
        return False
    if (
        "max_tension" in thresholds
        and dimensions["tension"] > thresholds["max_tension"]
    ):
        return False
    return True


def _derive_stage_v1(
    previous: str,
    dimensions: dict[str, float],
    stages: Mapping[str, Mapping[str, float]] | None = None,
) -> str:
    """Apply the frozen relationship-v1 rule to one pack's thresholds.

    The rule -- strongest stage first, hold on a relaxed floor before testing
    the entry bar -- is the frozen part. The numbers are the pack's: a pack
    authors its own pacing in `growth.stages`, and the specification treats a
    change to them as a state migration, which only means anything if they are
    read. `stages` of `None` falls back to the reference curve.
    """

    resolved = FROZEN_STAGES_V1 if stages is None else stages
    for stage in _STAGE_ORDER:
        thresholds = resolved.get(stage)
        if not thresholds:
            continue
        if previous == stage and _holds(dimensions, thresholds):
            return stage
        if _enters(dimensions, thresholds):
            return stage
    return "unknown"
