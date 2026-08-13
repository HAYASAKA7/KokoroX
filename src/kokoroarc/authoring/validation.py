"""Cross-artifact validation for character-pack authoring."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping
from typing import Any

from kokoroarc import __version__
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry


_FIRST_CLASS_LOCALES = ("zh-CN", "en-US", "ja-JP")
_ORIGINAL_CLAIM_SOURCES = frozenset({"creative_brief", "user_override"})
_DOSSIER_CLAIM_SOURCES = frozenset(
    {"user_dossier", "creative_brief", "user_override"}
)
_MAX_FINDINGS = 256


def validate_authoring_pack(
    request: dict[str, Any],
    source: dict[str, Any],
    schemas: SchemaRegistry,
    *,
    research_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a deterministic cross-artifact authoring validation report."""
    hard_failures: list[dict[str, Any]] = []
    advisory_findings: list[dict[str, Any]] = []

    if source.get("character_id") != request.get("character_id"):
        hard_failures.append(
            _finding(
                "AUTHORING_IDENTITY_MISMATCH",
                ["character_id"],
                "Source character ID does not match the build request.",
            )
        )
    if source.get("character_version") != request.get("character_version"):
        hard_failures.append(
            _finding(
                "AUTHORING_VERSION_MISMATCH",
                ["character_version"],
                "Source character version does not match the build request.",
            )
        )
    if source.get("namespace") != request.get("namespace"):
        hard_failures.append(
            _finding(
                "AUTHORING_NAMESPACE_MISMATCH",
                ["namespace"],
                "Source namespace does not match the build request.",
            )
        )
    identity_value = source.get("identity")
    identity = identity_value if isinstance(identity_value, Mapping) else {}
    if identity.get("display_name") != request.get("display_name"):
        hard_failures.append(
            _finding(
                "AUTHORING_DISPLAY_NAME_MISMATCH",
                ["identity", "display_name"],
                "Source display name does not match the build request.",
            )
        )

    evidence = source.get("evidence")
    evidence_map = evidence if isinstance(evidence, Mapping) else {}
    claims_value = evidence_map.get("claims")
    claims = claims_value if isinstance(claims_value, list) else []

    mode = request.get("mode")
    if mode == "original":
        _validate_original_provenance(evidence_map, claims, hard_failures)
    elif mode == "dossier":
        _validate_dossier_provenance(
            request, source, evidence_map, claims, hard_failures
        )
    elif mode in {"researched", "hybrid"}:
        _validate_research_provenance(
            request,
            evidence_map,
            claims,
            research_bundle,
            schemas,
            hard_failures,
        )
    else:
        hard_failures.append(
            _finding(
                "AUTHORING_MODE_UNSUPPORTED",
                ["mode"],
                "Construction mode is not available in this milestone.",
            )
        )

    locales_value = source.get("locales")
    locales = locales_value if isinstance(locales_value, Mapping) else {}
    expressions_value = source.get("expressions")
    expressions = (
        expressions_value if isinstance(expressions_value, Mapping) else {}
    )
    locale_coverage = {
        locale: locale in locales
        and bool(expressions)
        and all(
            isinstance(locale_set, Mapping) and locale in locale_set
            for locale_set in expressions.values()
        )
        for locale in _FIRST_CLASS_LOCALES
    }
    for locale, covered in locale_coverage.items():
        if not covered:
            path = (
                ["locales", locale]
                if locale not in locales
                else ["expressions", locale]
            )
            hard_failures.append(
                _finding(
                    "AUTHORING_LOCALE_MISSING",
                    path,
                    f"Source pack does not provide the {locale} locale.",
                )
            )

    if len(expressions) < 2:
        advisory_findings.append(
            _finding(
                "AUTHORING_SPARSE_EXAMPLES",
                ["expressions"],
                "More expression examples would improve coverage.",
            )
        )

    hard_failures.sort(key=_finding_sort_key)
    advisory_findings.sort(key=_finding_sort_key)
    hard_failures = hard_failures[:_MAX_FINDINGS]
    advisory_findings = advisory_findings[:_MAX_FINDINGS]
    report = {
        "schema_version": "1.0",
        "artifact_id": _report_artifact_id(request),
        "created_by": {"component": "kokoroarc", "version": __version__},
        "hard_failures": hard_failures,
        "advisory_findings": advisory_findings,
        "locale_coverage": locale_coverage,
        "provenance_counts": {
            "evidence": len(claims),
            "derived_profile": _mapping_count(
                source.get("derived_profile"), "traits"
            ),
            "user_override": _mapping_count(source.get("overrides"), "values"),
        },
        "valid": not hard_failures,
    }
    schemas.validate("build-validation-report", report)
    return report


