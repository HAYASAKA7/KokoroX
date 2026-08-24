from __future__ import annotations

import builtins
from copy import deepcopy
from dataclasses import FrozenInstanceError, dataclass, fields, replace
import gc
from hashlib import sha256
import importlib
import inspect
import io
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Literal, get_type_hints
import weakref

import pytest


SKILLS_ROOT = Path(__file__).resolve().parent
FIXTURES_ROOT = SKILLS_ROOT.parent / "fixtures"
sys.path.insert(0, str(SKILLS_ROOT))

import complete_suite_command_plan as command_plan  # noqa: E402
import complete_suite_command_policy as command_policy  # noqa: E402


ZERO_SHA256 = "0" * 64
CHUNK_BYTES = 64 * 1024
DOCUMENT_BYTES = 4 * 1024 * 1024
SESSION_BYTES = 64 * 1024 * 1024
EVIDENCE_VERSION = "complete-suite-session-command-evidence-v1"


def _binding():
    try:
        return importlib.import_module("complete_suite_cli_binding")
    except ModuleNotFoundError as exc:
        if exc.name == "complete_suite_cli_binding":
            pytest.fail(
                "Task 6 RED: complete_suite_cli_binding is not implemented",
                pytrace=False,
            )
        raise


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _pack_list_document(*installed: object) -> dict[str, object]:
    return {
        "ok": True,
        "scope": "global",
        "workspace_id": None,
        "installed": list(installed),
        "activates_character": False,
    }


def _fixture(*parts: str) -> dict[str, Any]:
    return json.loads(
        (FIXTURES_ROOT.joinpath(*parts)).read_text(encoding="utf-8")
    )


def _valid_success_documents() -> dict[tuple[str, ...], dict[str, Any]]:
    original_request = _fixture("authoring", "original-request.json")
    build_report = {
        "schema_version": "1.0",
        "artifact_id": "original/rin-aster/build-validation",
        "created_by": {"component": "kokoroarc", "version": "0.0.0.dev0"},
        "hard_failures": [],
        "advisory_findings": [
            {
                "code": "AUTHORING_SPARSE_EXAMPLES",
                "path": ["expressions"],
                "message": "More examples would improve coverage.",
            }
        ],
        "locale_coverage": {"zh-CN": True, "en-US": True, "ja-JP": True},
        "provenance_counts": {
            "evidence": 1,
            "derived_profile": 2,
            "user_override": 0,
        },
        "valid": True,
    }
    research_request = _fixture("research", "complete", "request.json")
    research_report = _fixture(
        "research", "complete", "validation-report.json"
    )
    research_bundle = _fixture("research", "complete", "bundle.json")
    bundle_summary = {
        field: deepcopy(research_bundle[field])
        for field in (
            "artifact_id",
            "request_hash",
            "workspace_hash",
            "validation_report_hash",
            "bundle_hash",
            "build_status",
            "visibility",
            "activation_allowed",
            "authoring_allowed",
            "conflicts",
            "limitations",
            "blocking_reasons",
        )
    }
    bundle_summary["coverage_summary"] = deepcopy(
        research_report["coverage_summary"]
    )
    standalone = _fixture("standalone-contracts", "private-global.json")
    runtime = _fixture("schema", "runtime-artifacts.json")
    registry = standalone["installed_registry"]
    registry_identity, registry_value = next(iter(registry["entries"].items()))
    installed = {"registry_identity": registry_identity, **deepcopy(registry_value)}
    install_plan = {
        "schema_version": "1.0",
        "operation": "install",
        "scope": "global",
        "workspace_id": None,
        "registry_identity": registry_identity,
        "installation_id": installed["installation_id"],
        "archive_sha256": installed["archive_sha256"],
        "manifest_sha256": installed["manifest_sha256"],
        "compiled_artifact_id": installed["compiled_artifact_id"],
        "compiled_sha256": installed["compiled_sha256"],
        "visibility": installed["visibility"],
        "relative_path": installed["relative_path"],
        "registry_revision_before": 0,
        "registry_revision_after": 1,
        "idempotent": False,
        "will_write": True,
        "activates_character": False,
    }
    runtime_context = {
        "character_id": "rin-aster",
        "character_version": "1.0.0",
        "identity": {
            "display_name": "Rin Aster",
            "declared_age": "adult",
            "role": "systems architect",
            "worldview": ["clarity before confidence"],
            "non_negotiables": ["never fabricates certainty"],
        },
        "effective_profile": {"composure": 0.9, "warmth": 0.38},
        "locales": {
            "zh-CN": {
                "register": "calm and direct",
                "addressing": {"unknown": "you", "trusted": "you"},
            }
        },
        "scenarios": {
            "debugging": {
                "first_action": "inspect evidence",
                "intensity_cap": "balanced",
            }
        },
        "expressions": {
            "restrained_diagnosis": {"zh-CN": ["Cause identified."]}
        },
        "growth": {
            "dimensions": ["familiarity", "trust", "collaboration", "tension"]
        },
        "state": {
            "revision": 7,
            "stage": "acquainted",
            "dimensions": {
                "familiarity": 24.0,
                "trust": 31,
                "collaboration": 42.5,
                "tension": 4,
            },
        },
    }
    digest = "a" * 64
    documents: dict[tuple[str, ...], dict[str, Any]] = {
        ("pack", "validate"): {
            "ok": True,
            "artifact_id": "original/rin-aster/source",
            "character_id": "rin-aster",
            "character_version": "1.0.0",
        },
        ("pack", "compile"): {
            "ok": True,
            "path": r"outputs\compiled.json",
            "character_id": "rin-aster",
            "character_version": "1.0.0",
            "source_hash": digest,
            "artifact_id": "original/rin-aster/compiled",
        },
        ("pack", "install"): {
            "ok": True,
            "dry_run": True,
            "plan": install_plan,
            "activates_character": False,
        },
        ("pack", "list"): {
            "ok": True,
            "scope": "global",
            "workspace_id": None,
            "installed": [installed],
            "activates_character": False,
        },
        ("pack", "export"): {
            "ok": True,
            "path": r"outputs\rin-aster.karc",
            "archive_sha256": digest,
            "visibility": "private",
        },
        ("pack", "test"): {
            "ok": True,
            "path": r"reports\hard.json",
            "artifact_id": "original/rin-aster/hard-validation",
            "passed": True,
            "source_hash": digest,
            "compiled_hash": digest,
            "report_hash": digest,
        },
        ("pack", "soft-eval"): {
            "ok": True,
            "path": r"reports\soft.json",
            "artifact_id": "original/rin-aster/soft-evaluation",
            "passed": True,
            "report_hash": digest,
        },
        ("pack", "promote"): {
            "ok": True,
            "path": r"reports\promotion.json",
            "bundle_path": "reports",
            "artifact_id": "original/rin-aster/promotion",
            "promotion_id": "promotion-01",
            "to_status": "verified",
            "activation_allowed": True,
            "record_hash": digest,
        },
        ("pack", "publication-check"): {
            "ok": True,
            "path": r"reports\publication.json",
            "artifact_id": "original/rin-aster/publication",
            "ready_for_private_export": True,
            "ready_for_publication": True,
            "blockers": [],
            "report_hash": digest,
        },
        ("character", "request", "validate"): {
            "ok": True,
            "request": original_request,
        },
        ("character", "draft", "validate"): {
            "ok": True,
            "valid": True,
            "validation_report": build_report,
        },
        ("character", "draft", "compile"): {
            "ok": True,
            "path": r"outputs\draft.json",
            "artifact_id": "original/rin-aster/draft/0123456789abcdef",
            "request_hash": digest,
            "source_pack_hash": digest,
            "validation_report_hash": digest,
            "build_status": "draft",
            "visibility": "private",
            "activation_allowed": False,
            "validation_report": deepcopy(build_report),
        },
        ("research", "request", "validate"): {
            "ok": True,
            "request": research_request,
        },
        ("research", "workspace", "validate"): {
            "ok": True,
            "valid": True,
            "workspace_hash": research_bundle["workspace_hash"],
            "validation_report": research_report,
        },
        ("research", "bundle", "compile"): {
            "ok": True,
            "path": r"outputs\research-bundle.json",
            **deepcopy(bundle_summary),
        },
        ("research", "bundle", "validate"): {
            "ok": True,
            "valid": True,
            **deepcopy(bundle_summary),
        },
        ("config", "default", "set"): {
            "ok": True,
            "default": deepcopy(standalone["default_config"]),
            "activates_character": False,
        },
        ("config", "default", "show"): {
            "ok": True,
            "default": deepcopy(standalone["default_config"]),
            "activates_character": False,
        },
        ("session", "start"): {
            "ok": True,
            "session": deepcopy(runtime["session_manifest"]),
        },
        ("session", "show"): {
            "ok": True,
            "session": deepcopy(runtime["session_manifest"]),
        },
        ("consent", "show"): {
            "ok": True,
            "consent": deepcopy(standalone["persistence_consent"]),
        },
        ("state", "preview"): {
            "ok": True,
            "state": deepcopy(runtime["relationship_state"]),
        },
        ("state", "apply"): {
            "ok": True,
            "state": deepcopy(runtime["relationship_state"]),
        },
        ("state", "export"): {"ok": True, "export_sha256": digest},
        ("memory", "add"): {
            "ok": True,
            "memory_reference": deepcopy(standalone["memory_reference"]),
        },
        ("memory", "list"): {
            "ok": True,
            "memory_references": [
                {
                    "reference": deepcopy(standalone["memory_reference"]),
                    "active_consent_generation": True,
                }
            ],
        },
        ("memory", "remove"): {
            "ok": True,
            "dry_run": True,
            "plan": {
                "action": "remove_memory_reference",
                "host_memory_id": "host-memory-preference-01",
                "memory_reference_id": "rin-aster-preference-01",
                "will_remove": True,
            },
        },
        ("policy", "compile"): {
            "ok": True,
            "policy": deepcopy(runtime["language_policy"]),
        },
        ("runtime", "context"): {"ok": True, "context": runtime_context},
        ("runtime", "plan"): {
            "ok": True,
            "plan": deepcopy(runtime["render_plan"]),
        },
        ("runtime", "validate"): {
            "ok": True,
            "validation": deepcopy(runtime["validation_result"]),
        },
    }
    assert set(documents) == set(command_policy._CLI_ACTIONS)
    return documents


def _literal(value: str) -> dict[str, object]:
    encoded = value.encode("utf-8")
    return {
        "kind": "bare",
        "sha256": sha256(encoded).hexdigest(),
        "utf8_bytes": len(encoded),
        "value": value,
    }


def _normalized_command_document(
    statements: tuple[tuple[tuple[tuple[str, ...], str], ...], ...],
) -> dict[str, object]:
    nodes: list[dict[str, object]] = [
        {
            "index": 0,
            "ast_type": "ScriptBlockAst",
            "role": "script_block",
            "parent_index": None,
            "child_indices": [1],
            "invocation_operator": None,
            "literal": None,
        },
        {
            "index": 1,
            "ast_type": "NamedBlockAst",
            "role": "statement",
            "parent_index": 0,
            "child_indices": [],
            "invocation_operator": None,
            "literal": None,
        },
    ]
    tokens: list[dict[str, object]] = []
    operation_count = 0

    def add_token(kind: str, text: str, literal: object = None) -> None:
        tokens.append(
            {
                "flags": [],
                "index": len(tokens),
                "kind": kind,
                "literal": literal,
                "text": text,
            }
        )

    for statement_index, pipeline in enumerate(statements):
        pipeline_index = len(nodes)
        child_indices = nodes[1]["child_indices"]
        assert isinstance(child_indices, list)
        child_indices.append(pipeline_index)
        nodes.append(
            {
                "index": pipeline_index,
                "ast_type": "PipelineAst",
                "role": "pipeline",
                "parent_index": 1,
                "child_indices": [],
                "invocation_operator": None,
                "literal": None,
            }
        )
        for stage_index, (argv, operator) in enumerate(pipeline):
            command_index = len(nodes)
            pipeline_children = nodes[pipeline_index]["child_indices"]
            assert isinstance(pipeline_children, list)
            pipeline_children.append(command_index)
            nodes.append(
                {
                    "index": command_index,
                    "ast_type": "CommandAst",
                    "role": "command",
                    "parent_index": pipeline_index,
                    "child_indices": [],
                    "invocation_operator": operator,
                    "literal": None,
                }
            )
            if operator == "call":
                add_token("Ampersand", "&")
            for value in argv:
                child_index = len(nodes)
                command_children = nodes[command_index]["child_indices"]
                assert isinstance(command_children, list)
                command_children.append(child_index)
                if value.startswith("-") and not value.startswith("--"):
                    node_type = "CommandParameterAst"
                    node_literal = None
                    token_kind = "Parameter"
                    token_literal = None
                else:
                    node_type = "StringConstantExpressionAst"
                    node_literal = _literal(value)
                    token_kind = "Identifier"
                    token_literal = node_literal
                nodes.append(
                    {
                        "index": child_index,
                        "ast_type": node_type,
                        "role": "command_element" if node_literal is None else "expression",
                        "parent_index": command_index,
                        "child_indices": [],
                        "invocation_operator": None,
                        "literal": node_literal,
                    }
                )
                add_token(token_kind, value, token_literal)
            operation_count += 1
            if stage_index + 1 < len(pipeline):
                add_token("Pipe", "|")
        if statement_index + 1 < len(statements):
            add_token("Semi", ";")
    add_token("EndOfInput", "")
    return {
        "metrics": {
            "ast_depth": 5,
            "ast_nodes": len(nodes),
            "operations": operation_count,
            "pipeline_stages": operation_count,
            "statements": len(statements) + operation_count,
        },
        "nodes": nodes,
        "tokens": tokens,
    }


