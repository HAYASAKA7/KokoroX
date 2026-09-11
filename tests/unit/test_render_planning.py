from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from kokorox import __version__
from kokorox.errors import KokoroError
from kokorox.runtime.planning import build_render_plan
from kokorox.schemas import SchemaRegistry


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
            # Carries only lines the pack authored, so it follows the pack.
            "character_dialogue": "ja-JP",
            # The answer, so it follows the reader.
            "conclusion": "zh-CN",
            "technical_explanation": "zh-CN",
            "recommendations": "en-US",
            "warnings": "zh-CN",
        },
        "mixing": {"max_switches": 4, "min_primary_ratio": 0.7},
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
        "created_by": {"component": "kokorox", "version": __version__},
        "primary_language": "zh-CN",
        "segments": [
            {
                "id": "s1",
                "channel": "conclusion",
                "target_language": "zh-CN",
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
        "min_primary_ratio": 0.7,
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
        created_by={"component": "kokorox", "version": "2.0.0"},
        scenario="debugging",
        format_constraints=["preserve_code_blocks"],
    )
    policy_value = policy(
        schema_version="1.0",
        artifact_id="policy/session-1",
        created_by={"component": "kokorox", "version": "2.0.0"},
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


@pytest.mark.parametrize("primary", [None, "preserve", "fr_FR", 1, []])
def test_rejects_invalid_primary_language(primary: Any) -> None:
    assert_invalid(semantic(), policy(primary_language=primary))


@pytest.mark.parametrize("channels", [None, [], "channels"])
def test_rejects_invalid_channel_mappings(channels: Any) -> None:
    assert_invalid(semantic(), policy(channels=channels))


@pytest.mark.parametrize("route", [None, "fr_FR", 1, []])
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


def test_the_planner_refuses_a_conclusion_it_knows_will_never_validate() -> None:
    """Fail where the mistake is fixable, not one step later.

    `runtime validate` rejects a conclusion routed off the primary language,
    but every fallback rung operates on the rendered candidate and none can
    change a plan. An agent following the ladder renders once, descends all
    four rungs, and is still invalid. The only repair is upstream -- recompile
    the policy -- which the ladder never suggests.
    """

    with pytest.raises(KokoroError) as raised:
        build_render_plan(
            semantic(),
            policy(channels={
                "character_dialogue": "ja-JP",
                "conclusion": "ja-JP",
                "technical_explanation": "zh-CN",
                "recommendations": "zh-CN",
                "warnings": "zh-CN",
            }),
        )

    assert raised.value.code == "PLAN_CONCLUSION_LANGUAGE_MISMATCH"
    assert raised.value.details == {"expected": "zh-CN", "actual": "ja-JP"}


def test_other_channels_may_still_leave_the_primary_language() -> None:
    """Only the conclusion is pinned; mixed policies remain legitimate."""

    plan = build_render_plan(
        semantic(),
        policy(channels={
            "character_dialogue": "ja-JP",
            "conclusion": "zh-CN",
            "technical_explanation": "zh-CN",
            "recommendations": "en-US",
            "warnings": "ja-JP",
        }),
    )

    languages = {
        segment["channel"]: segment["target_language"]
        for segment in plan["segments"]
    }
    assert languages["conclusion"] == "zh-CN"
    assert languages["recommendations"] == "en-US"
    assert languages["warnings"] == "ja-JP"


def context(**overrides: Any) -> dict[str, Any]:
    """A runtime context whose pack authors Japanese, for a Chinese reader."""

    value: dict[str, Any] = {
        "character_id": "rin-aster",
        "character_version": "1.0.0",
        "requested_locale": "zh-CN",
        "persona_locale": "ja-JP",
        "expressions": {
            "restrained_diagnosis": {"ja-JP": ["原因は明確です。"]},
        },
    }
    value.update(overrides)
    return value


def test_the_character_speaks_the_locale_it_was_written_in() -> None:
    """The line leads in Japanese; every formed answer follows the reader."""

    plan = build_render_plan(
        semantic(),
        policy(),
        expression_intent="restrained_diagnosis",
        context=context(),
    )

    assert plan["segments"][0] == {
        "id": "s1",
        "channel": "character_dialogue",
        "target_language": "ja-JP",
        "fixed_line": {
            "intent": "restrained_diagnosis",
            "index": 0,
            "text": "原因は明確です。",
        },
    }
    assert [segment["id"] for segment in plan["segments"]] == [
        "s1",
        "s2",
        "s3",
        "s4",
        "s5",
    ]
    assert [segment["channel"] for segment in plan["segments"][1:]] == [
        "conclusion",
        "technical_explanation",
        "recommendations",
        "warnings",
    ]
    SchemaRegistry(Path("schemas/v1")).validate("render-plan", plan)


def test_the_authored_line_becomes_a_protected_span() -> None:
    """Without this the model could translate the catchphrase and pass."""

    plan = build_render_plan(
        semantic(),
        policy(),
        expression_intent="restrained_diagnosis",
        context=context(),
    )

    assert plan["protected_spans"] == [
        "go test -race ./...",
        "原因は明確です。",
    ]


def test_a_line_already_named_as_immutable_is_not_listed_twice() -> None:
    plan = build_render_plan(
        semantic(immutable_spans=["原因は明確です。"]),
        policy(),
        expression_intent="restrained_diagnosis",
        context=context(),
    )

    assert plan["protected_spans"] == ["原因は明確です。"]


def test_the_conclusion_still_carries_the_intent_that_produced_the_line() -> None:
    """The line is the manner shown; the intent is the manner named."""

    plan = build_render_plan(
        semantic(),
        policy(),
        expression_intent="restrained_diagnosis",
        context=context(),
    )
    conclusion = next(
        segment
        for segment in plan["segments"]
        if segment.get("channel") == "conclusion"
    )

    assert conclusion["expression_intent"] == "restrained_diagnosis"


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"expressions": {}},
        {"expressions": {"other_intent": {"ja-JP": ["原因は明確です。"]}}},
        # Authored, but not in the locale the dialogue channel routes to.
        {"expressions": {"restrained_diagnosis": {"en-US": ["The cause is clear."]}}},
        {"expressions": {"restrained_diagnosis": {"ja-JP": []}}},
    ],
)
def test_an_unauthored_line_quiets_the_persona_rather_than_failing(
    value: Any,
) -> None:
    """A pack that never wrote this line should still get its answer out."""

    plan = build_render_plan(
        semantic(),
        policy(),
        expression_intent="restrained_diagnosis",
        context=value,
    )

    assert all("fixed_line" not in segment for segment in plan["segments"])
    assert plan["segments"][0]["channel"] == "conclusion"
    assert plan["protected_spans"] == ["go test -race ./..."]


