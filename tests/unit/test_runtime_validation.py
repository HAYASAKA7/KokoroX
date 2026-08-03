from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from kokoroarc import __version__
from kokoroarc.errors import KokoroError
from kokoroarc.runtime.validation import fallback_action, validate_rendered_output
from kokoroarc.schemas import SchemaRegistry


def plan(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact_id": "plan/turn-1",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "primary_language": "zh-CN",
        "segments": [
            {
                "id": "s1",
                "channel": "technical_explanation",
                "target_language": "zh-CN",
                "semantic_keys": ["explanation"],
            },
            {
                "id": "s2",
                "channel": "warnings",
                "target_language": "en-US",
                "semantic_keys": ["warnings"],
            },
        ],
        "protected_spans": ["go test -race ./..."],
        "max_switches": 2,
    }
    value.update(overrides)
    return value


def semantic(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "immutable_spans": ["go test -race ./..."],
        "warnings": ["Do not trust repeated runs."],
    }
    value.update(overrides)
    return value


def full_semantic(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact_id": "semantic/turn-1",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "scenario": "debugging",
        "conclusion": "The cause is clear.",
        "explanation": ["The read path is not protected."],
        "recommendations": ["Add a concurrent regression test."],
        "warnings": ["Do not trust repeated runs."],
        "immutable_spans": ["go test -race ./..."],
        "format_constraints": ["preserve_code_blocks"],
    }
    value.update(overrides)
    return value


def rendered(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "text": "原因已经明确。 go test -race ./...",
        "segments": [
            {
                "id": "s1",
                "channel": "technical_explanation",
                "target_language": "zh-CN",
                "semantic_keys": ["explanation"],
            },
            {
                "id": "s2",
                "channel": "warnings",
                "target_language": "en-US",
                "semantic_keys": ["warnings"],
            },
        ],
        "switch_count": 1,
    }
    value.update(overrides)
    return value


def codes(result: dict[str, Any]) -> list[str]:
    return [violation["code"] for violation in result["violations"]]


def assert_schema_valid(result: dict[str, Any]) -> None:
    SchemaRegistry(Path("schemas/v1")).validate("validation-result", result)


def test_validation_reports_missing_protected_span_and_warning() -> None:
    minimal_plan = {
        "max_switches": 4,
        "segments": [
            {
                "id": "s1",
                "channel": "warnings",
                "target_language": "zh-CN",
                "semantic_keys": ["warnings"],
            }
        ],
    }
    result = validate_rendered_output(
        rendered={"text": "原因已经明确。", "segments": [], "switch_count": 0},
        semantic={
            "immutable_spans": ["go test -race ./..."],
            "warnings": ["Do not trust repeated runs."],
        },
        plan=minimal_plan,
    )
    assert result["valid"] is False
    assert {item["code"] for item in result["violations"]} == {
        "MISSING_PROTECTED_SPAN",
        "MISSING_WARNING",
    }
    assert fallback_action(attempt=0) == "repair_segments"
    assert fallback_action(attempt=3) == "neutral_renderer"
    assert_schema_valid(result)


def test_validation_rejects_duplicate_planned_segment_ids_before_matching() -> None:
    duplicate_plan = {
        "max_switches": 4,
        "segments": [
            {
                "id": "s1",
                "channel": "warnings",
                "target_language": "zh-CN",
                "semantic_keys": ["warnings"],
            },
            {
                "id": "s1",
                "channel": "technical_explanation",
                "target_language": "en-US",
                "semantic_keys": ["explanation"],
            },
        ],
    }
    result = validate_rendered_output(
        rendered={"text": "", "segments": [], "switch_count": 0},
        semantic={"immutable_spans": [], "warnings": []},
        plan=duplicate_plan,
    )
    assert result["violations"][0]["code"] == "DUPLICATE_SEGMENT_ID"
    assert_schema_valid(result)


