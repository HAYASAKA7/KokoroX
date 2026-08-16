"""Deterministic hard validation for authored Character Packs."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
from typing import Any, Mapping, cast

from kokoroarc import __version__
from kokoroarc.authoring.validation import validate_authoring_pack
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes, compile_pack
from kokoroarc.packs.loader import load_source_pack_from_contents, parse_yaml_bytes
from kokoroarc.packs.security import PackLimits, scan_pack
from kokoroarc.runtime.planning import build_render_plan
from kokoroarc.runtime.validation import validate_rendered_output
from kokoroarc.schemas import SchemaRegistry
from kokoroarc.state.transitions import apply_event
from kokoroarc.testing.corpus import (
    PackTestCorpus,
    load_test_corpus_from_contents,
)


_FIRST_CLASS_LOCALES = frozenset({"zh-CN", "en-US", "ja-JP"})
_SEMANTIC_KEYS = frozenset(
    {"conclusion", "explanation", "recommendations", "warnings"}
)
_CHECK_NAMES = (
    "source_schema",
    "pack_layout",
    "provenance",
    "security",
    "compile",
    "fixture_structure",
    "locale_coverage",
    "protected_content",
    "state_replay",
)
_EXECUTABLE_SUFFIXES = frozenset(
    {
        ".bat",
        ".cmd",
        ".com",
        ".dll",
        ".exe",
        ".js",
        ".msi",
        ".ps1",
        ".py",
        ".sh",
        ".vbs",
    }
)
_SAFE_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+\Z", re.ASCII)
_MAX_FINDINGS = 256
_FileFingerprint = tuple[str, int, int, int, int, int, str]


@dataclass(frozen=True, slots=True)
class _PackSnapshot:
    root: Path
    fingerprints: tuple[_FileFingerprint, ...]
    contents: Mapping[str, bytes]
    executable_permissions: tuple[str, ...]

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(item[0] for item in self.fingerprints)


def run_hard_validation(
    root: Path,
    request: dict[str, Any],
    schemas: SchemaRegistry,
    *,
    research_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run deterministic, release-blocking checks over one authored pack.

    ``request`` is required because a source pack intentionally excludes private
    construction metadata and cannot distinguish dossier, researched, and
    hybrid modes on its own. Unsafe files, invalid YAML, invalid source schemas,
    and invalid corpus shapes are rejected before a report is constructed.
    """
    schemas.validate("character-build-request", request)
    request_bytes = canonical_bytes(request)
    request_snapshot = cast(dict[str, Any], json.loads(request_bytes))
    research_bundle_bytes = (
        canonical_bytes(research_bundle) if research_bundle is not None else None
    )
    research_bundle_snapshot = (
        cast(dict[str, Any], json.loads(research_bundle_bytes))
        if research_bundle_bytes is not None
        else None
    )

    initial_snapshot = _snapshot_pack(root)
    source = load_source_pack_from_contents(initial_snapshot.contents, schemas)
    corpus = load_test_corpus_from_contents(
        initial_snapshot.root, initial_snapshot.contents
    )
    schemas.validate("character-source", source)
    source_bytes = canonical_bytes(source)
    source_hash = sha256(source_bytes).hexdigest()
    source_snapshot = cast(dict[str, Any], json.loads(source_bytes))

    checks: dict[str, list[dict[str, Any]]] = {
        name: [] for name in _CHECK_NAMES
    }
    _check_layout(initial_snapshot, checks["pack_layout"])
    _check_security(initial_snapshot, checks["security"])
    provenance_request = cast(dict[str, Any], json.loads(request_bytes))
    provenance_source = cast(dict[str, Any], json.loads(source_bytes))
    provenance_bundle = (
        cast(dict[str, Any], json.loads(research_bundle_bytes))
        if research_bundle_bytes is not None
        else None
    )
    _check_provenance(
        provenance_request,
        provenance_source,
        schemas,
        provenance_bundle,
        checks["provenance"],
        checks["locale_coverage"],
    )
    if not (
        _canonical_matches(provenance_request, request_bytes)
        and _canonical_matches(provenance_source, source_bytes)
        and (
            provenance_bundle is None
            if research_bundle_bytes is None
            else _canonical_matches(provenance_bundle, research_bundle_bytes)
        )
    ):
        checks["provenance"].append(
            _finding(
                "PACK_PROVENANCE_INPUT_MUTATION",
                ["provenance"],
                "Provenance validation mutated a canonical probe input.",
            )
        )

    first_compile_input = cast(dict[str, Any], json.loads(source_bytes))
    first_compiled = compile_pack(first_compile_input, schemas)
    schemas.validate("compiled-pack", first_compiled)
    first_compiled_bytes = canonical_bytes(first_compiled)
    second_compile_input = cast(dict[str, Any], json.loads(source_bytes))
    second_compiled = compile_pack(second_compile_input, schemas)
    schemas.validate("compiled-pack", second_compiled)
    second_compiled_bytes = canonical_bytes(second_compiled)
    first_compile_input_stable = _canonical_matches(
        first_compile_input, source_bytes
    )
    second_compile_input_stable = _canonical_matches(
        second_compile_input, source_bytes
    )
    first_compiled_stable = _canonical_matches(
        first_compiled, first_compiled_bytes
    )
    second_compiled_stable = _canonical_matches(
        second_compiled, second_compiled_bytes
    )
    if not first_compile_input_stable or not second_compile_input_stable:
        checks["compile"].append(
            _finding(
                "PACK_COMPILE_INPUT_MUTATION",
                ["source"],
                "Compilation mutated its source input.",
            )
        )
    if not first_compiled_stable or not second_compiled_stable:
        checks["compile"].append(
            _finding(
                "PACK_COMPILE_OUTPUT_MUTATION",
                ["compiled"],
                "Compilation mutated a previously returned output.",
            )
        )
    compiled_snapshot = cast(dict[str, Any], json.loads(first_compiled_bytes))
    if compiled_snapshot.get("source_hash") != source_hash:
        checks["compile"].append(
            _finding(
                "PACK_COMPILED_SOURCE_MISMATCH",
                ["source_hash"],
                "Compiled output is not bound to the loaded source hash.",
            )
        )
    if first_compiled_bytes != second_compiled_bytes:
        checks["compile"].append(
            _finding(
                "PACK_COMPILE_NONDETERMINISTIC",
                ["compiled"],
                "Two compilations of the same source produced different bytes.",
            )
        )

    _check_fixture_structure(
        corpus,
        cast(dict[str, Any], json.loads(first_compiled_bytes)),
        checks["fixture_structure"],
    )
    _check_locale_coverage(
        corpus,
        cast(dict[str, Any], json.loads(first_compiled_bytes)),
        checks["locale_coverage"],
    )
    protected_content_hash = _check_protected_content(
        corpus, schemas, checks["protected_content"]
    )
    state_replay_hash = _check_state_replay(
        cast(dict[str, Any], json.loads(first_compiled_bytes)),
        schemas,
        checks["state_replay"],
    )

    source_snapshot_stable = _source_snapshot_stable(
        root,
        request,
        request_bytes,
        research_bundle,
        research_bundle_bytes,
        source_bytes,
        corpus,
        initial_snapshot,
        schemas,
    )
    normalized_checks = {
        name: _check_result(checks[name]) for name in _CHECK_NAMES
    }
    deterministic = (
        normalized_checks["compile"]["passed"]
        and normalized_checks["state_replay"]["passed"]
    )
    passed = (
        source_snapshot_stable
        and deterministic
        and all(result["passed"] for result in normalized_checks.values())
    )
    visibility = (
        "public_candidate"
        if request_snapshot.get("requested_visibility") == "public"
        else "private"
    )
    report = {
        "schema_version": "1.0",
        "artifact_id": (
            f"{source_snapshot['namespace']}/{source_snapshot['character_id']}/"
            "release/hard-validation"
        ),
        "created_by": {"component": "kokoroarc", "version": __version__},
        "namespace": source_snapshot["namespace"],
        "character_id": source_snapshot["character_id"],
        "character_version": source_snapshot["character_version"],
        "mode": request_snapshot["mode"],
        "visibility": visibility,
        "source_artifact_id": source_snapshot["artifact_id"],
        "source_hash": source_hash,
        "compiled_artifact_id": compiled_snapshot["artifact_id"],
        "compiled_hash": sha256(first_compiled_bytes).hexdigest(),
        "corpus_hash": corpus.corpus_hash,
        "check_input_hashes": {
            "request_hash": sha256(request_bytes).hexdigest(),
            "source_tree_hash": _source_tree_hash(initial_snapshot),
            "provenance_hash": _canonical_hash(
                {
                    "request": request_snapshot,
                    "research_bundle": research_bundle_snapshot,
                }
            ),
            "protected_content_hash": protected_content_hash,
            "state_replay_hash": state_replay_hash,
        },
        "checks": normalized_checks,
        "source_snapshot_stable": source_snapshot_stable,
        "deterministic": deterministic,
        "passed": passed,
    }
    schemas.validate("pack-hard-validation-report", report)
    return cast(dict[str, Any], json.loads(canonical_bytes(report)))


