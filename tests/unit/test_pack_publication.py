from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Any, Callable

import pytest
import yaml

from kokoroarc import __version__
from kokoroarc.packs.compiler import canonical_bytes, compile_pack
from kokoroarc.packs.loader import load_source_pack
from kokoroarc.schemas import SchemaRegistry
from kokoroarc.testing.publication import (
    assess_publication_readiness,
    publication_report_is_current,
)


SCHEMAS = SchemaRegistry(Path("schemas/v1"))
RIN_PACK = Path("characters/original/rin-aster")


def _sha256(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _verified_promotion(
    pack: Path,
    *,
    mode: str = "original",
    visibility: str = "private",
) -> dict[str, Any]:
    source = load_source_pack(pack, SCHEMAS)
    compiled = compile_pack(source, SCHEMAS)
    prefix = f"{source['namespace']}/{source['character_id']}"
    record = {
        "schema_version": "1.0",
        "artifact_id": f"{prefix}/release/promotion-verified",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "promotion_id": f"{source['character_id']}-promotion-verified-01",
        "namespace": source["namespace"],
        "character_id": source["character_id"],
        "character_version": source["character_version"],
        "mode": mode,
        "visibility": visibility,
        "source_artifact_id": source["artifact_id"],
        "source_hash": _sha256(source),
        "compiled_artifact_id": compiled["artifact_id"],
        "compiled_hash": _sha256(compiled),
        "from_status": "reviewed",
        "to_status": "verified",
        "activation_allowed": True,
        "hard_report": {
            "artifact_id": f"{prefix}/release/hard-validation",
            "sha256": "1" * 64,
        },
        "review_attestation": {
            "artifact_id": f"{prefix}/release/review",
            "sha256": "2" * 64,
        },
        "previous_promotion": {
            "artifact_id": f"{prefix}/release/promotion-reviewed",
            "sha256": "3" * 64,
        },
        "soft_evaluation_report": {
            "artifact_id": f"{prefix}/release/soft-evaluation",
            "sha256": "4" * 64,
        },
    }
    SCHEMAS.validate("pack-promotion-record", record)
    return record


def _compliance(
    promotion: dict[str, Any],
    *,
    conclusion: str = "approved",
    basis_codes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "attestation_id": "rin-rights-review-01",
        "reviewer_id": "local-maintainer",
        "scope": "distribution_rights_reviewed",
        "conclusion": conclusion,
        "source_hash": promotion["source_hash"],
        "compiled_hash": promotion["compiled_hash"],
        "basis_codes": basis_codes or ["ORIGINAL_AUTHORSHIP_CONFIRMED"],
    }


def _researched_pack(tmp_path: Path) -> Path:
    pack = tmp_path / "researched-pack"
    shutil.copytree(RIN_PACK, pack)
    manifest_path = pack / "character.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "artifact_id": "research/aoi-kisaragi-fixture/source",
            "namespace": "research",
            "character_id": "aoi-kisaragi-fixture",
            "spoiler_scope": "episode-01 only",
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
                    {
                        "claim_id": "claim-role",
                        "source": "research_bundle",
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return pack


def test_private_rin_is_ready_for_portable_export_without_publication(
    rin_verified_release: dict[str, Any],
) -> None:
    promotion = rin_verified_release["promotion"]
    evidence = rin_verified_release["evidence"]
    before = deepcopy(promotion)

    report = assess_publication_readiness(
        RIN_PACK,
        promotion,
        SCHEMAS,
        promotion_evidence=evidence,
        requested_visibility="private",
    )

    assert report["requested_visibility"] == "private"
    assert report["ready_for_private_export"] is True
    assert report["ready_for_publication"] is False
    assert report["compliance_attestation"] is None
    assert report["blockers"] == []
    assert all(check["passed"] for check in report["checks"].values())
    assert report["promotion"] == {
        "artifact_id": promotion["artifact_id"],
        "sha256": _sha256(promotion),
    }
    assert report["promotion_evidence_hash"] == _sha256(evidence)
    assert report["compliance_input_hash"] == _sha256(None)
    assert promotion == before
    SCHEMAS.validate("pack-publication-readiness-report", report)
    assert publication_report_is_current(
        report,
        RIN_PACK,
        promotion,
        SCHEMAS,
        promotion_evidence=evidence,
    )


def test_original_public_candidate_requires_exact_approved_compliance(
    rin_public_verified_release: dict[str, Any],
) -> None:
    promotion = rin_public_verified_release["promotion"]
    evidence = rin_public_verified_release["evidence"]
    compliance = _compliance(promotion)

    report = assess_publication_readiness(
        RIN_PACK,
        promotion,
        SCHEMAS,
        promotion_evidence=evidence,
        requested_visibility="public_candidate",
        compliance_attestation=compliance,
    )

    assert report["ready_for_private_export"] is True
    assert report["ready_for_publication"] is True
    assert report["blockers"] == []
    assert report["compliance_attestation"] == compliance
    assert report["promotion_evidence_hash"] == _sha256(evidence)
    assert report["compliance_input_hash"] == _sha256(compliance)
    assert report["checks"]["compliance"] == {"passed": True, "findings": []}
    SCHEMAS.validate("pack-publication-readiness-report", report)
    assert publication_report_is_current(
        report,
        RIN_PACK,
        promotion,
        SCHEMAS,
        promotion_evidence=evidence,
    )


def test_private_verified_promotion_cannot_be_upgraded_to_public_candidate(
    rin_verified_release: dict[str, Any],
) -> None:
    promotion = rin_verified_release["promotion"]
    evidence = rin_verified_release["evidence"]
    compliance = _compliance(promotion)

    report = assess_publication_readiness(
        RIN_PACK,
        promotion,
        SCHEMAS,
        promotion_evidence=evidence,
        requested_visibility="public_candidate",
        compliance_attestation=compliance,
    )

    assert report["ready_for_private_export"] is True
    assert report["ready_for_publication"] is False
    assert report["checks"]["visibility_policy"]["passed"] is False
    assert {item["code"] for item in report["blockers"]} == {
        "PUBLICATION_PROMOTION_VISIBILITY_MISMATCH"
    }
    SCHEMAS.validate("pack-publication-readiness-report", report)


def test_structurally_valid_promotion_without_release_evidence_is_blocked() -> None:
    promotion = _verified_promotion(RIN_PACK)

    report = assess_publication_readiness(RIN_PACK, promotion, SCHEMAS)

    assert report["checks"]["verified_promotion"]["passed"] is False
    assert report["ready_for_private_export"] is False
    assert report["ready_for_publication"] is False
    assert {item["code"] for item in report["blockers"]} == {
        "PUBLICATION_PROMOTION_EVIDENCE_INVALID"
    }
    assert publication_report_is_current(report, RIN_PACK, promotion, SCHEMAS)
    assert not publication_report_is_current(
        report,
        RIN_PACK,
        promotion,
        SCHEMAS,
        promotion_evidence={},
    )


@pytest.mark.parametrize(
    "invalid_evidence",
    [
        42,
        [{}],
        [
            "request",
            "hard_report",
            "review_attestation",
            "previous_promotion",
            "soft_evaluation_input",
            "soft_evaluation_report",
        ],
    ],
)
def test_non_object_promotion_evidence_is_a_reportable_blocker(
    invalid_evidence: Any,
) -> None:
    promotion = _verified_promotion(RIN_PACK)

    report = assess_publication_readiness(
        RIN_PACK,
        promotion,
        SCHEMAS,
        promotion_evidence=invalid_evidence,
    )

    assert report["promotion_evidence_hash"] == _sha256(invalid_evidence)
    assert {item["code"] for item in report["blockers"]} == {
        "PUBLICATION_PROMOTION_EVIDENCE_INVALID"
    }
    assert publication_report_is_current(
        report,
        RIN_PACK,
        promotion,
        SCHEMAS,
        promotion_evidence=invalid_evidence,
    )


def test_currentness_rejects_non_object_report_without_raising() -> None:
    promotion = _verified_promotion(RIN_PACK)

    assert not publication_report_is_current([], RIN_PACK, promotion, SCHEMAS)


def test_researched_public_candidate_can_remain_private_export_ready(
    tmp_path: Path,
    verified_release_factory: Callable[..., dict[str, Any]],
) -> None:
    pack = _researched_pack(tmp_path)
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
    release = verified_release_factory(
        pack,
        request,
        visibility="private",
        research_bundle=research_bundle,
    )
    promotion = release["promotion"]
    compliance = _compliance(
        promotion,
        conclusion="blocked",
        basis_codes=["RIGHTS_NOT_ESTABLISHED"],
    )

    report = assess_publication_readiness(
        pack,
        promotion,
        SCHEMAS,
        promotion_evidence=release["evidence"],
        requested_visibility="public_candidate",
        compliance_attestation=compliance,
    )

    assert report["ready_for_private_export"] is True
    assert report["ready_for_publication"] is False
    assert report["checks"]["provenance"]["passed"] is True
    assert report["checks"]["compliance"]["passed"] is False
    assert {item["code"] for item in report["blockers"]} == {
        "PUBLICATION_PROMOTION_VISIBILITY_MISMATCH",
        "PUBLICATION_RIGHTS_NOT_ESTABLISHED",
    }
    SCHEMAS.validate("pack-publication-readiness-report", report)


def test_stale_verified_promotion_is_reported_as_a_private_export_blocker(
    tmp_path: Path,
    rin_verified_release: dict[str, Any],
) -> None:
    pack = tmp_path / "rin"
    shutil.copytree(RIN_PACK, pack)
    promotion = rin_verified_release["promotion"]
    evidence = rin_verified_release["evidence"]
    behavior_path = pack / "behavior.yaml"
    behavior = yaml.safe_load(behavior_path.read_text(encoding="utf-8"))
    behavior["correction_style"] = "gentle"
    behavior_path.write_text(
        yaml.safe_dump(behavior, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    report = assess_publication_readiness(
        pack,
        promotion,
        SCHEMAS,
        promotion_evidence=evidence,
        requested_visibility="private",
    )

    assert report["checks"]["verified_promotion"]["passed"] is False
    assert report["ready_for_private_export"] is False
    assert report["ready_for_publication"] is False
    assert "PUBLICATION_PROMOTION_STALE" in {
        item["code"] for item in report["blockers"]
    }
    SCHEMAS.validate("pack-publication-readiness-report", report)


@pytest.mark.parametrize(
    "mutate, expected_code",
    [
        (
            lambda pack: _mutate_yaml(
                pack / "identity.yaml", "declared_age", "unspecified"
            ),
            "PUBLICATION_AGE_DECLARATION_MISSING",
        ),
        (
            lambda pack: _mutate_yaml(
                pack / "identity.yaml", "declared_age", "   "
            ),
            "PUBLICATION_AGE_DECLARATION_MISSING",
        ),
        (
            lambda pack: _mutate_yaml(
                pack / "identity.yaml", "declared_age", "unknown age"
            ),
            "PUBLICATION_AGE_DECLARATION_MISSING",
        ),
        (
            lambda pack: _mutate_yaml(
                pack / "identity.yaml", "declared_age", "profile version 2"
            ),
            "PUBLICATION_AGE_DECLARATION_MISSING",
        ),
        (
            lambda pack: _mutate_yaml(
                pack / "identity.yaml", "declared_age", "minor version"
            ),
            "PUBLICATION_AGE_DECLARATION_MISSING",
        ),
        (
            lambda pack: _mutate_yaml(
                pack / "identity.yaml", "declared_age", "adult content rating"
            ),
            "PUBLICATION_AGE_DECLARATION_MISSING",
        ),
        (
            lambda pack: _mutate_yaml(
                pack / "identity.yaml",
                "declared_age",
                "software aged 2 releases",
            ),
            "PUBLICATION_AGE_DECLARATION_MISSING",
        ),
        (
            lambda pack: _remove_yaml_key(pack / "growth.yaml", "stages"),
            "PUBLICATION_ROUTE_DECLARATION_MISSING",
        ),
        (
            lambda pack: _mutate_yaml(
                pack / "growth.yaml",
                "stages",
                {"unknown": {"enter_familiarity": 0}},
            ),
            "PUBLICATION_ROUTE_DECLARATION_MISSING",
        ),
        (
            lambda pack: _mutate_yaml(
                pack / "growth.yaml",
                "stages",
                {
                    "acquainted": {"enter_familiarity": 10},
                    "familiar": {"enter_familiarity": 30},
                },
            ),
            "PUBLICATION_ROUTE_DECLARATION_MISSING",
        ),
        (
            lambda pack: _remove_yaml_key(pack / "character.yaml", "spoiler_scope"),
            "PUBLICATION_SPOILER_DECLARATION_MISSING",
        ),
        (
            lambda pack: _mutate_yaml(
                pack / "character.yaml", "spoiler_scope", "unknown"
            ),
            "PUBLICATION_SPOILER_DECLARATION_MISSING",
        ),
        (
            lambda pack: _mutate_yaml(
                pack / "evidence.yaml",
                "claims",
                [
                    {
                        "claim_id": "continuity-note",
                        "statement": "An unresolved continuity conflict remains.",
                    }
                ],
            ),
            "PUBLICATION_CONTINUITY_CONFLICT_UNRESOLVED",
        ),
        (
            lambda pack: _mutate_yaml(
                pack / "behavior.yaml",
                "correction_style",
                "No unresolved items. Later: unresolved canon conflict.",
            ),
            "PUBLICATION_CONTINUITY_CONFLICT_UNRESOLVED",
        ),
        (
            lambda pack: _mutate_yaml(
                pack / "behavior.yaml",
                "correction_style",
                "UNRESOLVED_CONFLICT",
            ),
            "PUBLICATION_CONTINUITY_CONFLICT_UNRESOLVED",
        ),
        (
            lambda pack: _mutate_yaml(
                pack / "identity.yaml",
                "role",
                "systems architect path:/home/alice/private.txt",
            ),
            "PUBLICATION_ABSOLUTE_PATH_PRESENT",
        ),
    ],
)
def test_missing_declarations_and_unresolved_conflicts_block_private_export(
    tmp_path: Path,
    mutate: Any,
    expected_code: str,
    rin_verified_release: dict[str, Any],
) -> None:
    pack = tmp_path / expected_code.lower()
    shutil.copytree(RIN_PACK, pack)
    mutate(pack)
    promotion = rin_verified_release["promotion"]

    report = assess_publication_readiness(
        pack,
        promotion,
        SCHEMAS,
        promotion_evidence=rin_verified_release["evidence"],
    )

    assert report["ready_for_private_export"] is False
    assert expected_code in {item["code"] for item in report["blockers"]}


@pytest.mark.parametrize(
    "declared_age",
    [
        "17",
        "age: 17",
        "aged 17",
        "17 years old",
        "17-year-old",
        "17-year old",
        "17 year-old",
        "17 yrs old",
        "17 y/o",
    ],
)
def test_explicit_numeric_age_declarations_are_usable(
    tmp_path: Path,
    declared_age: str,
    rin_verified_release: dict[str, Any],
) -> None:
    pack = tmp_path / "explicit-numeric-age"
    shutil.copytree(RIN_PACK, pack)
    _mutate_yaml(pack / "identity.yaml", "declared_age", declared_age)

    report = assess_publication_readiness(
        pack,
        rin_verified_release["promotion"],
        SCHEMAS,
        promotion_evidence=rin_verified_release["evidence"],
    )

    assert report["checks"]["age_routes"]["passed"] is True


def test_hyphenated_numeric_age_is_private_export_ready(
    tmp_path: Path,
    verified_release_factory: Callable[..., dict[str, Any]],
) -> None:
    pack = tmp_path / "hyphenated-numeric-age"
    shutil.copytree(RIN_PACK, pack)
    _mutate_yaml(pack / "identity.yaml", "declared_age", "17-year-old")
    request = json.loads(
        Path("tests/fixtures/authoring/original-request.json").read_text(
            encoding="utf-8"
        )
    )
    release = verified_release_factory(pack, request, visibility="private")

    report = assess_publication_readiness(
        pack,
        release["promotion"],
        SCHEMAS,
        promotion_evidence=release["evidence"],
    )

    assert report["checks"]["verified_promotion"]["passed"] is True
    assert report["checks"]["age_routes"]["passed"] is True
    assert report["ready_for_private_export"] is True


def test_exact_release_still_checks_routes_continuity_and_host_paths(
    tmp_path: Path,
    verified_release_factory: Callable[..., dict[str, Any]],
) -> None:
    pack = tmp_path / "semantic-publication-blockers"
    shutil.copytree(RIN_PACK, pack)
    _mutate_yaml(
        pack / "identity.yaml",
        "role",
        "systems architect path:/home/alice/private.txt "
        "file:///home/alice/private.txt UNRESOLVED_CONFLICT",
    )
    _mutate_yaml(pack / "identity.yaml", "declared_age", "minor version")
    _mutate_yaml(
        pack / "growth.yaml",
        "stages",
        {
            "acquainted": {"enter_familiarity": 10},
            "familiar": {"enter_familiarity": 30},
            "trusted": {"enter_trust": 50},
        },
    )
    request = json.loads(
        Path("tests/fixtures/authoring/original-request.json").read_text(
            encoding="utf-8"
        )
    )
    release = verified_release_factory(pack, request, visibility="private")

    report = assess_publication_readiness(
        pack,
        release["promotion"],
        SCHEMAS,
        promotion_evidence=release["evidence"],
    )

    assert report["checks"]["verified_promotion"]["passed"] is True
    assert {item["code"] for item in report["blockers"]} == {
        "PUBLICATION_ABSOLUTE_PATH_PRESENT",
        "PUBLICATION_AGE_DECLARATION_MISSING",
        "PUBLICATION_CONTINUITY_CONFLICT_UNRESOLVED",
        "PUBLICATION_ROUTE_DECLARATION_MISSING",
    }
    assert report["ready_for_private_export"] is False
    assert publication_report_is_current(
        report,
        pack,
        release["promotion"],
        SCHEMAS,
        promotion_evidence=release["evidence"],
    )


def test_whitespace_nonoriginal_source_reference_blocks_private_export(
    tmp_path: Path,
) -> None:
    pack = _researched_pack(tmp_path)
    evidence_path = pack / "evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    evidence["claims"][0]["source"] = "   "
    evidence_path.write_text(
        yaml.safe_dump(evidence, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    promotion = _verified_promotion(pack, mode="researched")

    report = assess_publication_readiness(pack, promotion, SCHEMAS)

    assert report["ready_for_private_export"] is False
    assert "PUBLICATION_SOURCE_REFERENCE_MISSING" in {
        item["code"] for item in report["blockers"]
    }


@pytest.mark.parametrize(
    "change",
    [
        {"source_hash": "0" * 64},
        {"conclusion": "blocked"},
        {"basis_codes": ["SELF_ASSERTED"]},
    ],
)
def test_fake_or_non_approving_compliance_never_unlocks_publication(
    change: dict[str, Any],
    rin_public_verified_release: dict[str, Any],
) -> None:
    promotion = rin_public_verified_release["promotion"]
    compliance = _compliance(promotion)
    compliance.update(change)

    report = assess_publication_readiness(
        RIN_PACK,
        promotion,
        SCHEMAS,
        promotion_evidence=rin_public_verified_release["evidence"],
        requested_visibility="public_candidate",
        compliance_attestation=compliance,
    )

    assert report["ready_for_private_export"] is True
    assert report["ready_for_publication"] is False
    assert report["checks"]["compliance"]["passed"] is False


def test_report_bytes_are_deterministic_and_mapping_order_independent(
    rin_verified_release: dict[str, Any],
) -> None:
    promotion = rin_verified_release["promotion"]
    evidence = rin_verified_release["evidence"]
    reversed_promotion = dict(reversed(list(promotion.items())))

    first = assess_publication_readiness(
        RIN_PACK,
        promotion,
        SCHEMAS,
        promotion_evidence=evidence,
    )
    second = assess_publication_readiness(
        RIN_PACK,
        reversed_promotion,
        SCHEMAS,
        promotion_evidence=evidence,
    )

    assert canonical_bytes(first) == canonical_bytes(second)


def _mutate_yaml(path: Path, key: str, value: Any) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document[key] = value
    path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _remove_yaml_key(path: Path, key: str) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document.pop(key, None)
    path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
