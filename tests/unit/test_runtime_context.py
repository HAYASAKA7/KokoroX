from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.runtime.context import build_runtime_context


def _compiled() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": "original/rin-aster/compiled",
        "created_by": {"component": "kokoroarc", "version": "0.0.0.dev0"},
        "character_id": "rin-aster",
        "character_version": "1.0.0",
        "source_hash": "a" * 64,
        "identity": {
            "display_name": "Rin Aster",
            "declared_age": "adult",
            "role": "systems architect",
            "worldview": ["clarity before confidence"],
            "non_negotiables": ["never fabricates certainty"],
        },
        "effective_profile": {"composure": 0.9, "warmth": 0.38},
        "provenance": {
            "composure": {"selected_layer": "derived_profile"},
            "warmth": {"selected_layer": "user_override"},
        },
        "behavior": {"default_intensity": "balanced"},
        "growth": {
            "dimensions": ["familiarity", "trust", "collaboration", "tension"],
            "max_delta_per_event": 3,
            "repetition_window_turns": 8,
        },
        "expressions": {
            "restrained_diagnosis": {
                "zh-CN": ["原因已经明确。"],
                "en-US": ["The cause is clear."],
            },
            "quiet_encouragement": {
                "en-US": ["One step at a time."],
            },
            "calm_warning": {
                "zh-CN": ["先停一下。"],
                "ja-JP": ["少し止まりましょう。"],
            },
        },
        "locales": {
            "zh-CN": {
                "register": "calm and direct",
                "addressing": {"unknown": "你", "trusted": "你"},
            },
            "en-US": {"register": "calm and direct"},
            "ja-JP": {"register": "落ち着いて直接的"},
        },
        "scenarios": {
            "debugging": {
                "first_action": "inspect evidence",
                "intensity_cap": "balanced",
            },
            "reviewing": {"first_action": "read the diff"},
        },
    }


def _state() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": "state/session-one",
        "created_by": {"component": "kokoroarc", "version": "0.0.0.dev0"},
        "revision": 7,
        "turn_index": 12,
        "dimensions": {
            "familiarity": 24.0,
            "trust": 31,
            "collaboration": 42.5,
            "tension": 4,
        },
        "stage": "acquainted",
        "applied_event_ids": ["event-one"],
        "recent_novelty": {"debugging": 12},
    }


def _assert_error(
    code: str,
    compiled: Any,
    state: Any,
    locale: Any = "zh-CN",
    scenario: Any = "debugging",
) -> None:
    with pytest.raises(KokoroError) as raised:
        build_runtime_context(compiled, state, locale, scenario)
    assert raised.value.code == code
    assert raised.value.details == {}


def test_build_runtime_context_returns_only_the_selected_compact_view() -> None:
    result = build_runtime_context(_compiled(), _state(), "zh-CN", "debugging")

    assert result == {
        "character_id": "rin-aster",
        "character_version": "1.0.0",
        "identity": {
            "display_name": "Rin Aster",
            "declared_age": "adult",
            "role": "systems architect",
            "worldview": ["clarity before confidence"],
            "non_negotiables": ["never fabricates certainty"],
        },
        "effective_profile": {"composure": 0.9, "warmth": 0.38},
        "locales": {
            "zh-CN": {
                "register": "calm and direct",
                "addressing": {"unknown": "你", "trusted": "你"},
            }
        },
        "scenarios": {
            "debugging": {
                "first_action": "inspect evidence",
                "intensity_cap": "balanced",
            }
        },
        "expressions": {
            "restrained_diagnosis": {"zh-CN": ["原因已经明确。"]},
            "calm_warning": {"zh-CN": ["先停一下。"]},
        },
        "growth": {
            "dimensions": ["familiarity", "trust", "collaboration", "tension"]
        },
        "state": {
            "revision": 7,
            "stage": "acquainted",
            "dimensions": {
                "familiarity": 24.0,
                "trust": 31,
                "collaboration": 42.5,
                "tension": 4,
            },
        },
    }
    assert set(result["locales"]) == {"zh-CN"}
    assert set(result["scenarios"]) == {"debugging"}
    assert "provenance" not in result


