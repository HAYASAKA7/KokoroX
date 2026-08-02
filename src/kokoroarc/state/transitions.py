"""Pure relationship-state transitions."""

from __future__ import annotations

import copy

from kokoroarc.errors import KokoroError


def apply_event(
    state: dict,
    event: dict,
    max_delta: float,
    repetition_window: int = 3,
) -> dict:
    """Return a new state with one bounded interaction event applied."""
    result = copy.deepcopy(state)
    event_id = event["event_id"]
    if event_id in result["applied_event_ids"]:
        return result

    confidence = min(max(float(event["confidence"]), 0.0), 1.0)
    novelty_key = event["novelty_key"]
    last_seen = result["recent_novelty"].get(novelty_key)
    repeated = (
        last_seen is not None
        and result["turn_index"] - last_seen < repetition_window
    )

    for dimension, proposed in event["effects"].items():
        if dimension not in result["dimensions"]:
            raise KokoroError(
                "INVALID_EVENT",
                f"Unknown dimension: {dimension}",
            )
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
    result["stage"] = derive_stage(result["stage"], result["dimensions"])
    return result


def derive_stage(previous: str, dimensions: dict[str, float]) -> str:
    """Derive the relationship stage using first-slice hysteresis."""
    familiarity = dimensions["familiarity"]
    trust = dimensions["trust"]
    tension = dimensions["tension"]

    if previous == "trusted" and trust >= 42 and tension <= 40:
        return "trusted"
    if trust >= 50 and tension <= 35:
        return "trusted"
    if previous == "familiar" and familiarity >= 25 and trust >= 15:
        return "familiar"
    if familiarity >= 30 and trust >= 20:
        return "familiar"
    if previous == "acquainted" and familiarity >= 7:
        return "acquainted"
    if familiarity >= 10:
        return "acquainted"
    return "unknown"