def test_valid_output_has_derived_metadata_and_no_fallback() -> None:
    result = validate_rendered_output(rendered(), semantic(), plan())

    assert result == {
        "schema_version": "1.0",
        "artifact_id": "validation/turn-1",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "valid": True,
        "violations": [],
        "fallback_level": None,
    }
    assert_schema_valid(result)


def test_checks_switch_limit_and_every_segment_field() -> None:
    actual = rendered(switch_count=3)
    actual["segments"] = [
        {
            "id": "s1",
            "channel": "recommendations",
            "target_language": "ja-JP",
            "semantic_keys": ["conclusion", "warnings"],
        },
        {
            "id": "s3",
            "channel": "warnings",
            "target_language": "en-US",
            "semantic_keys": ["warnings"],
        },
    ]

    result = validate_rendered_output(actual, semantic(), plan())

    assert codes(result) == [
        "TOO_MANY_SWITCHES",
        "CHANNEL_MISMATCH",
        "LANGUAGE_MISMATCH",
        "MISSING_SEMANTIC_KEY",
        "UNEXPECTED_SEMANTIC_KEY",
        "UNEXPECTED_SEMANTIC_KEY",
        "UNEXPECTED_SEGMENT_ID",
        "MISSING_WARNING",
    ]
    assert_schema_valid(result)


def test_rejects_duplicate_rendered_ids_stably() -> None:
    actual = rendered()
    actual["segments"].append(deepcopy(actual["segments"][0]))

    result = validate_rendered_output(actual, semantic(), plan())

    assert codes(result) == ["DUPLICATE_RENDERED_SEGMENT_ID"]
    assert_schema_valid(result)


def test_missing_non_warning_segment_is_generic_but_warning_is_not() -> None:
    result = validate_rendered_output(
        rendered(segments=[]), semantic(), plan()
    )

    assert codes(result) == ["MISSING_SEGMENT", "MISSING_WARNING"]


def test_warning_is_not_required_when_semantic_warning_list_is_empty() -> None:
    no_warning_plan = plan(segments=[plan()["segments"][0]])
    result = validate_rendered_output(
        rendered(segments=[rendered()["segments"][0]]),
        semantic(warnings=[]),
        no_warning_plan,
    )

    assert result["valid"] is True


def test_planned_warning_is_required_when_semantic_warning_list_is_empty() -> None:
    warning_only_plan = plan(segments=[plan()["segments"][1]])

    result = validate_rendered_output(
        rendered(segments=[]), semantic(warnings=[]), warning_only_plan
    )

    assert result["valid"] is False
    assert codes(result) == ["MISSING_WARNING"]
    assert_schema_valid(result)


def test_each_planned_warning_requires_its_own_rendered_segment_id() -> None:
    warnings = [
        {
            "id": "s1",
            "channel": "warnings",
            "target_language": "en-US",
            "semantic_keys": ["warnings"],
        },
        {
            "id": "s2",
            "channel": "warnings",
            "target_language": "en-US",
            "semantic_keys": ["warnings"],
        },
    ]
    one_rendered = rendered(segments=[deepcopy(warnings[0])])

    result = validate_rendered_output(
        one_rendered, semantic(warnings=[]), plan(segments=warnings)
    )

    assert codes(result) == ["MISSING_WARNING"]
    assert result["violations"][0]["segment_id"] == "s2"
    assert_schema_valid(result)


def test_each_missing_planned_warning_has_one_ordered_violation() -> None:
    warnings = [
        {
            "id": "s1",
            "channel": "warnings",
            "target_language": "en-US",
            "semantic_keys": ["warnings"],
        },
        {
            "id": "s2",
            "channel": "warnings",
            "target_language": "zh-CN",
            "semantic_keys": ["warnings"],
        },
    ]

    result = validate_rendered_output(
        rendered(segments=[]), semantic(warnings=[]), plan(segments=warnings)
    )

    assert codes(result) == ["MISSING_WARNING", "MISSING_WARNING"]
    assert [item["segment_id"] for item in result["violations"]] == ["s1", "s2"]
    assert_schema_valid(result)