def _bound_plan(
    operation_argvs: tuple[tuple[str, ...], ...],
    *,
    rendered_command: str | None = None,
    one_pipeline: bool = False,
    namespaces: tuple[command_plan.BoundPathNamespace, ...] = (),
) -> tuple[command_plan.BoundCommandPlan, str]:
    if rendered_command is None:
        separator = " | " if one_pipeline else "; "
        rendered_command = separator.join(" ".join(argv) for argv in operation_argvs)
    if one_pipeline:
        statements = (tuple((argv, "none") for argv in operation_argvs),)
    else:
        statements = tuple(((argv, "none"),) for argv in operation_argvs)
    command = _normalized_command_document(statements)
    payload = b"synthetic-decoded-payload"
    payload_digest = sha256(payload).hexdigest()
    rendered = rendered_command.encode("utf-8")
    rendered_digest = sha256(rendered).hexdigest()
    manifest = command_plan._namespace_manifest(namespaces)
    manifest_sha256 = sha256(_canonical(manifest)).hexdigest()
    document = {
        "bindings": {
            side: {
                "payload": {
                    "sha256": payload_digest,
                    "utf8_bytes": len(payload),
                },
                "payload_field": {
                    "sha256": payload_digest,
                    "utf8_bytes": len(payload),
                },
                "rendered": {
                    "sha256": rendered_digest,
                    "utf8_bytes": len(rendered),
                },
            }
            for side in ("raw", "retained")
        },
        "command": command,
        "decoder": {"path": "synthetic-decoder.ps1", "sha256": ZERO_SHA256},
        "namespace_manifest_sha256": manifest_sha256,
        "namespaces": manifest["namespaces"],
        "shell": {
            "edition": "Core",
            "file_version": "7.5.0",
            "parser_version": "7.5.0",
            "path": r"C:\Program Files\PowerShell\7\pwsh.exe",
            "product_version": "7.5.0",
            "sha256": ZERO_SHA256,
        },
        "version": "complete-suite-bound-command-plan-v1",
    }
    normalized = _canonical(document)
    plan = command_plan.BoundCommandPlan(
        version="complete-suite-bound-command-plan-v1",
        raw_rendered_utf8_bytes=len(rendered),
        raw_rendered_sha256=rendered_digest,
        retained_rendered_utf8_bytes=len(rendered),
        retained_rendered_sha256=rendered_digest,
        raw_payload_field_utf8_bytes=len(payload),
        raw_payload_field_sha256=payload_digest,
        raw_payload_utf8_bytes=len(payload),
        raw_payload_sha256=payload_digest,
        retained_payload_field_utf8_bytes=len(payload),
        retained_payload_field_sha256=payload_digest,
        retained_payload_utf8_bytes=len(payload),
        retained_payload_sha256=payload_digest,
        namespaces=namespaces,
        namespace_manifest_sha256=manifest_sha256,
        normalized_plan_sha256=sha256(normalized).hexdigest(),
        normalized_plan_bytes=normalized,
    )
    return plan, rendered_command


@dataclass(frozen=True)
class _CommandSpec:
    plan: command_plan.BoundCommandPlan
    decision: command_policy.CommandPolicyDecision
    rendered_command: str
    raw_output: str
    retained_output: str
    exit_code: int
    event_id: str


def _operational_spec(
    documents: tuple[dict[str, Any], ...],
    *,
    raw_documents: tuple[dict[str, Any], ...] | None = None,
    retained_documents: tuple[dict[str, Any], ...] | None = None,
    raw_output: str | None = None,
    retained_output: str | None = None,
    argvs: tuple[tuple[str, ...], ...] | None = None,
    expected_outcomes: tuple[str, ...] | None = None,
    declared_outputs: tuple[tuple[str, ...], ...] | None = None,
    exit_code: int = 0,
    event_id: str = "command-1",
    namespaces: tuple[command_plan.BoundPathNamespace, ...] = (),
) -> _CommandSpec:
    count = len(documents)
    assert count > 0
    raw_documents = documents if raw_documents is None else raw_documents
    retained_documents = documents if retained_documents is None else retained_documents
    assert len(raw_documents) == count
    assert len(retained_documents) == count
    if argvs is None:
        argvs = tuple(
            ("kokoro", "pack", "list", "--scope", "global", "--json")
            for _ in range(count)
        )
    assert len(argvs) == count
    expected_outcomes = (
        ("success",) * count if expected_outcomes is None else expected_outcomes
    )
    declared_outputs = (
        ((),) * count if declared_outputs is None else declared_outputs
    )
    assert len(expected_outcomes) == count
    assert len(declared_outputs) == count
    plan, rendered = _bound_plan(argvs, namespaces=namespaces)
    operations = tuple(
        command_policy.ApprovedOperation(
            index=index,
            statement_index=index,
            pipeline_index=None,
            category="kokoro_cli",
            argv=argv,
            operational_json=True,
            expected_outcome=expected_outcomes[index],
            declared_output_paths=declared_outputs[index],
        )
        for index, argv in enumerate(argvs)
    )
    decision = command_policy._decision(
        plan.normalized_plan_sha256,
        "operational_json",
        operations,
    )
    command_policy._register_command_policy_decision(decision, plan=plan)
    if raw_output is None:
        raw_output = "".join(
            json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            for value in raw_documents
        )
    if retained_output is None:
        retained_output = "".join(
            json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            for value in retained_documents
        )
    return _CommandSpec(
        plan=plan,
        decision=decision,
        rendered_command=rendered,
        raw_output=raw_output,
        retained_output=retained_output,
        exit_code=exit_code,
        event_id=event_id,
    )


def _nonoperational_spec(
    output: str,
    *,
    help_only: bool,
    exit_code: int = 0,
    event_id: str = "command-1",
) -> _CommandSpec:
    if help_only:
        argvs = (("kokoro", "--help"),)
        category = "kokoro_cli"
        record_class = "help_discovery"
        pipeline_index = None
    else:
        argvs = (("Get-Content", r".\README.md"),)
        category = "read_only"
        record_class = "read_only_pipeline"
        pipeline_index = None
    plan, rendered = _bound_plan(argvs)
    operation = command_policy.ApprovedOperation(
        index=0,
        statement_index=0,
        pipeline_index=pipeline_index,
        category=category,
        argv=argvs[0],
        operational_json=False,
        expected_outcome="none",
        declared_output_paths=(),
    )
    decision = command_policy._decision(
        plan.normalized_plan_sha256,
        record_class,
        (operation,),
    )
    command_policy._register_command_policy_decision(decision, plan=plan)
    return _CommandSpec(
        plan=plan,
        decision=decision,
        rendered_command=rendered,
        raw_output=output,
        retained_output=output,
        exit_code=exit_code,
        event_id=event_id,
    )


def _silent_only_spec() -> _CommandSpec:
    argvs = (
        ("New-Item", "-ItemType", "Directory", "-Path", r".\outputs"),
        ("Out-Null",),
    )
    plan, rendered = _bound_plan(argvs, one_pipeline=True)
    operations = tuple(
        command_policy.ApprovedOperation(
            index=index,
            statement_index=0,
            pipeline_index=index,
            category="silent_directory",
            argv=argv,
            operational_json=False,
            expected_outcome="none",
            declared_output_paths=(),
        )
        for index, argv in enumerate(argvs)
    )
    topology = command_policy._decision_topology_record(
        "operational_json",
        operations,
    )
    topology_sha256 = sha256(command_policy._canonical_json_bytes(topology)).hexdigest()
    record = command_policy._decision_canonical_record(
        plan_sha256=plan.normalized_plan_sha256,
        record_class="operational_json",
        operations=operations,
        topology_sha256=topology_sha256,
    )
    decision = command_policy.CommandPolicyDecision.__new__(
        command_policy.CommandPolicyDecision
    )
    for name, value in (
        ("version", command_policy.COMMAND_POLICY_VERSION),
        ("plan_sha256", plan.normalized_plan_sha256),
        ("record_class", "operational_json"),
        ("operations", operations),
        ("topology_sha256", topology_sha256),
        ("canonical_sha256", sha256(command_policy._canonical_json_bytes(record)).hexdigest()),
    ):
        object.__setattr__(decision, name, value)
    command_policy._register_command_policy_decision(decision, plan=plan)
    return _CommandSpec(
        plan=plan,
        decision=decision,
        rendered_command=rendered,
        raw_output="",
        retained_output="",
        exit_code=0,
        event_id="silent-1",
    )


@dataclass
class _DomainRecord:
    event_id: str
    started_event_ordinal: int
    completed_event_ordinal: int
    event_start: int
    event_end: int
    output_field_start: int
    output_field_end: int
    output_field_bytes: bytes
    output_bytes: bytes
    exit_code: int


def _event_bytes(value: dict[str, Any], *, ensure_ascii: bool) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=ensure_ascii,
        separators=(",", ":"),
    ).encode("utf-8")


def _session_document(
    specs: tuple[_CommandSpec, ...],
    *,
    domain: Literal["raw", "retained"],
    ensure_ascii: bool,
    event_mutator=None,
) -> tuple[bytes, tuple[_DomainRecord, ...]]:
    chunks: list[bytes] = []
    records: list[_DomainRecord] = []
    offset = 0
    for index, spec in enumerate(specs):
        output = spec.raw_output if domain == "raw" else spec.retained_output
        started_item: dict[str, Any] = {
            "id": spec.event_id,
            "type": "command_execution",
            "command": spec.rendered_command,
            "aggregated_output": "",
            "exit_code": None,
            "status": "in_progress",
        }
        started = {"type": "item.started", "item": started_item}
        if event_mutator is not None:
            event_mutator(domain, index, "started", started)
        started_bytes = _event_bytes(started, ensure_ascii=ensure_ascii)
        chunks.extend((started_bytes, b"\n"))
        offset += len(started_bytes) + 1

        completed_item: dict[str, Any] = {
            "id": spec.event_id,
            "type": "command_execution",
            "command": spec.rendered_command,
            "aggregated_output": output,
            "exit_code": spec.exit_code,
            "status": "completed" if spec.exit_code == 0 else "failed",
        }
        completed = {"type": "item.completed", "item": completed_item}
        if event_mutator is not None:
            event_mutator(domain, index, "completed", completed)
        completed_bytes = _event_bytes(completed, ensure_ascii=ensure_ascii)
        marker = b'"aggregated_output":'
        marker_start = completed_bytes.index(marker)
        field_start_in_event = marker_start + len(marker)
        actual_output = completed["item"]["aggregated_output"]
        assert isinstance(actual_output, str)
        token = json.dumps(
            actual_output,
            ensure_ascii=ensure_ascii,
            separators=(",", ":"),
        ).encode("utf-8")
        assert (
            completed_bytes[field_start_in_event : field_start_in_event + len(token)]
            == token
        )
        try:
            decoded_output = actual_output.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            decoded_output = b""
        event_start = offset
        event_end = event_start + len(completed_bytes)
        records.append(
            _DomainRecord(
                event_id=str(completed["item"]["id"]),
                started_event_ordinal=index * 2,
                completed_event_ordinal=index * 2 + 1,
                event_start=event_start,
                event_end=event_end,
                output_field_start=event_start + field_start_in_event,
                output_field_end=event_start + field_start_in_event + len(token),
                output_field_bytes=token,
                output_bytes=decoded_output,
                exit_code=spec.exit_code,
            )
        )
        chunks.extend((completed_bytes, b"\n"))
        offset += len(completed_bytes) + 1
    return b"".join(chunks), tuple(records)


