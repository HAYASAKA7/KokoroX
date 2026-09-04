from __future__ import annotations

from copy import deepcopy
from decimal import DecimalException, Inexact, localcontext, Rounded, ROUND_UP
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import pytest

from kokoroarc import __version__
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry
from kokoroarc.testing.soft import (
    aggregate_soft_evaluation,
    soft_report_is_current,
)


SCHEMAS = SchemaRegistry(Path("schemas/v1"))
DIMENSIONS = (
    "semantic_equivalence",
    "character_consistency",
    "locale_naturalness",
    "cross_language_persona_equivalence",
    "repetition_catchphrase_quality",
    "safety_policy_retention",
)
LOCALES = ("zh-CN", "en-US", "ja-JP")
EXPECTED_THRESHOLD_PROFILE = {
    "profile_id": "default-release",
    "version": "1.0.0",
    "aggregation": "lower_confidence_bound",
    "dimensions": {
        dimension: {
            "min_samples": 3,
            "min_confidence": 0.8,
            "threshold": 0.8,
        }
        for dimension in DIMENSIONS
    },
}


def _evaluation_input() -> dict[str, Any]:
    samples: dict[str, dict[str, dict[str, Any]]] = {}
    scores = (0.96, 0.94, 0.92)
    confidences = (0.95, 0.93, 0.91)
    for dimension in DIMENSIONS:
        samples[dimension] = {
            f"{dimension.replace('_', '-')}-{index + 1}": {
                "locale": locale,
                "scenario_id": "debugging",
                "case_id": f"{dimension.replace('_', '-')}-{locale.lower()}",
                "score": scores[index],
                "confidence": confidences[index],
                "finding_codes": (
                    ["EVALUATOR_ADVISORY"] if index == 0 else []
                ),
            }
            for index, locale in enumerate(LOCALES)
        }
    return {
        "schema_version": "1.0",
        "artifact_id": "original/rin-aster/release/soft-input",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "namespace": "original",
        "character_id": "rin-aster",
        "character_version": "1.0.0",
        "mode": "original",
        "visibility": "private",
        "source_artifact_id": "original/rin-aster/source",
        "source_hash": "a" * 64,
        "compiled_artifact_id": "original/rin-aster/compiled",
        "compiled_hash": "b" * 64,
        "evaluator": {"id": "local-evaluator", "version": "1.0.0"},
        "rubric_version": "1.0.0",
        "fixture_version": "1.0.0",
        "samples": samples,
    }


def _expected_report(value: dict[str, Any]) -> dict[str, Any]:
    result = {
        "sample_count": 3,
        "score": 0.94,
        "confidence": 0.93,
        "lower_bound": 0.87,
        "passed": True,
        "finding_codes": ["EVALUATOR_ADVISORY"],
    }
    return {
        "schema_version": "1.0",
        "artifact_id": "original/rin-aster/release/soft-evaluation",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "namespace": "original",
        "character_id": "rin-aster",
        "character_version": "1.0.0",
        "mode": "original",
        "visibility": "private",
        "source_artifact_id": "original/rin-aster/source",
        "source_hash": "a" * 64,
        "compiled_artifact_id": "original/rin-aster/compiled",
        "compiled_hash": "b" * 64,
        "evaluation_input": {
            "artifact_id": "original/rin-aster/release/soft-input",
            "sha256": sha256(canonical_bytes(value)).hexdigest(),
        },
        "evaluator": {"id": "local-evaluator", "version": "1.0.0"},
        "rubric_version": "1.0.0",
        "fixture_version": "1.0.0",
        "threshold_profile": deepcopy(EXPECTED_THRESHOLD_PROFILE),
        "results": {
            dimension: deepcopy(result) for dimension in DIMENSIONS
        },
        "passed": True,
    }


def _assert_input_error(value: dict[str, Any], code: str) -> None:
    with pytest.raises(KokoroError) as captured:
        aggregate_soft_evaluation(value, SCHEMAS)
    assert captured.value.code == code


def test_aggregates_all_dimensions_and_locales_into_one_exact_report() -> None:
    value = _evaluation_input()

    report = aggregate_soft_evaluation(value, SCHEMAS)

    assert report == _expected_report(value)
    assert sha256(canonical_bytes(value)).hexdigest() == (
        "42a50a9d7125f78afff077850cd1efc4650f4186502e3dbb61009736547ca7ef"
    )
    assert sha256(canonical_bytes(report)).hexdigest() == (
        "a03f49b3fc6df4d73ac68198873706ed41bac28c61c3aec09025c4a029243867"
    )
    SCHEMAS.validate("pack-soft-evaluation-report", report)