def test_context_contains_only_active_locale_scenario_and_state() -> None:
    compiled = {
        "character_id": "rin-aster",
        "character_version": "1.0.0",
        "identity": {"display_name": "Rin Aster"},
        "effective_profile": {"composure": 0.9},
        "provenance": {"composure": {"selected_layer": "derived_profile"}},
        "locales": {
            "zh-CN": {"register": "standard"},
            "ja-JP": {"register": "teineigo"},
        },
        "scenarios": {"debugging": {"intensity_cap": "balanced"}},
        "expressions": {"restrained_diagnosis": {"zh-CN": ["原因明确。"]}},
        "growth": {"dimensions": ["trust"]},
    }
    context = build_runtime_context(
        compiled,
        {"revision": 0, "stage": "unknown", "dimensions": {"trust": 0}},
        "zh-CN",
        "debugging",
    )
    assert set(context["locales"]) == {"zh-CN"}
    assert "provenance" not in context
    assert set(context["scenarios"]) == {"debugging"}
    assert context["identity"] == {"display_name": "Rin Aster"}
    assert context["growth"] == {"dimensions": ["trust"]}
    assert context["state"] == {
        "revision": 0,
        "stage": "unknown",
        "dimensions": {"trust": 0},
    }


def test_build_runtime_context_projects_state_to_declared_growth_dimensions() -> None:
    compiled = _compiled()
    compiled["growth"]["dimensions"] = ["trust"]

    result = build_runtime_context(compiled, _state(), "zh-CN", "debugging")

    assert result["state"]["dimensions"] == {"trust": 31}


def test_build_runtime_context_preserves_declared_growth_dimension_order() -> None:
    compiled = _compiled()
    compiled["growth"]["dimensions"] = ["trust", "collaboration"]

    result = build_runtime_context(compiled, _state(), "zh-CN", "debugging")

    assert list(result["state"]["dimensions"]) == ["trust", "collaboration"]
    assert result["state"]["dimensions"] == {"trust": 31, "collaboration": 42.5}


def test_build_runtime_context_rejects_state_missing_a_growth_dimension() -> None:
    compiled = _compiled()
    compiled["growth"]["dimensions"] = ["trust", "collaboration"]
    state = _state()
    del state["dimensions"]["collaboration"]

    _assert_error("INVALID_RUNTIME_CONTEXT", compiled, state)


def test_build_runtime_context_accepts_the_minimal_consumed_shape() -> None:
    compiled = _compiled()
    state = _state()
    for key in (
        "schema_version",
        "artifact_id",
        "created_by",
        "source_hash",
        "provenance",
        "behavior",
    ):
        compiled.pop(key)
    for key in (
        "schema_version",
        "artifact_id",
        "created_by",
        "turn_index",
        "applied_event_ids",
        "recent_novelty",
    ):
        state.pop(key)

    result = build_runtime_context(compiled, state, "zh-CN", "debugging")

    assert result["character_id"] == "rin-aster"
    assert result["state"]["revision"] == 7


@pytest.mark.parametrize(
    ("locale", "code"),
    [("fr-FR", "UNSUPPORTED_LOCALE"), ("zh-cn", "INVALID_RUNTIME_CONTEXT"), (1, "INVALID_RUNTIME_CONTEXT")],
)
def test_build_runtime_context_classifies_locale_selection_errors(
    locale: Any, code: str
) -> None:
    _assert_error(code, _compiled(), _state(), locale=locale)


@pytest.mark.parametrize(
    ("scenario", "code"),
    [("unknown_case", "UNKNOWN_SCENARIO"), ("Bad-Scenario", "INVALID_RUNTIME_CONTEXT"), (None, "INVALID_RUNTIME_CONTEXT")],
)
def test_build_runtime_context_classifies_scenario_selection_errors(
    scenario: Any, code: str
) -> None:
    _assert_error(code, _compiled(), _state(), scenario=scenario)


def test_build_runtime_context_reports_missing_valid_selections_exactly() -> None:
    compiled = _compiled()
    del compiled["locales"]["zh-CN"]
    _assert_error("UNSUPPORTED_LOCALE", compiled, _state())

    compiled = _compiled()
    del compiled["scenarios"]["debugging"]
    _assert_error("UNKNOWN_SCENARIO", compiled, _state())