@dataclass
class _BoundCase:
    session_id: str
    commands: tuple[Any, ...]
    raw_identity: Any
    retained_identity: Any
    raw_root: Path
    retained_root: Path
    raw_path: Path
    retained_path: Path

    def cleanup_large_files(self) -> None:
        for path in (self.raw_path, self.retained_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def _session_identity(binding, path: Path, root: Path):
    path_stat = path.lstat()
    observed = command_policy._observe_live_identity(path)
    relative_path = str(path.relative_to(root)).replace("/", "\\")
    return binding.SessionFileIdentity(
        relative_path=relative_path,
        device=int(path_stat.st_dev),
        inode=int(path_stat.st_ino),
        size=path_stat.st_size,
        modified_ns=path_stat.st_mtime_ns,
        file_type=observed.file_type,
        link_count=path_stat.st_nlink,
    )


def _make_case(
    binding,
    tmp_path: Path,
    specs: tuple[_CommandSpec, ...],
    *,
    ensure_ascii: bool = False,
    event_mutator=None,
) -> _BoundCase:
    session_id = "session-1"
    raw_root = tmp_path / "raw" / session_id
    retained_root = tmp_path / "retained" / session_id
    raw_root.mkdir(parents=True, exist_ok=True)
    retained_root.mkdir(parents=True, exist_ok=True)
    raw_path = raw_root / "session.jsonl"
    retained_path = retained_root / "session.jsonl"
    raw_bytes, raw_records = _session_document(
        specs,
        domain="raw",
        ensure_ascii=ensure_ascii,
        event_mutator=event_mutator,
    )
    retained_bytes, retained_records = _session_document(
        specs,
        domain="retained",
        ensure_ascii=ensure_ascii,
        event_mutator=event_mutator,
    )
    raw_path.write_bytes(raw_bytes)
    retained_path.write_bytes(retained_bytes)
    raw_identity = _session_identity(binding, raw_path, raw_root)
    retained_identity = _session_identity(binding, retained_path, retained_root)
    pairs: list[Any] = []
    for index, (spec, raw, retained) in enumerate(
        zip(specs, raw_records, retained_records, strict=True)
    ):
        raw_capture = binding.CompletedOutputCapture(
            domain="raw",
            session_root=raw_root,
            session_path=raw_path,
            started_event_ordinal=raw.started_event_ordinal,
            completed_event_ordinal=raw.completed_event_ordinal,
            event_id=raw.event_id,
            event_start=raw.event_start,
            event_end=raw.event_end,
            output_field_start=raw.output_field_start,
            output_field_end=raw.output_field_end,
            exit_code=raw.exit_code,
            output_field_utf8_bytes=len(raw.output_field_bytes),
            output_field_sha256=sha256(raw.output_field_bytes).hexdigest(),
            output_utf8_bytes=len(raw.output_bytes),
            output_sha256=sha256(raw.output_bytes).hexdigest(),
            session_identity=raw_identity,
        )
        retained_capture = binding.CompletedOutputCapture(
            domain="retained",
            session_root=retained_root,
            session_path=retained_path,
            started_event_ordinal=retained.started_event_ordinal,
            completed_event_ordinal=retained.completed_event_ordinal,
            event_id=retained.event_id,
            event_start=retained.event_start,
            event_end=retained.event_end,
            output_field_start=retained.output_field_start,
            output_field_end=retained.output_field_end,
            exit_code=retained.exit_code,
            output_field_utf8_bytes=len(retained.output_field_bytes),
            output_field_sha256=sha256(retained.output_field_bytes).hexdigest(),
            output_utf8_bytes=len(retained.output_bytes),
            output_sha256=sha256(retained.output_bytes).hexdigest(),
            session_identity=retained_identity,
        )
        pairs.append(
            binding.CommandCapturePair(
                command_index=index,
                plan=spec.plan,
                decision=spec.decision,
                raw_capture=raw_capture,
                retained_capture=retained_capture,
            )
        )
    return _BoundCase(
        session_id=session_id,
        commands=tuple(pairs),
        raw_identity=raw_identity,
        retained_identity=retained_identity,
        raw_root=raw_root,
        retained_root=retained_root,
        raw_path=raw_path,
        retained_path=retained_path,
    )


def _bind(binding, case: _BoundCase, *, session_id: str | None = None):
    return binding.bind_session_cli_results(
        case.session_id if session_id is None else session_id,
        case.commands,
        raw_session_identity=case.raw_identity,
        retained_session_identity=case.retained_identity,
    )


def _replace_capture(
    case: _BoundCase,
    command_index: int,
    domain: Literal["raw", "retained"],
    **changes: object,
) -> None:
    pairs = list(case.commands)
    pair = pairs[command_index]
    field = f"{domain}_capture"
    capture = replace(getattr(pair, field), **changes)
    pairs[command_index] = replace(pair, **{field: capture})
    case.commands = tuple(pairs)


def _refresh_domain_identity(
    binding,
    case: _BoundCase,
    domain: Literal["raw", "retained"],
) -> None:
    path = case.raw_path if domain == "raw" else case.retained_path
    root = case.raw_root if domain == "raw" else case.retained_root
    identity = _session_identity(binding, path, root)
    pairs = []
    capture_field = f"{domain}_capture"
    for pair in case.commands:
        capture = replace(getattr(pair, capture_field), session_identity=identity)
        pairs.append(replace(pair, **{capture_field: capture}))
    case.commands = tuple(pairs)
    if domain == "raw":
        case.raw_identity = identity
    else:
        case.retained_identity = identity


def _append_session_event(
    binding,
    case: _BoundCase,
    event: dict[str, Any],
) -> None:
    encoded = _event_bytes(event, ensure_ascii=False) + b"\n"
    case.raw_path.write_bytes(case.raw_path.read_bytes() + encoded)
    case.retained_path.write_bytes(case.retained_path.read_bytes() + encoded)
    _refresh_domain_identity(binding, case, "raw")
    _refresh_domain_identity(binding, case, "retained")


def _prepend_session_events(
    binding,
    case: _BoundCase,
    events: tuple[dict[str, Any], ...],
) -> None:
    prefix = b"".join(
        _event_bytes(event, ensure_ascii=False) + b"\n" for event in events
    )
    ordinal_delta = len(events)
    for domain in ("raw", "retained"):
        path = case.raw_path if domain == "raw" else case.retained_path
        path.write_bytes(prefix + path.read_bytes())
        pairs = []
        field = f"{domain}_capture"
        for pair in case.commands:
            capture = getattr(pair, field)
            shifted = replace(
                capture,
                started_event_ordinal=capture.started_event_ordinal + ordinal_delta,
                completed_event_ordinal=capture.completed_event_ordinal + ordinal_delta,
                event_start=capture.event_start + len(prefix),
                event_end=capture.event_end + len(prefix),
                output_field_start=capture.output_field_start + len(prefix),
                output_field_end=capture.output_field_end + len(prefix),
            )
            pairs.append(replace(pair, **{field: shifted}))
        case.commands = tuple(pairs)
        _refresh_domain_identity(binding, case, domain)


def _exact_json_document(size: int, index: int = 0) -> str:
    request = _fixture("authoring", "original-request.json")
    request["inputs"] = [
        {"type": "creative_brief", "content": f"document-{index}-x"}
    ]
    value = {"ok": True, "request": request}

    while True:
        document = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        deficit = size - len(document.encode("utf-8"))
        assert deficit >= 0
        if deficit == 0:
            break
        content = request["inputs"][-1]["content"]
        available = 262_144 - len(content)
        if deficit <= available:
            request["inputs"][-1]["content"] += "x" * deficit
            continue
        request["inputs"][-1]["content"] += "x" * available
        assert len(request["inputs"]) < 64
        request["inputs"].append({"type": "creative_brief", "content": "x"})
    assert len(document.encode("utf-8")) == size
    return document


def _large_document_argv() -> tuple[str, ...]:
    return (
        "kokoro",
        "character",
        "request",
        "validate",
        "--input",
        r".\inputs\request.json",
        "--json",
    )


def _assert_sha256(value: str) -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _set_nested_value(
    value: dict[str, Any],
    path: tuple[str | int, ...],
    replacement: object,
) -> None:
    cursor: Any = value
    for part in path[:-1]:
        cursor = cursor[part]
    cursor[path[-1]] = replacement


_INVALID_SUCCESS_MUTATIONS: dict[
    tuple[str, ...], tuple[tuple[str | int, ...], object]
] = {
    ("pack", "validate"): (("character_version",), ""),
    ("pack", "compile"): (("character_id",), ""),
    ("pack", "install"): (("plan", "operation"), "remove"),
    ("pack", "list"): (
        ("installed", 0, "promotion_status"),
        "reviewed",
    ),
    ("pack", "export"): (("visibility",), "public"),
    ("pack", "test"): (("compiled_hash",), None),
    ("pack", "soft-eval"): (("report_hash",), "bad-hash"),
    ("pack", "promote"): (("bundle_path",), "other"),
    ("pack", "publication-check"): (
        ("ready_for_private_export",),
        False,
    ),
    ("character", "request", "validate"): (
        ("request", "mode"),
        "invalid",
    ),
    ("character", "draft", "validate"): (("valid",), False),
    ("character", "draft", "compile"): (("build_status",), "research"),
    ("research", "request", "validate"): (("request", "medium"), ""),
    ("research", "workspace", "validate"): (("valid",), False),
    ("research", "bundle", "compile"): (("build_status",), "draft"),
    ("research", "bundle", "validate"): (("valid",), False),
    ("config", "default", "set"): (("default", "binding"), None),
    ("config", "default", "show"): (("default", "revision"), -1),
    ("session", "start"): (("session", "active"), False),
    ("session", "show"): (("session", "compiled_pack_hash"), "bad-hash"),
    ("consent", "show"): (("consent", "status"), "unknown"),
    ("state", "preview"): (("state", "stage"), "impossible"),
    ("state", "apply"): (("state", "revision"), -1),
    ("state", "export"): (("export_sha256",), "bad-hash"),
    ("memory", "add"): (("memory_reference", "embedded_content"), True),
    ("memory", "list"): (
        ("memory_references", 0, "active_consent_generation"),
        1,
    ),
    ("memory", "remove"): (("plan", "will_remove"), False),
    ("policy", "compile"): (("policy", "mode"), "invalid"),
    ("runtime", "context"): (("context", "state", "stage"), "impossible"),
    ("runtime", "plan"): (("plan", "segments", 0, "id"), "wrong"),
    ("runtime", "validate"): (("validation", "valid"), False),
}


@pytest.mark.parametrize(
    "action",
    command_policy._CLI_ACTIONS,
    ids=("-".join(action) for action in command_policy._CLI_ACTIONS),
)
def test_every_success_action_has_a_closed_nested_contract_and_rejects_mutation(
    action: tuple[str, ...],
) -> None:
    binding = _binding()
    assert set(_INVALID_SUCCESS_MUTATIONS) == set(command_policy._CLI_ACTIONS)
    document = _valid_success_documents()[action]
    assert frozenset(document) in binding._SUCCESS_TOP_LEVEL_KEYS[action]
    binding._validate_success_field_types(action, document)

    invalid = deepcopy(document)
    path, replacement = _INVALID_SUCCESS_MUTATIONS[action]
    _set_nested_value(invalid, path, replacement)
    with pytest.raises(RuntimeError, match=binding.COMMAND_RESULT_INCONSISTENT):
        binding._validate_success_field_types(action, invalid)


def _assert_selector_pair(
    binding,
    tmp_path: Path,
    action: tuple[str, ...],
    raw: dict[str, Any],
    retained: dict[str, Any],
    *,
    matches: bool,
) -> None:
    argv = ("kokoro", *action, "--json")
    spec = _operational_spec(
        (raw,),
        raw_documents=(raw,),
        retained_documents=(retained,),
        argvs=(argv,),
    )
    case = _make_case(binding, tmp_path, (spec,))
    if matches:
        assert _bind(binding, case).commands[0].results[0].outcome == "success"
    else:
        with pytest.raises(RuntimeError, match=binding.COMMAND_RESULT_INCONSISTENT):
            _bind(binding, case)


@pytest.mark.parametrize("mutate_stable", (False, True))
def test_research_request_selector_omits_prose_but_binds_research_scope(
    tmp_path: Path,
    mutate_stable: bool,
) -> None:
    binding = _binding()
    raw = _valid_success_documents()[("research", "request", "validate")]
    retained = deepcopy(raw)
    retained_request = retained["request"]
    retained_request["display_name"] = "Redacted Fixture"
    retained_request["aliases"] = ["Alias One", "Alias Two"]
    retained_request["research_questions"] = [
        "Redacted question one?",
        "Redacted question two?",
    ]
    retained_request["constraints"] = ["Redacted private constraint."]
    if mutate_stable:
        retained_request["medium"] = "graphic novel"
    _assert_selector_pair(
        binding,
        tmp_path,
        ("research", "request", "validate"),
        raw,
        retained,
        matches=not mutate_stable,
    )


@pytest.mark.parametrize("mutate_stable", (False, True))
def test_character_draft_selector_omits_finding_message_but_binds_code(
    tmp_path: Path,
    mutate_stable: bool,
) -> None:
    binding = _binding()
    raw = _valid_success_documents()[("character", "draft", "validate")]
    retained = deepcopy(raw)
    finding = retained["validation_report"]["advisory_findings"][0]
    finding["message"] = "Redacted advisory message."
    if mutate_stable:
        finding["code"] = "AUTHORING_MORE_EXAMPLES"
    _assert_selector_pair(
        binding,
        tmp_path,
        ("character", "draft", "validate"),
        raw,
        retained,
        matches=not mutate_stable,
    )


@pytest.mark.parametrize("mutate_stable", (False, True))
def test_research_report_selector_omits_finding_and_blocking_prose_only(
    tmp_path: Path,
    mutate_stable: bool,
) -> None:
    binding = _binding()
    report = _fixture("research", "partial", "validation-report.json")
    raw = {
        "ok": True,
        "valid": report["valid"],
        "workspace_hash": "b" * 64,
        "validation_report": report,
    }
    retained = deepcopy(raw)
    retained_report = retained["validation_report"]
    retained_report["advisory_findings"][0]["message"] = (
        "Redacted finding message."
    )
    retained_report["blocking_reasons"] = ["Redacted blocking reason."]
    if mutate_stable:
        retained_report["advisory_findings"][0]["code"] = "TOPIC_PARTIAL"
    _assert_selector_pair(
        binding,
        tmp_path,
        ("research", "workspace", "validate"),
        raw,
        retained,
        matches=not mutate_stable,
    )


@pytest.mark.parametrize("mutate_stable", (False, True))
def test_research_bundle_selector_omits_resolution_prose_but_binds_status(
    tmp_path: Path,
    mutate_stable: bool,
) -> None:
    binding = _binding()
    raw = _valid_success_documents()[("research", "bundle", "validate")]
    raw["limitations"] = ["Private source limitation."]
    retained = deepcopy(raw)
    retained["limitations"] = ["Redacted source limitation."]
    retained["conflicts"][0]["scopes"] = [
        "redacted-primary",
        "redacted-alternate",
    ]
    retained["conflicts"][0]["resolution_rationale"] = (
        "Redacted resolution rationale."
    )
    if mutate_stable:
        retained["conflicts"][0]["status"] = "resolved_with_rationale"
    _assert_selector_pair(
        binding,
        tmp_path,
        ("research", "bundle", "validate"),
        raw,
        retained,
        matches=not mutate_stable,
    )


@pytest.mark.parametrize("action", (("memory", "add"), ("memory", "list")))
@pytest.mark.parametrize("mutate_stable", (False, True))
def test_memory_selectors_omit_summaries_but_bind_content_hash(
    tmp_path: Path,
    action: tuple[str, ...],
    mutate_stable: bool,
) -> None:
    binding = _binding()
    raw = _valid_success_documents()[action]
    retained = deepcopy(raw)
    if action == ("memory", "add"):
        reference = retained["memory_reference"]
    else:
        reference = retained["memory_references"][0]["reference"]
    reference["summary"] = "Redacted approved-memory summary."
    reference["localized_summaries"] = {
        "zh-CN": "Redacted Chinese summary.",
        "en-US": "Redacted English summary.",
        "ja-JP": "Redacted Japanese summary.",
    }
    if mutate_stable:
        reference["content_hash"] = "e" * 64
    _assert_selector_pair(
        binding,
        tmp_path,
        action,
        raw,
        retained,
        matches=not mutate_stable,
    )


@pytest.mark.parametrize("mutate_stable", (False, True))
def test_runtime_context_selector_omits_selected_text_but_binds_identity_and_stage(
    tmp_path: Path,
    mutate_stable: bool,
) -> None:
    binding = _binding()
    raw = _valid_success_documents()[("runtime", "context")]
    retained = deepcopy(raw)
    context = retained["context"]
    context["identity"]["display_name"] = "Redacted character"
    context["locales"]["zh-CN"]["register"] = "redacted register"
    context["scenarios"]["debugging"]["first_action"] = "redacted action"
    context["expressions"]["restrained_diagnosis"]["zh-CN"] = [
        "Redacted expression."
    ]
    if mutate_stable:
        context["state"]["stage"] = "trusted"
    _assert_selector_pair(
        binding,
        tmp_path,
        ("runtime", "context"),
        raw,
        retained,
        matches=not mutate_stable,
    )


@pytest.mark.parametrize("mutate_stable", (False, True))
def test_runtime_plan_selector_omits_protected_text_but_binds_routes(
    tmp_path: Path,
    mutate_stable: bool,
) -> None:
    binding = _binding()
    raw = _valid_success_documents()[("runtime", "plan")]
    retained = deepcopy(raw)
    retained["plan"]["protected_spans"] = ["<redacted-command>"]
    if mutate_stable:
        segment = retained["plan"]["segments"][1]
        segment["channel"] = "recommendations"
        segment["semantic_keys"] = ["recommendations"]
    _assert_selector_pair(
        binding,
        tmp_path,
        ("runtime", "plan"),
        raw,
        retained,
        matches=not mutate_stable,
    )


@pytest.mark.parametrize("mutate_stable", (False, True))
def test_runtime_validation_selector_omits_violation_prose_but_binds_code(
    tmp_path: Path,
    mutate_stable: bool,
) -> None:
    binding = _binding()
    base = _fixture("schema", "runtime-artifacts.json")["validation_result"]
    validation = {
        **base,
        "valid": False,
        "violations": [
            {
                "code": "MISSING_PROTECTED_SPAN",
                "message": "Private protected span is missing.",
                "details": {
                    "expected": "present",
                    "protected_span": "private-command --token value",
                },
            }
        ],
        "fallback_level": 0,
    }
    raw = {"ok": True, "validation": validation}
    retained = deepcopy(raw)
    violation = retained["validation"]["violations"][0]
    violation["message"] = "Redacted violation message."
    violation["details"]["protected_span"] = "<redacted-command>"
    if mutate_stable:
        violation["code"] = "PROTECTED_SPAN_MISMATCH"
    _assert_selector_pair(
        binding,
        tmp_path,
        ("runtime", "validate"),
        raw,
        retained,
        matches=not mutate_stable,
    )


def test_public_models_and_typed_api_are_exact() -> None:
    binding = _binding()
    expected = {
        binding.SessionFileIdentity: {
            "relative_path": str,
            "device": int,
            "inode": int,
            "size": int,
            "modified_ns": int,
            "file_type": int,
            "link_count": int,
        },
        binding.CompletedOutputCapture: {
            "domain": Literal["raw", "retained"],
            "session_root": Path,
            "session_path": Path,
            "started_event_ordinal": int,
            "completed_event_ordinal": int,
            "event_id": str,
            "event_start": int,
            "event_end": int,
            "output_field_start": int,
            "output_field_end": int,
            "exit_code": int,
            "output_field_utf8_bytes": int,
            "output_field_sha256": str,
            "output_utf8_bytes": int,
            "output_sha256": str,
            "session_identity": binding.SessionFileIdentity,
        },
        binding.BoundCliResult: {
            "operation_index": int,
            "argv": tuple[str, ...],
            "raw_document_sha256": str,
            "retained_document_bytes": bytes,
            "retained_document_sha256": str,
            "exit_code": int,
            "outcome": Literal["success", "expected_refusal"],
        },
        binding.CommandCapturePair: {
            "command_index": int,
            "plan": command_plan.BoundCommandPlan,
            "decision": command_policy.CommandPolicyDecision,
            "raw_capture": binding.CompletedOutputCapture,
            "retained_capture": binding.CompletedOutputCapture,
        },
        binding.BoundCommandEvidence: {
            "command_index": int,
            "event_id": str,
            "started_event_ordinal": int,
            "completed_event_ordinal": int,
            "plan_sha256": str,
            "namespace_manifest_sha256": str,
            "decision_sha256": str,
            "record_class": str,
            "raw_output_utf8_bytes": int,
            "raw_output_sha256": str,
            "retained_output_utf8_bytes": int,
            "retained_output_sha256": str,
            "results": tuple[binding.BoundCliResult, ...],
            "canonical_sha256": str,
        },
        binding.BoundSessionCommandEvidence: {
            "version": Literal["complete-suite-session-command-evidence-v1"],
            "session_id": str,
            "raw_session_identity": binding.SessionFileIdentity,
            "retained_session_identity": binding.SessionFileIdentity,
            "commands": tuple[binding.BoundCommandEvidence, ...],
            "raw_bytes_consumed": int,
            "retained_bytes_consumed": int,
            "canonical_bytes": bytes,
            "canonical_sha256": str,
        },
    }
    repr_disabled = {
        binding.BoundCliResult,
        binding.BoundCommandEvidence,
        binding.BoundSessionCommandEvidence,
    }
    for model, hints in expected.items():
        assert [field.name for field in fields(model)] == list(hints)
        assert get_type_hints(model) == hints
        assert model.__dataclass_params__.frozen is True
        assert model.__dataclass_params__.repr is (model not in repr_disabled)

    signature = inspect.signature(binding.bind_session_cli_results)
    assert list(signature.parameters) == [
        "session_id",
        "commands",
        "raw_session_identity",
        "retained_session_identity",
    ]
    assert signature.parameters["session_id"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert signature.parameters["commands"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert signature.parameters["raw_session_identity"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["retained_session_identity"].kind is inspect.Parameter.KEYWORD_ONLY
    assert get_type_hints(binding.bind_session_cli_results) == {
        "session_id": str,
        "commands": tuple[binding.CommandCapturePair, ...],
        "raw_session_identity": binding.SessionFileIdentity,
        "retained_session_identity": binding.SessionFileIdentity,
        "return": binding.BoundSessionCommandEvidence,
    }


def test_spans_are_half_open_and_output_span_includes_quoted_token(
    tmp_path: Path,
) -> None:
    binding = _binding()
    document = _pack_list_document()
    spec = _operational_spec((document,))
    case = _make_case(binding, tmp_path, (spec,))
    capture = case.commands[0].raw_capture
    session_bytes = case.raw_path.read_bytes()
    event = session_bytes[capture.event_start : capture.event_end]
    token = session_bytes[
        capture.output_field_start : capture.output_field_end
    ]
    assert event.startswith(b'{"type":"item.completed"')
    assert event.endswith(b"}")
    assert session_bytes[capture.event_end : capture.event_end + 1] == b"\n"
    assert token == json.dumps(
        spec.raw_output,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    assert token.startswith(b'"') and token.endswith(b'"')
    assert session_bytes[capture.output_field_start - 1 : capture.output_field_start] == b":"
    assert (
        session_bytes[capture.output_field_end : capture.output_field_end + 1]
        == b","
    )
    evidence = _bind(binding, case)
    assert len(evidence.commands) == 1


def test_one_operational_document_binds_canonical_raw_and_retained(
    tmp_path: Path,
) -> None:
    binding = _binding()
    document = _pack_list_document()
    spec = _operational_spec((document,))
    case = _make_case(binding, tmp_path, (spec,))
    evidence = _bind(binding, case)
    assert evidence.version == EVIDENCE_VERSION
    assert evidence.session_id == "session-1"
    assert evidence.raw_session_identity == case.raw_identity
    assert evidence.retained_session_identity == case.retained_identity
    assert evidence.raw_bytes_consumed == len(spec.raw_output.encode("utf-8"))
    assert evidence.retained_bytes_consumed == len(spec.retained_output.encode("utf-8"))
    assert len(evidence.commands) == 1
    command = evidence.commands[0]
    assert command.command_index == 0
    assert command.event_id == spec.event_id
    assert command.plan_sha256 == spec.plan.normalized_plan_sha256
    assert command.namespace_manifest_sha256 == spec.plan.namespace_manifest_sha256
    assert command.decision_sha256 == spec.decision.canonical_sha256
    assert command.record_class == "operational_json"
    assert command.raw_output_utf8_bytes == len(spec.raw_output.encode("utf-8"))
    assert command.retained_output_utf8_bytes == len(spec.retained_output.encode("utf-8"))
    assert len(command.results) == 1
    result = command.results[0]
    expected_retained = _canonical(document) + b"\n"
    assert result.operation_index == 0
    assert result.argv == spec.decision.operations[0].argv
    assert result.raw_document_sha256 == sha256(_canonical(document)).hexdigest()
    assert result.retained_document_bytes == expected_retained
    assert result.retained_document_sha256 == sha256(expected_retained).hexdigest()
    assert result.exit_code == 0
    assert result.outcome == "success"
    assert sha256(evidence.canonical_bytes).hexdigest() == evidence.canonical_sha256
    _assert_sha256(command.canonical_sha256)


def test_multiple_operational_documents_bind_in_operation_order(
    tmp_path: Path,
) -> None:
    binding = _binding()
    documents = (
        _pack_list_document(),
        {
            "ok": True,
            "default": {
                "schema_version": "1.0",
                "artifact_id": "config/global/default-character",
                "created_by": {"component": "kokoroarc", "version": "1.0.0"},
                "scope": "global",
                "workspace_id": None,
                "revision": 0,
                "binding": None,
                "activation_policy": "explicit_only",
            },
            "activates_character": False,
        },
    )
    argvs = (
        ("kokoro", "pack", "list", "--scope", "global", "--json"),
        ("kokoro", "config", "default", "show", "--scope", "global", "--json"),
    )
    spec = _operational_spec(documents, argvs=argvs)
    case = _make_case(binding, tmp_path, (spec,))
    evidence = _bind(binding, case)
    results = evidence.commands[0].results
    assert tuple(result.operation_index for result in results) == (0, 1)
    assert tuple(result.argv for result in results) == argvs
    assert tuple(result.retained_document_bytes for result in results) == tuple(
        _canonical(document) + b"\n" for document in documents
    )


def test_multiple_command_records_fold_once_in_source_order(tmp_path: Path) -> None:
    binding = _binding()
    first = _operational_spec(
        (_pack_list_document(),),
        event_id="command-1",
    )
    second = _operational_spec(
        (_valid_success_documents()[("pack", "list")],),
        event_id="command-2",
    )
    case = _make_case(binding, tmp_path, (first, second))
    evidence = _bind(binding, case)
    assert tuple(command.command_index for command in evidence.commands) == (0, 1)
    assert tuple(command.event_id for command in evidence.commands) == (
        "command-1",
        "command-2",
    )
    assert evidence.raw_bytes_consumed == sum(
        len(spec.raw_output.encode("utf-8")) for spec in (first, second)
    )


@pytest.mark.parametrize(
    ("help_only", "output"),
    ((False, "bounded read output\r\n"), (True, "")),
    ids=("read-only", "help"),
)
def test_nonoperational_read_or_help_accepts_bounded_utf8_text(
    tmp_path: Path,
    help_only: bool,
    output: str,
) -> None:
    binding = _binding()
    spec = _nonoperational_spec(output, help_only=help_only)
    case = _make_case(binding, tmp_path, (spec,))
    evidence = _bind(binding, case)
    assert evidence.commands[0].results == ()
    assert evidence.commands[0].record_class == (
        "help_discovery" if help_only else "read_only_pipeline"
    )
    assert evidence.raw_bytes_consumed == len(output.encode("utf-8"))
    assert evidence.retained_bytes_consumed == len(output.encode("utf-8"))


@pytest.mark.parametrize(
    ("output", "exit_code"),
    (("\ufeffnoise", 0), ("noise", 9)),
    ids=("bom", "nonzero-exit"),
)
def test_nonoperational_invalid_output_or_exit_rejects(
    tmp_path: Path,
    output: str,
    exit_code: int,
) -> None:
    binding = _binding()
    case = _make_case(
        binding,
        tmp_path,
        (_nonoperational_spec(output, help_only=False, exit_code=exit_code),),
    )
    with pytest.raises(
        RuntimeError,
        match=(
            binding.COMMAND_JSON_INVALID
            if output.startswith("\ufeff")
            else binding.COMMAND_RESULT_INCONSISTENT
        ),
    ):
        _bind(binding, case)


def test_silent_directory_only_record_is_not_an_n_zero_class(tmp_path: Path) -> None:
    binding = _binding()
    with pytest.raises(RuntimeError, match=command_policy.COMMAND_POLICY_PLAN_INVALID):
        case = _make_case(binding, tmp_path, (_silent_only_spec(),))
        _bind(binding, case)


def test_value_equivalent_unregistered_decision_rejects(tmp_path: Path) -> None:
    binding = _binding()
    case = _make_case(
        binding,
        tmp_path,
        (_operational_spec((_pack_list_document(),)),),
    )
    forged = replace(case.commands[0].decision)
    case.commands = (replace(case.commands[0], decision=forged),)
    with pytest.raises(RuntimeError, match=command_policy.COMMAND_POLICY_PLAN_INVALID):
        _bind(binding, case)


@pytest.mark.parametrize("mutation", ("decision", "operation", "argv_identity"))
def test_registered_policy_decision_mutation_rejects(
    tmp_path: Path,
    mutation: str,
) -> None:
    binding = _binding()
    case = _make_case(
        binding,
        tmp_path,
        (_operational_spec((_pack_list_document(),)),),
    )
    decision = case.commands[0].decision
    operation = decision.operations[0]
    if mutation == "decision":
        object.__setattr__(decision, "record_class", "help_discovery")
    elif mutation == "operation":
        object.__setattr__(operation, "statement_index", 1)
    else:
        object.__setattr__(operation, "argv", tuple(list(operation.argv)))
    with pytest.raises(RuntimeError, match=command_policy.COMMAND_POLICY_PLAN_INVALID):
        _bind(binding, case)


@pytest.mark.parametrize(
    ("document_count", "output"),
    (
        (1, ""),
        (1, "[]"),
        (1, "banner\n{\"ok\":true}"),
        (1, "{\"ok\":true}trailing"),
        (1, "{\"ok\":true,\"nested\":{\"a\":1,\"a\":2}}"),
        (1, "{\"ok\":true,\"value\":NaN}"),
        (1, "\ufeff{\"ok\":true}"),
        (1, "{\"ok\":true}{\"ok\":true,\"n\":2}"),
        (2, "{\"ok\":true}"),
        (2, "{\"ok\":true}{\"ok\":true}"),
        (1, "{\"ok\":true,\"value\":\"\\ud800\"}"),
    ),
    ids=(
        "missing",
        "nonobject",
        "banner",
        "trailing",
        "duplicate-key",
        "nonfinite",
        "bom",
        "extra-document",
        "short-count",
        "repeated-document",
        "unpaired-surrogate",
    ),
)
def test_operational_output_rejects_malformed_or_wrong_count_streams(
    tmp_path: Path,
    document_count: int,
    output: str,
) -> None:
    binding = _binding()
    documents = tuple({"ok": True, "packs": [index]} for index in range(document_count))
    spec = _operational_spec(
        documents,
        raw_output=output,
        retained_output=output,
    )
    case = _make_case(binding, tmp_path, (spec,))
    with pytest.raises(RuntimeError):
        _bind(binding, case)


def test_invalid_utf8_in_quoted_output_field_rejects(tmp_path: Path) -> None:
    binding = _binding()
    spec = _operational_spec(
        ({"ok": True},),
        raw_output="x",
        retained_output="x",
    )
    case = _make_case(binding, tmp_path, (spec,))
    capture = case.commands[0].raw_capture
    payload = bytearray(case.raw_path.read_bytes())
    assert payload[capture.output_field_start : capture.output_field_end] == b'"x"'
    payload[capture.output_field_start + 1] = 0xFF
    case.raw_path.write_bytes(payload)
    token = bytes(payload[capture.output_field_start : capture.output_field_end])
    _replace_capture(
        case,
        0,
        "raw",
        output_field_sha256=sha256(token).hexdigest(),
        output_utf8_bytes=1,
        output_sha256=sha256(b"\xff").hexdigest(),
    )
    _refresh_domain_identity(binding, case, "raw")
    with pytest.raises(RuntimeError):
        _bind(binding, case)


def test_nonoperational_invalid_utf8_in_output_field_rejects(tmp_path: Path) -> None:
    binding = _binding()
    case = _make_case(
        binding,
        tmp_path,
        (_nonoperational_spec("x", help_only=False),),
    )
    capture = case.commands[0].raw_capture
    payload = bytearray(case.raw_path.read_bytes())
    payload[capture.output_field_start + 1] = 0xFF
    case.raw_path.write_bytes(payload)
    token = bytes(payload[capture.output_field_start : capture.output_field_end])
    _replace_capture(
        case,
        0,
        "raw",
        output_field_sha256=sha256(token).hexdigest(),
        output_utf8_bytes=1,
        output_sha256=sha256(b"\xff").hexdigest(),
    )
    _refresh_domain_identity(binding, case, "raw")
    with pytest.raises(RuntimeError, match=binding.COMMAND_JSON_INVALID):
        _bind(binding, case)


def test_same_shape_different_success_selector_rejects(tmp_path: Path) -> None:
    binding = _binding()
    raw = {
        "ok": True,
        "scope": "global",
        "workspace_id": None,
        "installed": [],
        "activates_character": False,
    }
    retained = {**raw, "scope": "workspace"}
    spec = _operational_spec(
        (raw,),
        raw_documents=(raw,),
        retained_documents=(retained,),
    )
    case = _make_case(binding, tmp_path, (spec,))
    with pytest.raises(RuntimeError, match=binding.COMMAND_RESULT_INCONSISTENT):
        _bind(binding, case)


def test_success_document_must_match_the_action_top_level_schema(
    tmp_path: Path,
) -> None:
    binding = _binding()
    case = _make_case(
        binding,
        tmp_path,
        (_operational_spec(({"ok": True, "packs": []},)),),
    )
    with pytest.raises(RuntimeError, match=binding.COMMAND_RESULT_INCONSISTENT):
        _bind(binding, case)


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("scope", 0),
        ("workspace_id", []),
        ("installed", {}),
        ("activates_character", 0),
    ),
)
def test_success_document_must_match_closed_action_field_types(
    tmp_path: Path,
    field: str,
    invalid: object,
) -> None:
    binding = _binding()
    document = _pack_list_document()
    document[field] = invalid
    case = _make_case(binding, tmp_path, (_operational_spec((document,)),))
    with pytest.raises(RuntimeError, match=binding.COMMAND_RESULT_INCONSISTENT):
        _bind(binding, case)


def test_workspace_pack_list_requires_a_sha256_workspace_identity() -> None:
    binding = _binding()
    document = _pack_list_document()
    document["scope"] = "workspace"
    document["workspace_id"] = "workspace-name"
    with pytest.raises(RuntimeError, match=binding.COMMAND_RESULT_INCONSISTENT):
        binding._validate_success_field_types(("pack", "list"), document)


@pytest.mark.parametrize(
    "action",
    (
        ("pack", "export"),
        ("pack", "test"),
        ("pack", "soft-eval"),
        ("pack", "promote"),
        ("pack", "publication-check"),
    ),
    ids=lambda action: "-".join(action),
)
@pytest.mark.parametrize("declared_matches", (True, False))
def test_success_result_path_is_bound_to_the_policy_declared_output(
    tmp_path: Path,
    action: tuple[str, ...],
    declared_matches: bool,
) -> None:
    binding = _binding()
    document = _valid_success_documents()[action]
    declared = document["path"] if declared_matches else r"outputs\other.json"
    spec = _operational_spec(
        (document,),
        argvs=(("kokoro", *action, "--json"),),
        declared_outputs=((declared,),),
    )
    case = _make_case(binding, tmp_path, (spec,))
    if declared_matches:
        assert _bind(binding, case).commands[0].results[0].outcome == "success"
    else:
        with pytest.raises(RuntimeError, match=binding.COMMAND_RESULT_INCONSISTENT):
            _bind(binding, case)


@pytest.mark.parametrize("declared_matches", (True, False))
def test_absolute_result_path_is_bound_by_authenticated_namespace_suffix(
    tmp_path: Path,
    declared_matches: bool,
) -> None:
    binding = _binding()
    raw_root = tmp_path / "raw-workspace"
    retained_root = tmp_path / "retained-workspace"
    raw_root.mkdir()
    retained_root.mkdir()
    namespaces = command_plan.bind_path_namespaces(
        (
            command_plan.PathNamespaceRequest(
                raw_root=str(raw_root),
                retained_root=str(retained_root),
                label="workspace",
            ),
        )
    )
    raw = _valid_success_documents()[("pack", "export")]
    raw["path"] = str(raw_root / "outputs" / "rin-aster.karc")
    retained = {**raw, "path": str(retained_root / "outputs" / "rin-aster.karc")}
    declared = (
        r"outputs\rin-aster.karc"
        if declared_matches
        else r"outputs\different.karc"
    )
    spec = _operational_spec(
        (raw,),
        raw_documents=(raw,),
        retained_documents=(retained,),
        argvs=(("kokoro", "pack", "export", "--json"),),
        declared_outputs=((declared,),),
        namespaces=namespaces,
    )
    case = _make_case(binding, tmp_path, (spec,))
    if declared_matches:
        assert _bind(binding, case).commands[0].results[0].outcome == "success"
    else:
        with pytest.raises(RuntimeError, match=binding.COMMAND_RESULT_INCONSISTENT):
            _bind(binding, case)


@pytest.mark.parametrize(
    ("action", "document", "declared_outputs"),
    (
        (
            ("pack", "export"),
            _valid_success_documents()[("pack", "export")],
            (),
        ),
        (
            ("state", "export"),
            _valid_success_documents()[("state", "export")],
            (),
        ),
        (
            ("pack", "compile"),
            _valid_success_documents()[("pack", "compile")],
            (r"outputs\unexpected.json",),
        ),
    ),
    ids=("missing-result-output", "missing-state-output", "unexpected-output"),
)
def test_operation_output_cardinality_must_match_the_authorized_action(
    tmp_path: Path,
    action: tuple[str, ...],
    document: dict[str, Any],
    declared_outputs: tuple[str, ...],
) -> None:
    binding = _binding()
    spec = _operational_spec(
        (deepcopy(document),),
        argvs=(("kokoro", *action, "--json"),),
        declared_outputs=(declared_outputs,),
    )
    case = _make_case(binding, tmp_path, (spec,))
    with pytest.raises(RuntimeError, match=binding.COMMAND_RESULT_INCONSISTENT):
        _bind(binding, case)


def test_state_export_accepts_its_single_declared_output(tmp_path: Path) -> None:
    binding = _binding()
    document = _valid_success_documents()[("state", "export")]
    spec = _operational_spec(
        (document,),
        argvs=(("kokoro", "state", "export", "--json"),),
        declared_outputs=((r"outputs\persistent-state.json",),),
    )
    case = _make_case(binding, tmp_path, (spec,))
    assert _bind(binding, case).commands[0].results[0].outcome == "success"


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("registry_identity", "not-a-registry-identity"),
        ("installation_id", "INVALID INSTALLATION"),
        ("compiled_artifact_id", "Invalid Artifact"),
        ("relative_path", "Upper/Path"),
    ),
)
def test_install_and_list_identifiers_follow_the_registry_contract(
    field: str,
    invalid: str,
) -> None:
    binding = _binding()
    documents = _valid_success_documents()
    install_plan = documents[("pack", "install")]["plan"]
    installed = documents[("pack", "list")]["installed"][0]
    install_plan[field] = invalid
    installed[field] = invalid
    with pytest.raises(RuntimeError, match=binding.COMMAND_RESULT_INCONSISTENT):
        binding._validate_install_plan(install_plan)
    with pytest.raises(RuntimeError, match=binding.COMMAND_RESULT_INCONSISTENT):
        binding._validate_installed_entry(installed)


def test_research_bundle_rejects_duplicate_conflicts() -> None:
    binding = _binding()
    document = _valid_success_documents()[("research", "bundle", "validate")]
    document["conflicts"].append(deepcopy(document["conflicts"][0]))
    with pytest.raises(RuntimeError, match=binding.COMMAND_RESULT_INCONSISTENT):
        binding._validate_success_field_types(
            ("research", "bundle", "validate"),
            document,
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("limitations", ["x" * 2001]),
        ("blocking_reasons", [f"x{index}" for index in range(129)]),
        (
            "coverage_summary",
            {"covered": 129, "partial": 0, "missing": 0, "blocked": 0},
        ),
    ),
)
def test_research_bundle_summary_respects_emittable_bounds(
    field: str,
    replacement: object,
) -> None:
    binding = _binding()
    document = _valid_success_documents()[("research", "bundle", "validate")]
    document[field] = replacement
    with pytest.raises(RuntimeError, match=binding.COMMAND_RESULT_INCONSISTENT):
        binding._validate_success_field_types(
            ("research", "bundle", "validate"),
            document,
        )


