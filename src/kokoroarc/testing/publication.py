"""Deterministic, local-only Character Pack publication-readiness checks."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable, Mapping, cast

import yaml

from kokoroarc import __version__
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes, compile_pack
from kokoroarc.packs.loader import (
    assemble_source_pack_from_contents,
    parse_yaml_bytes,
)
from kokoroarc.schemas import SchemaRegistry
from kokoroarc.testing.hard import _PackSnapshot, _snapshot_pack
from kokoroarc.testing.promotion import create_promotion_record


_VISIBILITIES = frozenset({"private", "public_candidate"})
_BASELINE_CHECKS = (
    "verified_promotion",
    "provenance",
    "private_material_absent",
    "executable_content_absent",
    "secrets_absent",
    "absolute_paths_absent",
    "continuity",
    "spoiler_scope",
    "source_references",
    "age_routes",
)
_CHECK_NAMES = (
    "verified_promotion",
    "visibility_policy",
    "provenance",
    "private_material_absent",
    "executable_content_absent",
    "secrets_absent",
    "absolute_paths_absent",
    "compliance",
    "continuity",
    "spoiler_scope",
    "source_references",
    "age_routes",
)
_EXECUTABLE_SUFFIXES = frozenset(
    {
        ".bat",
        ".cmd",
        ".com",
        ".dll",
        ".dylib",
        ".exe",
        ".jar",
        ".js",
        ".msi",
        ".ps1",
        ".py",
        ".scr",
        ".sh",
        ".so",
        ".vbs",
        ".wasm",
    }
)
_MEDIA_SUFFIXES = frozenset(
    {
        ".avi",
        ".bmp",
        ".doc",
        ".docx",
        ".flac",
        ".gif",
        ".jpeg",
        ".jpg",
        ".m4a",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".ogg",
        ".pdf",
        ".png",
        ".svg",
        ".wav",
        ".webm",
        ".webp",
    }
)
_PRIVATE_PATH_MARKERS = frozenset(
    {
        "chat",
        "dialogue",
        "dossier",
        "interview",
        "raw",
        "research",
        "snapshot",
        "transcript",
    }
)
_APPROVED_BASIS_CODES = frozenset(
    {
        "DISTRIBUTION_RIGHTS_CONFIRMED",
        "LICENSE_VERIFIED",
        "ORIGINAL_AUTHORSHIP_CONFIRMED",
        "PUBLIC_DOMAIN_VERIFIED",
    }
)
_STABLE_ID = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*\Z", re.ASCII)
_FINDING_CODE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*\Z", re.ASCII)
_SHA256 = re.compile(r"^[a-f0-9]{64}\Z", re.ASCII)
_WINDOWS_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/](?:[^\s\"'<>|]+)", re.ASCII
)
_UNC_PATH = re.compile(
    r"(?<![A-Za-z0-9_\\])\\\\[^\\\s]+\\[^\\\s]+",
    re.ASCII,
)
_POSIX_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9._~/-])/(?!/)[^\s\"'<>|]+",
    re.ASCII | re.MULTILINE,
)
_FILE_URI_PATH = re.compile(
    r"(?i)(?<![A-Za-z0-9])file:(?:/+|[A-Za-z]:[\\/])",
    re.ASCII,
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?<![A-Za-z0-9_])[\"']?(?:api[_-]?key|access[_-]?key|"
    r"authorization|client[_-]?secret|"
    r"credentials?|password|passwd|private[_-]?key|secret|token)"
    r"(?![A-Za-z0-9_-])[\"']?\s*[:=]\s*"
    r"(?![\"']?<redacted-)[\"']?[^\s,;\]}]{4,}"
)
_KNOWN_CREDENTIALS = (
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(
        r"-----BEGIN (?:(?:RSA|EC|OPENSSH|ENCRYPTED) )?PRIVATE KEY-----",
        re.ASCII,
    ),
    re.compile(r"\bhttps?://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE),
)
_MAX_FINDINGS = 256
_MAX_PORTABLE_TEXT_VALUE = 2000
_MAX_PORTABLE_FILE_TEXT = 8 * _MAX_PORTABLE_TEXT_VALUE
_PROTECTED_SPANS_PATH = "tests/protected-spans.yaml"
_UNUSABLE_DECLARATION = re.compile(
    r"(?:\b(?:not\s+(?:known|provided|specified)|tbd|undisclosed|unknown|"
    r"unspecified)\b|\bn\s*/\s*a\b)",
    re.IGNORECASE | re.ASCII,
)
_USABLE_AGE = re.compile(
    r"\s*(?:(?:age|aged)\s*:?\s*)?\d{1,4}"
    r"(?:[\s-]*(?:(?:years?|yrs?)(?:[\s-]+old)?|y/?o))?\s*",
    re.IGNORECASE | re.ASCII,
)
_AGE_CLASS = re.compile(
    r"\s*(?:adult|adolescent|ageless|ancient|child|immortal|minor|teen)\s*",
    re.IGNORECASE | re.ASCII,
)
_UNRESOLVED_TOKEN = re.compile(
    r"(?<![a-z0-9])unresolved(?![a-z0-9])",
    re.ASCII,
)
_INITIAL_STAGE_NAMES = frozenset({"default", "initial", "unknown"})
_MUTATION_ERROR_CODES = frozenset(
    {
        "PACK_PUBLICATION_INPUT_MUTATION",
        "PACK_PUBLICATION_PIPELINE_MUTATION",
        "PACK_PUBLICATION_SOURCE_CHANGED",
        "PACK_PUBLICATION_VALIDATOR_MUTATION",
    }
)


def assess_publication_readiness(
    source_root: Path,
    promotion_record: dict[str, Any],
    schemas: SchemaRegistry,
    *,
    promotion_evidence: dict[str, Any] | None = None,
    requested_visibility: str = "private",
    compliance_attestation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a canonical advisory report without publishing or doing I/O online."""
    if requested_visibility not in _VISIBILITIES:
        raise KokoroError(
            "PACK_PUBLICATION_VISIBILITY_INVALID",
            "The requested publication visibility is invalid.",
        )
    if requested_visibility == "private" and compliance_attestation is not None:
        raise KokoroError(
            "PACK_PUBLICATION_COMPLIANCE_UNEXPECTED",
            "A private readiness check cannot consume a public compliance attestation.",
        )

    captured = _capture_inputs(
        promotion_record,
        promotion_evidence,
        compliance_attestation,
    )
    initial_snapshot = _snapshot_pack(source_root)
    boundary = _PublicationBoundary(
        source_root,
        initial_snapshot,
        tuple(captured.values()),
    )
    audited_schemas = _AuditedSchemaRegistry(schemas, boundary)
    promotion = cast(dict[str, Any], json.loads(captured["promotion"][1]))
    evidence_value = json.loads(captured["promotion_evidence"][1])
    evidence = (
        cast(dict[str, Any], evidence_value)
        if isinstance(evidence_value, dict)
        else None
    )
    compliance_value = json.loads(captured["compliance"][1])
    compliance_input = (
        cast(dict[str, Any], compliance_value)
        if compliance_value is not None
        else None
    )
    audited_schemas.retain_pipeline_value(
        evidence_value,
        captured["promotion_evidence"][1],
    )

    _validate_schema(
        audited_schemas,
        "pack-promotion-record",
        promotion,
        "PACK_PUBLICATION_PROMOTION_INVALID",
    )
    evidence_valid = _promotion_evidence_is_current(
        source_root,
        promotion,
        captured["promotion"][1],
        evidence,
        audited_schemas,
    )
    try:
        source = assemble_source_pack_from_contents(initial_snapshot.contents)
        source_bytes = canonical_bytes(source)
    except (KokoroError, OverflowError, TypeError, ValueError) as error:
        if isinstance(error, KokoroError) and error.code in _MUTATION_ERROR_CODES:
            raise
        raise KokoroError(
            "PACK_PUBLICATION_SOURCE_INVALID",
            "The Character Pack source cannot be inspected for publication readiness.",
        ) from error

    source_for_schema = cast(dict[str, Any], json.loads(source_bytes))
    audited_schemas.retain_pipeline_value(source_for_schema, source_bytes)
    _validate_schema(
        audited_schemas,
        "character-source",
        source_for_schema,
        "PACK_PUBLICATION_SOURCE_INVALID",
    )
    mutation_probes: list[tuple[Any, bytes]] = [(source_for_schema, source_bytes)]

    source_for_compile = cast(dict[str, Any], json.loads(source_bytes))
    mutation_probes.append((source_for_compile, source_bytes))
    audited_schemas.retain_pipeline_value(source_for_compile, source_bytes)
    try:
        compiled = compile_pack(
            source_for_compile,
            cast(SchemaRegistry, audited_schemas),
        )
        compiled_bytes = canonical_bytes(compiled)
    except (KokoroError, OverflowError, TypeError, ValueError) as error:
        if isinstance(error, KokoroError) and error.code in _MUTATION_ERROR_CODES:
            raise
        raise KokoroError(
            "PACK_PUBLICATION_COMPILE_FAILED",
            "The Character Pack cannot be compiled for publication readiness.",
        ) from error
    mutation_probes.append((compiled, compiled_bytes))
    audited_schemas.retain_pipeline_value(compiled, compiled_bytes)
    compiled_snapshot = cast(dict[str, Any], json.loads(compiled_bytes))
    audited_schemas.retain_pipeline_value(compiled_snapshot, compiled_bytes)
    _validate_schema(
        audited_schemas,
        "compiled-pack",
        compiled_snapshot,
        "PACK_PUBLICATION_COMPILE_FAILED",
    )

    source_snapshot = cast(dict[str, Any], json.loads(source_bytes))
    audited_schemas.retain_pipeline_value(source_snapshot, source_bytes)
    findings = {name: [] for name in _CHECK_NAMES}
    _check_verified_promotion(
        promotion,
        source_snapshot,
        compiled_snapshot,
        evidence_valid,
        findings["verified_promotion"],
    )
    _check_visibility_policy(
        requested_visibility,
        promotion,
        findings["visibility_policy"],
    )
    _check_provenance(source_snapshot, promotion, findings["provenance"])
    _check_private_material(
        initial_snapshot,
        compiled_snapshot,
        findings["private_material_absent"],
    )
    _check_executable_content(
        initial_snapshot,
        findings["executable_content_absent"],
    )
    _check_secrets(
        initial_snapshot,
        compiled_snapshot,
        findings["secrets_absent"],
    )
    _check_absolute_paths(
        initial_snapshot,
        compiled_snapshot,
        findings["absolute_paths_absent"],
    )
    _check_continuity(
        initial_snapshot,
        compiled_snapshot,
        findings["continuity"],
    )
    _check_spoiler_scope(source_snapshot, findings["spoiler_scope"])
    _check_source_references(
        initial_snapshot,
        source_snapshot,
        promotion,
        findings["source_references"],
    )
    _check_age_routes(source_snapshot, findings["age_routes"])

    compliance, compliance_valid = _normalize_compliance(compliance_input)
    _check_compliance(
        requested_visibility,
        compliance,
        compliance_valid,
        source_hash=sha256(source_bytes).hexdigest(),
        compiled_hash=sha256(compiled_bytes).hexdigest(),
        findings=findings["compliance"],
    )

    checks = {
        name: _check_result(findings[name])
        for name in _CHECK_NAMES
    }
    ready_for_private_export = all(
        checks[name]["passed"] for name in _BASELINE_CHECKS
    )
    ready_for_publication = (
        requested_visibility == "public_candidate"
        and ready_for_private_export
        and checks["visibility_policy"]["passed"]
        and checks["compliance"]["passed"]
    )
    blockers = _blockers(checks)
    prefix = f"{source_snapshot['namespace']}/{source_snapshot['character_id']}"
    report = {
        "schema_version": "1.0",
        "artifact_id": f"{prefix}/release/publication-readiness",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "namespace": source_snapshot["namespace"],
        "character_id": source_snapshot["character_id"],
        "character_version": source_snapshot["character_version"],
        "mode": promotion["mode"],
        "requested_visibility": requested_visibility,
        "source_artifact_id": source_snapshot["artifact_id"],
        "source_hash": sha256(source_bytes).hexdigest(),
        "source_tree_hash": _publication_source_tree_hash(initial_snapshot),
        "compiled_artifact_id": compiled_snapshot["artifact_id"],
        "compiled_hash": sha256(compiled_bytes).hexdigest(),
        "promotion": {
            "artifact_id": promotion["artifact_id"],
            "sha256": sha256(captured["promotion"][1]).hexdigest(),
        },
        "promotion_evidence_hash": sha256(
            captured["promotion_evidence"][1]
        ).hexdigest(),
        "compliance_input_hash": sha256(captured["compliance"][1]).hexdigest(),
        "checks": checks,
        "blockers": blockers,
        "compliance_attestation": compliance,
        "ready_for_private_export": ready_for_private_export,
        "ready_for_publication": ready_for_publication,
    }
    report_bytes = canonical_bytes(report)
    _validate_schema(
        audited_schemas,
        "pack-publication-readiness-report",
        cast(dict[str, Any], json.loads(report_bytes)),
        "PACK_PUBLICATION_REPORT_INVALID",
    )
    audited_schemas.assert_clean()
    _assert_mutation_probes(mutation_probes)
    return cast(dict[str, Any], json.loads(report_bytes))