def _validate_research_provenance(
    request: Mapping[str, Any],
    evidence: Mapping[str, Any],
    claims: list[Any],
    bundle: dict[str, Any] | None,
    schemas: SchemaRegistry,
    findings: list[dict[str, Any]],
) -> None:
    if bundle is None:
        findings.append(
            _finding(
                "RESEARCH_BUNDLE_REQUIRED",
                ["inputs"],
                "An eligible Research Bundle is required for this authoring mode.",
            )
        )
        return
    try:
        schemas.validate("research-bundle", bundle)
    except KokoroError:
        findings.append(
            _finding(
                "RESEARCH_BUNDLE_INVALID",
                ["inputs"],
                "The Research Bundle is invalid.",
            )
        )
        return
    unhashed = dict(bundle)
    bundle_hash = unhashed.pop("bundle_hash")
    if hashlib.sha256(canonical_bytes(unhashed)).hexdigest() != bundle_hash:
        findings.append(
            _finding(
                "RESEARCH_BUNDLE_INVALID",
                ["inputs", "research_bundle", "sha256"],
                "The Research Bundle hash is invalid.",
            )
        )
        return

    bindings = [
        item
        for item in _mapping_items(request.get("inputs"))
        if item.get("type") == "research_bundle"
    ]
    if len(bindings) != 1:
        findings.append(
            _finding(
                "RESEARCH_BUNDLE_REQUIRED",
                ["inputs"],
                "Exactly one Research Bundle binding is required.",
            )
        )
    else:
        binding = bindings[0]
        if binding.get("artifact_id") != bundle.get("artifact_id"):
            findings.append(
                _finding(
                    "RESEARCH_BUNDLE_IDENTITY_MISMATCH",
                    ["inputs", "research_bundle", "artifact_id"],
                    "Research Bundle identity does not match the request binding.",
                )
            )
        if binding.get("sha256") != bundle.get("bundle_hash"):
            findings.append(
                _finding(
                    "RESEARCH_BUNDLE_HASH_MISMATCH",
                    ["inputs", "research_bundle", "sha256"],
                    "Research Bundle hash does not match the request binding.",
                )
            )

    for request_field, bundle_field in (
        ("namespace", "namespace"),
        ("character_id", "character_id"),
        ("display_name", "display_name"),
    ):
        if request.get(request_field) != bundle.get(bundle_field):
            findings.append(
                _finding(
                    "RESEARCH_BUNDLE_IDENTITY_MISMATCH",
                    [request_field],
                    "Research Bundle character identity does not match the request.",
                )
            )
    for request_field, bundle_field, code, message in (
        (
            "continuity",
            "continuity",
            "RESEARCH_BUNDLE_CONTINUITY_MISMATCH",
            "Research Bundle continuity does not match the request.",
        ),
        (
            "timeline",
            "timeline_cutoff",
            "RESEARCH_BUNDLE_TIMELINE_MISMATCH",
            "Research Bundle timeline does not match the request.",
        ),
        (
            "spoiler_scope",
            "spoiler_scope",
            "RESEARCH_BUNDLE_SPOILER_MISMATCH",
            "Research Bundle spoiler scope does not match the request.",
        ),
    ):
        if request.get(request_field) != bundle.get(bundle_field):
            findings.append(_finding(code, [request_field], message))

    coverage = bundle.get("coverage")
    coverage_blocks = (
        isinstance(coverage, Mapping) and coverage.get("blocks_authoring") is True
    )
    if (
        bundle.get("build_status") != "research"
        or bundle.get("visibility") != "private"
        or bundle.get("activation_allowed") is not False
        or bundle.get("authoring_allowed") is not True
        or bool(bundle.get("blocking_reasons"))
        or coverage_blocks
    ):
        findings.append(
            _finding(
                "RESEARCH_BUNDLE_INELIGIBLE",
                ["inputs", "research_bundle"],
                "Research Bundle is not eligible for character authoring.",
            )
        )
    conflicts = _mapping_items(bundle.get("conflicts"))
    if any(conflict.get("status") == "unresolved" for conflict in conflicts):
        findings.append(
            _finding(
                "RESEARCH_BUNDLE_CONFLICT_UNRESOLVED",
                ["inputs", "research_bundle", "conflicts"],
                "Research Bundle contains an unresolved conflict.",
            )
        )

    supported_claim_ids = {
        claim.get("claim_id")
        for claim in _mapping_items(bundle.get("claims"))
        if claim.get("support") != "unsupported"
        and isinstance(claim.get("claim_id"), str)
    }
    request_input_types = {
        item.get("type") for item in _mapping_items(request.get("inputs"))
    }
    research_reference_count = 0
    for index, claim in enumerate(claims):
        if not isinstance(claim, Mapping):
            findings.append(
                _finding(
                    "AUTHORING_RESEARCH_CLAIM_UNBOUND",
                    ["evidence", "claims", index],
                    "Research evidence must reference a supported bundle claim.",
                )
            )
            continue
        source_label = _normalize_source_label(claim.get("source"))
        claim_id = claim.get("claim_id")
        if source_label == "research_bundle":
            research_reference_count += 1
            if (
                claim_id not in supported_claim_ids
                or set(claim) != {"claim_id", "source"}
            ):
                findings.append(
                    _finding(
                        "AUTHORING_RESEARCH_CLAIM_UNBOUND",
                        ["evidence", "claims", index],
                        "Research evidence must be an exact supported-claim reference.",
                    )
                )
            continue
        allowed_user_source = (
            request.get("mode") == "hybrid"
            and source_label in {"user_dossier", "user_override"}
            and source_label in request_input_types
        )
        if not allowed_user_source:
            findings.append(
                _finding(
                    "AUTHORING_RESEARCH_PROVENANCE_INVALID",
                    ["evidence", "claims", index, "source"],
                    "Research-backed evidence provenance is invalid.",
                )
            )
        elif claim_id in supported_claim_ids:
            findings.append(
                _finding(
                    "AUTHORING_RESEARCH_FACT_OVERRIDE",
                    ["evidence", "claims", index, "claim_id"],
                    "User assertions cannot rewrite a Research Bundle fact.",
                )
            )
    if research_reference_count == 0:
        findings.append(
            _finding(
                "AUTHORING_RESEARCH_EVIDENCE_REQUIRED",
                ["evidence", "claims"],
                "A supported Research Bundle claim reference is required.",
            )
        )
    if evidence.get("authored_original") is True:
        findings.append(
            _finding(
                "AUTHORING_RESEARCH_ORIGINAL_PROVENANCE_PROHIBITED",
                ["evidence", "authored_original"],
                "Research-backed evidence cannot be marked as authored original.",
            )
        )