def test_research_conflict_accepts_the_schema_scope_limit() -> None:
    binding = _binding()
    document = _valid_success_documents()[("research", "bundle", "validate")]
    document["conflicts"][0]["scopes"] = ["x" * 512]
    binding._validate_success_field_types(
        ("research", "bundle", "validate"),
        document,
    )


def test_success_contract_companion_variants_are_accepted() -> None:
    binding = _binding()
    documents = _valid_success_documents()
    companions = {
        ("memory", "remove"): {
            "ok": True,
            "dry_run": False,
            "result": {
                "removed": True,
                "memory_reference_id": "rin-aster-preference-01",
            },
        },
        ("session", "show"): {"ok": True, "session": None},
        ("consent", "show"): {"ok": True, "consent": None},
        ("pack", "test"): {
            **documents[("pack", "test")],
            "passed": False,
            "compiled_hash": None,
        },
    }
    for action, document in companions.items():
        binding._validate_success_field_types(action, document)


def test_publication_blockers_cannot_be_warning_findings() -> None:
    binding = _binding()
    document = _valid_success_documents()[("pack", "publication-check")]
    document["ready_for_private_export"] = False
    document["ready_for_publication"] = False
    document["blockers"] = [
        {
            "severity": "warning",
            "code": "NON_BLOCKING_FINDING",
            "path": ["checks"],
            "message": "A warning cannot be promoted into the blocker list.",
        }
    ]
    with pytest.raises(RuntimeError, match=binding.COMMAND_RESULT_INCONSISTENT):
        binding._validate_success_field_types(
            ("pack", "publication-check"),
            document,
        )


