"""Deterministic metadata for private, inactive character drafts."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from kokoroarc import __version__
from kokoroarc.packs.compiler import canonical_bytes


_SOURCE_HASH_ID_PREFIX_LENGTH = 16


def build_character_draft(
    request: dict[str, Any],
    source: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    """Build byte-stable draft metadata without mutating its inputs.

    ``source_pack_hash`` is deliberately the hash of the canonical assembled
    source object, not a hash of the source directory's serialization.
    """
    request_hash = _canonical_hash(request)
    source_hash = _canonical_hash(source)
    report_hash = _canonical_hash(report)
    artifact_id = (
        f"{request['namespace']}/{request['character_id']}/draft/"
        f"{source_hash[:_SOURCE_HASH_ID_PREFIX_LENGTH]}"
    )
    return {
        "schema_version": "1.0",
        "artifact_id": artifact_id,
        "created_by": {"component": "kokoroarc", "version": __version__},
        "build_status": "draft",
        "visibility": "private",
        "activation_allowed": False,
        "mode": request["mode"],
        "namespace": request["namespace"],
        "character_id": request["character_id"],
        "display_name": request["display_name"],
        "character_version": request["character_version"],
        "request_hash": request_hash,
        "source_pack_hash": source_hash,
        "validation_report_hash": report_hash,
        "bundle_references": {
            "request": "request.json",
            "source_pack": "source-pack",
            "validation_report": "validation-report.json",
        },
        "locale_coverage": _canonical_clone(report["locale_coverage"]),
        "provenance_counts": _canonical_clone(report["provenance_counts"]),
        "unresolved_warnings": sorted(
            {
                finding["code"]
                for finding in report.get("advisory_findings", [])
            }
        ),
    }


def _canonical_hash(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _canonical_clone(value: Any) -> Any:
    return json.loads(canonical_bytes(value))
