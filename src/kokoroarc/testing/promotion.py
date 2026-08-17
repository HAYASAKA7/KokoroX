"""Explicit, deterministic Character Pack review and promotion adjudication."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, cast

from kokoroarc import __version__
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry
from kokoroarc.testing.hard import hard_report_is_current
from kokoroarc.testing.soft import soft_report_is_current


_TARGETS = frozenset({"reviewed", "verified"})


def create_promotion_record(
    source_root: Path,
    request: dict[str, Any],
    hard_report: dict[str, Any],
    review_attestation: dict[str, Any],
    schemas: SchemaRegistry,
    *,
    target: str,
    promotion_id: str,
    research_bundle: dict[str, Any] | None = None,
    previous_promotion: dict[str, Any] | None = None,
    soft_evaluation_input: dict[str, Any] | None = None,
    soft_evaluation_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one canonical sequential promotion record from exact evidence."""
    if target not in _TARGETS:
        raise KokoroError(
            "PACK_PROMOTION_TRANSITION_INVALID",
            "The requested Character Pack promotion transition is invalid.",
        )
    if target == "reviewed" and any(
        value is not None
        for value in (
            previous_promotion,
            soft_evaluation_input,
            soft_evaluation_report,
        )
    ):
        raise KokoroError(
            "PACK_PROMOTION_TRANSITION_INVALID",
            "A draft-to-reviewed promotion cannot consume verified-stage evidence.",
        )
    if target == "verified" and any(
        value is None
        for value in (
            previous_promotion,
            soft_evaluation_input,
            soft_evaluation_report,
        )
    ):
        raise KokoroError(
            "PACK_PROMOTION_EVIDENCE_REQUIRED",
            "A reviewed-to-verified promotion requires previous and soft evidence.",
        )

    captured = _capture_inputs(
        request=request,
        hard_report=hard_report,
        review_attestation=review_attestation,
        research_bundle=research_bundle,
        previous_promotion=previous_promotion,
        soft_evaluation_input=soft_evaluation_input,
        soft_evaluation_report=soft_evaluation_report,
    )
    snapshots = {
        name: cast(dict[str, Any], json.loads(payload))
        for name, (_value, payload) in captured.items()
    }
    audited_schemas = _AuditedSchemaRegistry(schemas, tuple(captured.values()))

    hard_current = hard_report_is_current(
        hard_report,
        source_root,
        request,
        cast(SchemaRegistry, audited_schemas),
        research_bundle=research_bundle,
    )
    _validate_schema(
        audited_schemas,
        "pack-hard-validation-report",
        snapshots["hard_report"],
        "PACK_PROMOTION_HARD_REPORT_INVALID",
    )
    if snapshots["hard_report"]["passed"] is not True:
        raise KokoroError(
            "PACK_PROMOTION_HARD_GATE_FAILED",
            "The hard-validation report did not pass.",
        )
    if not hard_current:
        raise KokoroError(
            "PACK_PROMOTION_HARD_REPORT_STALE",
            "The hard-validation report is not current for the exact pack inputs.",
        )

    _validate_schema(
        audited_schemas,
        "pack-review-attestation",
        snapshots["review_attestation"],
        "PACK_PROMOTION_REVIEW_INVALID",
    )
    _validate_review(
        snapshots["hard_report"],
        snapshots["review_attestation"],
        captured["hard_report"][1],
    )

    previous_snapshot = snapshots.get("previous_promotion")
    soft_input_snapshot = snapshots.get("soft_evaluation_input")
    soft_report_snapshot = snapshots.get("soft_evaluation_report")
    if target == "verified":
        assert previous_snapshot is not None
        assert soft_input_snapshot is not None
        assert soft_report_snapshot is not None
        _validate_schema(
            audited_schemas,
            "pack-promotion-record",
            previous_snapshot,
            "PACK_PROMOTION_PREVIOUS_INVALID",
        )
        _validate_schema(
            audited_schemas,
            "pack-soft-evaluation-input",
            soft_input_snapshot,
            "PACK_PROMOTION_SOFT_INPUT_INVALID",
        )
        _validate_schema(
            audited_schemas,
            "pack-soft-evaluation-report",
            soft_report_snapshot,
            "PACK_PROMOTION_SOFT_REPORT_INVALID",
        )
        if soft_report_snapshot["passed"] is not True:
            raise KokoroError(
                "PACK_PROMOTION_SOFT_GATE_FAILED",
                "The soft-evaluation report did not pass.",
            )
        if not soft_report_is_current(
            soft_evaluation_report,
            soft_evaluation_input,
            cast(SchemaRegistry, audited_schemas),
        ):
            raise KokoroError(
                "PACK_PROMOTION_SOFT_REPORT_STALE",
                "The soft-evaluation report is not current for its exact input.",
            )
        _validate_verified_evidence(
            snapshots["hard_report"],
            snapshots["review_attestation"],
            previous_snapshot,
            soft_input_snapshot,
            soft_report_snapshot,
            captured,
        )

    hard = snapshots["hard_report"]
    review = snapshots["review_attestation"]
    prefix = f"{hard['namespace']}/{hard['character_id']}"
    record = {
        "schema_version": "1.0",
        "artifact_id": f"{prefix}/release/promotion-{target}",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "promotion_id": promotion_id,
        "namespace": hard["namespace"],
        "character_id": hard["character_id"],
        "character_version": hard["character_version"],
        "mode": hard["mode"],
        "visibility": "private" if target == "reviewed" else hard["visibility"],
        "source_artifact_id": hard["source_artifact_id"],
        "source_hash": hard["source_hash"],
        "compiled_artifact_id": hard["compiled_artifact_id"],
        "compiled_hash": hard["compiled_hash"],
        "from_status": "draft" if target == "reviewed" else "reviewed",
        "to_status": target,
        "activation_allowed": target == "verified",
        "hard_report": _artifact_reference(hard, captured["hard_report"][1]),
        "review_attestation": _artifact_reference(
            review, captured["review_attestation"][1]
        ),
        "previous_promotion": (
            None
            if previous_snapshot is None
            else _artifact_reference(
                previous_snapshot,
                captured["previous_promotion"][1],
            )
        ),
        "soft_evaluation_report": (
            None
            if soft_report_snapshot is None
            else _artifact_reference(
                soft_report_snapshot,
                captured["soft_evaluation_report"][1],
            )
        ),
    }
    record_bytes = canonical_bytes(record)
    _validate_schema(
        audited_schemas,
        "pack-promotion-record",
        cast(dict[str, Any], json.loads(record_bytes)),
        "PACK_PROMOTION_RECORD_INVALID",
    )

    if target == "verified" and not soft_report_is_current(
        soft_evaluation_report,
        soft_evaluation_input,
        cast(SchemaRegistry, audited_schemas),
    ):
        raise KokoroError(
            "PACK_PROMOTION_INPUT_MUTATION",
            "The verified-stage evidence changed during promotion.",
        )
    if not hard_report_is_current(
        hard_report,
        source_root,
        request,
        cast(SchemaRegistry, audited_schemas),
        research_bundle=research_bundle,
    ):
        raise KokoroError(
            "PACK_PROMOTION_SOURCE_CHANGED",
            "The Character Pack source changed during promotion.",
        )
    _assert_inputs_unchanged(captured)
    return cast(dict[str, Any], json.loads(record_bytes))