def test_schema_backed_success_document_is_recursively_closed() -> None:
    binding = _binding()
    document = _valid_success_documents()[("character", "request", "validate")]
    document["request"]["unexpected_nested_field"] = True
    with pytest.raises(RuntimeError, match=binding.COMMAND_RESULT_INCONSISTENT):
        binding._validate_success_field_types(
            ("character", "request", "validate"),
            document,
        )


def test_frozen_schema_digest_rejects_valid_but_unpinned_schema_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding()
    schema_name = "character-build-request"
    source = (
        SKILLS_ROOT.parent.parent
        / "schemas"
        / "v1"
        / f"{schema_name}.schema.json"
    )
    schema_root = tmp_path / "schemas" / "v1"
    schema_root.mkdir(parents=True)
    (schema_root / source.name).write_bytes(source.read_bytes() + b"\n")
    fake_module = tmp_path / "tests" / "skills" / "binding.py"
    monkeypatch.setattr(binding, "__file__", str(fake_module))
    monkeypatch.setattr(binding, "_FROZEN_SCHEMA_VALIDATORS", {})
    request = _fixture("authoring", "original-request.json")
    with pytest.raises(RuntimeError, match=binding.COMMAND_RESULT_INCONSISTENT):
        binding._validate_frozen_schema(schema_name, request)


@pytest.mark.parametrize("mutate_stable_code", (False, True))
def test_publication_selector_omits_only_blocker_prose(
    tmp_path: Path,
    mutate_stable_code: bool,
) -> None:
    binding = _binding()
    raw = {
        "ok": True,
        "path": r"outputs\publication.json",
        "artifact_id": "report/publication",
        "ready_for_private_export": False,
        "ready_for_publication": False,
        "blockers": [
            {
                "severity": "error",
                "code": "MISSING_ATTESTATION",
                "path": ["review"],
                "message": r"C:\Users\private\review is missing",
            }
        ],
        "report_hash": "1" * 64,
    }
    retained = json.loads(json.dumps(raw))
    retained["blockers"][0]["message"] = "<redacted-user-profile>\\review is missing"
    if mutate_stable_code:
        retained["blockers"][0]["code"] = "DIFFERENT_BLOCKER"
    argv = (
        "kokoro",
        "pack",
        "publication-check",
        "--json",
    )
    spec = _operational_spec(
        (raw,),
        raw_documents=(raw,),
        retained_documents=(retained,),
        argvs=(argv,),
        declared_outputs=((r"outputs\publication.json",),),
    )
    case = _make_case(binding, tmp_path, (spec,))
    if mutate_stable_code:
        with pytest.raises(RuntimeError, match=binding.COMMAND_RESULT_INCONSISTENT):
            _bind(binding, case)
    else:
        assert _bind(binding, case).commands[0].results[0].outcome == "success"


