from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import io
import json
from pathlib import Path
from typing import Any
import zipfile

import pytest

from kokoroarc.distribution.archive import build_karc_archive, load_karc_archive
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes, compile_pack
from kokoroarc.packs.loader import load_source_pack
from kokoroarc.schemas import SchemaRegistry
from kokoroarc.testing.publication import assess_publication_readiness


SCHEMAS = SchemaRegistry(Path("schemas/v1"))
RIN_PACK = Path("characters/original/rin-aster")
PRIVATE_PATHS = (
    "manifest.json",
    "pack/compiled.json",
    "release/hard-validation-report.json",
    "release/promotion-record.json",
    "release/review-attestation.json",
    "release/soft-evaluation-report.json",
)
PUBLIC_PATHS = (
    "manifest.json",
    "pack/compiled.json",
    "release/hard-validation-report.json",
    "release/promotion-record.json",
    "release/publication-readiness-report.json",
    "release/review-attestation.json",
    "release/soft-evaluation-report.json",
)


def _release_parts(release: dict[str, Any]) -> dict[str, Any]:
    evidence = release["evidence"]
    source = load_source_pack(RIN_PACK, SCHEMAS)
    return {
        "compiled_pack": compile_pack(source, SCHEMAS),
        "hard_validation_report": evidence["hard_report"],
        "soft_evaluation_report": evidence["soft_evaluation_report"],
        "review_attestation": evidence["review_attestation"],
        "promotion_record": release["promotion"],
        "schemas": SCHEMAS,
    }


def _compliance(promotion: dict[str, Any]) -> dict[str, Any]:
    return {
        "attestation_id": "rin-rights-review-01",
        "reviewer_id": "local-maintainer",
        "scope": "distribution_rights_reviewed",
        "conclusion": "approved",
        "source_hash": promotion["source_hash"],
        "compiled_hash": promotion["compiled_hash"],
        "basis_codes": ["ORIGINAL_AUTHORSHIP_CONFIRMED"],
    }


def _public_parts(release: dict[str, Any]) -> dict[str, Any]:
    parts = _release_parts(release)
    promotion = release["promotion"]
    publication = assess_publication_readiness(
        RIN_PACK,
        promotion,
        SCHEMAS,
        promotion_evidence=release["evidence"],
        requested_visibility="public_candidate",
        compliance_attestation=_compliance(promotion),
    )
    assert publication["ready_for_publication"]
    parts["publication_readiness_report"] = publication
    return parts


def _assert_code(code: str, function: Any, *args: Any, **kwargs: Any) -> None:
    with pytest.raises(KokoroError) as caught:
        function(*args, **kwargs)
    assert caught.value.code == code


def test_private_export_is_byte_identical_and_manifest_bound(
    rin_verified_release: dict[str, Any],
) -> None:
    parts = _release_parts(rin_verified_release)

    first = build_karc_archive(**parts)
    second = build_karc_archive(**parts)
    loaded = load_karc_archive(first, SCHEMAS)

    assert first == second
    assert tuple(loaded.documents) == PRIVATE_PATHS
    assert loaded.archive_sha256 == sha256(first).hexdigest()
    assert loaded.manifest["visibility"] == "private"
    assert loaded.manifest["promotion_status"] == "verified"
    assert loaded.manifest["activation_allowed"] is True
    assert loaded.manifest["trust"] == "unsigned_local"
    assert loaded.manifest["publication_readiness_report"] is None
    assert [member["path"] for member in loaded.manifest["members"]] == list(
        PRIVATE_PATHS[1:]
    )
    for member in loaded.manifest["members"]:
        payload = canonical_bytes(loaded.documents[member["path"]])
        assert member["size"] == len(payload)
        assert member["sha256"] == sha256(payload).hexdigest()


def test_public_export_requires_and_includes_ready_publication_report(
    rin_public_verified_release: dict[str, Any],
) -> None:
    parts = _public_parts(rin_public_verified_release)

    archive = build_karc_archive(**parts)
    loaded = load_karc_archive(archive, SCHEMAS)

    assert tuple(loaded.documents) == PUBLIC_PATHS
    assert loaded.manifest["visibility"] == "public_candidate"
    reference = loaded.manifest["publication_readiness_report"]
    report = loaded.documents["release/publication-readiness-report.json"]
    assert reference == {
        "artifact_id": report["artifact_id"],
        "sha256": sha256(canonical_bytes(report)).hexdigest(),
    }