def test_nonempty_warning_requires_a_planned_warning_route() -> None:
    no_warning_plan = plan(segments=[plan()["segments"][0]])

    result = validate_rendered_output(
        rendered(segments=[rendered()["segments"][0]]), semantic(), no_warning_plan
    )

    assert codes(result) == ["MISSING_WARNING"]
    assert "segment_id" not in result["violations"][0]


def test_warning_match_requires_warning_channel_and_semantic_key() -> None:
    actual = rendered()
    actual["segments"][1]["channel"] = "recommendations"
    actual["segments"][1]["semantic_keys"] = ["recommendations"]

    result = validate_rendered_output(actual, semantic(), plan())

    assert codes(result) == [
        "CHANNEL_MISMATCH",
        "MISSING_SEMANTIC_KEY",
        "UNEXPECTED_SEMANTIC_KEY",
        "MISSING_WARNING",
    ]


def test_rendered_segment_contract_rejects_unknown_channel_and_language() -> None:
    actual = rendered()
    actual["segments"][0]["channel"] = "unknown"
    actual["segments"][0]["target_language"] = "fr-FR"

    result = validate_rendered_output(actual, semantic(), plan())

    assert "INVALID_RENDERED_SEGMENT" in codes(result)
    assert_schema_valid(result)


def test_rendered_root_contract_rejects_unknown_keys() -> None:
    actual = rendered(unknown=True)

    result = validate_rendered_output(actual, semantic(), plan())

    assert codes(result)[0] == "INVALID_RENDERED"
    assert_schema_valid(result)


def test_each_unique_missing_immutable_span_has_ordered_bounded_details() -> None:
    spans = ["first", "second", "first"]
    result = validate_rendered_output(
        rendered(text="none"),
        semantic(immutable_spans=spans),
        plan(protected_spans=["first", "second"]),
    )

    protected = [
        item["details"]["protected_span"]
        for item in result["violations"]
        if item["code"] == "MISSING_PROTECTED_SPAN"
    ]
    assert protected == ["first", "second"]
    assert_schema_valid(result)


@pytest.mark.parametrize(
    ("attempt", "action"),
    [
        (-100, "repair_segments"),
        (0, "repair_segments"),
        (1, "reduce_switches"),
        (2, "lower_intensity"),
        (3, "neutral_renderer"),
        (100, "neutral_renderer"),
    ],
)
def test_fallback_action_clamps_integer_attempts(attempt: int, action: str) -> None:
    assert fallback_action(attempt) == action


@pytest.mark.parametrize(
    "attempt",
    [True, False, None, 1.0, Fraction(1, 1), "1", 10**1000],
    ids=["true", "false", "none", "float", "fraction", "string", "huge"],
)
def test_fallback_action_rejects_unsafe_attempts(attempt: Any) -> None:
    with pytest.raises(KokoroError) as raised:
        fallback_action(attempt)

    assert raised.value.code == "INVALID_FALLBACK_ATTEMPT"
    assert raised.value.retryable is False
    assert raised.value.details == {}


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("text", None, "INVALID_RENDERED_TEXT"),
        ("text", "x" * 100_001, "INVALID_RENDERED_TEXT"),
        ("segments", None, "INVALID_RENDERED_SEGMENTS"),
        ("segments", [{}] * 129, "INVALID_RENDERED_SEGMENTS"),
        ("switch_count", True, "INVALID_SWITCH_COUNT"),
        ("switch_count", float("nan"), "INVALID_SWITCH_COUNT"),
        ("switch_count", 10**1000, "INVALID_SWITCH_COUNT"),
    ],
    ids=[
        "text-type",
        "text-size",
        "segments-type",
        "segments-size",
        "switch-bool",
        "switch-nan",
        "switch-huge",
    ],
)
def test_malformed_rendered_fields_return_stable_schema_valid_results(
    field: str, value: Any, expected: str
) -> None:
    actual = rendered(**{field: value})

    result = validate_rendered_output(actual, semantic(), plan())

    assert expected in codes(result)
    assert len(result["violations"]) <= 128
    assert_schema_valid(result)


