from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from kokoroarc import __version__
from kokoroarc.errors import KokoroError
from kokoroarc.runtime.planning import build_render_plan
from kokoroarc.schemas import SchemaRegistry


def semantic(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "artifact_id": "semantic/turn-1",
        "conclusion": "The read path is unprotected.",
        "explanation": ["Writes are locked while reads are not."],
        "recommendations": ["Add a failing concurrent test."],
        "warnings": ["Do not rely on repeated successful runs."],
        "immutable_spans": ["go test -race ./..."],
    }
    value.update(overrides)
    return value


def policy(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "primary_language": "zh-CN",
        "channels": {
            "character_dialogue": "ja-JP",
            "technical_explanation": "zh-CN",
            "recommendations": "en-US",
            "warnings": "zh-CN",
        },
        "mixing": {"max_switches": 4},
    }
    value.update(overrides)
    return value


def assert_invalid(semantic_value: Any, policy_value: Any, expression: Any = None) -> KokoroError:
    with pytest.raises(KokoroError) as raised:
        build_render_plan(semantic_value, policy_value, expression_intent=expression)
    assert raised.value.code == "INVALID_RENDER_PLAN_INPUT"
    assert raised.value.retryable is False
    assert raised.value.details == {}
    return raised.value


def test_builds_ordered_schema_valid_plan_with_exact_protected_span() -> None:
    plan = build_render_plan(semantic(), policy(), expression_intent="restrained_diagnosis")

    assert plan == {
        "schema_version": "1.0",
        "artifact_id": "plan/turn-1",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "primary_language": "zh-CN",
        "segments": [
            {
                "id": "s1",
                "channel": "character_dialogue",
                "target_language": "ja-JP",
                "semantic_keys": ["conclusion"],
                "expression_intent": "restrained_diagnosis",
            },
            {
                "id": "s2",
                "channel": "technical_explanation",
                "target_language": "zh-CN",
                "semantic_keys": ["explanation"],
            },
            {
                "id": "s3",
                "channel": "recommendations",
                "target_language": "en-US",
                "semantic_keys": ["recommendations"],
            },
            {
                "id": "s4",
                "channel": "warnings",
                "target_language": "zh-CN",
                "semantic_keys": ["warnings"],
            },
        ],
        "protected_spans": ["go test -race ./..."],
        "max_switches": 4,
    }
    SchemaRegistry(Path("schemas/v1")).validate("render-plan", plan)


def test_omits_absent_segments_and_numbers_remaining_segments_without_gaps() -> None:
    value = semantic()
    value.pop("conclusion")
    value["explanation"] = []
    value["warnings"] = []

    plan = build_render_plan(value, policy(), expression_intent="calm_focus")

    assert plan["segments"] == [
        {
            "id": "s1",
            "channel": "recommendations",
            "target_language": "en-US",
            "semantic_keys": ["recommendations"],
        }
    ]
    SchemaRegistry(Path("schemas/v1")).validate("render-plan", plan)


def test_accepts_complete_schema_artifacts() -> None:
    semantic_value = semantic(
        schema_version="1.0",
        created_by={"component": "kokoroarc", "version": "2.0.0"},
        scenario="debugging",
        format_constraints=["preserve_code_blocks"],
    )
    policy_value = policy(
        schema_version="1.0",
        artifact_id="policy/session-1",
        created_by={"component": "kokoroarc", "version": "2.0.0"},
        mode="mixed",
        subtitles={"enabled": False, "language": None},
    )

    SchemaRegistry(Path("schemas/v1")).validate(
        "render-plan", build_render_plan(semantic_value, policy_value)
    )


def test_result_is_deterministic_detached_and_does_not_mutate_inputs() -> None:
    semantic_value = semantic()
    policy_value = policy()
    original = deepcopy((semantic_value, policy_value))

    first = build_render_plan(semantic_value, policy_value)
    second = build_render_plan(semantic_value, policy_value)
    first["segments"][0]["semantic_keys"].append("warnings")
    first["protected_spans"].append("changed")

    assert (semantic_value, policy_value) == original
    assert second == build_render_plan(semantic_value, policy_value)
    assert second["segments"][0]["semantic_keys"] == ["conclusion"]
    assert second["protected_spans"] == ["go test -race ./..."]


@pytest.mark.parametrize(
    "value",
    [None, [], "semantic", 1, True],
)
def test_rejects_non_mapping_semantic_values(value: Any) -> None:
    assert_invalid(value, policy())


