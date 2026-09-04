from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.research import build_research_bundle
from kokoroarc.research.bundles import canonical_hash
from kokoroarc.research.validation import validate_research_workspace
from kokoroarc.research.workspace import ResearchWorkspace, load_research_workspace
from kokoroarc.schemas import SchemaRegistry


SCHEMAS = SchemaRegistry(Path("schemas/v1"))


def loaded(tree: str = "complete") -> ResearchWorkspace:
    return load_research_workspace(Path("tests/fixtures/research") / tree, SCHEMAS)


def report_for(workspace: ResearchWorkspace) -> dict[str, Any]:
    return validate_research_workspace(workspace, SCHEMAS)


def test_build_research_bundle_is_byte_stable_and_non_mutating() -> None:
    workspace = loaded()
    report = report_for(workspace)
    report_before = deepcopy(report)
    workspace_before = canonical_bytes(
        {
            "request": workspace.request,
            "sources": list(workspace.sources),
            "claims": list(workspace.claims),
            "conflicts": list(workspace.conflicts),
            "coverage": workspace.coverage,
        }
    )

    first = build_research_bundle(workspace, report)
    second = build_research_bundle(workspace, report)

    assert canonical_bytes(first) == canonical_bytes(second)
    assert first["build_status"] == "research"
    assert first["visibility"] == "private"
    assert first["activation_allowed"] is False
    assert first["authoring_allowed"] is True
    assert first["workspace_hash"] == workspace.workspace_hash
    assert first["request_hash"] == canonical_hash(workspace.request)
    assert (
        first["request_hash"]
        == "ce2816fe46ddd45950a939d6286d148ea4cab94218ec65df62daa361d4307fec"
    )
    assert first["validation_report_hash"] == canonical_hash(report)
    assert (
        first["validation_report_hash"]
        == "e7c93e4131ece711232525fd01f39213bc4499cda00caf35edc1e4a8202bd3f1"
    )
    assert report == report_before
    assert workspace_before == canonical_bytes(
        {
            "request": workspace.request,
            "sources": list(workspace.sources),
            "claims": list(workspace.claims),
            "conflicts": list(workspace.conflicts),
            "coverage": workspace.coverage,
        }
    )
    SCHEMAS.validate("research-bundle", first)


def test_bundle_hash_covers_every_member_except_itself() -> None:
    workspace = loaded()
    bundle = build_research_bundle(workspace, report_for(workspace))

    unhashed = deepcopy(bundle)
    actual_hash = unhashed.pop("bundle_hash")

    assert actual_hash == canonical_hash(unhashed)
    changed = deepcopy(unhashed)
    changed["display_name"] = "Changed display name"
    assert canonical_hash(changed) != actual_hash


def test_semantic_record_order_is_independent_of_workspace_tuple_order() -> None:
    workspace = loaded()
    report = report_for(workspace)
    manifest = deepcopy(workspace.manifest)
    manifest["sources"] = list(reversed(manifest["sources"]))
    manifest["claims"] = list(reversed(manifest["claims"]))
    shuffled = replace(
        workspace,
        manifest=manifest,
        sources=tuple(reversed(workspace.sources)),
        claims=tuple(reversed(workspace.claims)),
        conflicts=tuple(reversed(workspace.conflicts)),
    )

    assert canonical_bytes(build_research_bundle(shuffled, report)) == canonical_bytes(
        build_research_bundle(workspace, report)
    )


def test_research_question_order_changes_request_workspace_and_bundle_hashes() -> None:
    workspace = loaded()
    report = report_for(workspace)
    request = deepcopy(workspace.request)
    request["research_questions"] = list(reversed(request["research_questions"]))
    assembled = {
        "request": request,
        "sources": list(workspace.sources),
        "claims": list(workspace.claims),
        "conflicts": list(workspace.conflicts),
        "coverage": workspace.coverage,
    }
    reordered = replace(
        workspace,
        request=request,
        workspace_hash=canonical_hash(assembled),
    )

    original = build_research_bundle(workspace, report)
    changed = build_research_bundle(reordered, report)

    assert original["request_hash"] != changed["request_hash"]
    assert original["workspace_hash"] != changed["workspace_hash"]
    assert original["bundle_hash"] != changed["bundle_hash"]