def test_export_uses_fixed_lexicographic_stored_zip_metadata(
    rin_verified_release: dict[str, Any],
) -> None:
    archive = build_karc_archive(**_release_parts(rin_verified_release))

    with zipfile.ZipFile(io.BytesIO(archive), "r") as package:
        infos = package.infolist()

    assert [info.filename for info in infos] == list(PRIVATE_PATHS)
    for info in infos:
        assert info.date_time == (1980, 1, 1, 0, 0, 0)
        assert info.compress_type == zipfile.ZIP_STORED
        assert info.flag_bits == 0
        assert info.extra == b""
        assert info.comment == b""
        assert info.create_system == 3
        assert info.external_attr == 0o100644 << 16


def test_export_does_not_mutate_any_caller_input(
    rin_verified_release: dict[str, Any],
) -> None:
    parts = _release_parts(rin_verified_release)
    before = {
        name: canonical_bytes(value)
        for name, value in parts.items()
        if name != "schemas"
    }

    build_karc_archive(**parts)

    assert {
        name: canonical_bytes(value)
        for name, value in parts.items()
        if name != "schemas"
    } == before


def test_export_rejects_a_non_verified_promotion(
    rin_verified_release: dict[str, Any],
) -> None:
    parts = _release_parts(rin_verified_release)
    parts["promotion_record"] = rin_verified_release["evidence"][
        "previous_promotion"
    ]

    _assert_code("KARC_PROMOTION_NOT_VERIFIED", build_karc_archive, **parts)


@pytest.mark.parametrize(
    "part_name,path",
    [
        ("compiled_pack", ("artifact_id",)),
        ("hard_validation_report", ("source_hash",)),
        ("soft_evaluation_report", ("compiled_hash",)),
        ("review_attestation", ("source_hash",)),
        ("promotion_record", ("compiled_hash",)),
    ],
)
def test_export_rejects_stale_or_cross_release_artifacts(
    rin_verified_release: dict[str, Any],
    part_name: str,
    path: tuple[str, ...],
) -> None:
    parts = _release_parts(rin_verified_release)
    parts[part_name] = deepcopy(parts[part_name])
    field = path[0]
    parts[part_name][field] = (
        "original/rin-aster/compiled-stale"
        if field == "artifact_id"
        else "0" * 64
    )

    _assert_code("KARC_BINDING_MISMATCH", build_karc_archive, **parts)


def test_private_export_rejects_a_publication_report(
    rin_verified_release: dict[str, Any],
    rin_public_verified_release: dict[str, Any],
) -> None:
    parts = _release_parts(rin_verified_release)
    parts["publication_readiness_report"] = _public_parts(
        rin_public_verified_release
    )["publication_readiness_report"]

    _assert_code("KARC_PUBLICATION_UNEXPECTED", build_karc_archive, **parts)


def test_public_export_rejects_missing_or_blocked_publication_report(
    rin_public_verified_release: dict[str, Any],
) -> None:
    parts = _public_parts(rin_public_verified_release)
    without_report = {**parts}
    del without_report["publication_readiness_report"]
    blocked = deepcopy(parts)
    blocked["publication_readiness_report"]["ready_for_publication"] = False

    _assert_code("KARC_PUBLICATION_REQUIRED", build_karc_archive, **without_report)
    _assert_code("KARC_RELEASE_INVALID", build_karc_archive, **blocked)


class _MutatingRegistry:
    def __init__(self, target: dict[str, Any]) -> None:
        self._target = target
        self._mutated = False

    def validate(self, name: str, instance: Any) -> None:
        SCHEMAS.validate(name, instance)
        if not self._mutated:
            self._target["character_id"] = "mutated-character"
            self._mutated = True


def test_export_rejects_caller_mutation_during_schema_callbacks(
    rin_verified_release: dict[str, Any],
) -> None:
    parts = _release_parts(rin_verified_release)
    target = parts["compiled_pack"]
    parts["schemas"] = _MutatingRegistry(target)

    _assert_code("KARC_INPUT_MUTATION", build_karc_archive, **parts)


def test_archive_contains_only_the_closed_runtime_release_surface(
    rin_verified_release: dict[str, Any],
) -> None:
    archive = build_karc_archive(**_release_parts(rin_verified_release))
    loaded = load_karc_archive(archive, SCHEMAS)

    assert all(path.endswith(".json") for path in loaded.documents)
    assert not any(
        marker in path
        for path in loaded.documents
        for marker in ("source", "dossier", "research", "state", "memory")
    )
    assert not any(
        path.endswith((".yaml", ".yml", ".py", ".exe"))
        for path in loaded.documents
    )
