"""Deterministic construction of private Research Bundles."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any, cast

from kokoroarc import __version__
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.research.workspace import ResearchWorkspace


_WORKSPACE_HASH_ID_PREFIX_LENGTH = 16
_ARTIFACT_ID_MAX_LENGTH = 128
_MAX_AGGREGATE_LIMITATIONS = 128


def canonical_hash(value: Any) -> str:
    """Return the SHA-256 digest of canonical JSON bytes for *value*."""
    return sha256(canonical_bytes(value)).hexdigest()


def build_research_bundle(
    workspace: ResearchWorkspace,
    report: dict[str, Any],
) -> dict[str, Any]:
    """Build byte-stable private bundle data without mutating validated inputs."""
    request = workspace.request
    request_hash = canonical_hash(request)
    report_hash = canonical_hash(report)
    sources = sorted(workspace.sources, key=lambda item: item["source_id"])
    claims = sorted(workspace.claims, key=lambda item: item["claim_id"])
    conflicts = sorted(workspace.conflicts, key=lambda item: item["conflict_id"])
    bundle = {
        "schema_version": "1.0",
        "artifact_id": _bundle_artifact_id(workspace),
        "created_by": {"component": "kokoroarc", "version": __version__},
        "namespace": request["namespace"],
        "character_id": request["character_id"],
        "display_name": request["display_name"],
        "continuity": request["continuity"],
        "timeline_cutoff": request["timeline_cutoff"],
        "spoiler_scope": request["spoiler_scope"],
        "request_hash": request_hash,
        "workspace_hash": workspace.workspace_hash,
        "validation_report_hash": report_hash,
        "sources": _canonical_clone(sources),
        "claims": _canonical_clone(claims),
        "conflicts": _canonical_clone(conflicts),
        "coverage": _canonical_clone(workspace.coverage),
        "limitations": aggregate_limitations(workspace),
        "blocking_reasons": _canonical_clone(report["blocking_reasons"]),
        "build_status": "research",
        "visibility": "private",
        "activation_allowed": False,
        "authoring_allowed": report["authoring_allowed"],
    }
    bundle["bundle_hash"] = canonical_hash(bundle)
    return bundle


def aggregate_limitations(workspace: ResearchWorkspace) -> list[str]:
    """Return a bounded summary; full details remain in embedded sources."""
    limitations = sorted(
        {
            limitation
            for source in workspace.sources
            for limitation in source["limitations"]
        }
    )
    return limitations[:_MAX_AGGREGATE_LIMITATIONS]


def _bundle_artifact_id(workspace: ResearchWorkspace) -> str:
    request = workspace.request
    readable = (
        f"{request['namespace']}/{request['character_id']}/research/"
        f"{workspace.workspace_hash[:_WORKSPACE_HASH_ID_PREFIX_LENGTH]}"
    )
    if len(readable) <= _ARTIFACT_ID_MAX_LENGTH:
        return readable
    return f"research/{sha256(readable.encode('utf-8')).hexdigest()}"


def _canonical_clone(value: Any) -> Any:
    return cast(Any, json.loads(canonical_bytes(value)))