@pytest.mark.parametrize("mutate_character_id", (False, True))
def test_character_request_selector_omits_prose_but_binds_identity(
    tmp_path: Path,
    mutate_character_id: bool,
) -> None:
    binding = _binding()
    request = {
        "schema_version": "1.0",
        "artifact_id": "request/example",
        "created_by": {"component": "kokoroarc", "version": "1.0"},
        "mode": "original",
        "namespace": "original",
        "character_id": "example",
        "display_name": "Private Example",
        "character_version": "1.0.0",
        "requested_locales": ["zh-CN", "en-US", "ja-JP"],
        "intended_use_cases": ["C:\\Users\\private\\case"],
        "user_constraints": ["keep private"],
        "inputs": [
            {
                "type": "creative_brief",
                "content": "Authorization: Bearer private-value",
            }
        ],
        "requested_visibility": "private",
    }
    raw = {"ok": True, "request": request}
    retained = json.loads(json.dumps(raw))
    retained_request = retained["request"]
    retained_request["display_name"] = "Redacted Example"
    retained_request["intended_use_cases"] = ["<redacted-user-profile>\\case"]
    retained_request["inputs"][0]["content"] = "Authorization: <redacted-credential>"
    if mutate_character_id:
        retained_request["character_id"] = "different"
    argv = (
        "kokoro",
        "character",
        "request",
        "validate",
        "--input",
        r".\inputs\request.json",
        "--json",
    )
    spec = _operational_spec(
        (raw,),
        raw_documents=(raw,),
        retained_documents=(retained,),
        argvs=(argv,),
    )
    case = _make_case(binding, tmp_path, (spec,))
    if mutate_character_id:
        with pytest.raises(RuntimeError, match=binding.COMMAND_RESULT_INCONSISTENT):
            _bind(binding, case)
    else:
        assert _bind(binding, case).commands[0].results[0].outcome == "success"


@pytest.mark.parametrize("different_suffix", (False, True))
def test_result_paths_compare_through_authenticated_namespaces(
    tmp_path: Path,
    different_suffix: bool,
) -> None:
    binding = _binding()
    raw_root = tmp_path / "raw-workspace"
    retained_root = tmp_path / "retained-workspace"
    raw_root.mkdir()
    retained_root.mkdir()
    namespaces = command_plan.bind_path_namespaces(
        (
            command_plan.PathNamespaceRequest(
                raw_root=str(raw_root),
                retained_root=str(retained_root),
                label="workspace",
            ),
        )
    )
    raw = {
        "ok": True,
        "path": str(raw_root / "compiled" / "example.json"),
        "character_id": "example",
        "character_version": "1.0.0",
        "source_hash": "1" * 64,
        "artifact_id": "compiled/example",
    }
    retained_name = "different.json" if different_suffix else "example.json"
    retained = {
        **raw,
        "path": str(retained_root / "compiled" / retained_name),
    }
    argv = (
        "kokoro",
        "pack",
        "compile",
        r".\source-packs\example",
        "--json",
    )
    spec = _operational_spec(
        (raw,),
        raw_documents=(raw,),
        retained_documents=(retained,),
        argvs=(argv,),
        namespaces=namespaces,
    )
    case = _make_case(binding, tmp_path, (spec,))
    if different_suffix:
        with pytest.raises(RuntimeError, match=binding.COMMAND_RESULT_INCONSISTENT):
            _bind(binding, case)
    else:
        assert _bind(binding, case).commands[0].results[0].outcome == "success"


@pytest.mark.parametrize(
    "suffix",
    (
        r"compiled\..\outside.json",
        r"compiled\session.json:stream",
        r"compiled\CON.json",
        "compiled\\trailing.\\result.json",
    ),
)
def test_result_namespace_paths_reject_lexical_escape_and_invalid_components(
    tmp_path: Path,
    suffix: str,
) -> None:
    binding = _binding()
    raw_root = tmp_path / "raw-workspace"
    retained_root = tmp_path / "retained-workspace"
    raw_root.mkdir()
    retained_root.mkdir()
    namespaces = command_plan.bind_path_namespaces(
        (
            command_plan.PathNamespaceRequest(
                raw_root=str(raw_root),
                retained_root=str(retained_root),
                label="workspace",
            ),
        )
    )
    raw = {
        "ok": True,
        "path": str(raw_root) + "\\" + suffix,
        "character_id": "example",
        "character_version": "1.0.0",
        "source_hash": "1" * 64,
        "artifact_id": "compiled/example",
    }
    retained = {**raw, "path": str(retained_root) + "\\" + suffix}
    argv = ("kokoro", "pack", "compile", r".\source-packs\example", "--json")
    spec = _operational_spec(
        (raw,),
        raw_documents=(raw,),
        retained_documents=(retained,),
        argvs=(argv,),
        namespaces=namespaces,
    )
    case = _make_case(binding, tmp_path, (spec,))
    with pytest.raises(RuntimeError, match=binding.COMMAND_RESULT_INCONSISTENT):
        _bind(binding, case)


@pytest.mark.skipif(os.name != "nt", reason="Windows case semantics")
def test_result_namespace_paths_use_bound_case_semantics(tmp_path: Path) -> None:
    binding = _binding()
    raw_root = tmp_path / "raw-workspace"
    retained_root = tmp_path / "retained-workspace"
    raw_root.mkdir()
    retained_root.mkdir()
    namespaces = command_plan.bind_path_namespaces(
        (
            command_plan.PathNamespaceRequest(
                raw_root=str(raw_root),
                retained_root=str(retained_root),
                label="workspace",
            ),
        )
    )
    assert not namespaces[0].raw_case_sensitive
    assert not namespaces[0].retained_case_sensitive
    raw = {
        "ok": True,
        "path": str(raw_root / "Compiled" / "Example.JSON"),
        "character_id": "example",
        "character_version": "1.0.0",
        "source_hash": "1" * 64,
        "artifact_id": "compiled/example",
    }
    retained = {
        **raw,
        "path": str(retained_root / "compiled" / "example.json"),
    }
    argv = ("kokoro", "pack", "compile", r".\source-packs\example", "--json")
    spec = _operational_spec(
        (raw,),
        raw_documents=(raw,),
        retained_documents=(retained,),
        argvs=(argv,),
        namespaces=namespaces,
    )
    case = _make_case(binding, tmp_path, (spec,))
    assert _bind(binding, case).commands[0].results[0].outcome == "success"


def _refusal_spec(
    *,
    raw_document: dict[str, Any],
    retained_document: dict[str, Any] | None = None,
    exit_code: int = 7,
    compound: bool = False,
    wrong_action: bool = False,
) -> _CommandSpec:
    retained_document = raw_document if retained_document is None else retained_document
    if compound:
        documents = (raw_document, _pack_list_document())
        retained = (retained_document, _pack_list_document())
        argvs = (
            (
                "kokoro", "pack", "export", "--compiled", r".\inputs\compiled.json",
                "--promotion", r".\inputs\promotion.json", "--hard-report",
                r".\inputs\hard.json", "--soft-report", r".\inputs\soft.json",
                "--out", r".\outputs\existing.karc", "--json",
            ),
            ("kokoro", "pack", "list", "--scope", "global", "--json"),
        )
        outcomes = ("expected_refusal", "success")
        outputs = ((r"outputs\existing.karc",), ())
    else:
        documents = (raw_document,)
        retained = (retained_document,)
        argvs = (
            ("kokoro", "pack", "list", "--scope", "global", "--json"),
        ) if wrong_action else (
            (
                "kokoro", "pack", "export", "--compiled", r".\inputs\compiled.json",
                "--promotion", r".\inputs\promotion.json", "--hard-report",
                r".\inputs\hard.json", "--soft-report", r".\inputs\soft.json",
                "--out", r".\outputs\existing.karc", "--json",
            ),
        )
        outcomes = ("expected_refusal",)
        outputs = ((),) if wrong_action else ((r"outputs\existing.karc",),)
    return _operational_spec(
        documents,
        raw_documents=documents,
        retained_documents=retained,
        argvs=argvs,
        expected_outcomes=outcomes,
        declared_outputs=outputs,
        exit_code=exit_code,
    )


def test_expected_refusal_binds_code_but_retains_no_raw_message(
    tmp_path: Path,
) -> None:
    binding = _binding()
    raw_message = r"D:\private\existing.karc already exists"
    raw = {
        "ok": False,
        "error": {"code": "OUTPUT_EXISTS", "message": raw_message},
    }
    retained = {"ok": False, "error": {"code": "OUTPUT_EXISTS"}}
    spec = _refusal_spec(raw_document=raw, retained_document=retained)
    case = _make_case(binding, tmp_path, (spec,))
    evidence = _bind(binding, case)
    result = evidence.commands[0].results[0]
    assert result.outcome == "expected_refusal"
    assert result.exit_code == 7
    assert result.raw_document_sha256 == sha256(_canonical(raw)).hexdigest()
    assert result.retained_document_bytes == _canonical(retained) + b"\n"
    assert raw_message.encode("utf-8") not in result.retained_document_bytes
    assert raw_message not in repr(result)
    assert raw_message.encode("utf-8") not in evidence.canonical_bytes


@pytest.mark.parametrize(
    ("kind", "exit_code", "document"),
    (
        ("success-nonzero", 1, _pack_list_document()),
        ("success-false", 0, {"ok": False, "error": {"code": "OTHER"}}),
        ("refusal-zero", 0, {"ok": False, "error": {"code": "OUTPUT_EXISTS"}}),
        ("refusal-true", 7, {"ok": True}),
        ("refusal-code", 7, {"ok": False, "error": {"code": "OTHER"}}),
        (
            "refusal-open-error",
            7,
            {"ok": False, "error": {"code": "OUTPUT_EXISTS", "extra": True}},
        ),
    ),
)
def test_success_and_refusal_exit_document_consistency_rejects(
    tmp_path: Path,
    kind: str,
    exit_code: int,
    document: dict[str, Any],
) -> None:
    binding = _binding()
    if kind.startswith("success"):
        spec = _operational_spec((document,), exit_code=exit_code)
    else:
        spec = _refusal_spec(raw_document=document, exit_code=exit_code)
    case = _make_case(binding, tmp_path, (spec,))
    with pytest.raises(RuntimeError):
        _bind(binding, case)


@pytest.mark.parametrize(("compound", "wrong_action"), ((True, False), (False, True)))
def test_forged_compound_or_wrong_action_refusal_rejects(
    tmp_path: Path,
    compound: bool,
    wrong_action: bool,
) -> None:
    binding = _binding()
    refusal = {"ok": False, "error": {"code": "OUTPUT_EXISTS"}}
    spec = _refusal_spec(
        raw_document=refusal,
        compound=compound,
        wrong_action=wrong_action,
    )
    case = _make_case(binding, tmp_path, (spec,))
    with pytest.raises(RuntimeError):
        _bind(binding, case)


@pytest.mark.parametrize(("delta", "valid"), ((0, True), (1, False)))
def test_json_document_four_mib_exact_and_plus_one(
    tmp_path: Path,
    delta: int,
    valid: bool,
) -> None:
    binding = _binding()
    output = _exact_json_document(DOCUMENT_BYTES + delta)
    spec = _operational_spec(
        ({"ok": True},),
        raw_output=output,
        retained_output=output,
        argvs=(_large_document_argv(),),
    )
    case = _make_case(binding, tmp_path, (spec,))
    try:
        if valid:
            evidence = _bind(binding, case)
            assert evidence.commands[0].raw_output_utf8_bytes == DOCUMENT_BYTES
        else:
            with pytest.raises(RuntimeError):
                _bind(binding, case)
    finally:
        case.cleanup_large_files()


@pytest.mark.parametrize(("delta", "valid"), ((0, True), (1, False)))
def test_nonoperational_text_four_mib_exact_and_plus_one(
    tmp_path: Path,
    delta: int,
    valid: bool,
) -> None:
    binding = _binding()
    output = "x" * (DOCUMENT_BYTES + delta)
    spec = _nonoperational_spec(output, help_only=False)
    case = _make_case(binding, tmp_path, (spec,))
    try:
        if valid:
            evidence = _bind(binding, case)
            assert evidence.raw_bytes_consumed == DOCUMENT_BYTES
        else:
            with pytest.raises(RuntimeError):
                _bind(binding, case)
    finally:
        case.cleanup_large_files()


@pytest.mark.parametrize(("extra_byte", "valid"), ((False, True), (True, False)))
def test_session_budget_sixty_four_mib_exact_and_plus_one(
    tmp_path: Path,
    extra_byte: bool,
    valid: bool,
) -> None:
    binding = _binding()
    outputs = tuple(_exact_json_document(DOCUMENT_BYTES, index) for index in range(16))
    output = "".join(outputs) + (" " if extra_byte else "")
    documents = tuple({"ok": True, "index": index} for index in range(16))
    spec = _operational_spec(
        documents,
        raw_output=output,
        retained_output=output,
        argvs=tuple(_large_document_argv() for _ in documents),
    )
    case = _make_case(binding, tmp_path, (spec,))
    try:
        if valid:
            evidence = _bind(binding, case)
            assert evidence.raw_bytes_consumed == SESSION_BYTES
            assert evidence.retained_bytes_consumed == SESSION_BYTES
        else:
            with pytest.raises(RuntimeError):
                _bind(binding, case)
    finally:
        case.cleanup_large_files()