@pytest.mark.parametrize(
    "value",
    [None, [], "policy", 1, True],
)
def test_rejects_non_mapping_policy_values(value: Any) -> None:
    assert_invalid(semantic(), value)


@pytest.mark.parametrize(
    "artifact_id",
    [
        None,
        1,
        "plan/turn-1",
        "semantic/",
        "semantic/UPPER",
        "semantic/turn 1",
        "semantic/" + "a" * 120,
        "semantic/turn-1\n",
    ],
)
def test_rejects_invalid_or_unbound_semantic_artifact_ids(artifact_id: Any) -> None:
    assert_invalid(semantic(artifact_id=artifact_id), policy())


@pytest.mark.parametrize("key", ["conclusion", "explanation", "recommendations", "warnings"])
def test_rejects_invalid_content_shapes(key: str) -> None:
    bad: Any = [] if key == "conclusion" else "not-an-array"
    assert_invalid(semantic(**{key: bad}), policy())


@pytest.mark.parametrize("key", ["explanation", "recommendations", "warnings"])
@pytest.mark.parametrize("entry", ["", 1, None, "x" * 4001, "bad\ud800"])
def test_rejects_invalid_content_entries(key: str, entry: Any) -> None:
    assert_invalid(semantic(**{key: [entry]}), policy())


@pytest.mark.parametrize("value", ["", "x" * 4001, "bad\ud800"])
def test_rejects_invalid_present_conclusion(value: str) -> None:
    assert_invalid(semantic(conclusion=value), policy())


def test_rejects_more_than_64_content_entries() -> None:
    assert_invalid(semantic(explanation=[str(index) for index in range(65)]), policy())


@pytest.mark.parametrize(
    "spans",
    [
        None,
        "command",
        [""],
        [1],
        ["same", "same"],
        ["x" * 4001],
        ["bad\ud800"],
        [str(index) for index in range(129)],
    ],
)
def test_rejects_invalid_immutable_spans(spans: Any) -> None:
    assert_invalid(semantic(immutable_spans=spans), policy())


@pytest.mark.parametrize("primary", [None, "preserve", "fr-FR", 1, []])
def test_rejects_invalid_primary_language(primary: Any) -> None:
    assert_invalid(semantic(), policy(primary_language=primary))


@pytest.mark.parametrize("channels", [None, [], "channels"])
def test_rejects_invalid_channel_mappings(channels: Any) -> None:
    assert_invalid(semantic(), policy(channels=channels))


@pytest.mark.parametrize("route", [None, "fr-FR", 1, []])
def test_rejects_invalid_emitted_channel_routes(route: Any) -> None:
    routes = policy()["channels"]
    routes["character_dialogue"] = route
    assert_invalid(semantic(), policy(channels=routes))


def test_rejects_missing_route_only_when_its_segment_is_emitted() -> None:
    routes = policy()["channels"]
    routes.pop("warnings")
    assert_invalid(semantic(), policy(channels=routes))

    value = semantic(warnings=[])
    plan = build_render_plan(value, policy(channels=routes))
    assert all(segment["channel"] != "warnings" for segment in plan["segments"])


@pytest.mark.parametrize(
    "mixing",
    [None, [], {}, {"max_switches": True}, {"max_switches": -1}, {"max_switches": 1.5}, {"max_switches": Fraction(1, 1)}],
)
def test_rejects_invalid_max_switches(mixing: Any) -> None:
    assert_invalid(semantic(), policy(mixing=mixing))


@pytest.mark.parametrize(
    "expression",
    [True, 1, [], {}, "", "Upper", "two words", "a" * 129, "calm_focus\n"],
)
def test_rejects_invalid_expression_intent(expression: Any) -> None:
    assert_invalid(semantic(), policy(), expression)


def test_rejects_semantic_input_that_would_emit_no_segments() -> None:
    value = semantic(explanation=[], recommendations=[], warnings=[])
    value.pop("conclusion")
    assert_invalid(value, policy())


def test_preserve_route_does_not_change_or_remove_protected_spans() -> None:
    routes = policy()["channels"]
    routes["technical_explanation"] = "preserve"
    plan = build_render_plan(semantic(), policy(channels=routes))

    assert plan["segments"][1]["target_language"] == "preserve"
    assert plan["protected_spans"] == ["go test -race ./..."]