def _capture_inputs(**values: Any) -> dict[str, tuple[Any, bytes]]:
    captured: dict[str, tuple[Any, bytes]] = {}
    for name, value in values.items():
        if value is None:
            continue
        try:
            captured[name] = (value, canonical_bytes(value))
        except KokoroError as error:
            raise KokoroError(
                "PACK_PROMOTION_INPUT_INVALID",
                "A promotion input is not canonical JSON data.",
                details={"input": name},
            ) from error
    return captured


def _validate_schema(
    schemas: Any,
    schema_name: str,
    value: dict[str, Any],
    invalid_code: str,
) -> None:
    try:
        schemas.validate(
            schema_name,
            cast(dict[str, Any], json.loads(canonical_bytes(value))),
        )
    except KokoroError as error:
        if error.code != "SCHEMA_VALIDATION_FAILED":
            raise
        raise KokoroError(
            invalid_code,
            "A promotion evidence artifact does not match its closed schema.",
        ) from error


def _validate_review(
    hard: dict[str, Any],
    review: dict[str, Any],
    hard_bytes: bytes,
) -> None:
    if review["decision"] != "accept":
        raise KokoroError(
            "PACK_PROMOTION_REVIEW_REJECTED",
            "The explicit Character Pack review did not accept promotion.",
        )
    prefix = f"{hard['namespace']}/{hard['character_id']}"
    expected = {
        "artifact_id": f"{prefix}/release/review",
        "namespace": hard["namespace"],
        "character_id": hard["character_id"],
        "character_version": hard["character_version"],
        "mode": hard["mode"],
        "source_artifact_id": hard["source_artifact_id"],
        "source_hash": hard["source_hash"],
        "hard_report": _artifact_reference(hard, hard_bytes),
    }
    if any(review[field] != value for field, value in expected.items()):
        raise KokoroError(
            "PACK_PROMOTION_BINDING_MISMATCH",
            "The review attestation does not bind the current hard evidence.",
        )


