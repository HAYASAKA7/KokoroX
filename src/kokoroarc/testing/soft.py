"""Deterministic aggregation of untrusted host-produced soft evaluations."""

from __future__ import annotations

from decimal import Context, Decimal, localcontext, ROUND_HALF_EVEN
from hashlib import sha256
import json
from typing import Any, cast

from kokoroarc import __version__
from kokoroarc.errors import KokoroError
from kokoroarc.language_tags import is_language_tag
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry


_DIMENSIONS = (
    "semantic_equivalence",
    "character_consistency",
    "locale_naturalness",
    "cross_language_persona_equivalence",
    "repetition_catchphrase_quality",
    "safety_policy_retention",
)
_PROFILE_ID = "default-release"
_PROFILE_VERSION = "1.0.0"
_QUANTUM = Decimal("0.000001")
_ARITHMETIC_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)
_MAX_RESULT_FINDINGS = 64
_SYSTEM_FINDING_CODES = frozenset(
    {
        "SOFT_INSUFFICIENT_SAMPLES",
        "SOFT_CONFIDENCE_BELOW_MINIMUM",
        "SOFT_LOWER_BOUND_BELOW_THRESHOLD",
        "SOFT_REQUIRED_LOCALE_MISSING",
    }
)


def aggregate_soft_evaluation(
    evaluation_input: dict[str, Any],
    schemas: SchemaRegistry,
    *,
    threshold_profile_id: str = _PROFILE_ID,
    threshold_profile_version: str = _PROFILE_VERSION,
) -> dict[str, Any]:
    """Validate and aggregate one closed, data-only evaluation artifact.

    The evaluator has already run outside KokoroX. This function performs no
    provider, process, network, runtime, relationship-state, or memory action.
    Every sample inherits the single source/evaluator/rubric/fixture binding at
    the artifact root, so sample-local binding overrides are rejected by the
    closed input schema.
    """
    input_bytes = _capture_input(evaluation_input)
    snapshot = cast(dict[str, Any], json.loads(input_bytes))
    try:
        schemas.validate(
            "pack-soft-evaluation-input",
            cast(dict[str, Any], json.loads(input_bytes)),
        )
    except KokoroError as error:
        if error.code != "SCHEMA_VALIDATION_FAILED":
            raise
        raise KokoroError(
            "SOFT_EVALUATION_INPUT_INVALID",
            "The soft-evaluation input does not match its closed schema.",
        ) from error
    finally:
        _assert_input_unchanged(evaluation_input, input_bytes)
    _validate_identity_bindings(snapshot)
    profile = _threshold_profile(
        threshold_profile_id,
        threshold_profile_version,
    )

    results = {
        dimension: _aggregate_dimension(
            dimension,
            cast(dict[str, dict[str, Any]], snapshot["samples"][dimension]),
            cast(dict[str, Any], profile["dimensions"][dimension]),
        )
        for dimension in _DIMENSIONS
    }
    report = {
        "schema_version": "1.0",
        "artifact_id": (
            f"{snapshot['namespace']}/{snapshot['character_id']}"
            "/release/soft-evaluation"
        ),
        "created_by": {"component": "kokoroarc", "version": __version__},
        "namespace": snapshot["namespace"],
        "character_id": snapshot["character_id"],
        "character_version": snapshot["character_version"],
        "mode": snapshot["mode"],
        "visibility": snapshot["visibility"],
        "source_artifact_id": snapshot["source_artifact_id"],
        "source_hash": snapshot["source_hash"],
        "compiled_artifact_id": snapshot["compiled_artifact_id"],
        "compiled_hash": snapshot["compiled_hash"],
        "evaluation_input": {
            "artifact_id": snapshot["artifact_id"],
            "sha256": sha256(input_bytes).hexdigest(),
        },
        "evaluator": snapshot["evaluator"],
        "rubric_version": snapshot["rubric_version"],
        "fixture_version": snapshot["fixture_version"],
        "threshold_profile": profile,
        "results": results,
        "passed": all(result["passed"] for result in results.values()),
    }
    report_bytes = canonical_bytes(report)
    try:
        schemas.validate(
            "pack-soft-evaluation-report",
            json.loads(report_bytes),
        )
    except KokoroError as error:
        if error.code != "SCHEMA_VALIDATION_FAILED":
            raise
        raise KokoroError(
            "SOFT_EVALUATION_REPORT_INVALID",
            "The deterministic soft-evaluation report is invalid.",
        ) from error
    finally:
        _assert_input_unchanged(evaluation_input, input_bytes)

    _assert_input_unchanged(evaluation_input, input_bytes)
    return cast(dict[str, Any], json.loads(report_bytes))