def _validate_original_provenance(
    evidence: Mapping[str, Any],
    claims: list[Any],
    findings: list[dict[str, Any]],
) -> None:
    if evidence.get("authored_original") is not True:
        findings.append(
            _finding(
                "AUTHORING_ORIGINAL_EVIDENCE_REQUIRED",
                ["evidence", "authored_original"],
                "Original mode requires explicitly authored-original evidence.",
            )
        )
    for index, claim in enumerate(claims):
        source = claim.get("source") if isinstance(claim, Mapping) else None
        if _normalize_source_label(source) not in _ORIGINAL_CLAIM_SOURCES:
            findings.append(
                _finding(
                    "AUTHORING_EXTERNAL_CANON_PROHIBITED",
                    ["evidence", "claims", index, "source"]
                    if isinstance(claim, Mapping)
                    else ["evidence", "claims", index],
                    "Original mode cannot present a claim as external canon.",
                )
            )


def _validate_dossier_provenance(
    request: Mapping[str, Any],
    source: Mapping[str, Any],
    evidence: Mapping[str, Any],
    claims: list[Any],
    findings: list[dict[str, Any]],
) -> None:
    inputs_value = request.get("inputs")
    inputs = inputs_value if isinstance(inputs_value, list) else []
    has_dossier_input = any(
        isinstance(item, Mapping) and item.get("type") == "user_dossier"
        for item in inputs
    )
    dossier_claims = [
        claim
        for claim in claims
        if isinstance(claim, Mapping)
        and _normalize_source_label(claim.get("source")) == "user_dossier"
        and isinstance(claim.get("statement"), str)
    ]
    if evidence.get("authored_original") is True:
        findings.append(
            _finding(
                "AUTHORING_DOSSIER_ORIGINAL_PROVENANCE_PROHIBITED",
                ["evidence", "authored_original"],
                "Dossier mode cannot be marked as authored original.",
            )
        )
    for index, claim in enumerate(claims):
        source_label = (
            _normalize_source_label(claim.get("source"))
            if isinstance(claim, Mapping)
            else None
        )
        if source_label not in _DOSSIER_CLAIM_SOURCES:
            findings.append(
                _finding(
                    "AUTHORING_DOSSIER_CANON_PROHIBITED",
                    ["evidence", "claims", index, "source"]
                    if isinstance(claim, Mapping)
                    else ["evidence", "claims", index],
                    "Dossier mode cannot relabel user assertions as canon.",
                )
            )
    if not has_dossier_input:
        findings.append(
            _finding(
                "AUTHORING_DOSSIER_EVIDENCE_REQUIRED",
                ["inputs"],
                "Dossier mode requires a typed user-dossier input.",
            )
        )
    elif not dossier_claims:
        findings.append(
            _finding(
                "AUTHORING_DOSSIER_EVIDENCE_REQUIRED",
                ["evidence", "claims"],
                "Dossier mode requires user-dossier evidence claims.",
            )
        )

    explicit_identity_values = {
        _normalize_identity_text(value)
        for value in (
            request.get("display_name"),
            *_string_items(request.get("user_constraints")),
            *(
                item.get("content")
                for item in inputs
                if isinstance(item, Mapping)
                and item.get("type") == "user_override"
            ),
        )
        if isinstance(value, str)
    }
    normalized_dossier_statements = (
        _normalize_identity_text(claim["statement"])
        for claim in dossier_claims
    )
    dossier_statements = {
        statement
        for statement in normalized_dossier_statements
        if statement not in explicit_identity_values
    }
    identity = source.get("identity")
    if not isinstance(identity, Mapping):
        return
    for path, value in _string_leaves(identity, ["identity"]):
        if _normalize_identity_text(value) in dossier_statements:
            findings.append(
                _finding(
                    "AUTHORING_IDENTITY_PROVENANCE_COLLAPSE",
                    path,
                    "Dossier evidence cannot become immutable identity without "
                    "explicit input.",
                )
            )