@pytest.mark.parametrize(
    "fixture_name",
    ["original-minimal.json", "research-full.json"],
)
def test_release_fixture_is_the_exact_current_aggregate(fixture_name: str) -> None:
    bundle = json.loads(
        (Path("tests/fixtures/pack-release") / fixture_name).read_text(
            encoding="utf-8"
        )
    )

    report = aggregate_soft_evaluation(bundle["soft_input"], SCHEMAS)

    assert report == bundle["soft_report"]
    assert report["evaluation_input"]["sha256"] == sha256(
        canonical_bytes(bundle["soft_input"])
    ).hexdigest()


def test_is_order_independent_byte_deterministic_and_does_not_mutate_input() -> None:
    value = _evaluation_input()
    original = deepcopy(value)
    reordered = deepcopy(value)
    reordered["samples"] = {
        dimension: dict(reversed(tuple(samples.items())))
        for dimension, samples in reversed(tuple(reordered["samples"].items()))
    }

    first = aggregate_soft_evaluation(value, SCHEMAS)
    second = aggregate_soft_evaluation(reordered, SCHEMAS)
    third = aggregate_soft_evaluation(value, SCHEMAS)

    assert canonical_bytes(first) == canonical_bytes(second) == canonical_bytes(third)
    assert value == original


@pytest.mark.parametrize(
    "replacement",
    [
        {"score": 0.8, "confidence": 0.8, "lower_bound": 0.8},
        {
            "score": 0.9000001,
            "confidence": 0.9000001,
            "lower_bound": 0.8000002,
        },
    ],
)
def test_currentness_rejects_structurally_valid_impossible_soft_results(
    replacement: dict[str, float],
) -> None:
    value = _evaluation_input()
    report = aggregate_soft_evaluation(value, SCHEMAS)
    forged = deepcopy(report)
    forged["results"]["semantic_equivalence"].update(replacement)

    SCHEMAS.validate("pack-soft-evaluation-report", forged)

    assert soft_report_is_current(report, value, SCHEMAS) is True
    assert soft_report_is_current(forged, value, SCHEMAS) is False


def test_currentness_rejects_a_changed_evaluation_input() -> None:
    value = _evaluation_input()
    report = aggregate_soft_evaluation(value, SCHEMAS)
    changed = deepcopy(value)
    changed["samples"]["semantic_equivalence"]["semantic-equivalence-1"][
        "score"
    ] = 0.8

    assert soft_report_is_current(report, changed, SCHEMAS) is False


def test_currentness_uses_disposable_schema_instances_and_audits_callers() -> None:
    value = _evaluation_input()
    report = aggregate_soft_evaluation(value, SCHEMAS)

    class DetachedMutatingRegistry:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            instance["created_by"] = {"component": "kokoroarc", "version": "9.0.0"}

    assert soft_report_is_current(
        report,
        value,
        DetachedMutatingRegistry(),  # type: ignore[arg-type]
    ) is True

    caller_value = deepcopy(value)
    caller_report = deepcopy(report)

    class CallerMutatingRegistry:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "pack-soft-evaluation-report":
                caller_report["source_hash"] = "0" * 64
                caller_value["rubric_version"] = "9.0.0"

    assert soft_report_is_current(
        caller_report,
        caller_value,
        CallerMutatingRegistry(),  # type: ignore[arg-type]
    ) is False


def test_aggregation_does_not_inherit_the_callers_decimal_context() -> None:
    value = _evaluation_input()
    baseline = aggregate_soft_evaluation(value, SCHEMAS)

    with localcontext() as context:
        context.prec = 4
        context.rounding = ROUND_UP
        constrained = aggregate_soft_evaluation(value, SCHEMAS)

    assert canonical_bytes(constrained) == canonical_bytes(baseline)