def soft_report_is_current(
    report: Any,
    evaluation_input: dict[str, Any],
    schemas: SchemaRegistry,
    *,
    threshold_profile_id: str = _PROFILE_ID,
    threshold_profile_version: str = _PROFILE_VERSION,
) -> bool:
    """Return whether a report exactly matches fresh deterministic aggregation.

    The JSON Schema is the closed structural envelope. This semantic check is
    the acceptance boundary: it re-aggregates the exact bound input so sibling
    arithmetic, six-place normalization, and every binding must also match.
    """
    try:
        report_bytes = canonical_bytes(report)
        input_bytes = _capture_input(evaluation_input)
        audited_schemas = _AuditedSchemaRegistry(
            schemas,
            ((report, report_bytes), (evaluation_input, input_bytes)),
        )
        audited_schemas.validate(
            "pack-soft-evaluation-report",
            json.loads(report_bytes),
        )
        current = aggregate_soft_evaluation(
            cast(dict[str, Any], json.loads(input_bytes)),
            cast(SchemaRegistry, audited_schemas),
            threshold_profile_id=threshold_profile_id,
            threshold_profile_version=threshold_profile_version,
        )
        return (
            report_bytes == canonical_bytes(current)
            and _canonical_matches(report, report_bytes)
            and _canonical_matches(evaluation_input, input_bytes)
            and current["evaluation_input"]["sha256"]
            == sha256(input_bytes).hexdigest()
        )
    except (
        ArithmeticError,
        KeyError,
        KokoroError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        return False


def _capture_input(value: Any) -> bytes:
    try:
        input_bytes = canonical_bytes(value)
    except KokoroError as error:
        raise KokoroError(
            "SOFT_EVALUATION_INPUT_INVALID",
            "The soft-evaluation input is not canonical JSON data.",
        ) from error
    return input_bytes


def _canonical_matches(value: Any, expected: bytes) -> bool:
    try:
        return canonical_bytes(value) == expected
    except KokoroError:
        return False


def _assert_input_unchanged(value: Any, expected: bytes) -> None:
    if not _canonical_matches(value, expected):
        raise KokoroError(
            "SOFT_EVALUATION_INPUT_MUTATION",
            "The soft-evaluation input changed during aggregation.",
        )


class _AuditedSchemaRegistry:
    """Audit caller-owned values after every delegated schema callback."""

    def __init__(
        self,
        delegate: SchemaRegistry,
        snapshots: tuple[tuple[Any, bytes], ...],
    ) -> None:
        self._delegate = delegate
        self._snapshots = snapshots

    def validate(self, name: str, instance: Any) -> None:
        try:
            self._delegate.validate(name, instance)
        finally:
            if any(
                not _canonical_matches(value, expected)
                for value, expected in self._snapshots
            ):
                raise KokoroError(
                    "SOFT_EVALUATION_CURRENTNESS_MUTATION",
                    "A soft-evaluation currentness input changed during validation.",
                )


def _validate_identity_bindings(value: dict[str, Any]) -> None:
    prefix = f"{value['namespace']}/{value['character_id']}"
    expected = {
        "artifact_id": f"{prefix}/release/soft-input",
        "source_artifact_id": f"{prefix}/source",
        "compiled_artifact_id": f"{prefix}/compiled",
    }
    if any(value[field] != binding for field, binding in expected.items()):
        raise KokoroError(
            "SOFT_EVALUATION_BINDING_MISMATCH",
            "The soft-evaluation identity bindings do not match.",
        )


def _threshold_profile(profile_id: str, version: str) -> dict[str, Any]:
    if profile_id != _PROFILE_ID or version != _PROFILE_VERSION:
        raise KokoroError(
            "SOFT_THRESHOLD_PROFILE_UNSUPPORTED",
            "The soft-evaluation threshold profile is unsupported.",
        )
    return {
        "profile_id": _PROFILE_ID,
        "version": _PROFILE_VERSION,
        "aggregation": "lower_confidence_bound",
        "dimensions": {
            dimension: {
                "min_samples": 3,
                "min_confidence": 0.8,
                "threshold": 0.8,
            }
            for dimension in _DIMENSIONS
        },
    }


def _aggregate_dimension(
    dimension: str,
    samples: dict[str, dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    ordered_samples = [samples[sample_id] for sample_id in sorted(samples)]
    identities: set[tuple[str, str, str]] = set()
    for sample in ordered_samples:
        identity = (
            cast(str, sample["locale"]),
            cast(str, sample["scenario_id"]),
            cast(str, sample["case_id"]),
        )
        if identity in identities:
            raise KokoroError(
                "SOFT_EVALUATION_DUPLICATE_SAMPLE",
                "The soft-evaluation input contains a duplicate sample.",
                details={"dimension": dimension},
            )
        identities.add(identity)

    count = len(ordered_samples)
    with localcontext(_ARITHMETIC_CONTEXT):
        divisor = Decimal(count)
        score = sum(
            (Decimal(str(sample["score"])) for sample in ordered_samples),
            Decimal(0),
        ) / divisor
        confidence = sum(
            (
                Decimal(str(sample["confidence"]))
                for sample in ordered_samples
            ),
            Decimal(0),
        ) / divisor
        normalized_score = _normalized(score)
        normalized_confidence = _normalized(confidence)
        lower_bound = max(
            Decimal(0),
            normalized_score - (Decimal(1) - normalized_confidence),
        )
        normalized_lower_bound = _normalized(lower_bound)

    finding_codes = {
        cast(str, code)
        for sample in ordered_samples
        for code in cast(list[str], sample["finding_codes"])
    }
    if finding_codes.intersection(_SYSTEM_FINDING_CODES):
        raise KokoroError(
            "SOFT_EVALUATION_RESERVED_FINDING",
            "The evaluator used an aggregator-owned finding code.",
            details={"dimension": dimension},
        )

    failure_codes: set[str] = set()
    if count < cast(int, policy["min_samples"]):
        failure_codes.add("SOFT_INSUFFICIENT_SAMPLES")
    if normalized_confidence < Decimal(str(policy["min_confidence"])):
        failure_codes.add("SOFT_CONFIDENCE_BELOW_MINIMUM")
    if normalized_lower_bound < Decimal(str(policy["threshold"])):
        failure_codes.add("SOFT_LOWER_BOUND_BELOW_THRESHOLD")
    locales = {cast(str, sample["locale"]) for sample in ordered_samples}
    if not locales or any(not is_language_tag(item) for item in locales):
        failure_codes.add("SOFT_REQUIRED_LOCALE_MISSING")

    finding_codes.update(failure_codes)
    if len(finding_codes) > _MAX_RESULT_FINDINGS:
        raise KokoroError(
            "SOFT_EVALUATION_FINDING_LIMIT",
            "The soft-evaluation finding set exceeds the report limit.",
            details={"dimension": dimension},
        )

    return {
        "sample_count": count,
        "score": float(normalized_score),
        "confidence": float(normalized_confidence),
        "lower_bound": float(normalized_lower_bound),
        "passed": not failure_codes,
        "finding_codes": sorted(finding_codes),
    }


def _normalized(value: Decimal) -> Decimal:
    return value.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)


__all__ = ["aggregate_soft_evaluation", "soft_report_is_current"]