def test_partial_bundle_retains_conflicts_limitations_coverage_and_blocks() -> None:
    workspace = loaded("partial")
    report = report_for(workspace)

    bundle = build_research_bundle(workspace, report)

    assert bundle["authoring_allowed"] is False
    assert bundle["activation_allowed"] is False
    assert bundle["conflicts"] == list(workspace.conflicts)
    assert bundle["coverage"] == workspace.coverage
    assert bundle["limitations"] == [
        "The requested historical appendix is unavailable."
    ]
    assert bundle["blocking_reasons"] == report["blocking_reasons"]
    assert bundle["sources"][0]["availability"] == "unavailable"
    SCHEMAS.validate("research-bundle", bundle)


def test_mutating_returned_bundle_does_not_mutate_workspace_or_report() -> None:
    workspace = loaded("partial")
    report = report_for(workspace)
    report_before = deepcopy(report)
    source_before = deepcopy(workspace.sources[0])
    coverage_before = deepcopy(workspace.coverage)

    bundle = build_research_bundle(workspace, report)
    bundle["sources"][0]["limitations"].append("Changed")
    bundle["coverage"]["topics"][0]["missing_evidence"].append("Changed")
    bundle["blocking_reasons"].append("Changed")

    assert workspace.sources[0] == source_before
    assert workspace.coverage == coverage_before
    assert report == report_before


def test_long_readable_artifact_identity_uses_hashed_fallback() -> None:
    workspace = loaded()
    request = deepcopy(workspace.request)
    request["character_id"] = "a" * 128
    long_identity = replace(workspace, request=request)

    bundle = build_research_bundle(long_identity, report_for(workspace))

    assert bundle["artifact_id"].startswith("research/")
    assert len(bundle["artifact_id"]) == len("research/") + 64
    assert "a" * 128 not in bundle["artifact_id"]
    SCHEMAS.validate("research-bundle", bundle)


def test_bundle_accepts_full_request_spoiler_scope_bound() -> None:
    workspace = loaded()
    scope = "s" * 512
    request = deepcopy(workspace.request)
    request["spoiler_scope"] = scope
    sources = tuple(deepcopy(list(workspace.sources)))
    claims = tuple(deepcopy(list(workspace.claims)))
    for source in sources:
        source["spoiler_scope"] = scope
    for claim in claims:
        claim["spoiler_scope"] = scope
    scoped = replace(workspace, request=request, sources=sources, claims=claims)
    report = validate_research_workspace(scoped, SCHEMAS)

    bundle = build_research_bundle(scoped, report)

    assert bundle["spoiler_scope"] == scope
    SCHEMAS.validate("research-bundle", bundle)


def test_bundle_rejects_spoiler_scope_above_request_bound() -> None:
    workspace = loaded()
    bundle = build_research_bundle(workspace, report_for(workspace))
    bundle["spoiler_scope"] = "s" * 513

    with pytest.raises(KokoroError):
        SCHEMAS.validate("research-bundle", bundle)


def test_aggregate_limitations_is_bounded_without_losing_source_details() -> None:
    workspace = loaded()
    sources = deepcopy(list(workspace.sources))
    third = deepcopy(sources[0])
    third["source_id"] = "source-tertiary"
    sources.append(third)
    for source_index, source in enumerate(sources):
        source["limitations"] = [
            f"limitation-{source_index:02d}-{item_index:02d}"
            for item_index in range(64)
        ]
    expanded = replace(workspace, sources=tuple(sources))

    bundle = build_research_bundle(expanded, report_for(workspace))

    assert len(bundle["limitations"]) == 128
    assert bundle["limitations"] == sorted(bundle["limitations"])
    assert all(len(source["limitations"]) == 64 for source in bundle["sources"])
    SCHEMAS.validate("research-bundle", bundle)
