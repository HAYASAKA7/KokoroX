from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import io
import json
from pathlib import Path
import stat
from typing import Any, Callable
import zipfile

from kokoroarc.distribution.archive import build_karc_archive
from kokoroarc.packs.compiler import canonical_bytes, compile_pack
from kokoroarc.packs.loader import load_source_pack
from kokoroarc.schemas import SchemaRegistry
from kokoroarc.testing.publication import assess_publication_readiness


SCHEMAS = SchemaRegistry(Path("schemas/v1"))
RIN_PACK = Path("characters/original/rin-aster")
COMPILED_PATH = "pack/compiled.json"
HARD_PATH = "release/hard-validation-report.json"
PROMOTION_PATH = "release/promotion-record.json"
PUBLICATION_PATH = "release/publication-readiness-report.json"
REVIEW_PATH = "release/review-attestation.json"
SOFT_PATH = "release/soft-evaluation-report.json"
ROLE_BY_PATH = {
    COMPILED_PATH: "compiled_pack",
    HARD_PATH: "hard_validation_report",
    PROMOTION_PATH: "promotion_record",
    PUBLICATION_PATH: "publication_readiness_report",
    REVIEW_PATH: "review_attestation",
    SOFT_PATH: "soft_evaluation_report",
}


def digest(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def reference(value: dict[str, Any]) -> dict[str, str]:
    return {"artifact_id": value["artifact_id"], "sha256": digest(value)}


def build_private_archive(release: dict[str, Any]) -> bytes:
    evidence = release["evidence"]
    compiled = compile_pack(load_source_pack(RIN_PACK, SCHEMAS), SCHEMAS)
    return build_karc_archive(
        compiled_pack=compiled,
        hard_validation_report=evidence["hard_report"],
        soft_evaluation_report=evidence["soft_evaluation_report"],
        review_attestation=evidence["review_attestation"],
        promotion_record=release["promotion"],
        schemas=SCHEMAS,
    )


def build_public_archive(release: dict[str, Any]) -> bytes:
    evidence = release["evidence"]
    promotion = release["promotion"]
    compiled = compile_pack(load_source_pack(RIN_PACK, SCHEMAS), SCHEMAS)
    compliance = {
        "attestation_id": "rin-rights-review-01",
        "reviewer_id": "local-maintainer",
        "scope": "distribution_rights_reviewed",
        "conclusion": "approved",
        "source_hash": promotion["source_hash"],
        "compiled_hash": promotion["compiled_hash"],
        "basis_codes": ["ORIGINAL_AUTHORSHIP_CONFIRMED"],
    }
    publication = assess_publication_readiness(
        RIN_PACK,
        promotion,
        SCHEMAS,
        promotion_evidence=evidence,
        requested_visibility="public_candidate",
        compliance_attestation=compliance,
    )
    assert publication["ready_for_publication"] is True
    return build_karc_archive(
        compiled_pack=compiled,
        hard_validation_report=evidence["hard_report"],
        soft_evaluation_report=evidence["soft_evaluation_report"],
        review_attestation=evidence["review_attestation"],
        promotion_record=promotion,
        publication_readiness_report=publication,
        schemas=SCHEMAS,
    )


def archive_documents(archive: bytes) -> dict[str, dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(archive), "r") as package:
        return {
            info.filename: json.loads(package.read(info))
            for info in package.infolist()
        }


def write_archive_documents(documents: dict[str, dict[str, Any]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_STORED,
        allowZip64=False,
    ) as package:
        for path in sorted(documents):
            info = zipfile.ZipInfo(path, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.create_version = 20
            info.extract_version = 20
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            package.writestr(info, canonical_bytes(documents[path]))
    return output.getvalue()


def rewrite_archive(
    archive: bytes,
    mutate: Callable[[dict[str, dict[str, Any]]], None],
) -> bytes:
    documents = archive_documents(archive)
    mutate(documents)
    return write_archive_documents(documents)


def reversion_archive(
    archive: bytes,
    *,
    format_version: str,
    document_schema_version: str,
    schema_version: str,
    schema_maximum: str,
) -> bytes:
    documents = deepcopy(archive_documents(archive))
    manifest = documents.pop("manifest.json")
    compiled = documents[COMPILED_PATH]
    hard = documents[HARD_PATH]
    promotion = documents[PROMOTION_PATH]
    review = documents[REVIEW_PATH]
    soft = documents[SOFT_PATH]
    publication = documents.get(PUBLICATION_PATH)

    for document in documents.values():
        document["schema_version"] = document_schema_version

    compiled_hash = digest(compiled)
    for document in (hard, promotion, soft):
        document["compiled_hash"] = compiled_hash
    if publication is not None:
        publication["compiled_hash"] = compiled_hash

    hard_reference = reference(hard)
    review["hard_report"] = hard_reference
    promotion["hard_report"] = hard_reference
    promotion["review_attestation"] = reference(review)
    promotion["soft_evaluation_report"] = reference(soft)
    if publication is not None:
        publication["promotion"] = reference(promotion)

    manifest["format_version"] = format_version
    manifest["archive_id"] = (
        f"{manifest['namespace']}.{manifest['character_id']}.{compiled_hash[:16]}"
    )
    manifest["compiled_hash"] = compiled_hash
    manifest["hard_validation_report"] = reference(hard)
    manifest["soft_evaluation_report"] = reference(soft)
    manifest["review_attestation"] = reference(review)
    manifest["promotion_record"] = reference(promotion)
    manifest["publication_readiness_report"] = (
        reference(publication) if publication is not None else None
    )
    ranges = manifest["compatibility"]["schemas"]
    for name, version_range in ranges.items():
        if version_range is not None:
            ranges[name] = {
                "minimum_inclusive": schema_version,
                "maximum_exclusive": schema_maximum,
            }
    payloads = {path: canonical_bytes(value) for path, value in documents.items()}
    manifest["members"] = [
        {
            "path": path,
            "role": ROLE_BY_PATH[path],
            "size": len(payloads[path]),
            "sha256": sha256(payloads[path]).hexdigest(),
        }
        for path in sorted(documents)
    ]
    return write_archive_documents({"manifest.json": manifest, **documents})


def make_legacy_090_archive(current: bytes) -> bytes:
    return reversion_archive(
        current,
        format_version="0.9.0",
        document_schema_version="0.9",
        schema_version="0.9.0",
        schema_maximum="1.0.0",
    )


def make_newer_200_archive(current: bytes) -> bytes:
    def mutate(documents: dict[str, dict[str, Any]]) -> None:
        documents["manifest.json"]["format_version"] = "2.0.0"

    return rewrite_archive(current, mutate)


def add_archive_code(current: bytes) -> bytes:
    documents = archive_documents(current)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", allowZip64=False) as package:
        for path in sorted([*documents, "migration.py"]):
            info = zipfile.ZipInfo(path, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.create_version = 20
            info.extract_version = 20
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            payload = (
                b"raise RuntimeError('must never execute')"
                if path == "migration.py"
                else canonical_bytes(documents[path])
            )
            package.writestr(info, payload)
    return output.getvalue()
