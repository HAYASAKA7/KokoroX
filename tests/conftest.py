from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import pytest

from kokoroarc import __version__
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry
from kokoroarc.testing.hard import run_hard_validation
from kokoroarc.testing.promotion import create_promotion_record
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


def _hash(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _build_verified_release(
    source_root: Path,
    request_value: dict[str, Any],
    *,
    visibility: str,
    research_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = json.loads(canonical_bytes(request_value))
    hard_report = run_hard_validation(
        source_root,
        request,
        SCHEMAS,
        research_bundle=research_bundle,
    )
    assert hard_report["passed"], {
        name: check
        for name, check in hard_report["checks"].items()
        if not check["passed"]
    }
    namespace = hard_report["namespace"]
    character_id = hard_report["character_id"]
    character_version = hard_report["character_version"]
    mode = hard_report["mode"]
    prefix = f"{namespace}/{character_id}"
    review = {
        "schema_version": "1.0",
        "artifact_id": f"{prefix}/release/review",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "review_id": f"{character_id}-review-01",
        "namespace": namespace,
        "character_id": character_id,
        "character_version": character_version,
        "mode": mode,
        "source_artifact_id": hard_report["source_artifact_id"],
        "source_hash": hard_report["source_hash"],
        "hard_report": {
            "artifact_id": hard_report["artifact_id"],
            "sha256": _hash(hard_report),
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
        "artifact_id": f"{prefix}/release/soft-input",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "namespace": namespace,
        "character_id": character_id,
        "character_version": character_version,
        "mode": mode,
        "visibility": visibility,
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
        source_root,
        request,
        hard_report,
        review,
        SCHEMAS,
        target="reviewed",
        promotion_id=f"{character_id}-promotion-reviewed-01",
        research_bundle=research_bundle,
    )
    verified = create_promotion_record(
        source_root,
        request,
        hard_report,
        review,
        SCHEMAS,
        target="verified",
        promotion_id=f"{character_id}-promotion-verified-01",
        research_bundle=research_bundle,
        previous_promotion=reviewed,
        soft_evaluation_input=soft_input,
        soft_evaluation_report=soft_report,
    )
    return {
        "promotion": verified,
        "evidence": {
            "request": request,
            "hard_report": hard_report,
            "review_attestation": review,
            "previous_promotion": reviewed,
            "soft_evaluation_input": soft_input,
            "soft_evaluation_report": soft_report,
            **(
                {"research_bundle": research_bundle}
                if research_bundle is not None
                else {}
            ),
        },
    }


def _build_rin_verified_release(visibility: str) -> dict[str, Any]:
    request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    request["requested_visibility"] = (
        "public" if visibility == "public_candidate" else "private"
    )
    return _build_verified_release(
        RIN_PACK,
        request,
        visibility=visibility,
    )


@pytest.fixture(scope="session")
def _rin_release_payloads() -> dict[str, bytes]:
    return {
        visibility: canonical_bytes(_build_rin_verified_release(visibility))
        for visibility in ("private", "public_candidate")
    }


@pytest.fixture
def rin_verified_release(_rin_release_payloads: dict[str, bytes]) -> dict[str, Any]:
    return json.loads(_rin_release_payloads["private"])


@pytest.fixture
def rin_public_verified_release(
    _rin_release_payloads: dict[str, bytes],
) -> dict[str, Any]:
    return json.loads(_rin_release_payloads["public_candidate"])


@pytest.fixture
def verified_release_factory() -> Callable[..., dict[str, Any]]:
    return _build_verified_release