@pytest.mark.parametrize("order", ("json-text", "text-json"))
@pytest.mark.parametrize(("delta", "valid"), ((-1, True), (0, True), (1, False)))
def test_cumulative_mixed_record_budget_is_owned_once_per_domain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    order: str,
    delta: int,
    valid: bool,
) -> None:
    binding = _binding()
    test_limit = CHUNK_BYTES * 4
    json_size = CHUNK_BYTES * 2
    json_output = _exact_json_document(json_size)
    text_output = "t" * (test_limit - json_size + delta)
    json_spec = _operational_spec(
        ({"ok": True},),
        raw_output=json_output,
        retained_output=json_output,
        argvs=(_large_document_argv(),),
        event_id="json-command",
    )
    text_spec = _nonoperational_spec(
        text_output,
        help_only=False,
        event_id="text-command",
    )
    specs = (json_spec, text_spec) if order == "json-text" else (text_spec, json_spec)
    case = _make_case(binding, tmp_path, specs)
    monkeypatch.setattr(binding, "_SESSION_OUTPUT_LIMIT_BYTES", test_limit)
    if valid:
        evidence = _bind(binding, case)
        assert evidence.raw_bytes_consumed == test_limit + delta
        assert evidence.retained_bytes_consumed == test_limit + delta
    else:
        with pytest.raises(RuntimeError, match=binding.COMMAND_OUTPUT_LIMIT_EXCEEDED):
            _bind(binding, case)


@pytest.mark.parametrize("overflow_domain", ("raw", "retained"))
def test_raw_and_retained_session_budgets_overflow_independently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overflow_domain: str,
) -> None:
    binding = _binding()
    test_limit = CHUNK_BYTES * 2
    json_output = _exact_json_document(CHUNK_BYTES)
    text_exact = "t" * CHUNK_BYTES
    text_over = text_exact + "x"
    text_spec = replace(
        _nonoperational_spec(text_exact, help_only=False, event_id="text-command"),
        raw_output=text_over if overflow_domain == "raw" else text_exact,
        retained_output=text_over if overflow_domain == "retained" else text_exact,
    )
    json_spec = _operational_spec(
        ({"ok": True},),
        raw_output=json_output,
        retained_output=json_output,
        argvs=(_large_document_argv(),),
        event_id="json-command",
    )
    case = _make_case(binding, tmp_path, (json_spec, text_spec))
    monkeypatch.setattr(binding, "_SESSION_OUTPUT_LIMIT_BYTES", test_limit)
    with pytest.raises(RuntimeError, match=binding.COMMAND_OUTPUT_LIMIT_EXCEEDED):
        _bind(binding, case)


def test_128_operational_documents_are_accepted(tmp_path: Path) -> None:
    binding = _binding()
    template = _valid_success_documents()[("config", "default", "show")]
    documents_list: list[dict[str, Any]] = []
    for index in range(128):
        document = deepcopy(template)
        document["default"]["revision"] = index
        documents_list.append(document)
    documents = tuple(documents_list)
    argvs = tuple(
        ("kokoro", "config", "default", "show", "--scope", "global", "--json")
        for _ in documents
    )
    spec = _operational_spec(documents, argvs=argvs)
    case = _make_case(binding, tmp_path, (spec,))
    evidence = _bind(binding, case)
    assert len(evidence.commands[0].results) == 128


def test_129_operational_documents_reject_before_session_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding()
    documents = tuple({"ok": True, "packs": [index]} for index in range(129))
    spec = _operational_spec(documents)
    case = _make_case(binding, tmp_path, (spec,))
    targets = {os.fspath(case.raw_path), os.fspath(case.retained_path)}
    accesses: list[str] = []
    original_builtin_open = builtins.open
    original_io_open = io.open
    original_os_open = os.open
    original_lstat = Path.lstat
    original_stat = Path.stat

    def target(value: object) -> str | None:
        try:
            normalized = os.fspath(value)
        except TypeError:
            return None
        return normalized if normalized in targets else None

    def guarded_builtin(file, *args, **kwargs):
        matched = target(file)
        if matched is not None:
            accesses.append(matched)
            raise AssertionError("129-document guard must run before open")
        return original_builtin_open(file, *args, **kwargs)

    def guarded_io(file, *args, **kwargs):
        matched = target(file)
        if matched is not None:
            accesses.append(matched)
            raise AssertionError("129-document guard must run before open")
        return original_io_open(file, *args, **kwargs)

    def guarded_os(file, *args, **kwargs):
        matched = target(file)
        if matched is not None:
            accesses.append(matched)
            raise AssertionError("129-document guard must run before open")
        return original_os_open(file, *args, **kwargs)

    def guarded_lstat(path: Path, *args, **kwargs):
        matched = target(path)
        if matched is not None:
            accesses.append(matched)
            raise AssertionError("129-document guard must run before lstat")
        return original_lstat(path, *args, **kwargs)

    def guarded_stat(path: Path, *args, **kwargs):
        matched = target(path)
        if matched is not None:
            accesses.append(matched)
            raise AssertionError("129-document guard must run before stat")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_builtin)
    monkeypatch.setattr(io, "open", guarded_io)
    monkeypatch.setattr(os, "open", guarded_os)
    monkeypatch.setattr(Path, "lstat", guarded_lstat)
    monkeypatch.setattr(Path, "stat", guarded_stat)
    with pytest.raises(RuntimeError):
        _bind(binding, case)
    assert accesses == []


@pytest.mark.parametrize(
    "mutation",
    ("swapped", "duplicate", "reused", "skipped", "raw-retained-order"),
)
def test_command_tuple_order_and_completeness_mutants_reject(
    tmp_path: Path,
    mutation: str,
) -> None:
    binding = _binding()
    first = _operational_spec(
        (_pack_list_document(1),),
        event_id="command-1",
    )
    second = _operational_spec(
        (_pack_list_document(2),),
        event_id="command-2",
    )
    case = _make_case(binding, tmp_path, (first, second))
    first_pair, second_pair = case.commands
    if mutation == "swapped":
        case.commands = (second_pair, first_pair)
    elif mutation == "duplicate":
        case.commands = (first_pair, replace(second_pair, command_index=0))
    elif mutation == "reused":
        case.commands = (first_pair, first_pair)
    elif mutation == "skipped":
        case.commands = (first_pair, replace(second_pair, command_index=2))
    else:
        case.commands = (
            replace(first_pair, retained_capture=second_pair.retained_capture),
            replace(second_pair, retained_capture=first_pair.retained_capture),
        )
    with pytest.raises(RuntimeError):
        _bind(binding, case)


@pytest.mark.parametrize(
    "mutation",
    ("wrong-session", "wrong-root", "wrong-path", "event-id", "ordinal-overlap"),
)
def test_session_event_and_capture_pair_drift_rejects(
    tmp_path: Path,
    mutation: str,
) -> None:
    binding = _binding()
    first = _operational_spec(
        (_pack_list_document(1),),
        event_id="command-1",
    )
    second = _operational_spec(
        (_pack_list_document(2),),
        event_id="command-2",
    )
    case = _make_case(binding, tmp_path, (first, second))
    session_id = case.session_id
    if mutation == "wrong-session":
        session_id = "session-2"
    elif mutation == "wrong-root":
        _replace_capture(case, 0, "raw", session_root=tmp_path / "other")
    elif mutation == "wrong-path":
        _replace_capture(case, 0, "raw", session_path=case.raw_root / "other.jsonl")
    elif mutation == "event-id":
        _replace_capture(case, 0, "retained", event_id="different")
    else:
        _replace_capture(case, 1, "raw", started_event_ordinal=1)
        _replace_capture(case, 1, "retained", started_event_ordinal=1)
    with pytest.raises(RuntimeError):
        _bind(binding, case, session_id=session_id)


@pytest.mark.parametrize("mode", ("correct", "wrong", "duplicate"))
def test_thread_started_binds_session_id_exactly_once(
    tmp_path: Path,
    mode: str,
) -> None:
    binding = _binding()
    case = _make_case(
        binding,
        tmp_path,
        (_operational_spec((_pack_list_document(),)),),
    )
    thread_id = case.session_id if mode != "wrong" else "different-session"
    event = {"type": "thread.started", "thread_id": thread_id}
    _prepend_session_events(
        binding,
        case,
        (event, event) if mode == "duplicate" else (event,),
    )
    if mode == "correct":
        assert _bind(binding, case).session_id == case.session_id
    else:
        with pytest.raises(RuntimeError, match=binding.COMMAND_CAPTURE_INVALID):
            _bind(binding, case)


@pytest.mark.parametrize(
    "field",
    ("device", "inode", "size", "modified_ns", "file_type", "link_count"),
)
def test_live_session_identity_scalar_drift_rejects(
    tmp_path: Path,
    field: str,
) -> None:
    binding = _binding()
    spec = _operational_spec((_pack_list_document(),))
    case = _make_case(binding, tmp_path, (spec,))
    identity = case.raw_identity
    forged = replace(identity, **{field: getattr(identity, field) + 1})
    case.raw_identity = forged
    _replace_capture(case, 0, "raw", session_identity=forged)
    with pytest.raises(RuntimeError):
        _bind(binding, case)


def test_top_level_identity_mutation_after_scan_rejects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding()
    case = _make_case(
        binding,
        tmp_path,
        (_operational_spec((_pack_list_document(),)),),
    )
    detached = replace(case.raw_identity)
    case.raw_identity = detached

    def mutate_after_scan(domain: str, _root: Path, _path: Path) -> None:
        if domain == "raw":
            object.__setattr__(detached, "modified_ns", detached.modified_ns + 1)

    monkeypatch.setattr(binding, "_before_session_file_recheck", mutate_after_scan)
    with pytest.raises(RuntimeError, match=binding.COMMAND_CAPTURE_INVALID):
        _bind(binding, case)


def test_session_identity_relative_path_drift_rejects(tmp_path: Path) -> None:
    binding = _binding()
    spec = _operational_spec((_pack_list_document(),))
    case = _make_case(binding, tmp_path, (spec,))
    forged = replace(case.raw_identity, relative_path="other.jsonl")
    case.raw_identity = forged
    _replace_capture(case, 0, "raw", session_identity=forged)
    with pytest.raises(RuntimeError):
        _bind(binding, case)


@pytest.mark.parametrize(
    "field",
    (
        "event_start",
        "event_end",
        "output_field_start",
        "output_field_end",
        "output_field_utf8_bytes",
        "output_field_sha256",
        "output_utf8_bytes",
        "output_sha256",
        "exit_code",
    ),
)
def test_span_length_hash_and_exit_capture_drift_rejects(
    tmp_path: Path,
    field: str,
) -> None:
    binding = _binding()
    spec = _operational_spec((_pack_list_document(),))
    case = _make_case(binding, tmp_path, (spec,))
    capture = case.commands[0].raw_capture
    if field.endswith("sha256"):
        value: object = ZERO_SHA256
    elif field in {"event_end", "output_field_end"}:
        value = getattr(capture, field) - 1
    else:
        value = getattr(capture, field) + 1
    with pytest.raises(RuntimeError):
        _replace_capture(case, 0, "raw", **{field: value})
        _bind(binding, case)


@pytest.mark.parametrize(
    "mutation",
    ("started-output", "completed-command", "completed-status", "extra-item-field"),
)
def test_exact_command_execution_lifecycle_shape_rejects(
    tmp_path: Path,
    mutation: str,
) -> None:
    binding = _binding()
    spec = _operational_spec((_pack_list_document(),))

    def mutate(_domain: str, _index: int, phase: str, event: dict[str, Any]) -> None:
        item = event["item"]
        if mutation == "started-output" and phase == "started":
            item["aggregated_output"] = "noise"
        elif mutation == "completed-command" and phase == "completed":
            item["command"] += " changed"
        elif mutation == "completed-status" and phase == "completed":
            item["status"] = "in_progress"
        elif mutation == "extra-item-field" and phase == "completed":
            item["unexpected"] = True

    case = _make_case(binding, tmp_path, (spec,), event_mutator=mutate)
    with pytest.raises(RuntimeError):
        _bind(binding, case)


def test_undeclared_unsupported_command_execution_event_rejects(
    tmp_path: Path,
) -> None:
    binding = _binding()
    case = _make_case(
        binding,
        tmp_path,
        (_operational_spec((_pack_list_document(),)),),
    )
    event = {
        "type": "item.updated",
        "item": {
            "id": "undeclared-command",
            "type": "command_execution",
            "command": "kokoro pack list --scope global --json",
            "aggregated_output": "",
            "exit_code": None,
            "status": "in_progress",
        },
    }
    _append_session_event(binding, case, event)
    with pytest.raises(RuntimeError, match=binding.COMMAND_CAPTURE_INVALID):
        _bind(binding, case)


class _GuardedReader:
    def __init__(self, source, requests: list[int]):
        self._source = source
        self._requests = requests

    def read(self, size: int = -1):
        self._requests.append(size)
        if type(size) is not int or not 0 < size <= CHUNK_BYTES:
            raise AssertionError(f"unbounded session read: {size!r}")
        return self._source.read(size)

    def __enter__(self):
        self._source.__enter__()
        return self

    def __exit__(self, *args):
        return self._source.__exit__(*args)

    def __getattr__(self, name: str):
        return getattr(self._source, name)


class _TrackedReader:
    def __init__(self, source):
        self._source = source

    @property
    def closed(self) -> bool:
        return self._source.closed

    def __getattr__(self, name: str):
        return getattr(self._source, name)


def test_session_handle_closes_when_post_open_hook_rejects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding()
    case = _make_case(
        binding,
        tmp_path,
        (_operational_spec((_pack_list_document(),)),),
    )
    opened: list[_TrackedReader] = []
    original_fdopen = binding.os.fdopen

    def tracked_fdopen(*args, **kwargs):
        tracked = _TrackedReader(original_fdopen(*args, **kwargs))
        opened.append(tracked)
        return tracked

    def reject_after_open(_domain: str, _root: Path, _path: Path) -> None:
        raise RuntimeError(binding.COMMAND_CAPTURE_INVALID)

    monkeypatch.setattr(binding.os, "fdopen", tracked_fdopen)
    monkeypatch.setattr(binding, "_after_session_file_open", reject_after_open)
    with pytest.raises(RuntimeError, match=binding.COMMAND_CAPTURE_INVALID):
        _bind(binding, case)
    assert opened
    assert all(reader.closed for reader in opened)