@pytest.mark.parametrize("trap_signal", [Inexact, Rounded])
def test_aggregation_does_not_inherit_the_callers_decimal_traps(
    trap_signal: type[DecimalException],
) -> None:
    value = _evaluation_input()
    samples = list(value["samples"]["character_consistency"].values())
    samples[0]["score"] = 0.9
    samples[1]["score"] = 0.9
    samples[2]["score"] = 0.8

    with localcontext() as context:
        context.traps[trap_signal] = True
        result = aggregate_soft_evaluation(value, SCHEMAS)

    assert result["results"]["character_consistency"]["score"] == 0.866667


def test_uses_a_closed_versioned_release_threshold_profile() -> None:
    report = aggregate_soft_evaluation(_evaluation_input(), SCHEMAS)
    assert report["threshold_profile"] == EXPECTED_THRESHOLD_PROFILE

    with pytest.raises(KokoroError) as captured:
        aggregate_soft_evaluation(
            _evaluation_input(),
            SCHEMAS,
            threshold_profile_id="unreviewed-profile",
        )

    assert captured.value.code == "SOFT_THRESHOLD_PROFILE_UNSUPPORTED"


def test_insufficient_samples_fail_the_dimension() -> None:
    """Dropping a sample no longer implies a missing required locale."""
    value = _evaluation_input()
    value["samples"]["locale_naturalness"].pop("locale-naturalness-3")

    report = aggregate_soft_evaluation(value, SCHEMAS)

    result = report["results"]["locale_naturalness"]
    assert result["sample_count"] == 2
    assert result["passed"] is False
    assert result["finding_codes"] == [
        "EVALUATOR_ADVISORY",
        "SOFT_INSUFFICIENT_SAMPLES",
    ]
    assert report["passed"] is False


def test_insufficient_confidence_and_lower_bound_fail_the_dimension() -> None:
    value = _evaluation_input()
    for sample in value["samples"]["semantic_equivalence"].values():
        sample["confidence"] = 0.5

    report = aggregate_soft_evaluation(value, SCHEMAS)

    result = report["results"]["semantic_equivalence"]
    assert result["score"] == 0.94
    assert result["confidence"] == 0.5
    assert result["lower_bound"] == 0.44
    assert result["passed"] is False
    assert result["finding_codes"] == [
        "EVALUATOR_ADVISORY",
        "SOFT_CONFIDENCE_BELOW_MINIMUM",
        "SOFT_LOWER_BOUND_BELOW_THRESHOLD",
    ]


def test_low_lower_bound_fails_even_with_sufficient_confidence() -> None:
    value = _evaluation_input()
    for sample in value["samples"]["character_consistency"].values():
        sample["score"] = 0.7
        sample["confidence"] = 0.95

    result = aggregate_soft_evaluation(value, SCHEMAS)["results"][
        "character_consistency"
    ]

    assert result["lower_bound"] == 0.65
    assert result["finding_codes"] == [
        "EVALUATOR_ADVISORY",
        "SOFT_LOWER_BOUND_BELOW_THRESHOLD",
    ]
    assert result["passed"] is False


def test_threshold_decision_uses_the_normalized_value_shown_in_report() -> None:
    value = _evaluation_input()
    for sample in value["samples"]["character_consistency"].values():
        sample["score"] = 0.8999996
        sample["confidence"] = 0.9

    result = aggregate_soft_evaluation(value, SCHEMAS)["results"][
        "character_consistency"
    ]

    assert result["lower_bound"] == 0.8
    assert result["passed"] is True


def test_lower_bound_is_derived_from_the_normalized_reported_means() -> None:
    value = _evaluation_input()
    for sample in value["samples"]["character_consistency"].values():
        sample["score"] = 0.89999949
        sample["confidence"] = 0.90000049

    result = aggregate_soft_evaluation(value, SCHEMAS)["results"][
        "character_consistency"
    ]

    assert result["score"] == 0.899999
    assert result["confidence"] == 0.9
    assert result["lower_bound"] == 0.799999
    assert result["passed"] is False
    assert "SOFT_LOWER_BOUND_BELOW_THRESHOLD" in result["finding_codes"]


def test_rejects_duplicate_logical_samples() -> None:
    value = _evaluation_input()
    samples = value["samples"]["semantic_equivalence"]
    samples["duplicate-observation"] = deepcopy(next(iter(samples.values())))

    _assert_input_error(value, "SOFT_EVALUATION_DUPLICATE_SAMPLE")