def publication_report_is_current(
    report: dict[str, Any],
    source_root: Path,
    promotion_record: dict[str, Any],
    schemas: SchemaRegistry,
    *,
    promotion_evidence: dict[str, Any] | None = None,
    compliance_attestation: dict[str, Any] | None = None,
) -> bool:
    """Return whether a report is the exact current deterministic report."""
    try:
        report_bytes = canonical_bytes(report)
        promotion_bytes = canonical_bytes(promotion_record)
        evidence_bytes = canonical_bytes(promotion_evidence)
        report_value = json.loads(report_bytes)
        promotion_value = json.loads(promotion_bytes)
        if not isinstance(report_value, dict) or not isinstance(
            promotion_value, dict
        ):
            return False
        report_snapshot = cast(dict[str, Any], report_value)
        promotion_snapshot = cast(dict[str, Any], promotion_value)
        embedded_compliance = report_snapshot.get("compliance_attestation")
        compliance = (
            compliance_attestation
            if compliance_attestation is not None
            else (
                cast(dict[str, Any], embedded_compliance)
                if isinstance(embedded_compliance, dict)
                else None
            )
        )
        compliance_bytes = canonical_bytes(compliance_attestation)
        initial_snapshot = _snapshot_pack(source_root)
        boundary = _PublicationBoundary(
            source_root,
            initial_snapshot,
            (
                (report, report_bytes),
                (promotion_record, promotion_bytes),
                (promotion_evidence, evidence_bytes),
                (compliance_attestation, compliance_bytes),
            ),
        )
        current = assess_publication_readiness(
            source_root,
            promotion_snapshot,
            cast(SchemaRegistry, _BoundarySchemaRegistry(schemas, boundary)),
            promotion_evidence=promotion_evidence,
            requested_visibility=cast(str, report_snapshot["requested_visibility"]),
            compliance_attestation=(
                cast(dict[str, Any], compliance) if compliance is not None else None
            ),
        )
        boundary.assert_unchanged()
        final_snapshot = _snapshot_pack(source_root)
        return (
            canonical_bytes(current) == report_bytes
            and canonical_bytes(report) == report_bytes
            and canonical_bytes(promotion_record) == promotion_bytes
            and canonical_bytes(promotion_evidence) == evidence_bytes
            and canonical_bytes(compliance_attestation) == compliance_bytes
            and final_snapshot == initial_snapshot
        )
    except (
        KeyError,
        KokoroError,
        OSError,
        OverflowError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        return False


def _capture_inputs(
    promotion: dict[str, Any],
    promotion_evidence: dict[str, Any] | None,
    compliance: dict[str, Any] | None,
) -> dict[str, tuple[Any, bytes]]:
    try:
        return {
            "promotion": (promotion, canonical_bytes(promotion)),
            "promotion_evidence": (
                promotion_evidence,
                canonical_bytes(promotion_evidence),
            ),
            "compliance": (compliance, canonical_bytes(compliance)),
        }
    except (KokoroError, OverflowError, TypeError, ValueError) as error:
        raise KokoroError(
            "PACK_PUBLICATION_INPUT_INVALID",
            "A publication-readiness input is not canonical JSON data.",
        ) from error


def _validate_schema(
    schemas: Any,
    name: str,
    value: dict[str, Any],
    code: str,
) -> None:
    try:
        schemas.validate(name, value)
    except KokoroError as error:
        if error.code in _MUTATION_ERROR_CODES:
            raise
        raise KokoroError(
            code,
            "A publication-readiness artifact is invalid.",
        ) from error


def _check_verified_promotion(
    promotion: Mapping[str, Any],
    source: Mapping[str, Any],
    compiled: Mapping[str, Any],
    evidence_valid: bool,
    findings: list[dict[str, Any]],
) -> None:
    expected = {
        "namespace": source.get("namespace"),
        "character_id": source.get("character_id"),
        "character_version": source.get("character_version"),
        "source_artifact_id": source.get("artifact_id"),
        "source_hash": sha256(canonical_bytes(source)).hexdigest(),
        "compiled_artifact_id": compiled.get("artifact_id"),
        "compiled_hash": sha256(canonical_bytes(compiled)).hexdigest(),
        "to_status": "verified",
        "from_status": "reviewed",
        "activation_allowed": True,
    }
    binding_valid = not any(
        promotion.get(field) != value for field, value in expected.items()
    )
    if not binding_valid:
        findings.append(
            _finding(
                "PUBLICATION_PROMOTION_STALE",
                ["promotion"],
                "The verified promotion does not bind the current Character Pack.",
            )
        )
    elif not evidence_valid:
        findings.append(
            _finding(
                "PUBLICATION_PROMOTION_EVIDENCE_INVALID",
                ["promotion"],
                "The verified promotion is not reproducible from current release "
                "evidence.",
            )
        )


def _promotion_evidence_is_current(
    source_root: Path,
    promotion: Mapping[str, Any],
    promotion_bytes: bytes,
    evidence: Mapping[str, Any] | None,
    schemas: "_AuditedSchemaRegistry",
) -> bool:
    required = {
        "request",
        "hard_report",
        "review_attestation",
        "previous_promotion",
        "soft_evaluation_input",
        "soft_evaluation_report",
    }
    if evidence is None or not required.issubset(evidence):
        return False
    if set(evidence) - {*required, "research_bundle"}:
        return False
    if any(not isinstance(evidence.get(name), dict) for name in required):
        return False
    research_bundle = evidence.get("research_bundle")
    if research_bundle is not None and not isinstance(research_bundle, dict):
        return False
    try:
        reproduced = create_promotion_record(
            source_root,
            cast(dict[str, Any], evidence["request"]),
            cast(dict[str, Any], evidence["hard_report"]),
            cast(dict[str, Any], evidence["review_attestation"]),
            cast(SchemaRegistry, schemas),
            target="verified",
            promotion_id=cast(str, promotion.get("promotion_id")),
            research_bundle=cast(dict[str, Any] | None, research_bundle),
            previous_promotion=cast(dict[str, Any], evidence["previous_promotion"]),
            soft_evaluation_input=cast(
                dict[str, Any], evidence["soft_evaluation_input"]
            ),
            soft_evaluation_report=cast(
                dict[str, Any], evidence["soft_evaluation_report"]
            ),
        )
    except KokoroError as error:
        if error.code in _MUTATION_ERROR_CODES:
            raise
        schemas.assert_clean()
        return False
    except (OverflowError, TypeError, ValueError):
        schemas.assert_clean()
        return False
    schemas.assert_clean()
    return canonical_bytes(reproduced) == promotion_bytes


def _check_visibility_policy(
    requested_visibility: str,
    promotion: Mapping[str, Any],
    findings: list[dict[str, Any]],
) -> None:
    if requested_visibility not in _VISIBILITIES:
        findings.append(
            _finding(
                "PUBLICATION_VISIBILITY_POLICY_INVALID",
                ["requested_visibility"],
                "The requested visibility is outside the local publication policy.",
            )
        )
    if (
        requested_visibility == "public_candidate"
        and promotion.get("visibility") != "public_candidate"
    ):
        findings.append(
            _finding(
                "PUBLICATION_PROMOTION_VISIBILITY_MISMATCH",
                ["promotion", "visibility"],
                "The requested visibility does not match the verified promotion.",
            )
        )


def _check_provenance(
    source: Mapping[str, Any],
    promotion: Mapping[str, Any],
    findings: list[dict[str, Any]],
) -> None:
    evidence = source.get("evidence")
    authored_original = (
        evidence.get("authored_original") if isinstance(evidence, Mapping) else None
    )
    mode = promotion.get("mode")
    if (mode == "original" and authored_original is not True) or (
        mode != "original" and authored_original is not False
    ):
        findings.append(
            _finding(
                "PUBLICATION_PROVENANCE_MISMATCH",
                ["evidence", "authored_original"],
                "The source provenance declaration does not match its construction "
                "mode.",
            )
        )


def _check_private_material(
    snapshot: _PackSnapshot,
    compiled: Mapping[str, Any],
    findings: list[dict[str, Any]],
) -> None:
    for relative in snapshot.paths:
        path = PurePosixPath(relative)
        lowered_parts = {
            token
            for part in path.parts
            for token in re.split(r"[^a-z0-9]+", part.casefold())
            if token
        }
        always_private = lowered_parts & _PRIVATE_PATH_MARKERS
        if (
            path.suffix.casefold() in _MEDIA_SUFFIXES
            or always_private
        ):
            findings.append(
                _finding(
                    "PUBLICATION_PRIVATE_MATERIAL_PRESENT",
                    _finding_path(relative),
                    "The pack contains private source material or non-portable media.",
                )
            )
        if relative != _PROTECTED_SPANS_PATH:
            if _raw_comment_length(snapshot.contents[relative]) > (
                _MAX_PORTABLE_TEXT_VALUE
            ):
                findings.append(
                    _finding(
                        "PUBLICATION_LONG_DIALOGUE_PRESENT",
                        _finding_path(relative),
                        "The portable source contains an overlong comment corpus.",
                    )
                )
            try:
                fixture = parse_yaml_bytes(snapshot.contents[relative])
            except KokoroError:
                fixture = None
            if fixture is not None:
                aggregate_text_length = 0
                for value_path, value in _walk_strings(fixture):
                    aggregate_text_length += len(value)
                    if len(value) > _MAX_PORTABLE_TEXT_VALUE:
                        findings.append(
                            _finding(
                                "PUBLICATION_LONG_DIALOGUE_PRESENT",
                                [
                                    *_finding_path(relative),
                                    *_finding_value_path(value_path),
                                ],
                                "The portable source contains an overlong dialogue "
                                "value.",
                            )
                        )
                if aggregate_text_length > _MAX_PORTABLE_FILE_TEXT:
                    findings.append(
                        _finding(
                            "PUBLICATION_LONG_DIALOGUE_PRESENT",
                            _finding_path(relative),
                            "The portable source contains an overlong aggregate text "
                            "corpus.",
                        )
                    )
        if (
            lowered_parts & {"chat", "dialogue", "transcript"}
            and len(snapshot.contents[relative]) > _MAX_PORTABLE_TEXT_VALUE
        ):
            findings.append(
                _finding(
                    "PUBLICATION_LONG_DIALOGUE_PRESENT",
                    _finding_path(relative),
                    "The pack contains an overlong dialogue or narrative corpus.",
                )
            )
    for path, value in _walk_strings(compiled):
        if len(value) > _MAX_PORTABLE_TEXT_VALUE:
            findings.append(
                _finding(
                    "PUBLICATION_LONG_DIALOGUE_PRESENT",
                    _finding_value_path(path),
                    "The compiled pack contains an overlong dialogue or narrative "
                    "corpus.",
                )
            )


def _check_executable_content(
    snapshot: _PackSnapshot,
    findings: list[dict[str, Any]],
) -> None:
    executable_permissions = set(snapshot.executable_permissions)
    for relative in snapshot.paths:
        data = snapshot.contents[relative]
        suffix = PurePosixPath(relative).suffix.casefold()
        if (
            suffix in _EXECUTABLE_SUFFIXES
            or relative in executable_permissions
            or data.startswith((b"MZ", b"\x7fELF", b"#!"))
        ):
            findings.append(
                _finding(
                    "PUBLICATION_EXECUTABLE_CONTENT_PRESENT",
                    _finding_path(relative),
                    "The pack contains executable or executable-marked content.",
                )
            )


def _check_secrets(
    snapshot: _PackSnapshot,
    compiled: Mapping[str, Any],
    findings: list[dict[str, Any]],
) -> None:
    for relative, text in _publication_texts(snapshot, compiled):
        if _contains_secret(text):
            findings.append(
                _finding(
                    "PUBLICATION_SECRET_PRESENT",
                    _finding_path(relative),
                    "The portable pack surface appears to contain credential material.",
                )
            )


def _check_absolute_paths(
    snapshot: _PackSnapshot,
    compiled: Mapping[str, Any],
    findings: list[dict[str, Any]],
) -> None:
    for relative, text in _publication_texts(snapshot, compiled):
        if _contains_absolute_path(text):
            findings.append(
                _finding(
                    "PUBLICATION_ABSOLUTE_PATH_PRESENT",
                    _finding_path(relative),
                    "The portable pack surface contains an absolute host path.",
                )
            )


def _check_continuity(
    snapshot: _PackSnapshot,
    compiled: Mapping[str, Any],
    findings: list[dict[str, Any]],
) -> None:
    for relative, text in _publication_texts(snapshot, compiled):
        lowered = text.casefold()
        unresolved_text = re.sub(
            r"\bno(?:\s+[a-z]+){0,2}\s+unresolved\b",
            "",
            lowered,
        )
        unresolved = _UNRESOLVED_TOKEN.search(unresolved_text) is not None
        merge_conflict = any(
            marker in text for marker in ("<<<<<<<", "=======", ">>>>>>>")
        )
        if unresolved or merge_conflict:
            findings.append(
                _finding(
                    "PUBLICATION_CONTINUITY_CONFLICT_UNRESOLVED",
                    _finding_path(relative),
                    "The source retains an unresolved continuity conflict.",
                )
            )


def _check_spoiler_scope(
    source: Mapping[str, Any], findings: list[dict[str, Any]]
) -> None:
    scope = source.get("spoiler_scope")
    if (
        not isinstance(scope, str)
        or not scope.strip()
        or _UNUSABLE_DECLARATION.search(scope) is not None
    ):
        findings.append(
            _finding(
                "PUBLICATION_SPOILER_DECLARATION_MISSING",
                ["spoiler_scope"],
                "The pack does not contain a usable spoiler-scope declaration.",
            )
        )


def _check_source_references(
    snapshot: _PackSnapshot,
    source: Mapping[str, Any],
    promotion: Mapping[str, Any],
    findings: list[dict[str, Any]],
) -> None:
    expected = _closed_layout_paths(snapshot)
    actual = set(snapshot.paths)
    for relative in sorted(expected - actual):
        findings.append(
            _finding(
                "PUBLICATION_SOURCE_REFERENCE_MISSING",
                _finding_path(relative),
                "A required source or test reference is missing.",
            )
        )
    for relative in sorted(actual - expected):
        findings.append(
            _finding(
                "PUBLICATION_SOURCE_LAYOUT_UNEXPECTED_FILE",
                _finding_path(relative),
                "The pack contains a file outside its closed portable source layout.",
            )
        )
    if promotion.get("mode") == "original":
        return
    evidence = source.get("evidence", {})
    claims = evidence.get("claims") if isinstance(evidence, Mapping) else None
    if not isinstance(claims, list) or not claims:
        findings.append(
            _finding(
                "PUBLICATION_SOURCE_REFERENCE_MISSING",
                ["evidence", "claims"],
                "A non-original pack requires bounded source references.",
            )
        )
        return
    for index, claim in enumerate(claims):
        source_reference = claim.get("source") if isinstance(claim, Mapping) else None
        if not isinstance(source_reference, str) or not source_reference.strip():
            findings.append(
                _finding(
                    "PUBLICATION_SOURCE_REFERENCE_MISSING",
                    ["evidence", "claims", index, "source"],
                    "A non-original evidence claim is missing its source reference.",
                )
            )


def _check_age_routes(
    source: Mapping[str, Any], findings: list[dict[str, Any]]
) -> None:
    identity = source.get("identity", {})
    age = identity.get("declared_age") if isinstance(identity, Mapping) else None
    if (
        not isinstance(age, str)
        or not age.strip()
        or _UNUSABLE_DECLARATION.search(age) is not None
        or (
            _USABLE_AGE.fullmatch(age) is None
            and _AGE_CLASS.fullmatch(age) is None
        )
    ):
        findings.append(
            _finding(
                "PUBLICATION_AGE_DECLARATION_MISSING",
                ["identity", "declared_age"],
                "The pack does not contain a usable age declaration.",
            )
        )
    growth = source.get("growth", {})
    stages = growth.get("stages") if isinstance(growth, Mapping) else None
    stage_names = (
        {
            name.casefold()
            for name in stages
            if isinstance(name, str)
        }
        if isinstance(stages, Mapping)
        else set()
    )
    initial_stages = stage_names & _INITIAL_STAGE_NAMES
    later_stages = stage_names - _INITIAL_STAGE_NAMES
    if (
        not isinstance(stages, Mapping)
        or not initial_stages
        or not later_stages
    ):
        findings.append(
            _finding(
                "PUBLICATION_ROUTE_DECLARATION_MISSING",
                ["growth", "stages"],
                "The pack does not declare its relationship progression routes.",
            )
        )


def _normalize_compliance(
    compliance: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, bool]:
    if compliance is None:
        return None, True
    try:
        decoded = json.loads(canonical_bytes(compliance))
    except (KokoroError, OverflowError, TypeError, ValueError):
        return None, False
    if not isinstance(decoded, dict):
        return None, False
    snapshot = cast(dict[str, Any], decoded)
    if set(snapshot) != {
        "attestation_id",
        "reviewer_id",
        "scope",
        "conclusion",
        "source_hash",
        "compiled_hash",
        "basis_codes",
    }:
        return None, False
    basis = snapshot.get("basis_codes")
    basis_valid = (
        isinstance(basis, list)
        and 1 <= len(basis) <= 64
        and all(
            isinstance(item, str)
            and len(item) <= 128
            and _FINDING_CODE.fullmatch(item) is not None
            for item in basis
        )
    )
    valid = (
        isinstance(snapshot.get("attestation_id"), str)
        and _STABLE_ID.fullmatch(snapshot["attestation_id"]) is not None
        and len(snapshot["attestation_id"]) <= 128
        and isinstance(snapshot.get("reviewer_id"), str)
        and _STABLE_ID.fullmatch(snapshot["reviewer_id"]) is not None
        and len(snapshot["reviewer_id"]) <= 128
        and snapshot.get("scope") == "distribution_rights_reviewed"
        and snapshot.get("conclusion") in {"approved", "blocked"}
        and isinstance(snapshot.get("source_hash"), str)
        and _SHA256.fullmatch(snapshot["source_hash"]) is not None
        and isinstance(snapshot.get("compiled_hash"), str)
        and _SHA256.fullmatch(snapshot["compiled_hash"]) is not None
        and basis_valid
        and len(set(cast(list[str], basis))) == len(cast(list[str], basis))
        and (
            snapshot.get("conclusion") != "approved"
            or set(cast(list[str], basis)).issubset(_APPROVED_BASIS_CODES)
        )
    )
    return (snapshot, True) if valid else (None, False)


def _check_compliance(
    requested_visibility: str,
    compliance: dict[str, Any] | None,
    structurally_valid: bool,
    *,
    source_hash: str,
    compiled_hash: str,
    findings: list[dict[str, Any]],
) -> None:
    if requested_visibility == "private":
        return
    if not structurally_valid:
        findings.append(
            _finding(
                "PUBLICATION_COMPLIANCE_INVALID",
                ["compliance_attestation"],
                "The compliance attestation is not valid closed local evidence.",
            )
        )
        return
    if compliance is None:
        findings.append(
            _finding(
                "PUBLICATION_COMPLIANCE_REQUIRED",
                ["compliance_attestation"],
                "Public-candidate readiness requires a local compliance attestation.",
            )
        )
        return
    basis = set(cast(list[str], compliance["basis_codes"]))
    if (
        compliance["conclusion"] != "approved"
        or compliance["source_hash"] != source_hash
        or compliance["compiled_hash"] != compiled_hash
        or not basis
        or not basis.issubset(_APPROVED_BASIS_CODES)
    ):
        findings.append(
            _finding(
                "PUBLICATION_RIGHTS_NOT_ESTABLISHED",
                ["compliance_attestation"],
                "The local attestation does not establish distribution rights.",
            )
        )


def _closed_layout_paths(snapshot: _PackSnapshot) -> set[str]:
    manifest_bytes = snapshot.contents.get("character.yaml")
    if manifest_bytes is None:
        return set()
    manifest = parse_yaml_bytes(manifest_bytes)
    expected = {
        "character.yaml",
        "tests/multilingual.yaml",
        "tests/negative.yaml",
        "tests/positive.yaml",
        "tests/protected-spans.yaml",
    }
    for section in ("files", "locale_files", "scenario_files"):
        values = manifest.get(section)
        if isinstance(values, Mapping):
            expected.update(
                value for value in values.values() if isinstance(value, str)
            )
    return expected


def _publication_texts(
    snapshot: _PackSnapshot,
    compiled: Mapping[str, Any],
) -> Iterable[tuple[str, str]]:
    yield "compiled.json", canonical_bytes(compiled).decode("utf-8")
    for relative in snapshot.paths:
        if relative == _PROTECTED_SPANS_PATH:
            continue
        try:
            text = snapshot.contents[relative].decode("utf-8")
        except UnicodeError:
            continue
        yield relative, text


def _raw_comment_length(contents: bytes) -> int:
    try:
        text = contents.decode("utf-8")
    except UnicodeError:
        return 0
    try:
        scalar_spans = [
            (token.start_mark.index, token.end_mark.index)
            for token in yaml.scan(text, Loader=yaml.SafeLoader)
            if isinstance(token, yaml.tokens.ScalarToken)
        ]
    except (yaml.YAMLError, OverflowError, TypeError, ValueError):
        return 0
    length = 0
    offset = 0
    span_index = 0
    for physical_line in text.splitlines(keepends=True):
        line = physical_line.rstrip("\r\n")
        comment_start = _yaml_comment_start(line)
        absolute_start = offset + comment_start if comment_start is not None else -1
        if comment_start is not None:
            while (
                span_index < len(scalar_spans)
                and scalar_spans[span_index][1] <= absolute_start
            ):
                span_index += 1
            inside_scalar = (
                span_index < len(scalar_spans)
                and scalar_spans[span_index][0]
                <= absolute_start
                < scalar_spans[span_index][1]
            )
            if not inside_scalar:
                length += len(line) - comment_start - 1
        offset += len(physical_line)
    return length


def _yaml_comment_start(line: str) -> int | None:
    in_single_quote = False
    in_double_quote = False
    escaped = False
    index = 0
    while index < len(line):
        character = line[index]
        if in_double_quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_double_quote = False
        elif in_single_quote:
            if character == "'":
                if index + 1 < len(line) and line[index + 1] == "'":
                    index += 1
                else:
                    in_single_quote = False
        elif character == '"':
            in_double_quote = True
        elif character == "'":
            in_single_quote = True
        elif character == "#" and (index == 0 or line[index - 1].isspace()):
            return index
        index += 1
    return None


def _contains_secret(text: str) -> bool:
    return _SECRET_ASSIGNMENT.search(text) is not None or any(
        pattern.search(text) is not None for pattern in _KNOWN_CREDENTIALS
    )


def _contains_absolute_path(text: str) -> bool:
    return any(
        pattern.search(text) is not None
        for pattern in (
            _WINDOWS_ABSOLUTE_PATH,
            _UNC_PATH,
            _POSIX_ABSOLUTE_PATH,
            _FILE_URI_PATH,
        )
    )


def _walk_strings(
    value: Any,
    *,
    prefix: list[str | int] | None = None,
) -> Iterable[tuple[list[str | int], str]]:
    path = [] if prefix is None else list(prefix)
    if isinstance(value, str):
        yield path or ["value"], value
    elif isinstance(value, Mapping):
        for index, (key, item) in enumerate(value.items()):
            segment: str | int = key if isinstance(key, str) else index
            yield from _walk_strings(item, prefix=[*path, segment])
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_strings(item, prefix=[*path, index])


def _check_result(findings: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = _bounded_findings(findings)
    return {
        "passed": not any(item["severity"] == "error" for item in normalized),
        "findings": normalized,
    }


def _bounded_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = {
        canonical_bytes(item): item
        for item in findings
    }
    ordered = [unique[key] for key in sorted(unique)]
    if len(ordered) <= _MAX_FINDINGS:
        return ordered
    return [
        *ordered[: _MAX_FINDINGS - 1],
        _finding(
            "PUBLICATION_FINDINGS_TRUNCATED",
            ["checks"],
            "Additional blocking publication-readiness findings were omitted.",
        ),
    ]


def _blockers(checks: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    blockers = [
        item
        for name in _CHECK_NAMES
        for item in cast(list[dict[str, Any]], checks[name]["findings"])
        if item["severity"] == "error"
    ]
    bounded = _bounded_findings(blockers)
    return cast(list[dict[str, Any]], json.loads(canonical_bytes(bounded)))


def _finding(
    code: str,
    path: list[str | int],
    message: str,
    *,
    severity: str = "error",
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "path": path,
        "message": message,
    }


def _finding_path(relative: str) -> list[str | int]:
    digest = sha256(relative.encode("utf-8", errors="replace")).hexdigest()[:16]
    return ["pack", f"file-{digest}"]


def _finding_value_path(path: list[str | int]) -> list[str | int]:
    digest = sha256(canonical_bytes(path)).hexdigest()[:16]
    return ["value", f"path-{digest}"]


def _publication_source_tree_hash(snapshot: _PackSnapshot) -> str:
    executable = set(snapshot.executable_permissions)
    files = [
        {
            "path": relative,
            "size": len(snapshot.contents[relative]),
            "sha256": sha256(snapshot.contents[relative]).hexdigest(),
            "executable": relative in executable,
        }
        for relative in snapshot.paths
    ]
    return sha256(
        canonical_bytes({"schema_version": "1.0", "files": files})
    ).hexdigest()


def _canonical_matches(value: Any, expected: bytes) -> bool:
    try:
        return canonical_bytes(value) == expected
    except (KokoroError, OverflowError, TypeError, ValueError):
        return False


def _assert_mutation_probes(probes: Iterable[tuple[Any, bytes]]) -> None:
    if any(not _canonical_matches(value, expected) for value, expected in probes):
        raise KokoroError(
            "PACK_PUBLICATION_PIPELINE_MUTATION",
            "A publication-readiness dependency mutated a retained value.",
        )


class _PublicationBoundary:
    def __init__(
        self,
        source_root: Path,
        initial_snapshot: _PackSnapshot,
        captured: tuple[tuple[Any, bytes], ...],
    ) -> None:
        self._source_root = source_root
        self._initial_snapshot = initial_snapshot
        self._captured = captured

    def assert_unchanged(self) -> None:
        if any(
            not _canonical_matches(value, payload)
            for value, payload in self._captured
        ):
            raise KokoroError(
                "PACK_PUBLICATION_INPUT_MUTATION",
                "A caller-owned publication-readiness input changed during inspection.",
            )
        try:
            current_snapshot = _snapshot_pack(self._source_root)
        except (KokoroError, OSError, RuntimeError, ValueError) as error:
            raise KokoroError(
                "PACK_PUBLICATION_SOURCE_CHANGED",
                "The Character Pack changed during publication-readiness inspection.",
            ) from error
        if current_snapshot != self._initial_snapshot:
            raise KokoroError(
                "PACK_PUBLICATION_SOURCE_CHANGED",
                "The Character Pack changed during publication-readiness inspection.",
            )


class _BoundarySchemaRegistry:
    def __init__(
        self,
        delegate: SchemaRegistry,
        boundary: _PublicationBoundary,
    ) -> None:
        self._delegate = delegate
        self._boundary = boundary

    def validate(self, name: str, instance: Any) -> None:
        try:
            self._delegate.validate(name, instance)
        finally:
            self._boundary.assert_unchanged()


class _AuditedSchemaRegistry:
    def __init__(
        self,
        delegate: SchemaRegistry,
        boundary: _PublicationBoundary,
    ) -> None:
        self._delegate = delegate
        self._boundary = boundary
        self._validator_probes: list[tuple[Any, bytes]] = []
        self._pipeline_probes: list[tuple[Any, bytes]] = []
        self._failure: KokoroError | None = None

    def retain_pipeline_value(self, value: Any, expected: bytes) -> None:
        self._pipeline_probes.append((value, expected))

    def assert_clean(self) -> None:
        if self._failure is not None:
            raise self._failure
        self._boundary.assert_unchanged()
        if any(
            not _canonical_matches(value, expected)
            for value, expected in self._validator_probes
        ):
            self._failure = KokoroError(
                "PACK_PUBLICATION_VALIDATOR_MUTATION",
                "Schema validation mutated a publication-readiness artifact.",
            )
            raise self._failure
        try:
            _assert_mutation_probes(self._pipeline_probes)
        except KokoroError as error:
            self._failure = error
            raise

    def validate(self, name: str, instance: Any) -> None:
        instance_bytes = canonical_bytes(instance)
        detached = json.loads(instance_bytes)
        self._validator_probes.append((detached, instance_bytes))
        try:
            self._delegate.validate(name, detached)
        finally:
            try:
                self.assert_clean()
            except KokoroError as error:
                self._failure = error
                raise


__all__ = ["assess_publication_readiness", "publication_report_is_current"]
