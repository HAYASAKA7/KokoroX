"""Cross-artifact validation for character-pack authoring."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from kokoroarc import __version__
from kokoroarc.schemas import SchemaRegistry


_FIRST_CLASS_LOCALES = ("zh-CN", "en-US", "ja-JP")
_EXTERNAL_CANON_SOURCES = frozenset(
    {"external canon", "external-canon", "external_canon"}
)
_MAX_FINDINGS = 256


def validate_authoring_pack(
    request: dict[str, Any],
    source: dict[str, Any],
    schemas: SchemaRegistry,
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
        "artifact_id": (
            f"{request['namespace']}/{request['character_id']}/build-validation"
        ),
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
        if (
            isinstance(claim, Mapping)
            and claim.get("source") in _EXTERNAL_CANON_SOURCES
        ):
            findings.append(
                _finding(
                    "AUTHORING_EXTERNAL_CANON_PROHIBITED",
                    ["evidence", "claims", index, "source"],
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
        and claim.get("source") == "user_dossier"
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
        if (
            isinstance(claim, Mapping)
            and claim.get("source") in _EXTERNAL_CANON_SOURCES
        ):
            findings.append(
                _finding(
                    "AUTHORING_DOSSIER_CANON_PROHIBITED",
                    ["evidence", "claims", index, "source"],
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
        value
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
    dossier_statements = {
        statement
        for claim in claims
        if isinstance(claim, Mapping)
        and isinstance((statement := claim.get("statement")), str)
        and statement not in explicit_identity_values
    }
    identity = source.get("identity")
    if not isinstance(identity, Mapping):
        return
    for path, value in _string_leaves(identity, ["identity"]):
        if value in dossier_statements:
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


def _mapping_count(value: Any, member: str) -> int:
    if not isinstance(value, Mapping):
        return 0
    items = value.get(member)
    return len(items) if isinstance(items, Mapping) else 0


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