def test_no_intent_means_no_line_even_when_the_pack_authored_one() -> None:
    plan = build_render_plan(semantic(), policy(), context=context())

    assert all("fixed_line" not in segment for segment in plan["segments"])


def test_preserve_draws_the_line_from_the_locale_the_context_served() -> None:
    """The default route. No policy compiled without the pack can name it."""

    channels = dict(policy()["channels"])
    channels["character_dialogue"] = "preserve"

    plan = build_render_plan(
        semantic(),
        policy(channels=channels),
        expression_intent="restrained_diagnosis",
        context=context(),
    )

    assert plan["segments"][0]["target_language"] == "ja-JP"
    assert plan["segments"][0]["fixed_line"]["text"] == "原因は明確です。"


def test_preserve_without_a_served_locale_leaves_the_persona_quiet() -> None:
    channels = dict(policy()["channels"])
    channels["character_dialogue"] = "preserve"
    without_locale = context()
    del without_locale["persona_locale"]

    plan = build_render_plan(
        semantic(),
        policy(channels=channels),
        expression_intent="restrained_diagnosis",
        context=without_locale,
    )

    assert all("fixed_line" not in segment for segment in plan["segments"])


@pytest.mark.parametrize(
    "route",
    ["not a tag", "", 7, None],
)
def test_a_dialogue_route_that_is_not_a_language_fails_loudly(route: Any) -> None:
    """It once skipped the segment silently, losing the persona without a word."""

    channels = dict(policy()["channels"])
    channels["character_dialogue"] = route
    if route is None:
        del channels["character_dialogue"]
        plan = build_render_plan(
            semantic(),
            policy(channels=channels),
            expression_intent="restrained_diagnosis",
            context=context(),
        )
        assert all("fixed_line" not in segment for segment in plan["segments"])
        return
    assert_invalid_with_context(
        semantic(), policy(channels=channels), "restrained_diagnosis", context()
    )


@pytest.mark.parametrize(
    "lines",
    [
        [""],
        ["x" * 2001],
        [7],
        [None],
    ],
)
def test_an_unusable_authored_line_is_refused_not_silently_dropped(
    lines: Any,
) -> None:
    assert_invalid_with_context(
        semantic(),
        policy(),
        "restrained_diagnosis",
        context(expressions={"restrained_diagnosis": {"ja-JP": lines}}),
    )


def assert_invalid_with_context(
    semantic_value: Any,
    policy_value: Any,
    expression: Any,
    context_value: Any,
) -> KokoroError:
    with pytest.raises(KokoroError) as raised:
        build_render_plan(
            semantic_value,
            policy_value,
            expression_intent=expression,
            context=context_value,
        )
    assert raised.value.code == "INVALID_RENDER_PLAN_INPUT"
    return raised.value


def test_a_fixed_segment_never_claims_preserve_as_its_language() -> None:
    """`preserve` on the channel means "the pack's locale", not "no locale"."""

    channels = dict(policy()["channels"])
    channels["character_dialogue"] = "preserve"

    plan = build_render_plan(
        semantic(),
        policy(channels=channels),
        expression_intent="restrained_diagnosis",
        context=context(),
    )

    assert plan["segments"][0]["target_language"] != "preserve"
    SchemaRegistry(Path("schemas/v1")).validate("render-plan", plan)