def _string_leaves(
    value: Any, path: list[str | int]
) -> list[tuple[list[str | int], str]]:
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, Mapping):
        leaves: list[tuple[list[str | int], str]] = []
        for key in sorted(value):
            if isinstance(key, str):
                leaves.extend(_string_leaves(value[key], [*path, key]))
        return leaves
    if isinstance(value, list):
        leaves = []
        for index, item in enumerate(value):
            leaves.extend(_string_leaves(item, [*path, index]))
        return leaves
    return []


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _mapping_items(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _mapping_count(value: Any, member: str) -> int:
    if not isinstance(value, Mapping):
        return 0
    items = value.get(member)
    return len(items) if isinstance(items, Mapping) else 0


def _report_artifact_id(request: Mapping[str, Any]) -> str:
    readable = f"{request['namespace']}/{request['character_id']}/build-validation"
    if len(readable) <= 128:
        return readable
    identity = (
        f"{request['namespace']}/{request['character_id']}/"
        f"{request['character_version']}"
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"build-validation/{digest}"


def _normalize_source_label(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return "_".join(
        value.casefold().replace("-", " ").replace("_", " ").split()
    )


def _normalize_identity_text(value: str) -> str:
    normalized = " ".join(
        unicodedata.normalize("NFKC", value).casefold().split()
    )
    start = 0
    end = len(normalized)
    while start < end and unicodedata.category(normalized[start]).startswith("P"):
        start += 1
    while end > start and unicodedata.category(normalized[end - 1]).startswith("P"):
        end -= 1
    return normalized[start:end].strip()


def _finding(
    code: str, path: list[str | int], message: str
) -> dict[str, Any]:
    return {"code": code, "path": path, "message": message}


def _finding_sort_key(finding: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(finding["code"]),
        json.dumps(finding["path"], ensure_ascii=False, separators=(",", ":")),
        str(finding["message"]),
    )