def _validate_verified_evidence(
    hard: dict[str, Any],
    review: dict[str, Any],
    previous: dict[str, Any],
    soft_input: dict[str, Any],
    soft_report: dict[str, Any],
    captured: dict[str, tuple[Any, bytes]],
) -> None:
    identity_fields = (
        "namespace",
        "character_id",
        "character_version",
        "mode",
        "source_artifact_id",
        "source_hash",
        "compiled_artifact_id",
        "compiled_hash",
    )
    if any(previous[field] != hard[field] for field in identity_fields):
        raise _binding_mismatch()
    if any(soft_input[field] != hard[field] for field in identity_fields):
        raise _binding_mismatch()
    if any(soft_report[field] != hard[field] for field in identity_fields):
        raise _binding_mismatch()
    expected_previous = {
        "from_status": "draft",
        "to_status": "reviewed",
        "activation_allowed": False,
        "visibility": "private",
        "artifact_id": (
            f"{hard['namespace']}/{hard['character_id']}"
            "/release/promotion-reviewed"
        ),
        "hard_report": _artifact_reference(hard, captured["hard_report"][1]),
        "review_attestation": _artifact_reference(
            review, captured["review_attestation"][1]
        ),
        "previous_promotion": None,
        "soft_evaluation_report": None,
    }
    if any(previous[field] != value for field, value in expected_previous.items()):
        raise _binding_mismatch()
    if soft_report["evaluation_input"] != _artifact_reference(
        soft_input, captured["soft_evaluation_input"][1]
    ):
        raise _binding_mismatch()


def _artifact_reference(value: dict[str, Any], payload: bytes) -> dict[str, str]:
    return {
        "artifact_id": cast(str, value["artifact_id"]),
        "sha256": sha256(payload).hexdigest(),
    }


def _binding_mismatch() -> KokoroError:
    return KokoroError(
        "PACK_PROMOTION_BINDING_MISMATCH",
        "The promotion evidence artifacts do not bind the same exact pack.",
    )


def _canonical_matches(value: Any, expected: bytes) -> bool:
    try:
        return canonical_bytes(value) == expected
    except KokoroError:
        return False


def _assert_inputs_unchanged(captured: dict[str, tuple[Any, bytes]]) -> None:
    if any(
        not _canonical_matches(value, payload)
        for value, payload in captured.values()
    ):
        raise KokoroError(
            "PACK_PROMOTION_INPUT_MUTATION",
            "A caller-owned promotion input changed during promotion.",
        )


class _AuditedSchemaRegistry:
    def __init__(
        self,
        delegate: SchemaRegistry,
        captured: tuple[tuple[Any, bytes], ...],
    ) -> None:
        self._delegate = delegate
        self._captured = captured

    def validate(self, name: str, instance: Any) -> None:
        try:
            self._delegate.validate(name, instance)
        finally:
            if any(
                not _canonical_matches(value, payload)
                for value, payload in self._captured
            ):
                raise KokoroError(
                    "PACK_PROMOTION_INPUT_MUTATION",
                    "A caller-owned promotion input changed during validation.",
                )


__all__ = ["create_promotion_record"]
