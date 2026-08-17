"""End-to-end publication readiness over the real release pipeline."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from kokoroarc import __version__
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry
from kokoroarc.testing.hard import run_hard_validation
from kokoroarc.testing.promotion import create_promotion_record
from kokoroarc.testing.publication import (
    assess_publication_readiness,
    publication_report_is_current,
)
from kokoroarc.testing.soft import aggregate_soft_evaluation


SCHEMAS = SchemaRegistry(Path("schemas/v1"))
RIN_PACK = Path("characters/original/rin-aster")
REQUEST_PATH = Path("tests/fixtures/authoring/original-request.json")
DIMENSIONS = (
    "semantic_equivalence",
    "character_consistency",
    "locale_naturalness",
    "cross_language_persona_equivalence",
    "repetition_catchphrase_quality",
    "safety_policy_retention",
)
LOCALES = ("zh-CN", "en-US", "ja-JP")


def _sha256(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def test_real_rin_pipeline_produces_a_current_private_readiness_report() -> None:
    request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    hard_report = run_hard_validation(RIN_PACK, request, SCHEMAS)
    review = {
        "schema_version": "1.0",
        "artifact_id": "original/rin-aster/release/review",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "review_id": "rin-review-01",
        "namespace": "original",
        "character_id": "rin-aster",
        "character_version": "1.0.0",
        "mode": "original",
        "source_artifact_id": hard_report["source_artifact_id"],
        "source_hash": hard_report["source_hash"],
        "hard_report": {
            "artifact_id": hard_report["artifact_id"],
            "sha256": _sha256(hard_report),
        },
        "decision": "accept",
        "reviewer": {"id": "local-user", "type": "user"},
        "reviewed": {
            "identity": True,
            "continuity": True,
            "provenance": True,
            "overrides": True,
            "privacy": True,
        },
        "corrections": {},
        "visibility_acknowledged": "private",
    }
    soft_input = {
        "schema_version": "1.0",
        "artifact_id": "original/rin-aster/release/soft-input",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "namespace": "original",
        "character_id": "rin-aster",
        "character_version": "1.0.0",
        "mode": "original",
        "visibility": "private",
        "source_artifact_id": hard_report["source_artifact_id"],
        "source_hash": hard_report["source_hash"],
        "compiled_artifact_id": hard_report["compiled_artifact_id"],
        "compiled_hash": hard_report["compiled_hash"],
        "evaluator": {"id": "local-evaluator", "version": "1.0.0"},
        "rubric_version": "1.0.0",
        "fixture_version": "1.0.0",
        "samples": {
            dimension: {
                f"{dimension.replace('_', '-')}-{index + 1}": {
                    "locale": locale,
                    "scenario_id": "debugging",
                    "case_id": f"{dimension.replace('_', '-')}-{locale.lower()}",
                    "score": 0.95,
                    "confidence": 0.95,
                    "finding_codes": [],
                }
                for index, locale in enumerate(LOCALES)
            }
            for dimension in DIMENSIONS
        },
    }
    soft_report = aggregate_soft_evaluation(soft_input, SCHEMAS)
    reviewed = create_promotion_record(
        RIN_PACK,
        request,
        hard_report,
        review,
        SCHEMAS,
        target="reviewed",
        promotion_id="rin-promotion-reviewed-01",
    )
    verified = create_promotion_record(
        RIN_PACK,
        request,
        hard_report,
        review,
        SCHEMAS,
        target="verified",
        promotion_id="rin-promotion-verified-01",
        previous_promotion=reviewed,
        soft_evaluation_input=soft_input,
        soft_evaluation_report=soft_report,
    )

    evidence = {
        "request": request,
        "hard_report": hard_report,
        "review_attestation": review,
        "previous_promotion": reviewed,
        "soft_evaluation_input": soft_input,
        "soft_evaluation_report": soft_report,
    }
    report = assess_publication_readiness(
        RIN_PACK,
        verified,
        SCHEMAS,
        promotion_evidence=evidence,
    )

    assert hard_report["passed"] is True
    assert soft_report["passed"] is True
    assert verified["to_status"] == "verified"
    assert report["ready_for_private_export"] is True
    assert report["ready_for_publication"] is False
    assert publication_report_is_current(
        report,
        RIN_PACK,
        verified,
        SCHEMAS,
        promotion_evidence=evidence,
    )