@pytest.mark.parametrize(
    ("target", "value"),
    [
        ("compiled", None),
        ("state", []),
        ("identity", []),
        ("effective_profile", []),
        ("growth", []),
        ("expressions", []),
        ("locales", []),
        ("scenarios", []),
        ("dimensions", []),
    ],
)
def test_build_runtime_context_sanitizes_malformed_consumed_mappings(
    target: str, value: Any
) -> None:
    compiled: Any = _compiled()
    state: Any = _state()
    if target == "compiled":
        compiled = value
    elif target == "state":
        state = value
    elif target == "dimensions":
        state["dimensions"] = value
    else:
        compiled[target] = value

    _assert_error("INVALID_RUNTIME_CONTEXT", compiled, state)


def test_build_runtime_context_does_not_chain_internal_mapping_failures() -> None:
    class FailingMapping(dict[str, Any]):
        def get(self, key: str, default: Any = None) -> Any:
            raise RuntimeError("sensitive internal failure")

    with pytest.raises(KokoroError) as raised:
        build_runtime_context(FailingMapping(), _state(), "zh-CN", "debugging")

    assert raised.value.code == "INVALID_RUNTIME_CONTEXT"
    assert raised.value.__cause__ is None


def test_build_runtime_context_rejects_hostile_root_without_calling_get() -> None:
    class HostileRoot(dict[str, Any]):
        called = False

        def get(self, key: str, default: Any = None) -> Any:
            self.called = True
            raise KokoroError("UNSUPPORTED_LOCALE", "injected")

    compiled = HostileRoot(_compiled())

    _assert_error("INVALID_RUNTIME_CONTEXT", compiled, _state())
    assert compiled.called is False


def test_build_runtime_context_rejects_hostile_nested_identity_without_copying() -> None:
    class HostileIdentity(dict[str, Any]):
        called = False

        def __deepcopy__(self, memo: dict[int, Any]) -> dict[str, str]:
            self.called = True
            return {"display_name": "attacker replacement"}

    compiled = _compiled()
    identity = HostileIdentity(compiled["identity"])
    compiled["identity"] = identity

    _assert_error("INVALID_RUNTIME_CONTEXT", compiled, _state())
    assert identity.called is False


def test_build_runtime_context_rejects_json_container_subclasses() -> None:
    class ListSubclass(list[Any]):
        pass

    compiled = _compiled()
    compiled["identity"]["worldview"] = ListSubclass(["looks like JSON"])

    _assert_error("INVALID_RUNTIME_CONTEXT", compiled, _state())


def test_build_runtime_context_rejects_json_scalar_subclasses_without_comparing() -> None:
    class HostileString(str):
        compared = False

        def __eq__(self, other: object) -> bool:
            self.compared = True
            raise KokoroError("UNKNOWN_SCENARIO", "injected")

    character_id = HostileString("rin-aster")
    compiled = _compiled()
    compiled["character_id"] = character_id

    _assert_error("INVALID_RUNTIME_CONTEXT", compiled, _state())
    assert character_id.compared is False


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c, s: c.update(character_id="Bad_ID"),
        lambda c, s: c.update(character_version="1.0.0-01"),
        lambda c, s: c["identity"].update(extra="not allowed"),
        lambda c, s: c["identity"].update(display_name=""),
        lambda c, s: c["effective_profile"].update(Bad=0.5),
        lambda c, s: c["effective_profile"].update(composure=True),
        lambda c, s: c["effective_profile"].update(composure=float("inf")),
        lambda c, s: c["growth"].update(dimensions=["trust", "trust"]),
        lambda c, s: c["growth"].update(dimensions=["curiosity"]),
        lambda c, s: c["locales"]["zh-CN"].update(extra="not allowed"),
        lambda c, s: c["scenarios"]["debugging"].update(extra="not allowed"),
        lambda c, s: c["expressions"].update({"Bad": {"zh-CN": ["line"]}}),
        lambda c, s: c["expressions"]["restrained_diagnosis"].update(
            {"zh-CN": []}
        ),
        lambda c, s: c["expressions"]["restrained_diagnosis"].update(
            {"zh-CN": ["x" * 501]}
        ),
        lambda c, s: s.update(revision=True),
        lambda c, s: s.update(revision=-1),
        lambda c, s: s.update(stage="close"),
        lambda c, s: s["dimensions"].update(trust=True),
        lambda c, s: s["dimensions"].update(trust=float("nan")),
        lambda c, s: s["dimensions"].update(trust=101),
        lambda c, s: s["dimensions"].update(curiosity=1),
    ],
)
def test_build_runtime_context_rejects_invalid_consumed_values(mutate: Any) -> None:
    compiled = _compiled()
    state = _state()
    mutate(compiled, state)

    _assert_error("INVALID_RUNTIME_CONTEXT", compiled, state)