@pytest.mark.parametrize(
    ("bad_semantic", "bad_plan", "expected"),
    [
        (None, plan(), "INVALID_SEMANTIC"),
        (semantic(immutable_spans="span"), plan(), "INVALID_IMMUTABLE_SPANS"),
        (semantic(warnings="warning"), plan(), "INVALID_WARNINGS"),
        (semantic(), None, "INVALID_PLAN"),
        (semantic(), plan(segments="segments"), "INVALID_PLANNED_SEGMENTS"),
        (semantic(), plan(max_switches=True), "INVALID_MAX_SWITCHES"),
    ],
)
def test_malformed_semantic_and_plan_return_stable_schema_valid_results(
    bad_semantic: Any, bad_plan: Any, expected: str
) -> None:
    result = validate_rendered_output(rendered(), bad_semantic, bad_plan)

    assert expected in codes(result)
    assert_schema_valid(result)


def test_malformed_segments_do_not_leak_exceptions_or_invalid_violation_shapes() -> None:
    malformed_plan = plan(
        artifact_id="not a plan id",
        segments=[
            None,
            {},
            {"id": "bad-id"},
            {
                "id": "s1",
                "channel": "x" * 1000,
                "target_language": object(),
                "semantic_keys": [object()],
            },
        ],
    )
    actual = rendered(segments=[None, {}, {"id": "bad-id"}])

    result = validate_rendered_output(actual, semantic(), malformed_plan)

    assert result["artifact_id"] == "validation/result"
    assert result["valid"] is False
    assert 1 <= len(result["violations"]) <= 128
    assert_schema_valid(result)


def test_unhashable_segment_fields_return_violations_instead_of_exceptions() -> None:
    actual = rendered()
    actual["segments"][0]["channel"] = []
    actual["segments"][0]["target_language"] = {}
    malformed_plan = plan()
    malformed_plan["segments"][0]["channel"] = []
    malformed_plan["segments"][0]["target_language"] = {}

    result = validate_rendered_output(actual, semantic(), malformed_plan)

    assert "INVALID_PLANNED_SEGMENT" in codes(result)
    assert "INVALID_RENDERED_SEGMENT" in codes(result)
    assert_schema_valid(result)


def test_malformed_optional_planned_expression_is_reported() -> None:
    malformed_plan = plan()
    malformed_plan["segments"][0]["expression_intent"] = []

    result = validate_rendered_output(rendered(), semantic(), malformed_plan)

    assert "INVALID_PLANNED_SEGMENT" in codes(result)
    assert_schema_valid(result)


def test_does_not_mutate_or_alias_inputs_and_is_deterministic() -> None:
    actual = rendered()
    meaning = semantic()
    route_plan = plan()
    original = deepcopy((actual, meaning, route_plan))

    first = validate_rendered_output(actual, meaning, route_plan)
    second = validate_rendered_output(actual, meaning, route_plan)
    first["violations"].append({"code": "CHANGED"})

    assert (actual, meaning, route_plan) == original
    assert second == validate_rendered_output(actual, meaning, route_plan)


def test_violations_are_capped_at_schema_maximum() -> None:
    actual = rendered(text="", segments=[])
    meaning = semantic(immutable_spans=[f"span-{index}" for index in range(128)])

    result = validate_rendered_output(actual, meaning, plan())

    assert len(result["violations"]) == 128
    assert_schema_valid(result)


@pytest.mark.parametrize(
    "meaning",
    [
        {},
        {"immutable_spans": []},
        {"warnings": []},
        {"immutable_spans": [], "warnings": [], "extra": True},
    ],
    ids=["empty", "missing-warnings", "missing-spans", "extra-key"],
)
def test_reduced_semantic_contract_requires_exact_root_keys(meaning: Any) -> None:
    result = validate_rendered_output(rendered(), meaning, plan())

    assert "INVALID_SEMANTIC" in codes(result)
    assert_schema_valid(result)