@pytest.mark.parametrize(
    "code",
    [
        "SOFT_INSUFFICIENT_SAMPLES",
        "SOFT_CONFIDENCE_BELOW_MINIMUM",
        "SOFT_LOWER_BOUND_BELOW_THRESHOLD",
        "SOFT_REQUIRED_LOCALE_MISSING",
    ],
)
def test_rejects_evaluator_use_of_aggregator_owned_codes(code: str) -> None:
    value = _evaluation_input()
    sample = next(iter(value["samples"]["semantic_equivalence"].values()))
    sample["finding_codes"] = [code]

    _assert_input_error(value, "SOFT_EVALUATION_RESERVED_FINDING")


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_hash", "c" * 64),
        ("compiled_hash", "d" * 64),
        ("evaluator", {"id": "other", "version": "9.0.0"}),
        ("rubric_version", "9.0.0"),
        ("fixture_version", "9.0.0"),
    ],
)
def test_rejects_sample_local_binding_overrides(field: str, value: Any) -> None:
    evaluation = _evaluation_input()
    sample = next(iter(evaluation["samples"]["semantic_equivalence"].values()))
    sample[field] = value

    _assert_input_error(evaluation, "SOFT_EVALUATION_INPUT_INVALID")


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_rejects_non_finite_scores_and_confidence(invalid: float) -> None:
    value = _evaluation_input()
    sample = next(iter(value["samples"]["semantic_equivalence"].values()))
    sample["score"] = invalid

    _assert_input_error(value, "SOFT_EVALUATION_INPUT_INVALID")


@pytest.mark.parametrize("change", ["missing", "unknown"])
def test_rejects_missing_and_unknown_dimensions(change: str) -> None:
    value = _evaluation_input()
    if change == "missing":
        value["samples"].pop("safety_policy_retention")
    else:
        value["samples"]["vibes"] = value["samples"].pop(
            "safety_policy_retention"
        )

    _assert_input_error(value, "SOFT_EVALUATION_INPUT_INVALID")


@pytest.mark.parametrize(
    "field,value",
    [
        ("artifact_id", "original/other/release/soft-input"),
        ("source_artifact_id", "original/other/source"),
        ("compiled_artifact_id", "original/other/compiled"),
    ],
)
def test_rejects_identity_binding_mismatches(field: str, value: str) -> None:
    evaluation = _evaluation_input()
    evaluation[field] = value

    _assert_input_error(evaluation, "SOFT_EVALUATION_BINDING_MISMATCH")


def test_uses_disposable_schema_instances_and_detects_caller_mutation() -> None:
    value = _evaluation_input()

    class MutatingRegistry:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "pack-soft-evaluation-input":
                instance["rubric_version"] = "9.0.0"

    baseline = aggregate_soft_evaluation(value, SCHEMAS)
    mutated = aggregate_soft_evaluation(
        value, MutatingRegistry()  # type: ignore[arg-type]
    )
    assert mutated == baseline

    class CallerMutatingRegistry:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "pack-soft-evaluation-report":
                value["rubric_version"] = "9.0.0"

    with pytest.raises(KokoroError) as captured:
        aggregate_soft_evaluation(
            value, CallerMutatingRegistry()  # type: ignore[arg-type]
        )
    assert captured.value.code == "SOFT_EVALUATION_INPUT_MUTATION"


def test_rejects_caller_input_aba_mutation_across_schema_callbacks() -> None:
    value = _evaluation_input()
    original_rubric = value["rubric_version"]

    class AbaMutatingRegistry:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "pack-soft-evaluation-input":
                value["rubric_version"] = "9.0.0"
            elif name == "pack-soft-evaluation-report":
                value["rubric_version"] = original_rubric

    with pytest.raises(KokoroError) as captured:
        aggregate_soft_evaluation(
            value, AbaMutatingRegistry()  # type: ignore[arg-type]
        )

    assert captured.value.code == "SOFT_EVALUATION_INPUT_MUTATION"


def test_propagates_schema_registry_operational_failures() -> None:
    class BrokenRegistry:
        def validate(self, name: str, instance: Any) -> None:
            raise KokoroError("SCHEMA_READ_FAILED", "registry unavailable")

    with pytest.raises(KokoroError) as captured:
        aggregate_soft_evaluation(
            _evaluation_input(), BrokenRegistry()  # type: ignore[arg-type]
        )

    assert captured.value.code == "SCHEMA_READ_FAILED"