def test_build_runtime_context_rejects_non_utf8_selected_text() -> None:
    compiled = _compiled()
    compiled["locales"]["zh-CN"]["register"] = "\ud800"

    _assert_error("INVALID_RUNTIME_CONTEXT", compiled, _state())


def test_build_runtime_context_rejects_cycles_and_shared_selected_containers() -> None:
    compiled = _compiled()
    compiled["identity"]["worldview"].append(compiled["identity"])
    _assert_error("INVALID_RUNTIME_CONTEXT", compiled, _state())

    compiled = _compiled()
    shared = ["same container"]
    compiled["identity"]["worldview"] = shared
    compiled["identity"]["non_negotiables"] = shared
    _assert_error("INVALID_RUNTIME_CONTEXT", compiled, _state())


def test_build_runtime_context_ignores_omitted_provenance_and_unselected_payloads() -> None:
    compiled = _compiled()
    compiled["provenance"] = compiled
    compiled["locales"]["en-US"] = object()
    compiled["scenarios"]["reviewing"] = {"first_action": float("nan")}
    compiled["expressions"]["restrained_diagnosis"]["en-US"] = [object()]

    result = build_runtime_context(compiled, _state(), "zh-CN", "debugging")

    assert set(result["locales"]) == {"zh-CN"}
    assert set(result["scenarios"]) == {"debugging"}
    assert result["expressions"]["restrained_diagnosis"] == {
        "zh-CN": ["原因已经明确。"]
    }


def test_build_runtime_context_can_filter_expressions_to_empty() -> None:
    compiled = _compiled()
    compiled["expressions"] = {"quiet_encouragement": {"en-US": ["Steady."]}}

    result = build_runtime_context(compiled, _state(), "zh-CN", "debugging")

    assert result["expressions"] == {}


def test_build_runtime_context_is_deterministic_detached_and_does_not_mutate_inputs() -> None:
    compiled = _compiled()
    state = _state()
    original_compiled = deepcopy(compiled)
    original_state = deepcopy(state)

    first = build_runtime_context(compiled, state, "zh-CN", "debugging")
    second = build_runtime_context(compiled, state, "zh-CN", "debugging")

    assert first == second
    assert compiled == original_compiled
    assert state == original_state
    first["identity"]["non_negotiables"].append("changed")
    first["locales"]["zh-CN"]["register"] = "changed"
    first["expressions"]["restrained_diagnosis"]["zh-CN"].append("changed")
    first["growth"]["dimensions"].append("changed")
    first["state"]["dimensions"]["trust"] = 0
    assert compiled == original_compiled
    assert state == original_state
    assert second == build_runtime_context(compiled, state, "zh-CN", "debugging")


def test_build_runtime_context_returns_only_fresh_exact_json_builtins() -> None:
    compiled = _compiled()
    state = _state()
    result = build_runtime_context(compiled, state, "zh-CN", "debugging")

    def assert_exact_json(value: Any) -> None:
        assert type(value) in {dict, list, str, int, float, bool, type(None)}
        if type(value) is dict:
            assert all(type(key) is str for key in value)
            for item in value.values():
                assert_exact_json(item)
        elif type(value) is list:
            for item in value:
                assert_exact_json(item)

    assert_exact_json(result)
    assert result["identity"] is not compiled["identity"]
    assert result["identity"]["worldview"] is not compiled["identity"]["worldview"]
    assert result["state"]["dimensions"] is not state["dimensions"]


def test_build_runtime_context_preserves_expression_intent_order() -> None:
    compiled = _compiled()
    compiled["expressions"] = {
        "third_intent": {"zh-CN": ["三"]},
        "first_intent": {"en-US": ["one"]},
        "second_intent": {"zh-CN": ["二"]},
    }

    result = build_runtime_context(compiled, _state(), "zh-CN", "debugging")

    assert list(result["expressions"]) == ["third_intent", "second_intent"]