def hard_report_is_current(
    report: Any,
    root: Path,
    request: dict[str, Any],
    schemas: SchemaRegistry,
    *,
    research_bundle: dict[str, Any] | None = None,
) -> bool:
    """Return whether a report exactly matches a fresh deterministic run."""
    try:
        schemas.validate("pack-hard-validation-report", report)
        current = run_hard_validation(
            root,
            request,
            schemas,
            research_bundle=research_bundle,
        )
        return canonical_bytes(report) == canonical_bytes(current)
    except (
        KokoroError,
        OSError,
        OverflowError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        return False


def _check_provenance(
    request: dict[str, Any],
    source: dict[str, Any],
    schemas: SchemaRegistry,
    research_bundle: dict[str, Any] | None,
    provenance_findings: list[dict[str, Any]],
    locale_findings: list[dict[str, Any]],
) -> None:
    mode = request.get("mode")
    report = validate_authoring_pack(
        request,
        source,
        schemas,
        research_bundle=research_bundle,
    )
    for item in report["hard_failures"]:
        target = (
            locale_findings
            if item["code"] == "AUTHORING_LOCALE_MISSING"
            else provenance_findings
        )
        target.append(_domain_finding(item, "error"))
    for item in report["advisory_findings"]:
        provenance_findings.append(_domain_finding(item, "warning"))
    if mode != "original":
        provenance_findings.append(
            _finding(
                "PACK_PROVENANCE_PRIVATE_ONLY",
                ["evidence"],
                "Non-original evidence remains private by default.",
                severity="warning",
            )
        )


def _check_layout(
    snapshot: _PackSnapshot, findings: list[dict[str, Any]]
) -> None:
    manifest = parse_yaml_bytes(snapshot.contents["character.yaml"])
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
    actual = set(snapshot.paths)
    for relative in sorted(expected - actual):
        findings.append(
            _finding(
                "PACK_LAYOUT_MISSING_FILE",
                _path_segments(relative),
                "A manifest or test-corpus file is missing from the pack.",
            )
        )
    for relative in sorted(actual - expected):
        findings.append(
            _finding(
                "PACK_LAYOUT_UNEXPECTED_FILE",
                _path_segments(relative),
                "The pack contains a file outside its closed layout.",
            )
        )


def _check_security(
    snapshot: _PackSnapshot, findings: list[dict[str, Any]]
) -> None:
    for relative in snapshot.paths:
        if Path(relative).suffix.casefold() in _EXECUTABLE_SUFFIXES:
            findings.append(
                _finding(
                    "PACK_EXECUTABLE_FILE",
                    _path_segments(relative),
                    "Character Packs must not contain executable-shaped files.",
                )
            )
    for relative in snapshot.executable_permissions:
        findings.append(
            _finding(
                "PACK_EXECUTABLE_PERMISSION",
                _path_segments(relative),
                "Character Pack data files must not have executable permissions.",
            )
        )


def _check_fixture_structure(
    corpus: PackTestCorpus,
    compiled: dict[str, Any],
    findings: list[dict[str, Any]],
) -> None:
    positive = corpus.document("tests/positive.yaml")
    negative = corpus.document("tests/negative.yaml")
    scenarios = compiled.get("scenarios", {})
    positive_scenario = positive["scenario"]
    negative_scenario = negative["scenario"]
    if positive_scenario != negative_scenario:
        findings.append(
            _finding(
                "PACK_TEST_SCENARIO_MISMATCH",
                ["tests", "negative.yaml", "scenario"],
                "Positive and negative fixtures must exercise the same scenario.",
            )
        )
    for file_name, scenario in (
        ("positive.yaml", positive_scenario),
        ("negative.yaml", negative_scenario),
    ):
        if scenario not in scenarios:
            findings.append(
                _finding(
                    "PACK_TEST_SCENARIO_MISSING",
                    ["tests", file_name, "scenario"],
                    "A fixture scenario is not present in the compiled pack.",
                )
            )
    positive_ids = {case["case_id"] for case in positive["cases"]}
    for index, case in enumerate(negative["cases"]):
        if case["case_id"] in positive_ids:
            findings.append(
                _finding(
                    "PACK_TEST_CASE_ID_REUSED",
                    ["tests", "negative.yaml", "cases", index, "case_id"],
                    "Positive and negative fixture IDs must be distinct.",
                )
            )


def _check_locale_coverage(
    corpus: PackTestCorpus,
    compiled: dict[str, Any],
    findings: list[dict[str, Any]],
) -> None:
    multilingual = corpus.document("tests/multilingual.yaml")
    locales = multilingual["expected_locales"]
    if set(locales) != _FIRST_CLASS_LOCALES or len(locales) != 3:
        findings.append(
            _finding(
                "PACK_TEST_LOCALE_COVERAGE_MISSING",
                ["tests", "multilingual.yaml", "expected_locales"],
                "The multilingual fixture must cover zh-CN, en-US, and ja-JP.",
            )
        )
    if multilingual["semantic_key"] not in _SEMANTIC_KEYS:
        findings.append(
            _finding(
                "PACK_TEST_SEMANTIC_KEY_UNKNOWN",
                ["tests", "multilingual.yaml", "semantic_key"],
                "The multilingual fixture names an unknown semantic field.",
            )
        )
    if multilingual["intent"] not in compiled.get("expressions", {}):
        findings.append(
            _finding(
                "PACK_TEST_INTENT_MISSING",
                ["tests", "multilingual.yaml", "intent"],
                "The multilingual fixture intent is absent from the compiled pack.",
            )
        )
    positive = corpus.document("tests/positive.yaml")
    for index, case in enumerate(positive["cases"]):
        case_locales = case["expected_locales"]
        if set(case_locales) != _FIRST_CLASS_LOCALES or len(case_locales) != 3:
            findings.append(
                _finding(
                    "PACK_TEST_CASE_LOCALE_COVERAGE_MISSING",
                    ["tests", "positive.yaml", "cases", index, "expected_locales"],
                    "Each positive fixture must cover all first-class locales.",
                )
            )


def _check_protected_content(
    corpus: PackTestCorpus,
    schemas: SchemaRegistry,
    findings: list[dict[str, Any]],
) -> str:
    fixture = corpus.document("tests/protected-spans.yaml")
    multilingual = corpus.document("tests/multilingual.yaml")
    spans = list(fixture["immutable_spans"])
    warning = fixture["required_warning_id"]
    semantic = {
        "schema_version": "1.0",
        "artifact_id": "semantic/pack-hard-validation",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "scenario": "debugging",
        "conclusion": "The deterministic hard-validation probe completed.",
        "explanation": list(spans),
        "recommendations": ["Preserve all declared test constraints."],
        "warnings": [warning],
        "immutable_spans": list(spans),
        "format_constraints": ["preserve_protected_content"],
    }
    policy = {
        "schema_version": "1.0",
        "artifact_id": "policy/pack-hard-validation",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "mode": "single",
        "primary_language": "en-US",
        "channels": {
            "character_dialogue": "en-US",
            "technical_explanation": "en-US",
            "recommendations": "en-US",
            "warnings": "en-US",
            "technical_terms": "preserve",
            "commands": "preserve",
            "file_paths": "preserve",
            "exact_errors": "preserve",
            "code_identifiers": "preserve",
        },
        "mixing": {"max_switches": 0, "min_primary_ratio": 1.0},
        "subtitles": {"enabled": False, "language": None},
    }
    check_input_hash = _canonical_hash(
        {
            "fixture": fixture,
            "intent": multilingual["intent"],
            "semantic": semantic,
            "policy": policy,
        }
    )
    semantic_bytes = canonical_bytes(semantic)
    policy_bytes = canonical_bytes(policy)
    try:
        semantic_for_plan = cast(dict[str, Any], json.loads(semantic_bytes))
        policy_for_plan = cast(dict[str, Any], json.loads(policy_bytes))
        schemas.validate("semantic-result", semantic_for_plan)
        schemas.validate("language-policy", policy_for_plan)
        plan = build_render_plan(
            semantic_for_plan,
            policy_for_plan,
            expression_intent=multilingual["intent"],
        )
        schemas.validate("render-plan", plan)
        plan_bytes = canonical_bytes(plan)
        plan_snapshot = cast(dict[str, Any], json.loads(plan_bytes))
        rendered = {
            "text": "\n".join([semantic["conclusion"], *spans, warning]),
            "segments": [
                {
                    "id": segment["id"],
                    "channel": segment["channel"],
                    "target_language": segment["target_language"],
                    "semantic_keys": list(segment["semantic_keys"]),
                }
                for segment in plan_snapshot["segments"]
            ],
            "switch_count": 0,
        }
        rendered_bytes = canonical_bytes(rendered)
        rendered_for_validation = cast(
            dict[str, Any], json.loads(rendered_bytes)
        )
        semantic_for_validation = cast(
            dict[str, Any], json.loads(semantic_bytes)
        )
        plan_for_validation = cast(dict[str, Any], json.loads(plan_bytes))
        validation = validate_rendered_output(
            rendered_for_validation,
            semantic_for_validation,
            plan_for_validation,
        )
        schemas.validate("validation-result", validation)
        validation_snapshot = cast(
            dict[str, Any], json.loads(canonical_bytes(validation))
        )
        inputs_stable = (
            _canonical_matches(semantic_for_plan, semantic_bytes)
            and _canonical_matches(policy_for_plan, policy_bytes)
            and _canonical_matches(rendered_for_validation, rendered_bytes)
            and _canonical_matches(semantic_for_validation, semantic_bytes)
            and _canonical_matches(plan_for_validation, plan_bytes)
        )
    except (KokoroError, KeyError, TypeError, ValueError, OverflowError):
        findings.append(
            _finding(
                "PACK_PROTECTED_PIPELINE_ERROR",
                ["tests", "protected-spans.yaml"],
                "The protected-content validation pipeline rejected its inputs.",
            )
        )
        return check_input_hash

    if not inputs_stable:
        findings.append(
            _finding(
                "PACK_PROTECTED_INPUT_MUTATION",
                ["validation"],
                "The protected-content pipeline mutated a canonical probe input.",
            )
        )
    if plan_snapshot["protected_spans"] != spans:
        findings.append(
            _finding(
                "PACK_PROTECTED_SPAN_MISMATCH",
                ["tests", "protected-spans.yaml", "immutable_spans"],
                "The render plan changed the declared protected spans.",
            )
        )
    warning_segments = [
        segment
        for segment in plan_snapshot["segments"]
        if segment["channel"] == "warnings"
        and "warnings" in segment["semantic_keys"]
    ]
    if not warning_segments or warning not in rendered["text"]:
        findings.append(
            _finding(
                "PACK_REQUIRED_WARNING_MISSING",
                ["tests", "protected-spans.yaml", "required_warning_id"],
                "The required warning was not preserved through render planning.",
            )
        )
    if validation_snapshot["valid"] is not True:
        findings.append(
            _finding(
                "PACK_RUNTIME_VALIDATION_FAILED",
                ["validation"],
                "Runtime validation rejected the protected-content probe.",
            )
        )
    return check_input_hash


def _check_state_replay(
    compiled: dict[str, Any],
    schemas: SchemaRegistry,
    findings: list[dict[str, Any]],
) -> str:
    growth = compiled["growth"]
    initial = {
        "schema_version": "1.0",
        "artifact_id": "state/pack-hard-validation",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "revision": 0,
        "turn_index": 0,
        "dimensions": {
            "familiarity": 0.0,
            "trust": 0.0,
            "collaboration": 0.0,
            "tension": 0.0,
        },
        "stage": "unknown",
        "applied_event_ids": [],
        "recent_novelty": {},
    }
    event = {
        "schema_version": "1.0",
        "artifact_id": "event/pack-hard-validation",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "event_id": "pack-hard-validation",
        "turn_id": "pack-hard-validation",
        "origin": "verified_task_outcome",
        "novelty_key": "pack-hard-validation",
        "expected_state_revision": 0,
        "evaluator_version": "pack-hard-v1",
        "evidence": {"kind": "test_result", "reference": "pack-hard-validation"},
        "confidence": 1.0,
        "effects": {"trust": 1.0},
    }
    max_delta = float(growth.get("max_delta_per_event", 4.0))
    repetition_window = int(growth.get("repetition_window_turns", 3))
    check_input_hash = _canonical_hash(
        {
            "initial_state": initial,
            "event": event,
            "max_delta": max_delta,
            "repetition_window": repetition_window,
        }
    )
    initial_bytes = canonical_bytes(initial)
    event_bytes = canonical_bytes(event)
    expected = cast(dict[str, Any], json.loads(initial_bytes))
    confidence = min(max(float(event["confidence"]), 0.0), 1.0)
    proposed = float(event["effects"]["trust"]) * confidence
    delta = min(max(proposed, -max_delta), max_delta)
    expected["dimensions"]["trust"] = min(
        max(float(expected["dimensions"]["trust"]) + delta, 0.0),
        100.0,
    )
    expected["applied_event_ids"].append(event["event_id"])
    expected["revision"] += 1
    expected["turn_index"] += 1
    expected["recent_novelty"][event["novelty_key"]] = expected["turn_index"]
    expected_bytes = canonical_bytes(expected)
    try:
        schemas.validate("relationship-state", initial)
        schemas.validate("interaction-event", event)
        first = apply_event(
            initial,
            event,
            max_delta=max_delta,
            repetition_window=repetition_window,
        )
        schemas.validate("relationship-state", first)
        first_bytes = canonical_bytes(first)
        replay = apply_event(
            initial,
            event,
            max_delta=max_delta,
            repetition_window=repetition_window,
        )
        schemas.validate("relationship-state", replay)
        replay_bytes = canonical_bytes(replay)
        idempotent = apply_event(
            first,
            event,
            max_delta=max_delta,
            repetition_window=repetition_window,
        )
        schemas.validate("relationship-state", idempotent)
        idempotent_bytes = canonical_bytes(idempotent)
    except (KokoroError, KeyError, TypeError, ValueError, OverflowError):
        findings.append(
            _finding(
                "PACK_STATE_PIPELINE_ERROR",
                ["growth"],
                "The relationship-state replay probe could not be validated.",
            )
        )
        return check_input_hash
    inputs_stable = (
        _canonical_matches(initial, initial_bytes)
        and _canonical_matches(event, event_bytes)
        and _canonical_matches(first, first_bytes)
    )
    outputs_stable = _canonical_matches(
        replay, replay_bytes
    ) and _canonical_matches(idempotent, idempotent_bytes)
    if not inputs_stable:
        findings.append(
            _finding(
                "PACK_STATE_INPUT_MUTATION",
                ["growth"],
                "The relationship-state engine mutated a probe input.",
            )
        )
    if not outputs_stable:
        findings.append(
            _finding(
                "PACK_STATE_OUTPUT_MUTATION",
                ["growth"],
                "The relationship-state engine mutated a previously returned output.",
            )
        )
    if first_bytes != expected_bytes:
        findings.append(
            _finding(
                "PACK_STATE_TRANSITION_INVALID",
                ["growth"],
                "The relationship-state probe did not apply its declared event.",
            )
        )
    if not (first_bytes == replay_bytes == idempotent_bytes):
        findings.append(
            _finding(
                "PACK_STATE_REPLAY_DRIFT",
                ["growth"],
                "Replaying the same interaction event changed relationship state.",
            )
        )
    return check_input_hash


def _source_snapshot_stable(
    root: Path,
    request: dict[str, Any],
    request_bytes: bytes,
    research_bundle: dict[str, Any] | None,
    research_bundle_bytes: bytes | None,
    source_bytes: bytes,
    corpus: PackTestCorpus,
    initial_snapshot: _PackSnapshot,
    schemas: SchemaRegistry,
) -> bool:
    try:
        final_snapshot = _snapshot_pack(root)
        final_source = load_source_pack_from_contents(
            final_snapshot.contents, schemas
        )
        final_corpus = load_test_corpus_from_contents(
            final_snapshot.root, final_snapshot.contents
        )
        return (
            canonical_bytes(request) == request_bytes
            and (
                canonical_bytes(research_bundle)
                if research_bundle is not None
                else None
            )
            == research_bundle_bytes
            and canonical_bytes(final_source) == source_bytes
            and final_corpus.canonical_bytes == corpus.canonical_bytes
            and final_snapshot.fingerprints == initial_snapshot.fingerprints
        )
    except (
        KokoroError,
        OSError,
        OverflowError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        return False


def _snapshot_pack(root: Path) -> _PackSnapshot:
    limits = PackLimits()
    files = scan_pack(root, limits)
    try:
        resolved_root = Path(root).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise KokoroError(
            "PACK_SCAN_FAILED",
            "Character pack filesystem scan failed.",
            details={"reason": type(error).__name__},
        ) from None
    fingerprints: list[_FileFingerprint] = []
    contents: dict[str, bytes] = {}
    executable_permissions: list[str] = []
    total_bytes = 0
    for path in files:
        try:
            relative = path.relative_to(resolved_root).as_posix()
        except ValueError:
            raise KokoroError(
                "UNSAFE_PACK_PATH",
                "Character pack contains an unsafe filesystem path.",
            ) from None
        data, file_stat = _read_stable_file(
            path,
            max_file_bytes=limits.max_file_bytes,
            max_total_bytes=limits.max_total_bytes - total_bytes,
        )
        total_bytes += len(data)
        fingerprints.append(
            (
                relative,
                file_stat.st_dev,
                file_stat.st_ino,
                stat.S_IFMT(file_stat.st_mode),
                file_stat.st_size,
                file_stat.st_mtime_ns,
                sha256(data).hexdigest(),
            )
        )
        contents[relative] = data
        if os.name == "posix" and file_stat.st_mode & 0o111:
            executable_permissions.append(relative)
    return _PackSnapshot(
        root=resolved_root,
        fingerprints=tuple(fingerprints),
        contents=MappingProxyType(contents),
        executable_permissions=tuple(executable_permissions),
    )


def _read_stable_file(
    path: Path,
    *,
    max_file_bytes: int,
    max_total_bytes: int,
) -> tuple[bytes, os.stat_result]:
    descriptor: int | None = None
    try:
        initial = path.lstat()
        if (
            not stat.S_ISREG(initial.st_mode)
            or stat.S_ISLNK(initial.st_mode)
            or initial.st_nlink != 1
        ):
            raise KokoroError(
                "UNSAFE_PACK_PATH",
                "Character pack contains an unsafe filesystem path.",
            )
        if initial.st_size > max_file_bytes:
            raise _snapshot_limit_exceeded("max_file_bytes")
        if initial.st_size > max_total_bytes:
            raise _snapshot_limit_exceeded("max_total_bytes")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(
            os, "O_NOFOLLOW", 0
        )
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if _stat_identity(initial) != _stat_identity(opened):
            raise _pack_changed()
        chunks: list[bytes] = []
        bytes_read = 0
        read_limit = min(max_file_bytes, max_total_bytes)
        while True:
            chunk = os.read(
                descriptor,
                min(64 * 1024, read_limit + 1 - bytes_read),
            )
            if not chunk:
                break
            bytes_read += len(chunk)
            if bytes_read > max_file_bytes:
                raise _snapshot_limit_exceeded("max_file_bytes")
            if bytes_read > max_total_bytes:
                raise _snapshot_limit_exceeded("max_total_bytes")
            chunks.append(chunk)
        final_opened = os.fstat(descriptor)
    except KokoroError:
        raise
    except OSError:
        raise KokoroError(
            "PACK_SCAN_FAILED",
            "Character pack filesystem scan failed.",
        ) from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                raise _pack_changed() from None
    try:
        final = path.lstat()
    except OSError:
        raise _pack_changed() from None
    data = b"".join(chunks)
    if (
        len(data) != initial.st_size
        or _stat_identity(initial) != _stat_identity(final_opened)
        or _stat_identity(initial) != _stat_identity(final)
    ):
        raise _pack_changed()
    return data, final


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
    )


def _pack_changed() -> KokoroError:
    return KokoroError(
        "PACK_CHANGED",
        "Character pack changed while hard validation was running.",
    )


def _snapshot_limit_exceeded(limit: str) -> KokoroError:
    return KokoroError(
        "PACK_LIMIT_EXCEEDED",
        "Character pack filesystem limit exceeded.",
        details={"limit": limit},
    )


def _source_tree_hash(snapshot: _PackSnapshot) -> str:
    files = [
        {"path": item[0], "size": item[4], "sha256": item[6]}
        for item in snapshot.fingerprints
    ]
    return _canonical_hash({"schema_version": "1.0", "files": files})


def _canonical_hash(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _canonical_matches(value: Any, expected: bytes) -> bool:
    try:
        return canonical_bytes(value) == expected
    except (KokoroError, RecursionError):
        return False


def _domain_finding(item: Mapping[str, Any], severity: str) -> dict[str, Any]:
    return _finding(
        str(item.get("code", "PACK_DOMAIN_VALIDATION_FAILED")),
        item.get("path", []),
        str(item.get("message", "A domain validation check failed.")),
        severity=severity,
    )


def _finding(
    code: str,
    path: Any,
    message: str,
    *,
    severity: str = "error",
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "path": _normalize_path(path),
        "message": _normalize_message(message),
    }


def _normalize_path(value: Any) -> list[str | int]:
    items = value if isinstance(value, (list, tuple)) else []
    normalized: list[str | int] = []
    for item in items[:32]:
        if isinstance(item, bool):
            normalized.append(str(item).lower())
        elif isinstance(item, int) and 0 <= item <= 1_000_000:
            normalized.append(item)
        else:
            text = str(item).strip()[:128]
            if not text:
                text = "field"
            if _SAFE_PATH_SEGMENT.fullmatch(text) is None:
                text = re.sub(r"[^A-Za-z0-9._-]", "_", text)[:128] or "field"
            normalized.append(text)
    return normalized


def _normalize_message(value: str) -> str:
    text = " ".join(str(value).split())[:1000]
    return text or "A hard-validation check failed."


def _path_segments(relative: str) -> list[str]:
    return [segment for segment in relative.replace("\\", "/").split("/") if segment]


def _check_result(findings: list[dict[str, Any]]) -> dict[str, Any]:
    unique = {
        canonical_bytes(finding): finding for finding in findings
    }
    passed = not any(
        item["severity"] == "error" for item in unique.values()
    )
    ordered = sorted(
        unique.values(),
        key=lambda item: (
            item["severity"] != "error",
            item["code"],
            json.dumps(item["path"], ensure_ascii=False, separators=(",", ":")),
            item["message"],
        ),
    )[:_MAX_FINDINGS]
    return {
        "passed": passed,
        "findings": ordered,
    }


__all__ = ["hard_report_is_current", "run_hard_validation"]
