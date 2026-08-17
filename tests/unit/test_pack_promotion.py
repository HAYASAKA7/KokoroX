from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Any

import pytest
import yaml

from kokoroarc import __version__
from kokoroarc.errors import KokoroError
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


def _sha256(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _release_inputs() -> dict[str, Any]:
    request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    hard_report = run_hard_validation(RIN_PACK, request, SCHEMAS)
    hard_reference = {
        "artifact_id": hard_report["artifact_id"],
        "sha256": _sha256(hard_report),
    }
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
        "hard_report": hard_reference,
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
    return {
        "request": request,
        "hard_report": hard_report,
        "review": review,
        "soft_input": soft_input,
        "soft_report": soft_report,
    }


def _reviewed(inputs: dict[str, Any]) -> dict[str, Any]:
    return create_promotion_record(
        RIN_PACK,
        inputs["request"],
        inputs["hard_report"],
        inputs["review"],
        SCHEMAS,
        target="reviewed",
        promotion_id="rin-promotion-reviewed-01",
    )


def test_creates_exact_draft_to_reviewed_record_for_rin() -> None:
    inputs = _release_inputs()

    record = _reviewed(inputs)

    assert record == {
        "schema_version": "1.0",
        "artifact_id": "original/rin-aster/release/promotion-reviewed",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "promotion_id": "rin-promotion-reviewed-01",
        "namespace": "original",
        "character_id": "rin-aster",
        "character_version": "1.0.0",
        "mode": "original",
        "visibility": "private",
        "source_artifact_id": inputs["hard_report"]["source_artifact_id"],
        "source_hash": inputs["hard_report"]["source_hash"],
        "compiled_artifact_id": inputs["hard_report"]["compiled_artifact_id"],
        "compiled_hash": inputs["hard_report"]["compiled_hash"],
        "from_status": "draft",
        "to_status": "reviewed",
        "activation_allowed": False,
        "hard_report": {
            "artifact_id": inputs["hard_report"]["artifact_id"],
            "sha256": _sha256(inputs["hard_report"]),
        },
        "review_attestation": {
            "artifact_id": inputs["review"]["artifact_id"],
            "sha256": _sha256(inputs["review"]),
        },
        "previous_promotion": None,
        "soft_evaluation_report": None,
    }
    SCHEMAS.validate("pack-promotion-record", record)


def test_promotes_current_researched_report_with_exact_research_bundle(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "researched-pack"
    shutil.copytree(RIN_PACK, pack)
    request = json.loads(
        Path("tests/fixtures/authoring/researched-request.json").read_text(
            encoding="utf-8"
        )
    )
    research_bundle = json.loads(
        Path("tests/fixtures/research/complete/bundle.json").read_text(
            encoding="utf-8"
        )
    )
    request["inputs"] = [
        {
            "type": "research_bundle",
            "artifact_id": research_bundle["artifact_id"],
            "sha256": research_bundle["bundle_hash"],
        }
    ]

    manifest_path = pack / "character.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "artifact_id": "research/aoi-kisaragi-fixture/source",
            "character_id": "aoi-kisaragi-fixture",
            "namespace": "research",
        }
    )
    manifest_path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    identity_path = pack / "identity.yaml"
    identity = yaml.safe_load(identity_path.read_text(encoding="utf-8"))
    identity.update(
        {
            "display_name": "Aoi Kisaragi Fixture",
            "role": "observatory apprentice",
        }
    )
    identity_path.write_text(
        yaml.safe_dump(identity, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (pack / "evidence.yaml").write_text(
        yaml.safe_dump(
            {
                "authored_original": False,
                "claims": [
                    {"claim_id": "claim-role", "source": "research_bundle"}
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    hard_report = run_hard_validation(
        pack,
        request,
        SCHEMAS,
        research_bundle=research_bundle,
    )
    assert hard_report["passed"] is True
    review = {
        "schema_version": "1.0",
        "artifact_id": "research/aoi-kisaragi-fixture/release/review",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "review_id": "aoi-review-01",
        "namespace": "research",
        "character_id": "aoi-kisaragi-fixture",
        "character_version": "1.0.0",
        "mode": "researched",
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

    record = create_promotion_record(
        pack,
        request,
        hard_report,
        review,
        SCHEMAS,
        target="reviewed",
        promotion_id="aoi-promotion-reviewed-01",
        research_bundle=research_bundle,
    )

    assert record["mode"] == "researched"
    assert record["visibility"] == "private"
    assert record["activation_allowed"] is False


def test_creates_exact_reviewed_to_verified_record_for_rin() -> None:
    inputs = _release_inputs()
    reviewed = _reviewed(inputs)

    verified = create_promotion_record(
        RIN_PACK,
        inputs["request"],
        inputs["hard_report"],
        inputs["review"],
        SCHEMAS,
        target="verified",
        promotion_id="rin-promotion-verified-01",
        previous_promotion=reviewed,
        soft_evaluation_input=inputs["soft_input"],
        soft_evaluation_report=inputs["soft_report"],
    )

    assert verified["artifact_id"] == "original/rin-aster/release/promotion-verified"
    assert verified["from_status"] == "reviewed"
    assert verified["to_status"] == "verified"
    assert verified["activation_allowed"] is True
    assert verified["previous_promotion"] == {
        "artifact_id": reviewed["artifact_id"],
        "sha256": _sha256(reviewed),
    }
    assert verified["soft_evaluation_report"] == {
        "artifact_id": inputs["soft_report"]["artifact_id"],
        "sha256": _sha256(inputs["soft_report"]),
    }
    SCHEMAS.validate("pack-promotion-record", verified)


@pytest.mark.parametrize("target", ["draft", "archived", "released"])
def test_rejects_skipped_reversed_or_unknown_targets(target: str) -> None:
    inputs = _release_inputs()

    with pytest.raises(KokoroError) as captured:
        create_promotion_record(
            RIN_PACK,
            inputs["request"],
            inputs["hard_report"],
            inputs["review"],
            SCHEMAS,
            target=target,
            promotion_id="rin-promotion-invalid-01",
        )

    assert captured.value.code == "PACK_PROMOTION_TRANSITION_INVALID"


def test_verified_transition_requires_previous_and_soft_evidence() -> None:
    inputs = _release_inputs()

    with pytest.raises(KokoroError) as captured:
        create_promotion_record(
            RIN_PACK,
            inputs["request"],
            inputs["hard_report"],
            inputs["review"],
            SCHEMAS,
            target="verified",
            promotion_id="rin-promotion-verified-01",
        )

    assert captured.value.code == "PACK_PROMOTION_EVIDENCE_REQUIRED"


def test_promotion_does_not_mutate_any_input() -> None:
    inputs = _release_inputs()
    baseline = deepcopy(inputs)

    _reviewed(inputs)

    assert inputs == baseline


def test_rejects_a_stale_or_mismatched_hard_report() -> None:
    inputs = _release_inputs()
    stale = deepcopy(inputs["hard_report"])
    stale["source_hash"] = "0" * 64

    with pytest.raises(KokoroError) as captured:
        create_promotion_record(
            RIN_PACK,
            inputs["request"],
            stale,
            inputs["review"],
            SCHEMAS,
            target="reviewed",
            promotion_id="rin-promotion-reviewed-01",
        )

    assert captured.value.code == "PACK_PROMOTION_HARD_REPORT_STALE"


def test_rejects_a_failed_current_hard_gate(tmp_path: Path) -> None:
    pack = tmp_path / "rin"
    shutil.copytree(RIN_PACK, pack)
    (pack / "tests" / "positive.yaml").unlink()
    inputs = _release_inputs()
    failed = run_hard_validation(pack, inputs["request"], SCHEMAS)
    assert failed["passed"] is False

    with pytest.raises(KokoroError) as captured:
        create_promotion_record(
            pack,
            inputs["request"],
            failed,
            inputs["review"],
            SCHEMAS,
            target="reviewed",
            promotion_id="rin-promotion-reviewed-01",
        )

    assert captured.value.code == "PACK_PROMOTION_HARD_GATE_FAILED"


def test_rejects_a_rejected_or_mismatched_review() -> None:
    inputs = _release_inputs()
    rejected = deepcopy(inputs["review"])
    rejected["decision"] = "reject"
    rejected["reviewed"]["identity"] = False

    with pytest.raises(KokoroError) as rejected_error:
        create_promotion_record(
            RIN_PACK,
            inputs["request"],
            inputs["hard_report"],
            rejected,
            SCHEMAS,
            target="reviewed",
            promotion_id="rin-promotion-reviewed-01",
        )
    assert rejected_error.value.code == "PACK_PROMOTION_REVIEW_REJECTED"

    mismatched = deepcopy(inputs["review"])
    mismatched["source_hash"] = "0" * 64
    with pytest.raises(KokoroError) as mismatch_error:
        create_promotion_record(
            RIN_PACK,
            inputs["request"],
            inputs["hard_report"],
            mismatched,
            SCHEMAS,
            target="reviewed",
            promotion_id="rin-promotion-reviewed-01",
        )
    assert mismatch_error.value.code == "PACK_PROMOTION_BINDING_MISMATCH"


def test_rejects_failed_stale_and_cross_pack_verified_evidence() -> None:
    inputs = _release_inputs()
    reviewed = _reviewed(inputs)

    failed_input = deepcopy(inputs["soft_input"])
    for sample in failed_input["samples"]["semantic_equivalence"].values():
        sample["score"] = 0.5
    failed_report = aggregate_soft_evaluation(failed_input, SCHEMAS)
    assert failed_report["passed"] is False
    with pytest.raises(KokoroError) as failed_error:
        create_promotion_record(
            RIN_PACK,
            inputs["request"],
            inputs["hard_report"],
            inputs["review"],
            SCHEMAS,
            target="verified",
            promotion_id="rin-promotion-verified-01",
            previous_promotion=reviewed,
            soft_evaluation_input=failed_input,
            soft_evaluation_report=failed_report,
        )
    assert failed_error.value.code == "PACK_PROMOTION_SOFT_GATE_FAILED"

    stale_report = deepcopy(inputs["soft_report"])
    stale_report["source_hash"] = "0" * 64
    with pytest.raises(KokoroError) as stale_error:
        create_promotion_record(
            RIN_PACK,
            inputs["request"],
            inputs["hard_report"],
            inputs["review"],
            SCHEMAS,
            target="verified",
            promotion_id="rin-promotion-verified-01",
            previous_promotion=reviewed,
            soft_evaluation_input=inputs["soft_input"],
            soft_evaluation_report=stale_report,
        )
    assert stale_error.value.code == "PACK_PROMOTION_SOFT_REPORT_STALE"

    mismatched_previous = deepcopy(reviewed)
    mismatched_previous["compiled_hash"] = "0" * 64
    with pytest.raises(KokoroError) as previous_error:
        create_promotion_record(
            RIN_PACK,
            inputs["request"],
            inputs["hard_report"],
            inputs["review"],
            SCHEMAS,
            target="verified",
            promotion_id="rin-promotion-verified-01",
            previous_promotion=mismatched_previous,
            soft_evaluation_input=inputs["soft_input"],
            soft_evaluation_report=inputs["soft_report"],
        )
    assert previous_error.value.code == "PACK_PROMOTION_BINDING_MISMATCH"


def test_rejects_source_mutation_during_promotion(tmp_path: Path) -> None:
    pack = tmp_path / "rin"
    shutil.copytree(RIN_PACK, pack)
    request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    hard_report = run_hard_validation(pack, request, SCHEMAS)
    inputs = _release_inputs()
    review = deepcopy(inputs["review"])
    review["source_hash"] = hard_report["source_hash"]
    review["hard_report"] = {
        "artifact_id": hard_report["artifact_id"],
        "sha256": _sha256(hard_report),
    }

    class SourceMutatingRegistry:
        mutated = False

        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "pack-promotion-record" and not self.mutated:
                self.mutated = True
                behavior = pack / "behavior.yaml"
                behavior.write_text(
                    behavior.read_text(encoding="utf-8") + "\n# changed\n",
                    encoding="utf-8",
                )

    with pytest.raises(KokoroError) as captured:
        create_promotion_record(
            pack,
            request,
            hard_report,
            review,
            SourceMutatingRegistry(),  # type: ignore[arg-type]
            target="reviewed",
            promotion_id="rin-promotion-reviewed-01",
        )

    assert captured.value.code == "PACK_PROMOTION_SOURCE_CHANGED"


def test_first_schema_callback_cannot_rebase_the_entry_source(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "rin"
    shutil.copytree(RIN_PACK, pack)
    inputs = _release_inputs()
    behavior = pack / "behavior.yaml"
    original = behavior.read_bytes()
    behavior.write_bytes(original + b"\n# source visible at entry\n")

    class RebasingRegistry:
        restored = False

        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "pack-hard-validation-report" and not self.restored:
                self.restored = True
                behavior.write_bytes(original)

    registry = RebasingRegistry()
    with pytest.raises(KokoroError) as captured:
        create_promotion_record(
            pack,
            inputs["request"],
            inputs["hard_report"],
            inputs["review"],
            registry,  # type: ignore[arg-type]
            target="reviewed",
            promotion_id="rin-promotion-reviewed-01",
        )

    assert registry.restored is True
    assert captured.value.code == "PACK_PROMOTION_HARD_REPORT_STALE"


def test_rejects_caller_input_mutation_during_schema_callbacks() -> None:
    inputs = _release_inputs()

    class CallerMutatingRegistry:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "pack-review-attestation":
                inputs["review"]["source_hash"] = "0" * 64

    with pytest.raises(KokoroError) as captured:
        create_promotion_record(
            RIN_PACK,
            inputs["request"],
            inputs["hard_report"],
            inputs["review"],
            CallerMutatingRegistry(),  # type: ignore[arg-type]
            target="reviewed",
            promotion_id="rin-promotion-reviewed-01",
        )

    assert captured.value.code == "PACK_PROMOTION_INPUT_MUTATION"


def test_verified_rechecks_source_after_final_soft_validation_callback(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "rin"
    shutil.copytree(RIN_PACK, pack)
    inputs = _release_inputs()
    reviewed = create_promotion_record(
        pack,
        inputs["request"],
        inputs["hard_report"],
        inputs["review"],
        SCHEMAS,
        target="reviewed",
        promotion_id="rin-promotion-reviewed-01",
    )

    class LateSourceMutatingRegistry:
        report_validations = 0
        mutated = False

        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if name == "pack-soft-evaluation-report":
                self.report_validations += 1
                if self.report_validations == 5:
                    self.mutated = True
                    behavior = pack / "behavior.yaml"
                    behavior.write_text(
                        behavior.read_text(encoding="utf-8") + "\n# late change\n",
                        encoding="utf-8",
                    )

    registry = LateSourceMutatingRegistry()
    with pytest.raises(KokoroError) as captured:
        create_promotion_record(
            pack,
            inputs["request"],
            inputs["hard_report"],
            inputs["review"],
            registry,  # type: ignore[arg-type]
            target="verified",
            promotion_id="rin-promotion-verified-01",
            previous_promotion=reviewed,
            soft_evaluation_input=inputs["soft_input"],
            soft_evaluation_report=inputs["soft_report"],
        )

    assert registry.mutated is True
    assert captured.value.code == "PACK_PROMOTION_SOURCE_CHANGED"