def test_accepts_complete_semantic_and_render_plan_artifacts() -> None:
    meaning = full_semantic()
    route_plan = plan()
    registry = SchemaRegistry(Path("schemas/v1"))
    registry.validate("semantic-result", meaning)
    registry.validate("render-plan", route_plan)

    result = validate_rendered_output(rendered(), meaning, route_plan)

    assert result["valid"] is True
    assert_schema_valid(result)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"schema_version": "2.0"}),
        lambda value: value.update({"artifact_id": "Bad Artifact"}),
        lambda value: value.update({"created_by": {"component": "other", "version": "1"}}),
        lambda value: value.update({"scenario": "Bad Scenario"}),
        lambda value: value.update({"explanation": []}),
        lambda value: value.update({"format_constraints": ["same", "same"]}),
        lambda value: value.update({"unknown": True}),
    ],
    ids=[
        "version",
        "artifact",
        "creator",
        "scenario",
        "explanation",
        "duplicate-format",
        "extra-key",
    ],
)
def test_full_semantic_contract_rejects_schema_invalid_artifacts(mutation) -> None:
    meaning = full_semantic()
    mutation(meaning)

    result = validate_rendered_output(rendered(), meaning, plan())

    assert "INVALID_SEMANTIC" in codes(result)
    assert_schema_valid(result)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"schema_version": "2.0"}),
        lambda value: value.update({"artifact_id": "Bad Artifact"}),
        lambda value: value.update({"created_by": {"component": "other", "version": "1"}}),
        lambda value: value.update({"primary_language": "preserve"}),
        lambda value: value.update({"segments": []}),
        lambda value: value.update({"protected_spans": ["same", "same"]}),
        lambda value: value.update({"unknown": True}),
    ],
    ids=[
        "version",
        "artifact",
        "creator",
        "primary",
        "empty-segments",
        "duplicate-spans",
        "extra-key",
    ],
)
def test_full_plan_contract_rejects_schema_invalid_artifacts(mutation) -> None:
    route_plan = plan()
    mutation(route_plan)

    result = validate_rendered_output(rendered(), semantic(), route_plan)

    assert "INVALID_PLAN" in codes(result)
    assert result["valid"] is False
    assert_schema_valid(result)


def test_reduced_plan_contract_requires_exact_root_keys() -> None:
    reduced_plan = {
        "max_switches": 2,
        "segments": [deepcopy(plan()["segments"][0])],
        "unknown": True,
    }

    result = validate_rendered_output(rendered(), semantic(), reduced_plan)

    assert "INVALID_PLAN" in codes(result)
    assert_schema_valid(result)


def test_full_plan_protected_spans_must_match_semantic_and_rendered_text() -> None:
    route_plan = plan(protected_spans=["plan-only-span"])

    result = validate_rendered_output(
        rendered(text="", segments=rendered()["segments"]),
        semantic(immutable_spans=[]),
        route_plan,
    )

    assert "PROTECTED_SPAN_MISMATCH" in codes(result)
    missing = [
        item for item in result["violations"] if item["code"] == "MISSING_PROTECTED_SPAN"
    ]
    assert [item["details"]["protected_span"] for item in missing] == [
        "plan-only-span"
    ]
    assert_schema_valid(result)


def test_malformed_full_plan_cannot_bypass_its_protected_spans() -> None:
    route_plan = plan(protected_spans=["plan-only-span"], unknown=True)

    result = validate_rendered_output(
        rendered(text=""), semantic(immutable_spans=[]), route_plan
    )

    assert "INVALID_PLAN" in codes(result)
    assert "PROTECTED_SPAN_MISMATCH" in codes(result)
    assert any(
        item["code"] == "MISSING_PROTECTED_SPAN"
        and item["details"]["protected_span"] == "plan-only-span"
        for item in result["violations"]
    )
    assert_schema_valid(result)


def test_duplicate_reduced_semantic_spans_are_invalid() -> None:
    result = validate_rendered_output(
        rendered(),
        semantic(immutable_spans=["go test -race ./...", "go test -race ./..."]),
        plan(),
    )

    assert "INVALID_SEMANTIC" in codes(result)
    assert_schema_valid(result)