def test_nonwindows_open_closes_descriptor_when_fdopen_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding()
    closed: list[int] = []

    monkeypatch.setattr(binding.os, "open", lambda _path, _flags: 173)

    def reject_fdopen(*_args, **_kwargs):
        raise OSError("synthetic fdopen failure")

    monkeypatch.setattr(binding.os, "fdopen", reject_fdopen)
    monkeypatch.setattr(binding.os, "close", closed.append)
    with pytest.raises(RuntimeError, match=binding.COMMAND_CAPTURE_INVALID):
        binding._open_session_binary(Path("synthetic-session.jsonl"))
    assert closed == [173]


@pytest.mark.skipif(os.name != "nt", reason="Windows held-handle contract")
@pytest.mark.parametrize("mutation", ("replace-final", "add-hardlink", "replace-parent"))
def test_windows_preopen_namespace_and_link_mutants_reject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    binding = _binding()
    case = _make_case(
        binding,
        tmp_path,
        (_operational_spec((_pack_list_document(),)),),
    )

    def mutate_before_open(domain: str, root: Path, path: Path) -> None:
        if domain != "raw":
            return
        if mutation == "replace-final":
            original = path.with_name("original-session.jsonl")
            path.rename(original)
            path.write_bytes(b"{}\n".ljust(original.stat().st_size, b" "))
        elif mutation == "add-hardlink":
            os.link(path, path.with_name("alternate-session.jsonl"))
        else:
            moved = root.with_name("original-session-root")
            root.rename(moved)
            root.mkdir()
            (root / path.name).write_bytes((moved / path.name).read_bytes())

    monkeypatch.setattr(binding, "_before_session_file_open", mutate_before_open)
    with pytest.raises(RuntimeError, match=binding.COMMAND_CAPTURE_INVALID):
        _bind(binding, case)


@pytest.mark.skipif(os.name != "nt", reason="Windows no-follow reparse contract")
def test_windows_preopen_final_symlink_reparse_rejects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding()
    case = _make_case(
        binding,
        tmp_path,
        (_operational_spec((_pack_list_document(),)),),
    )
    backup = case.raw_path.with_name("symlink-target-session.jsonl")

    def replace_with_symlink(domain: str, _root: Path, path: Path) -> None:
        if domain != "raw":
            return
        path.rename(backup)
        try:
            os.symlink(backup.name, path, target_is_directory=False)
        except OSError as error:
            backup.rename(path)
            pytest.skip(f"Windows symlink creation unavailable: {error.winerror}")

    monkeypatch.setattr(binding, "_before_session_file_open", replace_with_symlink)
    with pytest.raises(RuntimeError, match=binding.COMMAND_CAPTURE_INVALID):
        _bind(binding, case)


@pytest.mark.skipif(os.name != "nt", reason="Windows held-handle contract")
def test_windows_postopen_final_name_swap_back_rejects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding()
    case = _make_case(
        binding,
        tmp_path,
        (_operational_spec((_pack_list_document(),)),),
    )
    backup = case.raw_path.with_name("held-original.jsonl")

    def swap_after_open(domain: str, _root: Path, path: Path) -> None:
        if domain == "raw":
            path.rename(backup)
            path.write_bytes(b'{"type":"attacker"}\n')

    def restore_before_recheck(domain: str, _root: Path, path: Path) -> None:
        if domain == "raw":
            path.unlink()
            backup.rename(path)

    monkeypatch.setattr(binding, "_after_session_file_open", swap_after_open)
    monkeypatch.setattr(binding, "_before_session_file_recheck", restore_before_recheck)
    with pytest.raises(RuntimeError, match=binding.COMMAND_CAPTURE_INVALID):
        _bind(binding, case)


@pytest.mark.skipif(os.name != "nt", reason="Windows held-handle contract")
def test_windows_postopen_hardlink_drift_rejects_and_closes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding()
    case = _make_case(
        binding,
        tmp_path,
        (_operational_spec((_pack_list_document(),)),),
    )
    streams: list[_TrackedReader] = []
    original_fdopen = binding.os.fdopen

    def tracked_fdopen(*args, **kwargs):
        tracked = _TrackedReader(original_fdopen(*args, **kwargs))
        streams.append(tracked)
        return tracked

    def add_link_after_open(domain: str, _root: Path, path: Path) -> None:
        if domain == "raw":
            os.link(path, path.with_name("post-open-hardlink.jsonl"))

    monkeypatch.setattr(binding.os, "fdopen", tracked_fdopen)
    monkeypatch.setattr(binding, "_after_session_file_open", add_link_after_open)
    with pytest.raises(RuntimeError, match=binding.COMMAND_CAPTURE_INVALID):
        _bind(binding, case)
    assert streams
    assert all(stream.closed for stream in streams)


@pytest.mark.skipif(os.name != "nt", reason="Windows native no-follow flags")
def test_windows_native_opens_require_no_reparse_flags() -> None:
    binding = _binding()
    api = binding._WindowsNativeApi()
    anchor_flags: list[int] = []
    relative_attributes: list[int] = []
    relative_options: list[int] = []

    def fake_create_file(
        _path,
        _desired,
        _sharing,
        _security,
        _disposition,
        flags,
        _template,
    ):
        anchor_flags.append(int(flags))
        return 123

    def fake_nt_create_file(
        handle_pointer,
        _desired,
        attributes_pointer,
        _io_status,
        _allocation,
        _file_attributes,
        _sharing,
        _disposition,
        options,
        _ea_buffer,
        _ea_length,
    ):
        attributes = binding.ctypes.cast(
            attributes_pointer,
            binding.ctypes.POINTER(binding._ObjectAttributes),
        ).contents
        relative_attributes.append(int(attributes.attributes))
        relative_options.append(int(options))
        output = binding.ctypes.cast(
            handle_pointer,
            binding.ctypes.POINTER(binding.wintypes.HANDLE),
        )
        output.contents.value = 456
        return 0

    api._create_file = fake_create_file
    api._nt_create_file = fake_nt_create_file
    assert api.open_anchor("C:\\") == 123
    assert api.open_relative(binding.wintypes.HANDLE(123), "child", directory=True)
    assert api.open_relative(binding.wintypes.HANDLE(123), "session.jsonl", directory=False)
    assert anchor_flags == [
        api._FILE_FLAG_OPEN_REPARSE_POINT | api._FILE_FLAG_BACKUP_SEMANTICS
    ]
    assert relative_attributes == [api._OBJ_DONT_REPARSE, api._OBJ_DONT_REPARSE]
    assert all(options & api._FILE_OPEN_REPARSE_POINT for options in relative_options)


def test_session_reader_never_requests_more_than_64_kib(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding()
    output = _exact_json_document(CHUNK_BYTES * 3 + 17)
    spec = _operational_spec(
        ({"ok": True},),
        raw_output=output,
        retained_output=output,
        argvs=(_large_document_argv(),),
    )
    case = _make_case(binding, tmp_path, (spec,))
    targets = {os.fspath(case.raw_path), os.fspath(case.retained_path)}
    requests: list[int] = []
    original_builtin_open = builtins.open
    original_io_open = io.open
    original_fdopen = os.fdopen

    def is_target(value: object) -> bool:
        try:
            return os.fspath(value) in targets
        except TypeError:
            return False

    def guarded_builtin(file, *args, **kwargs):
        source = original_builtin_open(file, *args, **kwargs)
        return _GuardedReader(source, requests) if is_target(file) else source

    def guarded_io(file, *args, **kwargs):
        source = original_io_open(file, *args, **kwargs)
        return _GuardedReader(source, requests) if is_target(file) else source

    def guarded_fdopen(*args, **kwargs):
        source = original_fdopen(*args, **kwargs)
        mode = args[1] if len(args) > 1 else kwargs.get("mode", "r")
        return _GuardedReader(source, requests) if "b" in mode else source

    monkeypatch.setattr(builtins, "open", guarded_builtin)
    monkeypatch.setattr(io, "open", guarded_io)
    monkeypatch.setattr(os, "fdopen", guarded_fdopen)
    evidence = _bind(binding, case)
    assert len(evidence.commands[0].results) == 1
    assert requests
    assert max(requests) <= CHUNK_BYTES


def test_peak_retained_decoder_buffer_is_one_document_plus_two_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding()
    output = _exact_json_document(CHUNK_BYTES * 3 + 17)
    spec = _operational_spec(
        ({"ok": True},),
        raw_output=output,
        retained_output=output,
        argvs=(_large_document_argv(),),
    )
    case = _make_case(binding, tmp_path, (spec,))
    observed: list[int] = []
    payload_types: list[type] = []
    original_decode = binding._decode_document

    def tracked_decode(payload):
        payload_types.append(type(payload))
        return original_decode(payload)

    monkeypatch.setattr(binding, "_note_decoder_buffer_size", observed.append)
    monkeypatch.setattr(binding, "_decode_document", tracked_decode)
    evidence = _bind(binding, case)
    assert evidence.commands[0].results
    document_bytes = len(output.encode("utf-8"))
    assert observed
    assert payload_types[:2] == [bytearray, bytearray]
    assert max(observed) <= document_bytes + (2 * CHUNK_BYTES)
    assert max(observed) >= document_bytes - 1


def test_raw_document_summaries_release_each_selector_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding()
    document = _pack_list_document()
    spec = _operational_spec((document,))
    operation = spec.decision.operations[0]
    selector_references: list[weakref.ReferenceType[object]] = []

    class TrackedSelector(dict[str, object]):
        pass

    def oversized_selector(*_args, **_kwargs) -> object:
        selector = TrackedSelector(
            payload=("x" * (256 * 1024)) + str(len(selector_references))
        )
        selector_references.append(weakref.ref(selector))
        return selector

    monkeypatch.setattr(
        binding,
        "_success_selector_projection",
        oversized_selector,
    )
    summaries = tuple(
        binding._summarize_document(
            document,
            _canonical(document),
            operation=operation,
            plan=spec.plan,
            domain="raw",
            retain=False,
        )
        for _index in range(128)
    )
    gc.collect()

    assert len(summaries) == 128
    assert "selector" not in {field.name for field in fields(binding._ParsedDocument)}
    assert all(reference() is None for reference in selector_references)


def test_session_budget_rejects_without_reading_the_unbounded_tail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding()
    test_limit = CHUNK_BYTES * 2
    document = _exact_json_document(test_limit - 1)
    output = document + (" " * (CHUNK_BYTES * 8))
    spec = _operational_spec(
        ({"ok": True},),
        raw_output=output,
        retained_output=output,
        argvs=(_large_document_argv(),),
    )
    case = _make_case(binding, tmp_path, (spec,))
    consumed = {"raw": 0, "retained": 0}
    original_read = binding._SessionReader.read

    def bounded_read(reader, size: int) -> bytes:
        data = original_read(reader, size)
        consumed[reader.domain] += len(data)
        if consumed[reader.domain] > test_limit + (CHUNK_BYTES * 2):
            raise AssertionError("binder read beyond the bounded rejection window")
        return data

    monkeypatch.setattr(binding, "_SESSION_OUTPUT_LIMIT_BYTES", test_limit)
    monkeypatch.setattr(binding._SessionReader, "read", bounded_read)
    with pytest.raises(RuntimeError, match=binding.COMMAND_OUTPUT_LIMIT_EXCEEDED):
        _bind(binding, case)
    assert consumed["raw"] <= test_limit + (CHUNK_BYTES * 2)
    assert consumed["retained"] == 0


def test_json_escape_and_surrogate_pair_cross_a_64_kib_source_boundary(
    tmp_path: Path,
) -> None:
    binding = _binding()
    pad = CHUNK_BYTES
    case: _BoundCase | None = None
    document: dict[str, Any]
    for _attempt in range(3):
        request = _fixture("authoring", "original-request.json")
        request["inputs"] = [
            {"type": "creative_brief", "content": ("x" * pad) + "😀"}
        ]
        document = {"ok": True, "request": request}
        spec = _operational_spec(
            (document,),
            argvs=(_large_document_argv(),),
        )
        case = _make_case(binding, tmp_path, (spec,), ensure_ascii=True)
        payload = case.raw_path.read_bytes()
        escape_start = payload.index(b"\\ud83d")
        remainder = escape_start % CHUNK_BYTES
        if remainder == CHUNK_BYTES - 2:
            break
        pad += (CHUNK_BYTES - 2 - remainder) % CHUNK_BYTES
    assert case is not None
    payload = case.raw_path.read_bytes()
    escape_start = payload.index(b"\\ud83d")
    assert escape_start % CHUNK_BYTES == CHUNK_BYTES - 2
    assert payload[escape_start : escape_start + 12] == b"\\ud83d\\ude00"
    evidence = _bind(binding, case)
    retained = json.loads(evidence.commands[0].results[0].retained_document_bytes)
    assert retained["request"]["inputs"][0]["content"].endswith("😀")


def test_bound_bytes_are_immutable_and_each_decode_is_fresh(tmp_path: Path) -> None:
    binding = _binding()
    document = _valid_success_documents()[("pack", "list")]
    spec = _operational_spec((document,))
    case = _make_case(binding, tmp_path, (spec,))
    evidence = _bind(binding, case)
    command = evidence.commands[0]
    result = command.results[0]
    trusted = result.retained_document_bytes
    first = result.decoded_retained_document()
    second = result.decoded_retained_document()
    first["installed"][0]["installation_id"] = "mutated"
    assert second == document
    assert json.loads(result.retained_document_bytes) == document
    assert result.retained_document_bytes is trusted
    with pytest.raises(FrozenInstanceError):
        result.exit_code = 9
    with pytest.raises(FrozenInstanceError):
        command.results = ()
    with pytest.raises(FrozenInstanceError):
        evidence.commands = ()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("device", True),
        ("inode", -1),
        ("size", -1),
        ("modified_ns", -1),
        ("file_type", 0),
        ("link_count", 0),
        ("relative_path", r"C:\absolute\session.jsonl"),
        ("relative_path", r"..\session.jsonl"),
        ("relative_path", "session.jsonl:stream"),
    ),
)
def test_session_identity_model_rejects_invalid_exact_types_and_paths(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    binding = _binding()
    spec = _operational_spec((_pack_list_document(),))
    case = _make_case(binding, tmp_path, (spec,))
    with pytest.raises(RuntimeError):
        replace(case.raw_identity, **{field: value})
