"""Integration coverage for deterministic standalone archives."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from kokoroarc.distribution.archive import build_karc_archive, load_karc_archive
from kokoroarc.packs.compiler import compile_pack
from kokoroarc.packs.loader import load_source_pack
from kokoroarc.schemas import SchemaRegistry
from kokoroarc.testing.publication import assess_publication_readiness


SCHEMAS = SchemaRegistry(Path("schemas/v1"))
RIN_PACK = Path("characters/original/rin-aster")


@pytest.mark.parametrize(
    "fixture_name,visibility",
    [
        ("rin_verified_release", "private"),
        ("rin_public_verified_release", "public_candidate"),
    ],
)
def test_real_verified_rin_release_round_trips_as_a_deterministic_archive(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    fixture_name: str,
    visibility: str,
) -> None:
    release: dict[str, Any] = request.getfixturevalue(fixture_name)
    evidence = release["evidence"]
    promotion = release["promotion"]
    publication = None
    if visibility == "public_candidate":
        publication = assess_publication_readiness(
            RIN_PACK,
            promotion,
            SCHEMAS,
            promotion_evidence=evidence,
            requested_visibility="public_candidate",
            compliance_attestation={
                "attestation_id": "rin-rights-review-01",
                "reviewer_id": "local-maintainer",
                "scope": "distribution_rights_reviewed",
                "conclusion": "approved",
                "source_hash": promotion["source_hash"],
                "compiled_hash": promotion["compiled_hash"],
                "basis_codes": ["ORIGINAL_AUTHORSHIP_CONFIRMED"],
            },
        )

    arguments = {
        "compiled_pack": compile_pack(load_source_pack(RIN_PACK, SCHEMAS), SCHEMAS),
        "hard_validation_report": evidence["hard_report"],
        "soft_evaluation_report": evidence["soft_evaluation_report"],
        "review_attestation": evidence["review_attestation"],
        "promotion_record": promotion,
        "publication_readiness_report": publication,
        "schemas": SCHEMAS,
    }
    first = build_karc_archive(**arguments)
    second = build_karc_archive(**arguments)
    target = tmp_path / f"rin-aster-{visibility}.karc"
    target.write_bytes(first)

    loaded = load_karc_archive(target.read_bytes(), SCHEMAS)

    assert first == second
    assert loaded.manifest["visibility"] == visibility
    assert loaded.documents["pack/compiled.json"]["character_id"] == "rin-aster"
    assert loaded.documents["release/promotion-record.json"] == promotion
