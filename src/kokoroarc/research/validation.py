"""Deterministic semantic validation for research evidence graphs."""

from __future__ import annotations

from hashlib import sha256
import json
from collections.abc import Mapping
from typing import Any
import unicodedata

from kokoroarc import __version__
from kokoroarc.research.workspace import ResearchWorkspace
from kokoroarc.schemas import SchemaRegistry


_MAX_FINDINGS = 256
_MAX_BLOCKING_REASONS = 128
_USABLE_SOURCE_AVAILABILITY = frozenset({"available", "partial", "archived"})
_DIRECT_SUPPORT = frozenset({"direct", "corroborated"})
_DERIVED_SUPPORT = frozenset({"indirect", "corroborated"})


def validate_research_workspace(
    workspace: ResearchWorkspace,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    """Return a deterministic, non-mutating cross-artifact validation report."""
    _validate_schemas(workspace, schemas)
    hard: list[dict[str, Any]] = []
    advisory: list[dict[str, Any]] = []
    blocking_reasons: set[str] = set()

    request = workspace.request
    sources = workspace.sources
    claims = workspace.claims
    conflicts = workspace.conflicts
    coverage = workspace.coverage
    character_id = request["character_id"]
    continuity = request["continuity"]
    timeline_cutoff = request["timeline_cutoff"]
    spoiler_scope = request["spoiler_scope"]

    _validate_artifact_identity(workspace, character_id, hard)
    source_by_id = _index_records(sources, "source_id", "sources", hard)
    claim_by_id = _index_records(claims, "claim_id", "claims", hard)
    _index_records(conflicts, "conflict_id", "conflicts", hard)

    for index, source in enumerate(sources):
        if source["continuity"] != continuity:
            hard.append(
                _finding(
                    "RESEARCH_CONTINUITY_MISMATCH",
                    ["sources", index, "continuity"],
                    "Source continuity does not match the requested continuity.",
                )
            )
        if source["spoiler_scope"] != spoiler_scope:
            hard.append(
                _finding(
                    "RESEARCH_SPOILER_SCOPE_VIOLATION",
                    ["sources", index, "spoiler_scope"],
                    "Source spoiler scope exceeds the requested scope.",
                )
            )

    request_assertions = {
        _normalize_assertion(value) for value in request["user_assertions"]
    }
    for index, claim in enumerate(claims):
        _validate_claim_scope(
            claim,
            index,
            character_id,
            continuity,
            timeline_cutoff,
            spoiler_scope,
            hard,
        )
        _validate_claim_provenance(
            claim,
            index,
            source_by_id,
            claim_by_id,
            request_assertions,
            hard,
        )

    _validate_derivation_graph(claims, claim_by_id, hard)
    _validate_conflicts(conflicts, claim_by_id, advisory, hard, blocking_reasons)
    coverage_summary = _validate_coverage(
        request,
        coverage,
        source_by_id,
        claim_by_id,
        advisory,
        hard,
        blocking_reasons,
    )

    hard = _bounded_findings(hard)
    advisory = _bounded_findings(advisory)
    has_blocking_reasons = bool(blocking_reasons)
    report = {
        "schema_version": "1.0",
        "artifact_id": _report_artifact_id(request),
        "created_by": {"component": "kokoroarc", "version": __version__},
        "hard_failures": hard,
        "advisory_findings": advisory,
        "coverage_summary": coverage_summary,
        "blocking_reasons": sorted(blocking_reasons)[:_MAX_BLOCKING_REASONS],
        "valid": not hard,
        "authoring_allowed": not hard and not has_blocking_reasons,
    }
    schemas.validate("research-validation-report", report)
    return report


def _validate_schemas(workspace: ResearchWorkspace, schemas: SchemaRegistry) -> None:
    schemas.validate("research-workspace", workspace.manifest)
    schemas.validate("research-request", workspace.request)
    for source in workspace.sources:
        schemas.validate("research-source-record", source)
    for claim in workspace.claims:
        schemas.validate("research-claim", claim)
    for conflict in workspace.conflicts:
        schemas.validate("research-conflict", conflict)
    schemas.validate("research-coverage", workspace.coverage)


def _validate_artifact_identity(
    workspace: ResearchWorkspace,
    character_id: str,
    findings: list[dict[str, Any]],
) -> None:
    prefix = f"research/{character_id}/"
    records: list[tuple[list[str | int], Mapping[str, Any]]] = [
        (["manifest"], workspace.manifest),
        (["request"], workspace.request),
        (["coverage"], workspace.coverage),
    ]
    records.extend(
        (["sources", index], item)
        for index, item in enumerate(workspace.sources)
    )
    records.extend(
        (["claims", index], item)
        for index, item in enumerate(workspace.claims)
    )
    records.extend(
        (["conflicts", index], item)
        for index, item in enumerate(workspace.conflicts)
    )
    for path, record in records:
        artifact_id = record["artifact_id"]
        if not artifact_id.startswith(prefix):
            findings.append(
                _finding(
                    "RESEARCH_IDENTITY_MISMATCH",
                    [*path, "artifact_id"],
                    "Artifact identity does not match the requested subject.",
                )
            )


def _index_records(
    records: tuple[dict[str, Any], ...],
    id_field: str,
    section: str,
    findings: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records):
        record_id = record[id_field]
        if record_id in indexed:
            findings.append(
                _finding(
                    "RESEARCH_DUPLICATE_ID",
                    [section, index, id_field],
                    f"Duplicate {section} identifier.",
                )
            )
        else:
            indexed[record_id] = record
    return indexed


def _validate_claim_scope(
    claim: Mapping[str, Any],
    index: int,
    character_id: str,
    continuity: str,
    timeline_cutoff: str,
    spoiler_scope: str,
    findings: list[dict[str, Any]],
) -> None:
    if claim["subject_id"] != character_id:
        findings.append(
            _finding(
                "RESEARCH_IDENTITY_MISMATCH",
                ["claims", index, "subject_id"],
                "Claim subject does not match the requested subject.",
            )
        )
    if claim["continuity"] != continuity:
        findings.append(
            _finding(
                "RESEARCH_CONTINUITY_MISMATCH",
                ["claims", index, "continuity"],
                "Claim continuity does not match the requested continuity.",
            )
        )
    if not _timeline_contained(claim["timeline"], timeline_cutoff):
        findings.append(
            _finding(
                "RESEARCH_TIMELINE_VIOLATION",
                ["claims", index, "timeline"],
                "Claim timeline exceeds the requested cutoff.",
            )
        )
    if claim["spoiler_scope"] != spoiler_scope:
        findings.append(
            _finding(
                "RESEARCH_SPOILER_SCOPE_VIOLATION",
                ["claims", index, "spoiler_scope"],
                "Claim spoiler scope exceeds the requested scope.",
            )
        )


def _validate_claim_provenance(
    claim: Mapping[str, Any],
    index: int,
    source_by_id: Mapping[str, Mapping[str, Any]],
    claim_by_id: Mapping[str, Mapping[str, Any]],
    request_assertions: set[str],
    findings: list[dict[str, Any]],
) -> None:
    source_ids = claim["source_ids"]
    supporting_ids = claim["supporting_claim_ids"]
    for source_id in source_ids:
        if source_id not in source_by_id:
            findings.append(
                _finding(
                    "RESEARCH_DANGLING_REFERENCE",
                    ["claims", index, "source_ids"],
                    "Claim references an unknown source.",
                )
            )
    for supporting_id in supporting_ids:
        if supporting_id not in claim_by_id:
            findings.append(
                _finding(
                    "RESEARCH_DANGLING_REFERENCE",
                    ["claims", index, "supporting_claim_ids"],
                    "Claim references an unknown supporting claim.",
                )
            )

    classification = claim["classification"]
    if classification in {"direct_fact", "direct_observation"}:
        usable_sources = [
            source_by_id[source_id]
            for source_id in source_ids
            if source_id in source_by_id
            and source_by_id[source_id]["availability"]
            in _USABLE_SOURCE_AVAILABILITY
        ]
        if claim["support"] not in _DIRECT_SUPPORT or not usable_sources:
            findings.append(
                _finding(
                    "RESEARCH_SOURCE_SUPPORT_REQUIRED",
                    ["claims", index, "source_ids"],
                    "Direct claim requires usable source support.",
                )
            )
        if any(source["category"] == "user_supplied" for source in usable_sources):
            findings.append(
                _finding(
                    "RESEARCH_USER_ASSERTION_RELABELLED",
                    ["claims", index, "classification"],
                    "User-supplied evidence cannot be relabelled as direct canon.",
                )
            )
    elif classification == "derived_interpretation":
        supports_are_usable = bool(supporting_ids) and all(
            supporting_id in claim_by_id
            and claim_by_id[supporting_id]["support"] != "unsupported"
            and claim_by_id[supporting_id]["classification"] != "user_assertion"
            for supporting_id in supporting_ids
        )
        if (
            claim["support"] not in _DERIVED_SUPPORT
            or not supports_are_usable
            or source_ids
            or not claim.get("derivation_rationale")
        ):
            findings.append(
                _finding(
                    "RESEARCH_DERIVATION_REQUIRED",
                    ["claims", index, "supporting_claim_ids"],
                    "Derived claim requires supported claims and a rationale.",
                )
            )
    elif supporting_ids:
        findings.append(
            _finding(
                "RESEARCH_USER_ASSERTION_RELABELLED",
                ["claims", index, "supporting_claim_ids"],
                "User assertion cannot be presented as derived evidence.",
            )
        )

    normalized_statement = _normalize_assertion(claim["statement"])
    if (
        normalized_statement in request_assertions
        and classification != "user_assertion"
    ):
        findings.append(
            _finding(
                "RESEARCH_USER_ASSERTION_RELABELLED",
                ["claims", index, "classification"],
                "User assertion cannot be relabelled as external evidence.",
            )
        )
    measurement = claim.get("measurement")
    if isinstance(measurement, Mapping) and measurement.get("kind") == "normalized_trait":
        findings.append(
            _finding(
                "RESEARCH_CANONICAL_TRAIT_SCORE_PROHIBITED",
                ["claims", index, "measurement", "kind"],
                "Normalized trait scores are derived authoring data, not canon.",
            )
        )


def _validate_derivation_graph(
    claims: tuple[dict[str, Any], ...],
    claim_by_id: Mapping[str, Mapping[str, Any]],
    findings: list[dict[str, Any]],
) -> None:
    index_by_id = {
        claim["claim_id"]: index
        for index, claim in enumerate(claims)
        if claim["claim_id"] in claim_by_id
    }
    edges = {
        claim_id: tuple(
            sorted(
                supporting_id
                for supporting_id in claim["supporting_claim_ids"]
                if supporting_id in claim_by_id
            )
        )
        for claim_id, claim in claim_by_id.items()
    }
    state: dict[str, int] = {}
    cycles: set[tuple[str, ...]] = set()

    for start_id in sorted(edges):
        if state.get(start_id, 0) != 0:
            continue
        state[start_id] = 1
        path = [start_id]
        positions = {start_id: 0}
        frames: list[tuple[str, int]] = [(start_id, 0)]
        while frames:
            claim_id, edge_index = frames[-1]
            if edge_index == len(edges[claim_id]):
                frames.pop()
                state[claim_id] = 2
                positions.pop(claim_id)
                path.pop()
                continue
            supporting_id = edges[claim_id][edge_index]
            frames[-1] = (claim_id, edge_index + 1)
            supporting_state = state.get(supporting_id, 0)
            if supporting_state == 0:
                state[supporting_id] = 1
                positions[supporting_id] = len(path)
                path.append(supporting_id)
                frames.append((supporting_id, 0))
            elif supporting_state == 1:
                cycle_start = positions[supporting_id]
                cycles.add(tuple(sorted(path[cycle_start:])))
    for cycle in sorted(cycles):
        findings.append(
            _finding(
                "RESEARCH_CIRCULAR_DERIVATION",
                ["claims", index_by_id[cycle[0]], "supporting_claim_ids"],
                "Claim derivation graph contains a cycle.",
            )
        )


def _validate_conflicts(
    conflicts: tuple[dict[str, Any], ...],
    claim_by_id: Mapping[str, Mapping[str, Any]],
    advisory: list[dict[str, Any]],
    hard: list[dict[str, Any]],
    blocking_reasons: set[str],
) -> None:
    for index, conflict in enumerate(conflicts):
        claim_ids = conflict["claim_ids"]
        for field in ("claim_ids", "selected_claim_ids"):
            for claim_id in conflict[field]:
                if claim_id not in claim_by_id or (
                    field == "selected_claim_ids" and claim_id not in claim_ids
                ):
                    hard.append(
                        _finding(
                            "RESEARCH_DANGLING_REFERENCE",
                            ["conflicts", index, field],
                            "Conflict references an unknown or unrelated claim.",
                        )
                    )
        if conflict["status"] == "unresolved":
            advisory.append(
                _finding(
                    "RESEARCH_CONFLICT_BLOCKING",
                    ["conflicts", index, "status"],
                    "Unresolved conflict blocks downstream authoring.",
                )
            )
            blocking_reasons.add(
                "Unresolved conflict blocks authoring: "
                f"{conflict['conflict_id']}."
            )
        elif conflict["status"] == "scope_separated":
            referenced = [
                claim_by_id[claim_id]
                for claim_id in claim_ids
                if claim_id in claim_by_id
            ]
            expected_scopes = {
                f"{claim['continuity']}@{claim['timeline']}" for claim in referenced
            }
            if len(expected_scopes) < 2 or set(conflict["scopes"]) != expected_scopes:
                hard.append(
                    _finding(
                        "RESEARCH_CONTINUITY_MISMATCH",
                        ["conflicts", index, "scopes"],
                        "Scope-separated conflict does not match distinct claim scopes.",
                    )
                )


def _validate_coverage(
    request: Mapping[str, Any],
    coverage: Mapping[str, Any],
    source_by_id: Mapping[str, Mapping[str, Any]],
    claim_by_id: Mapping[str, Mapping[str, Any]],
    advisory: list[dict[str, Any]],
    hard: list[dict[str, Any]],
    blocking_reasons: set[str],
) -> dict[str, int]:
    summary = {"covered": 0, "partial": 0, "missing": 0, "blocked": 0}
    topic_ids: set[str] = set()
    unavailable_accounted: set[str] = set()
    topic_blocks = False
    for index, topic in enumerate(coverage["topics"]):
        topic_id = topic["topic_id"]
        status = topic["status"]
        summary[status] += 1
        if topic_id in topic_ids:
            hard.append(
                _finding(
                    "RESEARCH_DUPLICATE_ID",
                    ["coverage", "topics", index, "topic_id"],
                    "Duplicate coverage topic identifier.",
                )
            )
        topic_ids.add(topic_id)
        topic_blocks = topic_blocks or topic["blocks_authoring"]
        unavailable_accounted.update(topic["unavailable_sources"])

        supported_claims = []
        for claim_id in topic["supporting_claim_ids"]:
            claim = claim_by_id.get(claim_id)
            if claim is None:
                hard.append(
                    _finding(
                        "RESEARCH_DANGLING_REFERENCE",
                        ["coverage", "topics", index, "supporting_claim_ids"],
                        "Coverage topic references an unknown claim.",
                    )
                )
            elif claim["support"] != "unsupported" and claim["classification"] != "user_assertion":
                supported_claims.append(claim)
        for source_id in topic["unavailable_sources"]:
            source = source_by_id.get(source_id)
            if source is None:
                hard.append(
                    _finding(
                        "RESEARCH_DANGLING_REFERENCE",
                        ["coverage", "topics", index, "unavailable_sources"],
                        "Coverage topic references an unknown unavailable source.",
                    )
                )
            elif source["availability"] not in {"unavailable", "partial"}:
                hard.append(
                    _finding(
                        "RESEARCH_COVERAGE_INCOMPLETE",
                        ["coverage", "topics", index, "unavailable_sources"],
                        "Coverage marks an available source as unavailable.",
                    )
                )

        limitations = (
            topic["missing_evidence"]
            or topic["unavailable_sources"]
            or topic["spoiler_restrictions"]
        )
        inconsistent = (
            (status == "covered" and (not supported_claims or limitations))
            or (status != "covered" and not limitations)
            or (status == "covered" and topic["blocks_authoring"])
        )
        if inconsistent:
            hard.append(
                _finding(
                    "RESEARCH_COVERAGE_INCOMPLETE",
                    ["coverage", "topics", index],
                    "Coverage status does not match its evidence accounting.",
                )
            )
        if status != "covered":
            advisory.append(
                _finding(
                    "RESEARCH_COVERAGE_INCOMPLETE",
                    ["coverage", "topics", index, "status"],
                    "Required coverage topic is incomplete.",
                )
            )
        if topic["blocks_authoring"]:
            blocking_reasons.add(
                f"Required coverage topic blocks authoring: {topic_id}."
            )

    requested_topics = set(request["required_coverage_topics"])
    if topic_ids != requested_topics:
        hard.append(
            _finding(
                "RESEARCH_COVERAGE_INCOMPLETE",
                ["coverage", "topics"],
                "Coverage topics do not exactly account for the request.",
            )
        )
    if coverage["blocks_authoring"] is not topic_blocks:
        hard.append(
            _finding(
                "RESEARCH_COVERAGE_INCOMPLETE",
                ["coverage", "blocks_authoring"],
                "Aggregate authoring block does not match its topics.",
            )
        )
    expected_unavailable = {
        source_id
        for source_id, source in source_by_id.items()
        if source["availability"] == "unavailable"
    }
    if not expected_unavailable.issubset(unavailable_accounted):
        hard.append(
            _finding(
                "RESEARCH_COVERAGE_INCOMPLETE",
                ["coverage", "topics"],
                "Unavailable sources are not retained in coverage limitations.",
            )
        )
    for source_id in sorted(expected_unavailable):
        if not source_by_id[source_id]["limitations"]:
            hard.append(
                _finding(
                    "RESEARCH_COVERAGE_INCOMPLETE",
                    ["sources", source_id, "limitations"],
                    "Unavailable source requires a retained limitation.",
                )
            )
    return summary


def _timeline_contained(value: str, cutoff: str) -> bool:
    return value == cutoff or value.startswith(f"{cutoff}-")


def _normalize_assertion(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _report_artifact_id(request: Mapping[str, Any]) -> str:
    request_id = request["artifact_id"]
    prefix, leaf = request_id.rsplit("/", 1)
    if leaf == "request":
        candidate = f"{prefix}/validation"
    elif leaf.endswith("-request"):
        candidate = f"{prefix}/{leaf[:-8]}-validation"
    else:
        candidate = f"{prefix}/validation-{leaf}"
    if len(candidate) <= 128:
        return candidate
    digest = sha256(request_id.encode("utf-8")).hexdigest()
    return f"research-validation/{digest}"


def _finding(code: str, path: list[str | int], message: str) -> dict[str, Any]:
    return {"code": code, "path": path, "message": message}


def _finding_key(item: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(item["code"]),
        json.dumps(item["path"], ensure_ascii=False, separators=(",", ":")),
        str(item["message"]),
    )


def _bounded_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = {_finding_key(item): item for item in findings}
    return [unique[key] for key in sorted(unique)[:_MAX_FINDINGS]]
