from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry
from kokoroarc.testing.storage import (
    load_published_promotion_record,
    publish_promotion_record,
)


SCHEMAS = SchemaRegistry(Path("schemas/v1"))
RELEASE_FIXTURE = Path("tests/fixtures/pack-release/original-minimal.json")


def _sha256(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _reviewed_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    fixture = json.loads(RELEASE_FIXTURE.read_text(encoding="utf-8"))
    review = deepcopy(fixture["review_attestation"])
    record = deepcopy(fixture["promotion_record"])
    record["review_attestation"] = {
        "artifact_id": review["artifact_id"],
        "sha256": _sha256(review),
    }
    SCHEMAS.validate("pack-review-attestation", review)
    SCHEMAS.validate("pack-promotion-record", record)
    return record, review


def _verified_record(reviewed: dict[str, Any]) -> dict[str, Any]:
    verified = deepcopy(reviewed)
    verified.update(
        {
            "artifact_id": "original/rin-aster/release/promotion-verified",
            "promotion_id": "rin-promotion-verified-01",
            "from_status": "reviewed",
            "to_status": "verified",
            "activation_allowed": True,
            "previous_promotion": {
                "artifact_id": reviewed["artifact_id"],
                "sha256": _sha256(reviewed),
            },
            "soft_evaluation_report": {
                "artifact_id": "original/rin-aster/release/soft-evaluation",
                "sha256": "f" * 64,
            },
        }
    )
    SCHEMAS.validate("pack-promotion-record", verified)
    return verified


def test_publishes_sequential_records_as_complete_immutable_bundles(
    tmp_path: Path,
) -> None:
    reviewed, review = _reviewed_artifacts()
    verified = _verified_record(reviewed)
    data_root = tmp_path / "data"

    reviewed_path = publish_promotion_record(
        data_root, reviewed, review, SCHEMAS
    )
    verified_path = publish_promotion_record(
        data_root, verified, review, SCHEMAS
    )

    expected_root = data_root / "reports" / "promotions" / "rin-aster"
    assert reviewed_path == (
        expected_root / "rin-promotion-reviewed-01" / "promotion.json"
    )
    assert verified_path == (
        expected_root / "rin-promotion-verified-01" / "promotion.json"
    )
    assert reviewed_path.read_bytes() == canonical_bytes(reviewed) + b"\n"
    assert verified_path.read_bytes() == canonical_bytes(verified) + b"\n"
    assert (reviewed_path.parent / "review-attestation.json").read_bytes() == (
        canonical_bytes(review) + b"\n"
    )
    assert (verified_path.parent / "review-attestation.json").read_bytes() == (
        canonical_bytes(review) + b"\n"
    )
    assert load_published_promotion_record(reviewed_path, SCHEMAS) == reviewed
    assert load_published_promotion_record(verified_path.parent, SCHEMAS) == verified
    assert sorted(path.name for path in expected_root.iterdir()) == [
        "rin-promotion-reviewed-01",
        "rin-promotion-verified-01",
    ]


def test_identical_retry_is_idempotent_and_conflicting_retry_never_overwrites(
    tmp_path: Path,
) -> None:
    record, review = _reviewed_artifacts()
    data_root = tmp_path / "data"
    published = publish_promotion_record(data_root, record, review, SCHEMAS)
    original_record = published.read_bytes()
    original_review = (published.parent / "review-attestation.json").read_bytes()
    original_identity = published.stat().st_ino

    assert publish_promotion_record(data_root, record, review, SCHEMAS) == published
    assert published.stat().st_ino == original_identity

    conflicting_review = deepcopy(review)
    conflicting_review["review_id"] = "rin-review-02"
    conflicting_record = deepcopy(record)
    conflicting_record["review_attestation"] = {
        "artifact_id": conflicting_review["artifact_id"],
        "sha256": _sha256(conflicting_review),
    }

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(
            data_root, conflicting_record, conflicting_review, SCHEMAS
        )

    assert caught.value.code == "PACK_PROMOTION_CONFLICT"
    assert published.read_bytes() == original_record
    assert (
        published.parent / "review-attestation.json"
    ).read_bytes() == original_review


def test_changed_reuse_of_review_id_is_rejected_but_exact_sequential_reuse_works(
    tmp_path: Path,
) -> None:
    reviewed, review = _reviewed_artifacts()
    data_root = tmp_path / "data"
    publish_promotion_record(data_root, reviewed, review, SCHEMAS)

    changed_review = deepcopy(review)
    changed_review["reviewer"]["id"] = "different-reviewer"
    second_reviewed = deepcopy(reviewed)
    second_reviewed["promotion_id"] = "rin-promotion-reviewed-02"
    second_reviewed["review_attestation"] = {
        "artifact_id": changed_review["artifact_id"],
        "sha256": _sha256(changed_review),
    }

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(
            data_root, second_reviewed, changed_review, SCHEMAS
        )

    assert caught.value.code == "PACK_PROMOTION_REVIEW_ID_CONFLICT"
    assert not (
        data_root
        / "reports"
        / "promotions"
        / "rin-aster"
        / "rin-promotion-reviewed-02"
    ).exists()

    verified = _verified_record(reviewed)
    published = publish_promotion_record(data_root, verified, review, SCHEMAS)
    assert load_published_promotion_record(published, SCHEMAS) == verified


def test_exact_review_id_reuse_is_limited_to_one_matching_verified_transition(
    tmp_path: Path,
) -> None:
    reviewed, review = _reviewed_artifacts()
    data_root = tmp_path / "data"
    publish_promotion_record(data_root, reviewed, review, SCHEMAS)

    duplicate_reviewed = deepcopy(reviewed)
    duplicate_reviewed["promotion_id"] = "rin-promotion-reviewed-02"
    with pytest.raises(KokoroError) as reviewed_error:
        publish_promotion_record(
            data_root,
            duplicate_reviewed,
            review,
            SCHEMAS,
        )
    assert reviewed_error.value.code == "PACK_PROMOTION_REVIEW_ID_CONFLICT"

    verified = _verified_record(reviewed)
    publish_promotion_record(data_root, verified, review, SCHEMAS)
    duplicate_verified = deepcopy(verified)
    duplicate_verified["promotion_id"] = "rin-promotion-verified-02"
    with pytest.raises(KokoroError) as verified_error:
        publish_promotion_record(
            data_root,
            duplicate_verified,
            review,
            SCHEMAS,
        )
    assert verified_error.value.code == "PACK_PROMOTION_REVIEW_ID_CONFLICT"


def test_verified_record_requires_its_exact_reviewed_record_to_be_published(
    tmp_path: Path,
) -> None:
    reviewed, review = _reviewed_artifacts()
    verified = _verified_record(reviewed)

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(tmp_path / "data", verified, review, SCHEMAS)

    assert caught.value.code == "PACK_PROMOTION_PREVIOUS_NOT_PUBLISHED"
    assert not (tmp_path / "data" / "reports" / "promotions" / "rin-aster").exists()


def test_original_pack_may_become_a_public_candidate_only_when_verified(
    tmp_path: Path,
) -> None:
    reviewed, review = _reviewed_artifacts()
    verified = _verified_record(reviewed)
    verified["visibility"] = "public_candidate"
    data_root = tmp_path / "data"
    publish_promotion_record(data_root, reviewed, review, SCHEMAS)

    published = publish_promotion_record(data_root, verified, review, SCHEMAS)

    assert load_published_promotion_record(published, SCHEMAS)["visibility"] == (
        "public_candidate"
    )


def test_record_must_bind_the_exact_review_before_any_storage_is_created(
    tmp_path: Path,
) -> None:
    record, review = _reviewed_artifacts()
    record["review_attestation"]["sha256"] = "0" * 64
    data_root = tmp_path / "data"

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(data_root, record, review, SCHEMAS)

    assert caught.value.code == "PACK_PROMOTION_BINDING_MISMATCH"
    assert not data_root.exists()


@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        ("activation_allowed", True),
        ("visibility", "public_candidate"),
    ],
)
def test_storage_rejects_activation_before_verified_or_research_escalation(
    tmp_path: Path,
    mutation: str,
    value: Any,
) -> None:
    record, review = _reviewed_artifacts()
    if mutation == "visibility":
        record["mode"] = "researched"
        review["mode"] = "researched"
        record["namespace"] = "research"
        review["namespace"] = "research"
        record["artifact_id"] = "research/rin-aster/release/promotion-reviewed"
        review["artifact_id"] = "research/rin-aster/release/review"
        record["review_attestation"]["artifact_id"] = review["artifact_id"]
    record[mutation] = value
    record["review_attestation"]["sha256"] = _sha256(review)
    data_root = tmp_path / "data"

    with pytest.raises(KokoroError) as caught:
        publish_promotion_record(data_root, record, review, SCHEMAS)

    assert caught.value.code == "PACK_PROMOTION_RECORD_INVALID"
    assert not data_root.exists()


def test_loader_rejects_tampering_and_unknown_bundle_members(tmp_path: Path) -> None:
    record, review = _reviewed_artifacts()
    first = publish_promotion_record(tmp_path / "first", record, review, SCHEMAS)
    tampered = deepcopy(record)
    tampered["source_hash"] = "0" * 64
    first.write_bytes(canonical_bytes(tampered) + b"\n")

    with pytest.raises(KokoroError) as tamper_error:
        load_published_promotion_record(first, SCHEMAS)

    assert tamper_error.value.code == "PACK_PROMOTION_BUNDLE_INVALID"

    second = publish_promotion_record(tmp_path / "second", record, review, SCHEMAS)
    (second.parent / "unexpected.json").write_bytes(b"{}\n")

    with pytest.raises(KokoroError) as layout_error:
        load_published_promotion_record(second.parent, SCHEMAS)

    assert layout_error.value.code == "PACK_PROMOTION_BUNDLE_INVALID"
