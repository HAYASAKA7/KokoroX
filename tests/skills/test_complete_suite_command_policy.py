from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from hashlib import sha256
import inspect
import json
import os
from pathlib import Path, PureWindowsPath
import sys
from typing import get_type_hints, Literal

import pytest


SKILLS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILLS_ROOT))

import complete_suite_command_plan as command_plan  # noqa: E402
import complete_suite_command_policy as command_policy  # noqa: E402


ZERO_SHA256 = "0" * 64
FILESYSTEM_VERSION = "complete-suite-policy-filesystem-state-v1"
_SYNTHETIC_PAYLOADS: dict[str, bytes] = {}


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _literal(value: str) -> dict[str, object]:
    encoded = value.encode("utf-8")
    return {
        "kind": "bare",
        "sha256": sha256(encoded).hexdigest(),
        "utf8_bytes": len(encoded),
        "value": value,
    }


def _command_document(
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
    operations = 0
    pipeline_stages = 0

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
        nodes[1]["child_indices"].append(pipeline_index)  # type: ignore[union-attr]
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
            nodes[pipeline_index]["child_indices"].append(command_index)  # type: ignore[union-attr]
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
            elif operator == "dot":
                add_token("Dot", ".")
            for value in argv:
                child_index = len(nodes)
                nodes[command_index]["child_indices"].append(child_index)  # type: ignore[union-attr]
                if value.startswith("-") and not value.startswith("--"):
                    node_type = "CommandParameterAst"
                    role = "command_element"
                    node_literal = None
                    token_kind = "Parameter"
                    token_literal = None
                elif value.isdecimal():
                    node_type = "ConstantExpressionAst"
                    role = "expression"
                    node_literal = None
                    token_kind = "Number"
                    token_literal = _literal(value)
                else:
                    node_type = "StringConstantExpressionAst"
                    role = "expression"
                    node_literal = _literal(value)
                    token_kind = "Identifier"
                    token_literal = node_literal
                nodes.append(
                    {
                        "index": child_index,
                        "ast_type": node_type,
                        "role": role,
                        "parent_index": command_index,
                        "child_indices": [],
                        "invocation_operator": None,
                        "literal": node_literal,
                    }
                )
                add_token(token_kind, value, token_literal)
            operations += 1
            pipeline_stages += 1
            if stage_index + 1 < len(pipeline):
                add_token("Pipe", "|")
        if statement_index + 1 < len(statements):
            add_token("Semi", ";")
    add_token("EndOfInput", "")
    return {
        "metrics": {
            "ast_depth": 5,
            "ast_nodes": len(nodes),
            "operations": operations,
            "pipeline_stages": pipeline_stages,
            "statements": len(statements) + operations,
        },
        "nodes": nodes,
        "tokens": tokens,
    }


def _bound_plan(
    *argv: str,
    operator: str = "none",
    statements: tuple[tuple[tuple[tuple[str, ...], str], ...], ...] | None = None,
    mutate_command=None,
) -> command_plan.BoundCommandPlan:
    if statements is None:
        statements = ((((tuple(argv)), operator),),)
    command = _command_document(statements)
    if mutate_command is not None:
        mutate_command(command)
    payload = b"synthetic"
    digest = sha256(payload).hexdigest()
    manifest = command_plan._namespace_manifest(())
    manifest_sha256 = sha256(_canonical_bytes(manifest)).hexdigest()
    document = {
        "bindings": {
            side: {
                field: {"sha256": digest, "utf8_bytes": len(payload)}
                for field in ("payload", "payload_field", "rendered")
            }
            for side in ("raw", "retained")
        },
        "command": command,
        "decoder": {"path": "synthetic-decoder.ps1", "sha256": ZERO_SHA256},
        "namespace_manifest_sha256": manifest_sha256,
        "namespaces": [],
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
    normalized = _canonical_bytes(document)
    return command_plan.BoundCommandPlan(
        version="complete-suite-bound-command-plan-v1",
        raw_rendered_utf8_bytes=len(payload),
        raw_rendered_sha256=digest,
        retained_rendered_utf8_bytes=len(payload),
        retained_rendered_sha256=digest,
        raw_payload_field_utf8_bytes=len(payload),
        raw_payload_field_sha256=digest,
        raw_payload_utf8_bytes=len(payload),
        raw_payload_sha256=digest,
        retained_payload_field_utf8_bytes=len(payload),
        retained_payload_field_sha256=digest,
        retained_payload_utf8_bytes=len(payload),
        retained_payload_sha256=digest,
        namespaces=(),
        namespace_manifest_sha256=manifest_sha256,
        normalized_plan_sha256=sha256(normalized).hexdigest(),
        normalized_plan_bytes=normalized,
    )


def _forge_normalized_command_plan(
    plan: command_plan.BoundCommandPlan,
    mutate,
) -> command_plan.BoundCommandPlan:
    document = json.loads(plan.normalized_plan_bytes)
    mutate(document["command"])
    forged_bytes = _canonical_bytes(document)
    object.__setattr__(plan, "normalized_plan_bytes", forged_bytes)
    object.__setattr__(
        plan,
        "normalized_plan_sha256",
        sha256(forged_bytes).hexdigest(),
    )
    return plan


def _identity(inode: int) -> dict[str, int]:
    return {
        "device": 7,
        "inode": inode,
        "file_type": 1,
        "reparse_tag": 0,
        "link_count": 1,
    }


def _entry(path: str, payload: bytes | None, inode: int) -> dict[str, object]:
    kind = "directory" if payload is None else "file"
    if payload is not None:
        _SYNTHETIC_PAYLOADS[sha256(payload).hexdigest()] = payload
    return {
        "identity": _identity(inode),
        "kind": kind,
        "link_count": 1,
        "relative_path": path,
        "sha256": None if payload is None else sha256(payload).hexdigest(),
        "size": 0 if payload is None else len(payload),
    }


def _root_record(
    entries: list[dict[str, object]],
    *,
    root_identity: dict[str, int] | None = None,
    ancestor_identities: list[dict[str, int]] | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "ancestor_identities": ancestor_identities or [_identity(1)],
        "entries": sorted(entries, key=lambda value: str(value["relative_path"])),
        "present": True,
        "relative_root": "workspace",
        "root_identity": root_identity or _identity(2),
        "root_index": 0,
    }
    record["manifest_sha256"] = sha256(_canonical_bytes(record)).hexdigest()
    return record


def _state_bytes(
    entries: list[dict[str, object]],
    *,
    post: bool,
    created: tuple[str, ...] = (),
    changed: tuple[str, ...] = (),
    removed: tuple[str, ...] = (),
    root_identity: dict[str, int] | None = None,
    ancestor_identities: list[dict[str, int]] | None = None,
) -> bytes:
    document: dict[str, object] = {
        "policy_filesystem_roots": [
            _root_record(
                entries,
                root_identity=root_identity,
                ancestor_identities=ancestor_identities,
            )
        ],
        "schema_version": FILESYSTEM_VERSION,
    }
    if post:
        document.update(
            {
                "changed_paths": list(changed),
                "created_paths": list(created),
                "removed_paths": list(removed),
            }
        )
    return _canonical_bytes(document)


def _base_entries() -> list[dict[str, object]]:
    values: list[tuple[str, bytes | None]] = [
        (".tools", None),
        (r".tools\kokoro.cmd", b"shim"),
        (r".tools\rg.exe", b"rg"),
        ("data", None),
        ("inputs", None),
        (r"inputs\archive.karc", b"archive"),
        (r"inputs\compiled.json", b"{}"),
        (r"inputs\event.json", b"{}"),
        (r"inputs\hard.json", b"{}"),
        (r"inputs\policy.json", b"{}"),
        (r"inputs\promotion.json", b"{}"),
        (r"inputs\rendered.txt", b"hello"),
        (r"inputs\request.json", b"{}"),
        (r"inputs\review.json", b"{}"),
        (r"inputs\semantic.json", b"{}"),
        (r"inputs\soft-input.json", b"{}"),
        (r"inputs\soft.json", b"{}"),
        (r"inputs\summary.txt", b"summary"),
        ("outputs", None),
        ("source-packs", None),
        (r"source-packs\rin", None),
        (r"source-packs\rin\pack.yaml", b"name: rin\n"),
    ]
    return [_entry(path, payload, index + 10) for index, (path, payload) in enumerate(values)]


def _context(
    tmp_path: Path,
    *,
    case_id: str = "synthetic-case",
    pre_extra: list[dict[str, object]] | None = None,
    post_extra: list[dict[str, object]] | None = None,
    created: tuple[str, ...] = (),
    changed: tuple[str, ...] = (),
    removed: tuple[str, ...] = (),
) -> command_policy.CommandPolicyContext:
    case_root = tmp_path / "case"
    workspace = case_root / "workspace"
    base = _base_entries()
    pre = base + list(pre_extra or [])
    post = base + list(post_extra if post_extra is not None else (pre_extra or []))
    for entry in sorted(post, key=lambda value: str(value["relative_path"]).count("\\")):
        target = workspace.joinpath(*PureWindowsPath(str(entry["relative_path"])).parts)
        if entry["kind"] == "directory":
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = str(entry["sha256"])
            target.write_bytes(_SYNTHETIC_PAYLOADS[digest])

    def live_identity(path: Path) -> dict[str, int]:
        return command_policy._identity_record(
            command_policy._observe_live_identity(path)
        )

    live_post: list[dict[str, object]] = []
    live_by_path: dict[str, dict[str, object]] = {}
    for entry in post:
        relative_path = str(entry["relative_path"])
        target = workspace.joinpath(*PureWindowsPath(relative_path).parts)
        detached = dict(entry)
        detached["identity"] = live_identity(target)
        detached["link_count"] = detached["identity"]["link_count"]  # type: ignore[index]
        live_post.append(detached)
        live_by_path[relative_path.casefold()] = detached
    live_pre: list[dict[str, object]] = []
    for entry in pre:
        detached = dict(entry)
        current = live_by_path.get(str(entry["relative_path"]).casefold())
        if current is not None and current["kind"] == entry["kind"]:
            detached["identity"] = current["identity"]
            detached["link_count"] = current["link_count"]
        live_pre.append(detached)
    _root, root_observation, ancestors, _case_sensitive = (
        command_plan._observe_namespace_root(str(workspace))
    )
    root_identity = command_policy._identity_record(root_observation)
    ancestor_identities = [
        command_policy._identity_record(identity) for identity in ancestors
    ]
    filesystem = command_policy.bind_filesystem_evidence(
        _state_bytes(
            live_pre,
            post=False,
            root_identity=root_identity,
            ancestor_identities=ancestor_identities,
        ),
        _state_bytes(
            live_post,
            post=True,
            created=created,
            changed=changed,
            removed=removed,
            root_identity=root_identity,
            ancestor_identities=ancestor_identities,
        ),
        case_root=case_root,
    )
    return command_policy.CommandPolicyContext(
        case_id=case_id,
        case_root=case_root,
        workspace_root=workspace,
        data_root=workspace / "data",
        approved_read_roots=(workspace,),
        approved_output_roots=(workspace / "outputs", workspace / "data" / "compiled"),
        kokoro_shim=workspace / ".tools" / "kokoro.cmd",
        kokoro_shim_sha256=sha256(b"shim").hexdigest(),
        rg_executable=workspace / ".tools" / "rg.exe",
        rg_sha256=sha256(b"rg").hexdigest(),
        shell_path_entries=(workspace / ".tools",),
        shell_pathext=(".COM", ".EXE", ".BAT", ".CMD"),
        shell_environment_sha256=command_policy._shell_environment_fact_sha256(
            (workspace / ".tools",),
            (".COM", ".EXE", ".BAT", ".CMD"),
        ),
        filesystem=filesystem,
    )


def _context_with_outputs(
    tmp_path: Path,
    outputs: tuple[str, ...],
    *,
    case_id: str = "synthetic-case",
) -> command_policy.CommandPolicyContext:
    entries = [
        _entry(path, b"{}", 500 + index)
        for index, path in enumerate(outputs)
    ]
    created = tuple(
        sorted((f"workspace\\{path}" for path in outputs), key=str.casefold)
    )
    return _context(
        tmp_path,
        case_id=case_id,
        post_extra=entries,
        created=created,
    )


def _context_with_narrow_snapshot_roots(
    tmp_path: Path,
    *,
    absent_output_root: bool = False,
    output_child_created: bool = False,
) -> command_policy.CommandPolicyContext:
    output_entry = _entry(r"outputs\fresh.json", b"{}", 699)
    include_output = absent_output_root or output_child_created
    context = _context(
        tmp_path,
        post_extra=[output_entry] if include_output else None,
        created=(r"workspace\outputs\fresh.json",)
        if include_output
        else (),
    )
    relative_roots = command_policy._windows_sorted(
        (
            r"workspace\.tools",
            r"workspace\data",
            r"workspace\inputs",
            r"workspace\outputs",
            r"workspace\source-packs",
        )
    )

    def identity_record(identity: command_plan.FilesystemObjectIdentity) -> dict[str, int]:
        return command_policy._identity_record(identity)

    def split_roots(
        source: command_policy.FilesystemRootSnapshot,
        *,
        pre: bool,
    ) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for index, relative_root in enumerate(relative_roots):
            within_workspace = str(
                PureWindowsPath(relative_root).relative_to("workspace")
            )
            root_entry = next(
                entry
                for entry in source.entries
                if command_policy._windows_path_equal(
                    entry.relative_path, within_workspace
                )
            )
            prefix = f"{within_workspace}\\"
            entries = []
            for entry in source.entries:
                if not entry.relative_path.startswith(prefix):
                    continue
                entries.append(
                    {
                        "identity": identity_record(entry.identity),
                        "kind": entry.kind,
                        "link_count": entry.link_count,
                        "relative_path": entry.relative_path[len(prefix) :],
                        "sha256": entry.sha256,
                        "size": entry.size,
                    }
                )
            absent = (
                absent_output_root
                and pre
                and relative_root == r"workspace\outputs"
            )
            record: dict[str, object] = {
                "ancestor_identities": [
                    identity_record(identity)
                    for identity in (
                        *source.ancestor_identities,
                        source.root_identity,
                    )
                ],
                "entries": [] if absent else entries,
                "present": not absent,
                "relative_root": relative_root,
                "root_identity": (
                    None if absent else identity_record(root_entry.identity)
                ),
                "root_index": index,
            }
            record["manifest_sha256"] = sha256(
                _canonical_bytes(record)
            ).hexdigest()
            result.append(record)
        return result

    pre_document = {
        "policy_filesystem_roots": split_roots(
            context.filesystem.pre_roots[0], pre=True
        ),
        "schema_version": FILESYSTEM_VERSION,
    }
    created_paths = []
    if absent_output_root:
        created_paths.append(r"workspace\outputs")
    if include_output:
        created_paths.append(r"workspace\outputs\fresh.json")
    post_document = {
        "changed_paths": [],
        "created_paths": created_paths,
        "policy_filesystem_roots": split_roots(
            context.filesystem.post_roots[0], pre=False
        ),
        "removed_paths": [],
        "schema_version": FILESYSTEM_VERSION,
    }
    return replace(
        context,
        filesystem=command_policy.bind_filesystem_evidence(
            _canonical_bytes(pre_document),
            _canonical_bytes(post_document),
            case_root=context.case_root,
        ),
    )


EXPECTED_FIELDS = {
    "FilesystemSnapshotEntry": (
        "relative_path", "kind", "size", "sha256", "link_count", "identity"
    ),
    "FilesystemRootSnapshot": (
        "root_index", "relative_root", "present", "root_identity",
        "ancestor_identities", "entries", "manifest_sha256",
    ),
    "BoundFilesystemEvidence": (
        "pre_run_state_sha256", "post_run_state_sha256", "pre_roots",
        "post_roots", "created_paths", "changed_paths", "removed_paths",
        "canonical_sha256",
    ),
    "CommandPolicyContext": (
        "case_id", "case_root", "workspace_root", "data_root",
        "approved_read_roots", "approved_output_roots", "kokoro_shim",
        "kokoro_shim_sha256", "rg_executable", "rg_sha256",
        "shell_path_entries", "shell_pathext", "shell_environment_sha256",
        "filesystem",
    ),
    "ApprovedOperation": (
        "index", "statement_index", "pipeline_index", "category", "argv",
        "operational_json", "expected_outcome", "declared_output_paths",
    ),
    "CommandPolicyDecision": (
        "version", "plan_sha256", "record_class", "operations",
        "topology_sha256", "canonical_sha256",
    ),
}


@pytest.mark.parametrize("name, expected", EXPECTED_FIELDS.items())
def test_policy_model_has_exact_frozen_fields(name: str, expected: tuple[str, ...]) -> None:
    cls = getattr(command_policy, name)
    assert tuple(field.name for field in fields(cls)) == expected
    assert cls.__dataclass_params__.frozen is True


def test_policy_model_reuses_task4_identity() -> None:
    hints = get_type_hints(command_policy.FilesystemSnapshotEntry)
    assert hints["identity"] is command_plan.FilesystemObjectIdentity
    with pytest.raises(FrozenInstanceError):
        identity = command_plan.FilesystemObjectIdentity(7, 8, 1, 0, 1)
        identity.inode = 9


def test_policy_public_signatures_and_core_type_hints_are_exact() -> None:
    bind_signature = inspect.signature(command_policy.bind_filesystem_evidence)
    assert tuple(bind_signature.parameters) == (
        "pre_run_state_bytes",
        "post_run_state_bytes",
        "case_root",
    )
    assert bind_signature.parameters["case_root"].kind is (
        inspect.Parameter.KEYWORD_ONLY
    )
    assert get_type_hints(command_policy.bind_filesystem_evidence) == {
        "pre_run_state_bytes": bytes,
        "post_run_state_bytes": bytes,
        "case_root": Path,
        "return": command_policy.BoundFilesystemEvidence,
    }

    authorize_signature = inspect.signature(command_policy.authorize_command_plan)
    assert tuple(authorize_signature.parameters) == ("plan", "context")
    assert authorize_signature.parameters["context"].kind is (
        inspect.Parameter.KEYWORD_ONLY
    )
    assert get_type_hints(command_policy.authorize_command_plan) == {
        "plan": command_plan.BoundCommandPlan,
        "context": command_policy.CommandPolicyContext,
        "return": command_policy.CommandPolicyDecision,
    }

    assert get_type_hints(command_policy.FilesystemSnapshotEntry) == {
        "relative_path": str,
        "kind": Literal["file", "directory"],
        "size": int,
        "sha256": str | None,
        "link_count": int,
        "identity": command_plan.FilesystemObjectIdentity,
    }
    assert get_type_hints(command_policy.FilesystemRootSnapshot) == {
        "root_index": int,
        "relative_root": str,
        "present": bool,
        "root_identity": command_plan.FilesystemObjectIdentity | None,
        "ancestor_identities": tuple[command_plan.FilesystemObjectIdentity, ...],
        "entries": tuple[command_policy.FilesystemSnapshotEntry, ...],
        "manifest_sha256": str,
    }
    assert get_type_hints(command_policy.BoundFilesystemEvidence) == {
        "pre_run_state_sha256": str,
        "post_run_state_sha256": str,
        "pre_roots": tuple[command_policy.FilesystemRootSnapshot, ...],
        "post_roots": tuple[command_policy.FilesystemRootSnapshot, ...],
        "created_paths": tuple[str, ...],
        "changed_paths": tuple[str, ...],
        "removed_paths": tuple[str, ...],
        "canonical_sha256": str,
    }
    assert get_type_hints(command_policy.CommandPolicyContext) == {
        "case_id": str,
        "case_root": Path,
        "workspace_root": Path,
        "data_root": Path,
        "approved_read_roots": tuple[Path, ...],
        "approved_output_roots": tuple[Path, ...],
        "kokoro_shim": Path,
        "kokoro_shim_sha256": str,
        "rg_executable": Path,
        "rg_sha256": str,
        "shell_path_entries": tuple[Path, ...],
        "shell_pathext": tuple[str, ...],
        "shell_environment_sha256": str,
        "filesystem": command_policy.BoundFilesystemEvidence,
    }


def test_filesystem_evidence_binds_canonical_detached_snapshots(tmp_path: Path) -> None:
    pre_entries = _base_entries()
    post_entries = pre_entries + [_entry(r"outputs\fresh.json", b"{}", 99)]
    pre = bytearray(_state_bytes(pre_entries, post=False))
    post = bytearray(
        _state_bytes(post_entries, post=True, created=(r"workspace\outputs\fresh.json",))
    )
    bound = command_policy.bind_filesystem_evidence(bytes(pre), bytes(post), case_root=tmp_path)
    before = repr(bound), bound.canonical_sha256
    pre[:] = b"{}"
    post[:] = b"{}"
    assert (repr(bound), bound.canonical_sha256) == before
    assert bound.created_paths == (r"workspace\outputs\fresh.json",)
    assert type(bound.pre_roots) is tuple
    assert type(bound.pre_roots[0].entries) is tuple


def test_snapshot_index_sort_lookup_and_delta_have_bounded_ordinal_comparisons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extras = [_entry(r"inputs\bulk", None, 800)]
    extras.extend(
        _entry(rf"inputs\bulk\member-{index:03d}.json", b"{}", 801 + index)
        for index in range(128)
    )
    context = _context(tmp_path, pre_extra=extras)
    ordinal_compare = command_policy._windows_ordinal_compare
    comparisons = 0

    def counted_compare(left: str, right: str) -> int:
        nonlocal comparisons
        comparisons += 1
        return ordinal_compare(left, right)

    monkeypatch.setattr(
        command_policy,
        "_windows_ordinal_compare",
        counted_compare,
        raising=True,
    )
    pre = command_policy._build_snapshot_index(context.filesystem.pre_roots)
    post = command_policy._build_snapshot_index(context.filesystem.post_roots)
    record_count = len(pre.records) + len(post.records)
    assert comparisons <= record_count * (record_count.bit_length() + 1)

    comparisons = 0
    for record in post.records:
        found = command_policy._snapshot_lookup(post, record[0].swapcase())
        assert found == record
    assert comparisons <= len(post.records) * (len(post.records).bit_length() + 1)

    comparisons = 0
    assert command_policy._snapshot_delta(pre, post) == ((), (), ())
    assert comparisons <= len(pre.records) + len(post.records)


def test_snapshot_index_merges_equal_case_aliases_and_rejects_conflicts(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    prototype = context.filesystem.post_roots[0]

    def reroot(
        relative_root: str,
        root_index: int,
        identity: command_plan.FilesystemObjectIdentity,
    ) -> command_policy.FilesystemRootSnapshot:
        payload = command_policy._root_payload(prototype)
        payload["relative_root"] = relative_root
        payload["root_index"] = root_index
        payload["root_identity"] = command_policy._identity_record(identity)
        return command_policy.FilesystemRootSnapshot(
            root_index=root_index,
            relative_root=relative_root,
            present=True,
            root_identity=identity,
            ancestor_identities=prototype.ancestor_identities,
            entries=prototype.entries,
            manifest_sha256=sha256(_canonical_bytes(payload)).hexdigest(),
        )

    lower = reroot("workspace", 0, prototype.root_identity)
    upper = reroot("WORKSPACE", 1, prototype.root_identity)
    merged = command_policy._build_snapshot_index((lower, upper))
    assert len(merged.records) == len(prototype.entries) + 1
    root = command_policy._snapshot_lookup(merged, "WoRkSpAcE")
    assert root is not None
    assert command_policy._windows_path_equal(root[0], "workspace")

    conflicting_identity = replace(
        prototype.root_identity,
        inode=prototype.root_identity.inode + 1,
    )
    conflict = reroot("WORKSPACE", 1, conflicting_identity)
    with pytest.raises(RuntimeError) as caught:
        command_policy._build_snapshot_index((lower, conflict))
    assert str(caught.value) == "COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID"


def test_registered_snapshot_indexes_are_reused_only_after_fresh_authentication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path / "reuse")
    build_snapshot_index = command_policy._build_snapshot_index
    builds = 0

    def counted_builder(roots: tuple[object, ...]) -> object:
        nonlocal builds
        builds += 1
        return build_snapshot_index(roots)

    monkeypatch.setattr(
        command_policy,
        "_build_snapshot_index",
        counted_builder,
        raising=True,
    )
    command_policy.authorize_command_plan(
        _bound_plan("Get-Content", r".\inputs\request.json"),
        context=context,
    )
    assert builds == 4
    pre = command_policy._registered_snapshot_index(context.filesystem, "pre")
    post = command_policy._registered_snapshot_index(context.filesystem, "post")
    for _ in range(64):
        assert command_policy._registered_snapshot_index(
            context.filesystem, "pre"
        ) is pre
        assert command_policy._registered_snapshot_index(
            context.filesystem, "post"
        ) is post
    assert builds == 4

    for name, mutate in (
        (
            "root",
            lambda evidence: object.__setattr__(
                evidence.pre_roots[0],
                "manifest_sha256",
                ZERO_SHA256,
            ),
        ),
        (
            "nested-entry",
            lambda evidence: object.__setattr__(
                evidence.pre_roots[0].entries[0],
                "relative_path",
                "forged-entry",
            ),
        ),
    ):
        forged_context = _context(tmp_path / name)
        mutate(forged_context.filesystem)
        with monkeypatch.context() as isolated:
            isolated.setattr(
                command_policy,
                "_registered_snapshot_index",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("tampered evidence reached cached index")
                ),
                raising=True,
            )
            with pytest.raises(RuntimeError) as caught:
                forged_context.__post_init__()
        assert str(caught.value) == "COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID"


@pytest.mark.parametrize(
    "mutant",
    (
        b'{"schema_version":"x","schema_version":"x","policy_filesystem_roots":[]}',
        b'{"schema_version":"x","policy_filesystem_roots":[]}',
        b'[]',
    ),
)
def test_filesystem_evidence_rejects_duplicate_or_noncanonical_shape(
    tmp_path: Path, mutant: bytes
) -> None:
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID"):
        command_policy.bind_filesystem_evidence(mutant, mutant, case_root=tmp_path)


def test_filesystem_evidence_rejects_extra_or_missing_top_level_members(
    tmp_path: Path,
) -> None:
    pre = json.loads(_state_bytes(_base_entries(), post=False))
    post = json.loads(_state_bytes(_base_entries(), post=True))
    pre["forged"] = True
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID"):
        command_policy.bind_filesystem_evidence(
            _canonical_bytes(pre), _canonical_bytes(post), case_root=tmp_path
        )

    pre.pop("forged")
    post.pop("removed_paths")
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID"):
        command_policy.bind_filesystem_evidence(
            _canonical_bytes(pre), _canonical_bytes(post), case_root=tmp_path
        )


def test_filesystem_evidence_rejects_unsorted_and_case_colliding_entries(
    tmp_path: Path,
) -> None:
    pre = json.loads(_state_bytes(_base_entries(), post=False))
    post = json.loads(_state_bytes(_base_entries(), post=True))
    pre_root = pre["policy_filesystem_roots"][0]
    pre_root["entries"] = list(reversed(pre_root["entries"]))
    payload = {key: value for key, value in pre_root.items() if key != "manifest_sha256"}
    pre_root["manifest_sha256"] = sha256(_canonical_bytes(payload)).hexdigest()
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID"):
        command_policy.bind_filesystem_evidence(
            _canonical_bytes(pre), _canonical_bytes(post), case_root=tmp_path
        )

    pre = json.loads(_state_bytes(_base_entries(), post=False))
    post = json.loads(_state_bytes(_base_entries(), post=True))
    collision = dict(pre["policy_filesystem_roots"][0]["entries"][0])
    collision["relative_path"] = str(collision["relative_path"]).upper()
    pre_root = pre["policy_filesystem_roots"][0]
    pre_root["entries"].append(collision)
    pre_root["entries"].sort(key=lambda item: str(item["relative_path"]).casefold())
    payload = {key: value for key, value in pre_root.items() if key != "manifest_sha256"}
    pre_root["manifest_sha256"] = sha256(_canonical_bytes(payload)).hexdigest()
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID"):
        command_policy.bind_filesystem_evidence(
            _canonical_bytes(pre), _canonical_bytes(post), case_root=tmp_path
        )


def test_context_rejects_a_directly_reconstructed_filesystem_evidence(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    forged = replace(context.filesystem)
    assert forged == context.filesystem and forged is not context.filesystem
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID"):
        replace(context, filesystem=forged)


def test_filesystem_evidence_provenance_rejects_cross_case_replay(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID"):
        replace(context, case_root=tmp_path / "different-case")


def test_public_authorizer_reauthenticates_object_setattr_forged_context(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    object.__setattr__(context, "case_root", tmp_path / "forged-case")
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_PLAN_INVALID"):
        command_policy.authorize_command_plan(
            _bound_plan("Get-Content", r".\inputs\request.json"),
            context=context,
        )

    evidence_context = _context(tmp_path / "evidence")
    object.__setattr__(
        evidence_context.filesystem,
        "canonical_sha256",
        ZERO_SHA256,
    )
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_PLAN_INVALID"):
        command_policy.authorize_command_plan(
            _bound_plan("Get-Content", r".\inputs\request.json"),
            context=evidence_context,
        )


def test_context_binds_exact_live_snapshot_backed_data_root(tmp_path: Path) -> None:
    context = _context(tmp_path)
    with pytest.raises(RuntimeError) as wrong_path:
        replace(context, data_root=context.workspace_root / "alternate-data")
    assert str(wrong_path.value) == "COMMAND_POLICY_CONTEXT_INVALID"

    drift_context = _context(tmp_path / "identity-drift")
    data_root = drift_context.data_root
    data_root.replace(drift_context.case_root / "displaced-data")
    data_root.mkdir()
    with pytest.raises(RuntimeError) as live_drift:
        command_policy.authorize_command_plan(
            _bound_plan("Get-Content", r".\inputs\request.json"),
            context=drift_context,
        )
    assert str(live_drift.value) == "COMMAND_POLICY_PLAN_INVALID"


def test_literal_argv_preserves_values_and_invocation_operator() -> None:
    plan = _bound_plan("kokoro", "pack", "validate", r".\source-packs\rin", "--json")
    assert command_policy._literal_argv(plan.normalized_plan_bytes, 3) == (
        "kokoro", "pack", "validate", r".\source-packs\rin", "--json"
    )
    call = _bound_plan(
        r".tools\kokoro.cmd", "pack", "validate", r".\source-packs\rin", "--json",
        operator="call",
    )
    assert command_policy._literal_argv(call.normalized_plan_bytes, 3) == (
        r".tools\kokoro.cmd", "pack", "validate", r".\source-packs\rin", "--json"
    )


def test_literal_argv_rejects_variable_expression_and_oversized_literal() -> None:
    def variable(document: dict[str, object]) -> None:
        nodes = document["nodes"]
        assert isinstance(nodes, list)
        nodes[4]["ast_type"] = "VariableExpressionAst"

    with pytest.raises(RuntimeError, match="COMMAND_POLICY_LITERAL_REQUIRED"):
        command_policy._literal_argv(
            _bound_plan("kokoro", mutate_command=variable).normalized_plan_bytes, 3
        )
    oversized = "a" * 4097
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_LITERAL_LIMIT_EXCEEDED"):
        command_policy._literal_argv(
            _bound_plan("Get-Content", oversized).normalized_plan_bytes, 3
        )


@pytest.mark.parametrize(
    "argv",
    (
        ("Get-Content", "-LiteralPath", r".\inputs\request.json", "-Raw", "-ErrorAction", "Stop"),
        ("Test-Path", r".\inputs\request.json", "-PathType", "Leaf"),
        ("Get-FileHash", "-LiteralPath", r".\inputs\request.json", "-Algorithm", "SHA256"),
        ("Get-ChildItem", r".\inputs", "-File", "-Name", "-Depth", "2"),
        ("rg", "--files", "--color", "never", "--glob", "*.json", r".\inputs"),
        ("rg", "--fixed-strings", "--color", "never", "--line-number", "--no-heading", "--max-count", "4", "needle", "--glob", "*.json", r".\inputs"),
    ),
)
def test_read_policy_accepts_only_closed_scalar_and_enumeration_rows(
    tmp_path: Path, argv: tuple[str, ...]
) -> None:
    decision = command_policy.authorize_command_plan(_bound_plan(*argv), context=_context(tmp_path))
    assert decision.record_class == "read_only_pipeline"
    expected = tuple(value[2:] if value.startswith(".\\") else value for value in argv)
    assert decision.operations[0].argv == expected
    assert decision.operations[0].category == "read_only"
    assert decision.operations[0].expected_outcome == "none"


@pytest.mark.parametrize(
    "argv",
    (
        ("Get-Content", "-Path", r".\inputs\request.json"),
        ("Get-Content", r".\inputs\*.json"),
        ("Test-Path", r".\inputs\request.json", "-PathType", "Any"),
        ("Get-FileHash", r".\inputs\request.json", "-Algorithm", "MD5"),
        ("Get-ChildItem", r".\inputs", "-Recurse", "-Depth", "2"),
        ("rg", "--files", "--hidden", r".\inputs"),
        ("rg", "--fixed-strings", "--color", "never", "needle", r".\inputs"),
    ),
)
def test_read_policy_rejects_alias_wildcard_and_unsupported_options(
    tmp_path: Path, argv: tuple[str, ...]
) -> None:
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(_bound_plan(*argv), context=_context(tmp_path))


def test_read_policy_allows_a_post_created_approved_artifact(tmp_path: Path) -> None:
    created = _entry(r"inputs\generated.json", b"{}", 300)
    context = _context(
        tmp_path,
        post_extra=[created],
        created=(r"workspace\inputs\generated.json",),
    )
    decision = command_policy.authorize_command_plan(
        _bound_plan("Get-Content", r".\inputs\generated.json", "-Raw"),
        context=context,
    )
    assert decision.operations[0].argv == (
        "Get-Content", r"inputs\generated.json", "-Raw"
    )


def test_live_traversal_selects_unique_longest_containing_snapshot_root(
    tmp_path: Path,
) -> None:
    context = _context_with_narrow_snapshot_roots(tmp_path)
    assert not any(
        root.relative_root == "workspace"
        for root in context.filesystem.post_roots
    )
    read = command_policy.authorize_command_plan(
        _bound_plan("Get-Content", r".\inputs\request.json", "-Raw"),
        context=context,
    )
    assert read.operations[0].argv == (
        "Get-Content", r"inputs\request.json", "-Raw"
    )


def test_output_policy_accepts_factory_bound_absent_snapshot_root_creation(
    tmp_path: Path,
) -> None:
    context = _context_with_narrow_snapshot_roots(
        tmp_path,
        absent_output_root=True,
    )
    pre_output = next(
        root
        for root in context.filesystem.pre_roots
        if root.relative_root == r"workspace\outputs"
    )
    assert pre_output.present is False
    decision = command_policy.authorize_command_plan(
        _bound_plan(
            "kokoro",
            "pack",
            "test",
            r".\source-packs\rin",
            "--request",
            r".\inputs\request.json",
            "--out",
            r".\outputs\fresh.json",
            "--json",
        ),
        context=context,
    )
    assert decision.operations[0].declared_output_paths == (
        r"outputs\fresh.json",
    )


def test_ripgrep_policy_rejects_digest_or_path_resolution_drift(tmp_path: Path) -> None:
    context = _context(tmp_path)
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan("rg", "--files", "--color", "never", r".\inputs"),
            context=replace(context, rg_sha256=ZERO_SHA256),
        )

    extras = [_entry("alternate", None, 310), _entry(r"alternate\rg.exe", b"other", 311)]
    context = _context(tmp_path / "alternate-case", pre_extra=extras)
    alternate_path = (
        context.workspace_root / "alternate",
        context.workspace_root / ".tools",
    )
    context = replace(
        context,
        shell_path_entries=alternate_path,
        shell_environment_sha256=command_policy._shell_environment_fact_sha256(
            alternate_path, context.shell_pathext
        ),
    )
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan("rg", "--files", "--color", "never", r".\inputs"),
            context=context,
        )


def test_recursive_read_scan_rejects_live_member_drift(tmp_path: Path) -> None:
    context = _context(tmp_path)
    (context.workspace_root / "inputs" / "unexpected.txt").write_text(
        "drift", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan("rg", "--files", "--color", "never", r".\inputs"),
            context=context,
        )


@pytest.mark.parametrize("target", ("root", "nested"))
def test_recursive_read_scan_holds_root_and_nested_parent_handles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    extras = [
        _entry(r"inputs\nested", None, 320),
        _entry(r"inputs\nested\member.json", b"{}", 321),
    ]
    context = _context(tmp_path, pre_extra=extras)
    inputs = context.workspace_root / "inputs"
    selected = inputs if target == "root" else inputs / "nested"
    displaced = selected.with_name(f"{selected.name}-displaced")
    swapped = False

    def swap_ancestor(path: Path) -> None:
        nonlocal swapped
        if swapped or path != selected:
            return
        swapped = True
        selected.rename(displaced)
        selected.mkdir()
        (selected / "replacement.json").write_bytes(b"{}")

    monkeypatch.setattr(
        command_policy,
        "_before_component_relative_directory_enumeration",
        swap_ancestor,
        raising=True,
    )
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan("rg", "--files", "--color", "never", r".\inputs"),
            context=context,
        )
    assert swapped is True


@pytest.mark.parametrize(
    "mutation",
    ("addition", "identity-replacement", "content-change"),
)
def test_recursive_read_scan_revalidates_membership_identity_and_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    context = _context(tmp_path)
    inputs = context.workspace_root / "inputs"
    request = inputs / "request.json"
    mutated = False

    def mutate_after_first_scan(path: Path) -> None:
        nonlocal mutated
        if mutated or path != inputs:
            return
        mutated = True
        if mutation == "addition":
            (inputs / "added-after-scan.json").write_bytes(b"{}")
        elif mutation == "identity-replacement":
            request.replace(context.case_root / "displaced-request.json")
            request.write_bytes(b"{}")
        else:
            request.write_bytes(b"[]")

    monkeypatch.setattr(
        command_policy,
        "_before_component_relative_directory_membership_revalidation",
        mutate_after_first_scan,
        raising=True,
    )
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan("rg", "--files", "--color", "never", r".\inputs"),
            context=context,
        )
    assert mutated is True


def test_read_scan_limit_direct_handle_accepts_4096_and_rejects_4097_before_retention(
) -> None:
    retained: list[str] = []
    for index in range(4096):
        command_policy._retain_direct_scan_path(
            retained,
            rf"workspace\inputs\member-{index:04d}.json",
        )
    assert len(retained) == 4096
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_LIMIT_EXCEEDED"):
        command_policy._retain_direct_scan_path(
            retained,
            r"workspace\inputs\member-4096.json",
        )
    assert len(retained) == 4096


def test_read_scan_deep_traversal_recursion_maps_to_stable_limit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)

    def synthetic_deep_tree(_path: Path) -> None:
        raise RecursionError("synthetic deep directory tree")

    monkeypatch.setattr(
        command_policy,
        "_before_component_relative_directory_enumeration",
        synthetic_deep_tree,
        raising=True,
    )
    with pytest.raises(RuntimeError) as caught:
        command_policy.authorize_command_plan(
            _bound_plan("rg", "--files", "--color", "never", r".\inputs"),
            context=context,
        )
    assert str(caught.value) == "COMMAND_POLICY_LIMIT_EXCEEDED"


def test_read_path_and_recursive_scan_reject_live_identity_or_link_drift(
    tmp_path: Path,
) -> None:
    scalar_context = _context(tmp_path / "scalar")
    scalar = scalar_context.workspace_root / "inputs" / "request.json"
    scalar.unlink()
    scalar.write_bytes(b"{}")
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan("Get-Content", r".\inputs\request.json"),
            context=scalar_context,
        )

    recursive_context = _context(tmp_path / "recursive")
    member = recursive_context.workspace_root / "inputs" / "review.json"
    member.unlink()
    member.write_bytes(b"{}")
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan("rg", "--files", "--color", "never", r".\inputs"),
            context=recursive_context,
        )

    link_context = _context(tmp_path / "link")
    source = link_context.workspace_root / "inputs" / "request.json"
    os.link(source, link_context.workspace_root / "outputs" / "hardlink.json")
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan("Get-Content", r".\inputs\request.json"),
            context=link_context,
        )


@pytest.mark.parametrize(
    ("family", "relative_target", "reparse_tag", "argv"),
    (
        (
            "symlink",
            r"inputs\request.json",
            0xA000000C,
            ("Get-Content", r".\inputs\request.json"),
        ),
        (
            "junction",
            "inputs",
            0xA0000003,
            ("rg", "--files", "--color", "never", r".\inputs"),
        ),
        (
            "path-reparse",
            r"inputs\review.json",
            1,
            ("rg", "--files", "--color", "never", r".\inputs"),
        ),
    ),
)
def test_command_reads_reject_symlink_junction_and_reparse_identities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    relative_target: str,
    reparse_tag: int,
    argv: tuple[str, ...],
) -> None:
    assert family
    context = _context(tmp_path)
    target = context.workspace_root.joinpath(
        *PureWindowsPath(relative_target).parts
    )
    query_live_handle = command_policy._query_live_handle

    def reparse_observation(handle: int, path: Path) -> object:
        observed = query_live_handle(handle, path)
        if path != target:
            return observed
        return replace(
            observed,
            identity=replace(
                observed.identity,
                reparse_tag=reparse_tag,
            ),
        )

    monkeypatch.setattr(
        command_policy,
        "_query_live_handle",
        reparse_observation,
        raising=True,
    )
    with pytest.raises(RuntimeError) as caught:
        command_policy.authorize_command_plan(
            _bound_plan(*argv),
            context=context,
        )
    assert str(caught.value) in {
        "COMMAND_POLICY_OPERATION_REJECTED",
        "COMMAND_POLICY_PLAN_INVALID",
    }


def test_rg_and_kokoro_live_executable_bytes_and_identity_are_revalidated(
    tmp_path: Path,
) -> None:
    rg_context = _context(tmp_path / "rg")
    rg_context.rg_executable.write_bytes(b"RG")
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan("rg", "--files", "--color", "never", r".\inputs"),
            context=rg_context,
        )

    shim_context = _context(tmp_path / "shim")
    shim_context.kokoro_shim.unlink()
    shim_context.kokoro_shim.write_bytes(b"shim")
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan(
                "kokoro", "pack", "validate", r".\source-packs\rin", "--json"
            ),
            context=shim_context,
        )


def test_scalar_read_holds_verified_ancestors_through_final_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    inputs = context.workspace_root / "inputs"
    displaced = context.workspace_root / "inputs-displaced"
    swapped = False

    def swap_ancestor(path: Path) -> None:
        nonlocal swapped
        if swapped or path != inputs / "request.json":
            return
        swapped = True
        inputs.rename(displaced)
        inputs.mkdir()
        (inputs / "request.json").write_bytes(b"{}")

    monkeypatch.setattr(
        command_policy,
        "_before_component_relative_final_open",
        swap_ancestor,
        raising=False,
    )
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan("Get-Content", r".\inputs\request.json"),
            context=context,
        )
    assert swapped is True


def test_executable_resolution_rejects_live_inserted_earlier_candidate(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    (context.workspace_root / ".tools" / "kokoro.com").write_bytes(b"alternate")
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan(
                "kokoro", "pack", "validate", r".\source-packs\rin", "--json"
            ),
            context=context,
        )


def test_executable_resolution_requires_unique_pre_run_candidate_set(
    tmp_path: Path,
) -> None:
    alternate = _entry(r".tools\kokoro.exe", b"alternate", 312)
    context = _context(
        tmp_path,
        pre_extra=[alternate],
        post_extra=[],
        removed=(r"workspace\.tools\kokoro.exe",),
    )
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan(
                "kokoro", "pack", "validate", r".\source-packs\rin", "--json"
            ),
            context=context,
        )


def test_pipeline_policy_accepts_closed_projections_and_preserves_grouping(tmp_path: Path) -> None:
    statements = (((
        (("Get-ChildItem", r".\inputs", "-File"), "none"),
        (("Sort-Object", "-Property", "Name", "-Unique"), "none"),
        (("Select-Object", "-First", "2"), "none"),
    )),)
    decision = command_policy.authorize_command_plan(
        _bound_plan(statements=statements), context=_context(tmp_path)
    )
    assert decision.record_class == "read_only_pipeline"
    assert tuple(item.pipeline_index for item in decision.operations) == (0, 1, 2)
    assert {item.statement_index for item in decision.operations} == {0}


@pytest.mark.parametrize(
    "projection",
    (
        ("Select-Object", "-ExpandProperty", "Name"),
        ("Select-Object", "-Skip", "1"),
        ("Select-Object", "-Property", "Name,Length"),
        ("Sort-Object", "-Property", "Unknown"),
        ("Sort-Object", "-Unique", "-Unique"),
    ),
)
def test_pipeline_policy_rejects_unclosed_projection_forms(
    tmp_path: Path, projection: tuple[str, ...]
) -> None:
    statements = (((
        (("Get-ChildItem", r".\inputs"), "none"),
        (projection, "none"),
    )),)
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan(statements=statements), context=_context(tmp_path)
        )


def _valid_cli_rows(context: command_policy.CommandPolicyContext) -> tuple[tuple[str, ...], ...]:
    workspace = str(context.workspace_root)
    read = r".\inputs\request.json"
    return (
        ("kokoro", "pack", "validate", r".\source-packs\rin", "--json"),
        ("kokoro", "pack", "compile", r".\source-packs\rin", "--json"),
        ("kokoro", "pack", "install", r".\inputs\archive.karc", "--scope", "global", "--dry-run", "--json"),
        ("kokoro", "pack", "install", r".\inputs\archive.karc", "--scope", "workspace", "--workspace", workspace, "--json"),
        ("kokoro", "pack", "list", "--scope", "global", "--json"),
        ("kokoro", "pack", "list", "--scope", "workspace", "--workspace", workspace, "--json"),
        ("kokoro", "pack", "export", "--compiled", r".\inputs\compiled.json", "--promotion", r".\inputs\promotion.json", "--hard-report", r".\inputs\hard.json", "--soft-report", r".\inputs\soft.json", "--out", r".\outputs\export.karc", "--json"),
        ("kokoro", "pack", "test", r".\source-packs\rin", "--request", read, "--out", r".\outputs\test.json", "--json"),
        ("kokoro", "pack", "soft-eval", r".\inputs\soft-input.json", "--out", r".\outputs\soft.json", "--json"),
        ("kokoro", "pack", "promote", r".\source-packs\rin", "--target", "reviewed", "--promotion-id", "promotion-1", "--request", read, "--hard-report", r".\inputs\hard.json", "--review", r".\inputs\review.json", "--out", r".\outputs\promoted.json", "--json"),
        ("kokoro", "pack", "promote", r".\source-packs\rin", "--target", "verified", "--promotion-id", "promotion-2", "--request", read, "--hard-report", r".\inputs\hard.json", "--review", r".\inputs\review.json", "--previous", r".\inputs\promotion.json", "--soft-input", r".\inputs\soft-input.json", "--soft-report", r".\inputs\soft.json", "--out", r".\outputs\verified.json", "--json"),
        ("kokoro", "pack", "publication-check", r".\source-packs\rin", "--promotion", r".\inputs\promotion.json", "--request", read, "--hard-report", r".\inputs\hard.json", "--review", r".\inputs\review.json", "--previous", r".\inputs\promotion.json", "--soft-input", r".\inputs\soft-input.json", "--soft-report", r".\inputs\soft.json", "--visibility", "private", "--out", r".\outputs\publication.json", "--json"),
        ("kokoro", "character", "request", "validate", "--input", read, "--json"),
        ("kokoro", "character", "draft", "validate", "--request", read, "--pack", r".\source-packs\rin", "--json"),
        ("kokoro", "character", "draft", "compile", "--request", read, "--pack", r".\source-packs\rin", "--json"),
        ("kokoro", "research", "request", "validate", "--input", read, "--json"),
        ("kokoro", "research", "workspace", "validate", "--workspace", r".\source-packs\rin", "--json"),
        ("kokoro", "research", "bundle", "compile", "--workspace", r".\source-packs\rin", "--json"),
        ("kokoro", "research", "bundle", "validate", "--bundle", read, "--json"),
        ("kokoro", "config", "default", "set", "--character", "mika", "--namespace", "original", "--version", "v1", "--scope", "workspace", "--workspace", workspace, "--json"),
        ("kokoro", "config", "default", "show", "--scope", "global", "--json"),
        ("kokoro", "session", "start", "--session", "s1", "--workspace", workspace, "--character", "mika", "--json"),
        ("kokoro", "session", "start", "--character", read, "--session", "s2", "--workspace", workspace, "--json"),
        ("kokoro", "session", "show", "--session", "s1", "--json"),
        ("kokoro", "consent", "show", "--character", "mika", "--scope", "global", "--json"),
        ("kokoro", "state", "preview", "--session", "s1", "--event", r".\inputs\event.json", "--json"),
        ("kokoro", "state", "apply", "--session", "s1", "--event", r".\inputs\event.json", "--json"),
        ("kokoro", "state", "export", "--character", "mika", "--scope", "global", "--out", r".\outputs\state.json", "--json"),
        ("kokoro", "memory", "add", "--character", "mika", "--host-id", "host-1", "--summary-file", r".\inputs\summary.txt", "--json"),
        ("kokoro", "memory", "list", "--character", "mika", "--scope", "workspace", "--workspace", workspace, "--json"),
        ("kokoro", "memory", "remove", "--character", "mika", "--host-id", "host-1", "--dry-run", "--json"),
        ("kokoro", "policy", "compile", "--input", r".\inputs\policy.json", "--json"),
        ("kokoro", "runtime", "context", "--session", "s1", "--locale", "ja-JP", "--scenario", "debugging", "--json"),
        ("kokoro", "runtime", "plan", "--semantic", r".\inputs\semantic.json", "--policy", r".\inputs\policy.json", "--expression-intent", "neutral", "--json"),
        ("kokoro", "runtime", "validate", "--semantic", r".\inputs\semantic.json", "--plan", r".\inputs\policy.json", "--rendered", r".\inputs\rendered.txt", "--json"),
    )


def test_pack_cli_policy_and_all_other_frozen_kokoro_cli_rows_are_authorized(
    tmp_path: Path,
) -> None:
    context = _context_with_outputs(
        tmp_path,
        (
            r"outputs\export.karc",
            r"outputs\test.json",
            r"outputs\soft.json",
            r"outputs\promoted.json",
            r"outputs\verified.json",
            r"outputs\publication.json",
            r"outputs\state.json",
        ),
    )
    for argv in _valid_cli_rows(context):
        decision = command_policy.authorize_command_plan(_bound_plan(*argv), context=context)
        assert decision.record_class == "operational_json", argv
        assert len(decision.operations) == 1
        operation = decision.operations[0]
        assert operation.category == "kokoro_cli"
        assert operation.operational_json is True
        assert operation.expected_outcome == "success"
        if "--out" in argv:
            expected = argv[argv.index("--out") + 1]
            assert operation.declared_output_paths == (expected[2:],)
        else:
            assert operation.declared_output_paths == ()


@pytest.mark.parametrize(
    "argv",
    (
        ("kokoro", "config", "default", "clear", "--json"),
        ("kokoro", "session", "end", "--json"),
        ("kokoro", "pack", "remove", "x", "--json"),
        ("kokoro", "state", "reset", "--json"),
        ("kokoro", "consent", "grant", "--json"),
        ("kokoro", "consent", "revoke", "--json"),
        ("kokoro", "suite", "install", "--json"),
        ("kokoro", "pack", "validate", r".\source-packs\rin"),
        ("kokoro", "pack", "validate", r".\source-packs\rin", "--json", "--json"),
        ("kokoro", "pack", "install", r".\inputs\archive.karc", "--workspace", ".", "--scope", "workspace", "--json"),
        ("kokoro", "runtime", "context", "--session", "s1", "--locale", "fr-FR", "--scenario", "x", "--json"),
    ),
)
def test_kokoro_cli_rejects_excluded_missing_duplicate_and_reordered_rows(
    tmp_path: Path, argv: tuple[str, ...]
) -> None:
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(_bound_plan(*argv), context=_context(tmp_path))


def test_closed_ascii_grammar_rejects_unicode_casefold_lookalikes(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    scope_option = list(_valid_cli_rows(context)[3])
    scope_option[scope_option.index("--scope")] = "--\u017fcope"
    scope_value = list(_valid_cli_rows(context)[3])
    scope_value[scope_value.index("workspace")] = "work\u017fpace"
    read_projection = (
        (
            (("Get-ChildItem", r".\inputs", "-File"), "none"),
            (("Sort-Object", "-Property", "La\u017ftWriteTimeUtc"), "none"),
        ),
    )
    cases = (
        _bound_plan(
            "\u212aokoro", "pack", "validate", r".\source-packs\rin", "--json"
        ),
        _bound_plan(*scope_option),
        _bound_plan(*scope_value),
        _bound_plan(statements=read_projection),
    )
    for plan in cases:
        with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
            command_policy.authorize_command_plan(plan, context=context)


@pytest.mark.parametrize(
    "argv",
    (
        ("kokoro",),
        ("kokoro", "pack"),
        ("kokoro", "character", "draft"),
        ("kokoro", "pack", "validate", "--help"),
    ),
)
def test_help_only_grammar_is_nonoperational(tmp_path: Path, argv: tuple[str, ...]) -> None:
    decision = command_policy.authorize_command_plan(_bound_plan(*argv), context=_context(tmp_path))
    assert decision.record_class == "help_discovery"
    assert all(not operation.operational_json for operation in decision.operations)
    assert all(operation.expected_outcome == "none" for operation in decision.operations)


@pytest.mark.parametrize(
    "command",
    (
        "python", "py", "node", "cmd", "pwsh", "Invoke-Expression",
        "Start-Process", "Invoke-WebRequest", "Import-Module", "Set-Location",
        "Set-Content", "Remove-Item", "chmod", "gci", "gc",
    ),
)
def test_fail_monotonic_policy_rejects_unsafe_or_alias_commands(
    tmp_path: Path, command: str
) -> None:
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan(command, "synthetic"), context=_context(tmp_path)
        )


_STEP2_AST_REJECTION_CASES = (
    ("comment-fake-text", "comment-token", "none", "Get-Content"),
    ("control-flow", "named-while", "none", "Get-Content"),
    ("dead-branch", "named-if", "none", "Get-Content"),
    ("dotnet-method", "command-expression", "none", "Get-Content"),
    ("expression-argument", "argument-binary", "none", "Get-Content"),
    ("function-definition", "named-function", "none", "Get-Content"),
    ("here-string-fake-text", "command-here-string", "none", "Get-Content"),
    ("interpolation", "command-expandable", "none", "Get-Content"),
    ("job-scriptblock", "argument-scriptblock", "none", "Start-Job"),
    ("parser-unclassified", "argument-unclassified", "none", "Get-Content"),
    ("redirection", "argument-redirection", "none", "Get-Content"),
    ("remoting-scriptblock", "argument-scriptblock", "none", "Invoke-Command"),
    ("scriptblock", "argument-scriptblock", "none", "Get-Content"),
    ("splatting", "command-splat", "none", "Get-Content"),
    ("string-fake-text", "command-string", "none", "Get-Content"),
    ("subexpression", "argument-subexpression", "none", "Get-Content"),
    ("trap-definition", "named-trap", "none", "Get-Content"),
    ("variable-call-target", "command-variable", "call", "Get-Content"),
    ("variable-command", "command-variable", "none", "Get-Content"),
)


def _apply_step2_ast_mutation(
    document: dict[str, object],
    mutation: str,
) -> None:
    nodes = document["nodes"]
    tokens = document["tokens"]
    assert isinstance(nodes, list)
    assert isinstance(tokens, list)
    if mutation == "comment-token":
        tokens[0]["kind"] = "Comment"
        tokens[0]["literal"] = None
        tokens[0]["text"] = "kokoro pack validate .\\source-packs\\rin --json"
        return
    if mutation.startswith("named-"):
        nodes[1]["ast_type"] = {
            "named-function": "FunctionDefinitionAst",
            "named-if": "IfStatementAst",
            "named-trap": "TrapStatementAst",
            "named-while": "WhileStatementAst",
        }[mutation]
        return
    if mutation.startswith("command-"):
        if mutation == "command-variable":
            nodes[4]["ast_type"] = "VariableExpressionAst"
        elif mutation == "command-expandable":
            nodes[4]["ast_type"] = "ExpandableStringExpressionAst"
        elif mutation == "command-splat":
            nodes[4]["ast_type"] = "VariableExpressionAst"
            tokens[0]["flags"] = ["Splatted"]
        else:
            nodes[3]["ast_type"] = {
                "command-expression": "CommandExpressionAst",
                "command-here-string": "ExpandableStringExpressionAst",
                "command-string": "StringConstantExpressionAst",
            }[mutation]
            nodes[3]["role"] = "expression"
        return
    nodes[5]["ast_type"] = {
        "argument-binary": "BinaryExpressionAst",
        "argument-redirection": "FileRedirectionAst",
        "argument-scriptblock": "ScriptBlockExpressionAst",
        "argument-subexpression": "SubExpressionAst",
        "argument-unclassified": "SyntheticUnclassifiedAst",
    }[mutation]


@pytest.mark.parametrize(
    ("family", "mutation", "operator", "command"),
    tuple(
        pytest.param(*case, id=case[0])
        for case in _STEP2_AST_REJECTION_CASES
    ),
)
def test_step2_rejection_matrix_ast_topology_and_role_families(
    tmp_path: Path,
    family: str,
    mutation: str,
    operator: str,
    command: str,
) -> None:
    assert family

    def mutate(document: dict[str, object]) -> None:
        _apply_step2_ast_mutation(document, mutation)

    with pytest.raises(
        RuntimeError,
        match="COMMAND_POLICY_(?:PLAN_INVALID|LITERAL_REQUIRED|OPERATION_REJECTED)",
    ):
        command_policy.authorize_command_plan(
            _bound_plan(
                command,
                r".\inputs\request.json",
                operator=operator,
                mutate_command=mutate,
            ),
            context=_context(tmp_path),
        )


_STEP2_CLOSED_GUARD_CASES = (
    ("abbreviated-parameter", ("Get-Content", "-Lit", r".\inputs\request.json"), "none"),
    ("alias-command", ("gci", r".\inputs"), "none"),
    ("alias-provider", ("Get-Content", "Alias::synthetic"), "none"),
    ("alternate-call-target", (r".tools\alternate.cmd", "pack", "validate"), "call"),
    ("certificate-provider", ("Get-Content", "Cert::CurrentUser\\My"), "none"),
    ("dot-source", (r".tools\kokoro.cmd",), "dot"),
    ("encoded-command", ("pwsh", "-EncodedCommand", "UwB5AG4AdABoAGUAdABpAGMA"), "none"),
    ("environment-provider", ("Get-Content", "Env::SYNTHETIC"), "none"),
    ("full-path-node", (r"C:\Program Files\nodejs\node.exe", "synthetic.js"), "none"),
    ("full-path-python", (r"C:\Python314\python.exe", "synthetic.py"), "none"),
    ("function-provider", ("Get-Content", "Function::synthetic"), "none"),
    ("host-profile-read", ("Get-Content", r"C:\Users\synthetic\Documents\PowerShell\profile.ps1"), "none"),
    ("job-command", ("Start-Job", "synthetic"), "none"),
    ("module-loading", ("Import-Module", "synthetic"), "none"),
    ("network-client", ("Invoke-WebRequest", "https://invalid.example"), "none"),
    ("outside-root-read", ("Get-Content", r"C:\synthetic\outside.txt"), "none"),
    ("permission-change", ("icacls", r".\inputs\request.json", "/grant", "synthetic:F"), "none"),
    ("registry-provider", ("Get-Content", "Registry::HKEY_CURRENT_USER\\Synthetic"), "none"),
    ("remoting-command", ("Invoke-Command", "synthetic"), "none"),
    ("replacement-command", ("Copy-Item", r".\inputs\request.json", r".\outputs\request.json"), "none"),
    ("set-location", ("Set-Location", r".\inputs"), "none"),
    ("trap-command", ("trap", "synthetic"), "none"),
    ("unknown-parameter", ("Get-Content", r".\inputs\request.json", "-Synthetic"), "none"),
    ("unsupported-rg-flag", ("rg", "--files", "--hidden", r".\inputs"), "none"),
    ("variable-provider", ("Get-Content", "Variable::synthetic"), "none"),
    ("write-command", ("Set-Content", r".\outputs\synthetic.txt", "synthetic"), "none"),
)


@pytest.mark.parametrize(
    ("family", "argv", "operator"),
    tuple(
        pytest.param(*case, id=case[0])
        for case in _STEP2_CLOSED_GUARD_CASES
    ),
)
def test_step2_rejection_matrix_closed_command_path_and_parameter_guards(
    tmp_path: Path,
    family: str,
    argv: tuple[str, ...],
    operator: str,
) -> None:
    assert family
    with pytest.raises(
        RuntimeError,
        match="COMMAND_POLICY_(?:LITERAL_REQUIRED|OPERATION_REJECTED)",
    ):
        command_policy.authorize_command_plan(
            _bound_plan(*argv, operator=operator),
            context=_context(tmp_path),
        )


def test_step2_rejection_family_registries_are_sorted_unique_and_nonempty() -> None:
    for cases in (_STEP2_AST_REJECTION_CASES, _STEP2_CLOSED_GUARD_CASES):
        families = tuple(case[0] for case in cases)
        assert families == tuple(sorted(families))
        assert len(families) == len(set(families))
        assert all(families)


def test_operational_json_may_not_mix_with_read_or_help(tmp_path: Path) -> None:
    context = _context(tmp_path)
    valid = _valid_cli_rows(context)[0]
    for second in (("Get-Content", r".\inputs\request.json"), ("kokoro", "pack", "--help")):
        statements = (
            ((valid, "none"),),
            ((second, "none"),),
        )
        with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
            command_policy.authorize_command_plan(
                _bound_plan(statements=statements), context=context
            )


def test_character_cli_policy_research_cli_policy_and_optional_rows(
    tmp_path: Path,
) -> None:
    context = _context_with_outputs(
        tmp_path,
        (
            r"outputs\optional-export.karc",
            r"outputs\optional-test.json",
            r"outputs\publication-public.json",
            r"outputs\state-workspace.json",
        ),
    )
    workspace = str(context.workspace_root)
    optional_rows = (
        (
            "kokoro", "pack", "export",
            "--compiled", r".\inputs\compiled.json",
            "--promotion", r".\inputs\promotion.json",
            "--hard-report", r".\inputs\hard.json",
            "--soft-report", r".\inputs\soft.json",
            "--publication-report", r".\inputs\review.json",
            "--out", r".\outputs\optional-export.karc", "--json",
        ),
        (
            "kokoro", "pack", "test", r".\source-packs\rin",
            "--request", r".\inputs\request.json",
            "--research-bundle", r".\inputs\compiled.json",
            "--out", r".\outputs\optional-test.json", "--json",
        ),
        (
            "kokoro", "pack", "publication-check", r".\source-packs\rin",
            "--promotion", r".\inputs\promotion.json",
            "--request", r".\inputs\request.json",
            "--hard-report", r".\inputs\hard.json",
            "--review", r".\inputs\review.json",
            "--previous", r".\inputs\promotion.json",
            "--soft-input", r".\inputs\soft-input.json",
            "--soft-report", r".\inputs\soft.json",
            "--research-bundle", r".\inputs\compiled.json",
            "--visibility", "public_candidate",
            "--compliance", r".\inputs\review.json",
            "--out", r".\outputs\publication-public.json", "--json",
        ),
        (
            "kokoro", "character", "draft", "compile",
            "--request", r".\inputs\request.json",
            "--pack", r".\source-packs\rin",
            "--research-bundle", r".\inputs\compiled.json", "--json",
        ),
        ("kokoro", "config", "default", "show", "--scope", "workspace", "--workspace", workspace, "--json"),
        ("kokoro", "session", "show", "--json"),
        ("kokoro", "consent", "show", "--character", "mika", "--namespace", "original", "--scope", "workspace", "--workspace", workspace, "--json"),
        ("kokoro", "state", "export", "--character", "mika", "--namespace", "original", "--scope", "workspace", "--workspace", workspace, "--out", r".\outputs\state-workspace.json", "--json"),
        ("kokoro", "memory", "add", "--character", "mika", "--namespace", "original", "--scope", "workspace", "--workspace", workspace, "--host-id", "host-2", "--summary-file", r".\inputs\summary.txt", "--json"),
        ("kokoro", "memory", "list", "--character", "mika", "--json"),
        ("kokoro", "memory", "remove", "--character", "mika", "--namespace", "original", "--scope", "global", "--host-id", "host-2", "--json"),
        ("kokoro", "runtime", "plan", "--semantic", r".\inputs\semantic.json", "--policy", r".\inputs\policy.json", "--json"),
    )
    for argv in optional_rows:
        decision = command_policy.authorize_command_plan(
            _bound_plan(*argv), context=context
        )
        assert decision.record_class == "operational_json", argv
        assert decision.operations[0].operational_json is True


@pytest.mark.parametrize(
    "argv",
    (
        ("kokoro", "config", "default", "set", "--character", "-bad", "--scope", "global", "--json"),
        ("kokoro", "session", "start", "--session", "x" * 129, "--json"),
        ("kokoro", "pack", "install", r".\inputs\archive.karc", "--scope", "global", "--workspace", ".", "--json"),
        ("kokoro", "memory", "list", "--character", "mika", "--scope", "workspace", "--json"),
        ("kokoro", "memory", "list", "--character", "mika", "--scope", "global", "--workspace", ".", "--json"),
        ("kokoro", "pack", "export", "--compiled", r".\inputs\compiled.json", "--promotion", r".\inputs\promotion.json", "--hard-report", r".\inputs\hard.json", "--soft-report", r".\inputs\soft.json", "--out", r".\inputs\wrong-root.karc", "--json"),
        ("kokoro", "pack", "validate", r".\inputs\*.json", "--json"),
    ),
)
def test_config_cli_policy_session_cli_policy_and_path_rules_reject_adjacent_mutants(
    tmp_path: Path, argv: tuple[str, ...]
) -> None:
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan(*argv), context=_context(tmp_path)
        )


def test_kokoro_resolution_and_literal_shim_binding(tmp_path: Path) -> None:
    context = _context(tmp_path)
    direct = command_policy.authorize_command_plan(
        _bound_plan(
            "KOKORO", "pack", "validate", r".\source-packs\rin", "--JSON"
        ),
        context=context,
    )
    assert direct.operations[0].argv[:3] == ("kokoro", "pack", "validate")

    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan(
                "KOKORO",
                "PACK",
                "VALIDATE",
                r".\source-packs\rin",
                "--JSON",
            ),
            context=context,
        )
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan("kokoro", "PACK", "--help"),
            context=context,
        )

    call = command_policy.authorize_command_plan(
        _bound_plan(
            r".tools\kokoro.cmd",
            "pack", "validate", r".\source-packs\rin", "--json",
            operator="call",
        ),
        context=context,
    )
    assert call.operations[0].argv[0] == r".tools\kokoro.cmd"


def test_kokoro_resolution_rejects_shim_path_pathext_and_environment_drift(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    plan = _bound_plan("kokoro", "pack", "validate", r".\source-packs\rin", "--json")
    command_policy.authorize_command_plan(plan, context=context)

    mutants = (
        replace(context, kokoro_shim_sha256=ZERO_SHA256),
        replace(context, shell_pathext=(".EXE", ".CMD")),
        replace(context, shell_environment_sha256="1" * 64),
    )
    for mutant in mutants:
        with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
            command_policy.authorize_command_plan(plan, context=mutant)

    fresh = _context(tmp_path / "environment-first")
    forged_first = replace(fresh, shell_environment_sha256="2" * 64)
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(plan, context=forged_first)

    extras = [
        _entry("alternate", None, 410),
        _entry(r"alternate\kokoro.cmd", b"other", 411),
    ]
    alternate = _context(tmp_path / "alternate", pre_extra=extras)
    alternate_path = (
        alternate.workspace_root / "alternate",
        alternate.workspace_root / ".tools",
    )
    alternate = replace(
        alternate,
        shell_path_entries=alternate_path,
        shell_environment_sha256=command_policy._shell_environment_fact_sha256(
            alternate_path, alternate.shell_pathext
        ),
    )
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(plan, context=alternate)

    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan(
                r".tools\other.cmd",
                "pack", "validate", r".\source-packs\rin", "--json",
                operator="call",
            ),
            context=context,
        )


def test_ripgrep_resolution_binds_platform_null_config_environment(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    drift_digest = command_policy._shell_environment_fact_sha256(
        context.shell_path_entries,
        context.shell_pathext,
        ripgrep_config_path=r"C:\synthetic\ripgreprc",
    )
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan("rg", "--files", "--color", "never", r".\inputs"),
            context=replace(
                context,
                shell_environment_sha256=drift_digest,
            ),
        )


def _pack_export_argv(output: str) -> tuple[str, ...]:
    return (
        "kokoro", "pack", "export",
        "--compiled", r".\inputs\compiled.json",
        "--promotion", r".\inputs\promotion.json",
        "--hard-report", r".\inputs\hard.json",
        "--soft-report", r".\inputs\soft.json",
        "--out", output, "--json",
    )


def test_archive_overwrite_expected_refusal_is_the_sole_refusal_row(
    tmp_path: Path,
) -> None:
    existing = _entry(r"outputs\existing.karc", b"sentinel", 420)
    context = _context(
        tmp_path,
        case_id="archive-overwrite-pressure",
        pre_extra=[existing],
    )
    decision = command_policy.authorize_command_plan(
        _bound_plan(*_pack_export_argv(r".\outputs\existing.karc")),
        context=context,
    )
    operation = decision.operations[0]
    assert operation.expected_outcome == "expected_refusal"
    assert operation.declared_output_paths == (r"outputs\existing.karc",)

    fresh_context = _context_with_outputs(
        tmp_path / "fresh",
        (r"outputs\fresh.karc",),
        case_id="archive-overwrite-pressure",
    )
    fresh = command_policy.authorize_command_plan(
        _bound_plan(*_pack_export_argv(r".\outputs\fresh.karc")),
        context=fresh_context,
    )
    assert fresh.operations[0].expected_outcome == "success"

    wrong_case = replace(context, case_id="synthetic-case")
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan(*_pack_export_argv(r".\outputs\existing.karc")),
            context=wrong_case,
        )

    statements = (
        ((_pack_export_argv(r".\outputs\existing.karc"), "none"),),
        ((("kokoro", "pack", "validate", r".\source-packs\rin", "--json"), "none"),),
    )
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan(statements=statements), context=context
        )


@pytest.mark.parametrize(
    ("target", "output"),
    (
        (r"outputs\run", r"outputs\run\result.json"),
        (r"data\compiled", r"data\compiled\result.json"),
    ),
)
def test_silent_directory_new_item_filesystem_transition_is_joined_to_cli_output(
    tmp_path: Path, target: str, output: str
) -> None:
    target_entry = _entry(target, None, 430)
    output_entry = _entry(output, b"{}", 431)
    context = _context(
        tmp_path,
        post_extra=[target_entry, output_entry],
        created=(f"workspace\\{target}", f"workspace\\{output}"),
    )
    statements = (
        ((
            (("New-Item", "-ItemType", "Directory", "-LiteralPath", f".\\{target}", "-ErrorAction", "Stop"), "none"),
            (("Out-Null",), "none"),
        )),
        ((_pack_export_argv(f".\\{output}"), "none"),),
    )
    decision = command_policy.authorize_command_plan(
        _bound_plan(statements=statements), context=context
    )
    assert decision.record_class == "operational_json"
    assert tuple(item.category for item in decision.operations) == (
        "silent_directory", "silent_directory", "kokoro_cli"
    )
    assert tuple(item.statement_index for item in decision.operations) == (0, 0, 1)
    assert tuple(item.pipeline_index for item in decision.operations) == (0, 1, None)
    assert sum(item.operational_json for item in decision.operations) == 1


def test_silent_directory_accepts_an_absent_narrow_approved_output_root_only(
    tmp_path: Path,
) -> None:
    statements = (
        ((
            ((
                "New-Item",
                "-ItemType",
                "Directory",
                "-LiteralPath",
                r".\outputs",
                "-ErrorAction",
                "Stop",
            ), "none"),
            (("Out-Null",), "none"),
        )),
        ((_pack_export_argv(r".\outputs\fresh.json"), "none"),),
    )
    context = _context_with_narrow_snapshot_roots(
        tmp_path / "absent",
        absent_output_root=True,
    )
    decision = command_policy.authorize_command_plan(
        _bound_plan(statements=statements),
        context=context,
    )
    assert tuple(operation.category for operation in decision.operations) == (
        "silent_directory",
        "silent_directory",
        "kokoro_cli",
    )

    preexisting = _context_with_narrow_snapshot_roots(
        tmp_path / "preexisting",
        output_child_created=True,
    )
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan(statements=statements),
            context=preexisting,
        )

    identity_drift = _context_with_narrow_snapshot_roots(
        tmp_path / "identity-drift",
        absent_output_root=True,
    )
    outputs = identity_drift.workspace_root / "outputs"
    outputs.replace(identity_drift.case_root / "displaced-outputs")
    outputs.mkdir()
    (outputs / "fresh.json").write_bytes(b"{}")
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan(statements=statements),
            context=identity_drift,
        )


def test_silent_directory_rejects_preexisting_or_unrelated_target(tmp_path: Path) -> None:
    target = _entry(r"outputs\run", None, 440)
    output = _entry(r"outputs\run\result.json", b"{}", 441)
    context = _context(
        tmp_path,
        pre_extra=[target],
        post_extra=[target, output],
        created=(r"workspace\outputs\run\result.json",),
    )
    statements = (
        ((
            (("New-Item", "-ItemType", "Directory", "-Path", r".\outputs\run"), "none"),
            (("Out-Null",), "none"),
        )),
        ((_pack_export_argv(r".\outputs\run\result.json"), "none"),),
    )
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan(statements=statements), context=context
        )

    unrelated_context = _context(
        tmp_path / "unrelated",
        post_extra=[_entry(r"outputs\run", None, 442)],
        created=(r"workspace\outputs\run",),
    )
    unrelated = (
        statements[0],
        ((_pack_export_argv(r".\outputs\other.json"), "none"),),
    )
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan(statements=unrelated), context=unrelated_context
        )


@pytest.mark.parametrize(
    "argv",
    (
        ("New-Item", "-ItemType", "Directory", "-Path", r".\outputs\run", "-Force"),
        ("New-Item", "-Path", r".\outputs\run", "-ItemType", "Directory"),
        ("Out-Null", "-InputObject", "x"),
    ),
)
def test_new_item_and_out_null_are_never_independently_authorized(
    tmp_path: Path, argv: tuple[str, ...]
) -> None:
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan(*argv), context=_context(tmp_path)
        )


_EXACT_ASCII_LITERAL = "a" * 4096
_EXACT_NON_ASCII_LITERAL = "界" * 1365 + "a"
_LITERAL_BOUNDARY_CASES = (
    pytest.param(
        "glob",
        ("rg", "--files", "--color", "never", "--glob", _EXACT_ASCII_LITERAL, r".\inputs"),
        ("rg", "--files", "--color", "never", "--glob", _EXACT_ASCII_LITERAL + "b", r".\inputs"),
        id="glob",
    ),
    pytest.param(
        "non-ascii",
        ("Get-Content", _EXACT_NON_ASCII_LITERAL),
        ("Get-Content", _EXACT_NON_ASCII_LITERAL + "b"),
        id="non-ascii",
    ),
    pytest.param(
        "path",
        ("Get-Content", _EXACT_ASCII_LITERAL),
        ("Get-Content", _EXACT_ASCII_LITERAL + "b"),
        id="path",
    ),
    pytest.param(
        "rg-pattern",
        ("rg", "--fixed-strings", "--color", "never", "--max-count", "1", _EXACT_ASCII_LITERAL, r".\inputs"),
        ("rg", "--fixed-strings", "--color", "never", "--max-count", "1", _EXACT_ASCII_LITERAL + "b", r".\inputs"),
        id="rg-pattern",
    ),
)


@pytest.mark.parametrize(
    ("category", "exact_argv", "over_argv"),
    _LITERAL_BOUNDARY_CASES,
)
def test_literal_argv_enforces_exact_utf8_boundary_before_policy_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    category: str,
    exact_argv: tuple[str, ...],
    over_argv: tuple[str, ...],
) -> None:
    assert category
    assert len(_EXACT_NON_ASCII_LITERAL.encode("utf-8")) == 4096
    exact = command_policy._literal_argv(
        _bound_plan(*exact_argv).normalized_plan_bytes,
        3,
    )
    assert any(len(value.encode("utf-8")) == 4096 for value in exact)
    context = _context(tmp_path)

    def forbidden_policy_access(*args: object, **kwargs: object) -> object:
        raise AssertionError("oversized literal reached resolver or filesystem")

    monkeypatch.setattr(
        command_policy,
        "_normalize_operand_path",
        forbidden_policy_access,
        raising=True,
    )
    monkeypatch.setattr(
        command_policy,
        "_resolve_frozen_executable",
        forbidden_policy_access,
        raising=True,
    )
    monkeypatch.setattr(
        command_policy,
        "_bind_path_operand",
        forbidden_policy_access,
        raising=True,
    )
    monkeypatch.setattr(
        command_policy,
        "_read_subtree_count",
        forbidden_policy_access,
        raising=True,
    )
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_LITERAL_LIMIT_EXCEEDED"):
        command_policy.authorize_command_plan(
            _bound_plan(*over_argv),
            context=context,
        )


@pytest.mark.parametrize(
    "argv",
    (
        ("rg", "--files", "--color", "never", "--hidden"),
        ("rg", "--files", "--color", "never", "--follow"),
        (
            "rg",
            "--fixed-strings",
            "--color",
            "never",
            "--max-count",
            "1",
            "--hidden",
            r".\inputs",
        ),
        (
            "rg",
            "--fixed-strings",
            "--color",
            "never",
            "--max-count",
            "1",
            "--",
            r".\inputs",
        ),
        (
            "rg",
            "--fixed-strings",
            "--color",
            "never",
            "--max-count",
            "1",
            "needle",
            "--pre",
        ),
    ),
    ids=(
        "files-root-hidden",
        "files-root-follow",
        "fixed-pattern-hidden",
        "fixed-pattern-end-options",
        "fixed-root-pre",
    ),
)
def test_rg_positional_option_injection_rejects_before_resolution_or_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    argv: tuple[str, ...],
) -> None:
    context = _context(tmp_path)

    def forbidden_policy_access(*args: object, **kwargs: object) -> object:
        raise AssertionError("option-looking positional reached policy access")

    for name in (
        "_resolve_frozen_executable",
        "_bind_path_operand",
        "_read_subtree_count",
    ):
        monkeypatch.setattr(
            command_policy,
            name,
            forbidden_policy_access,
            raising=True,
        )
    with pytest.raises(RuntimeError) as caught:
        command_policy.authorize_command_plan(
            _bound_plan(*argv),
            context=context,
        )
    assert str(caught.value) == "COMMAND_POLICY_OPERATION_REJECTED"


def test_authorize_command_plan_policy_limit_exactly_256_and_one_over(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    base = (("Get-ChildItem", r".\inputs", "-File"), "none")
    projection = (("Sort-Object", "-Property", "Name"), "none")
    exact = ((base, *(projection for _ in range(255))),)
    decision = command_policy.authorize_command_plan(
        _bound_plan(statements=exact), context=context
    )
    assert len(decision.operations) == 256

    over = ((base, *(projection for _ in range(256))),)
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_(?:LIMIT_EXCEEDED|OPERATION_REJECTED)"):
        command_policy.authorize_command_plan(
            _bound_plan(statements=over), context=context
        )


def test_authorizer_decodes_and_segments_256_operations_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    base = (("Get-ChildItem", r".\inputs", "-File"), "none")
    projection = (("Sort-Object", "-Property", "Name"), "none")
    statements = ((base, *(projection for _ in range(255))),)
    plan = _bound_plan(statements=statements)
    expected_token_count = len(
        json.loads(plan.normalized_plan_bytes)["command"]["tokens"]
    )
    decode_calls = 0
    segment_calls = 0
    segmented_tokens = 0
    original_decode = command_policy._decode_plan_object
    original_segments = command_policy._command_segments

    def counted_decode(payload: bytes) -> dict[str, object]:
        nonlocal decode_calls
        decode_calls += 1
        return original_decode(payload)

    def counted_segments(
        tokens: object,
    ) -> tuple[tuple[dict[str, object], ...], ...]:
        nonlocal segment_calls, segmented_tokens
        segment_calls += 1
        assert isinstance(tokens, list)
        segmented_tokens += len(tokens)
        return original_segments(tokens)

    monkeypatch.setattr(command_policy, "_decode_plan_object", counted_decode)
    monkeypatch.setattr(command_policy, "_command_segments", counted_segments)

    decision = command_policy.authorize_command_plan(plan, context=context)

    assert len(decision.operations) == 256
    assert decode_calls == 1
    assert segment_calls <= 1
    assert segmented_tokens <= expected_token_count


def test_help_only_requires_exactly_one_statement(tmp_path: Path) -> None:
    statements = (
        ((("kokoro", "pack", "--help"), "none"),),
        ((("kokoro", "runtime", "--help"), "none"),),
    )
    with pytest.raises(RuntimeError, match="COMMAND_POLICY_OPERATION_REJECTED"):
        command_policy.authorize_command_plan(
            _bound_plan(statements=statements), context=_context(tmp_path)
        )


def test_decision_rejects_forged_record_class_topology_and_canonical_hash(
    tmp_path: Path,
) -> None:
    decision = command_policy.authorize_command_plan(
        _bound_plan("Get-Content", r".\inputs\request.json"),
        context=_context(tmp_path),
    )
    for mutation in (
        {"record_class": "help_discovery"},
        {"topology_sha256": ZERO_SHA256},
        {"canonical_sha256": ZERO_SHA256},
    ):
        with pytest.raises(RuntimeError, match="COMMAND_POLICY_PLAN_INVALID"):
            replace(decision, **mutation)


def test_public_authorizer_rejects_object_setattr_forged_plan_bindings(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)

    scalar_mutations: tuple[tuple[str, object], ...] = (
        ("raw_payload_sha256", ZERO_SHA256),
        ("namespace_manifest_sha256", ZERO_SHA256),
        ("normalized_plan_sha256", ZERO_SHA256),
    )
    for field, value in scalar_mutations:
        plan = _bound_plan("Get-Content", r".\inputs\request.json")
        object.__setattr__(plan, field, value)
        with pytest.raises(RuntimeError) as caught:
            command_policy.authorize_command_plan(plan, context=context)
        assert str(caught.value) == "COMMAND_POLICY_PLAN_INVALID"

    binding_plan = _bound_plan("Get-Content", r".\inputs\request.json")
    document = json.loads(binding_plan.normalized_plan_bytes)
    document["bindings"]["raw"]["payload"]["sha256"] = "1" * 64
    forged_bytes = _canonical_bytes(document)
    object.__setattr__(binding_plan, "normalized_plan_bytes", forged_bytes)
    object.__setattr__(
        binding_plan,
        "normalized_plan_sha256",
        sha256(forged_bytes).hexdigest(),
    )
    with pytest.raises(RuntimeError) as binding_drift:
        command_policy.authorize_command_plan(binding_plan, context=context)
    assert str(binding_drift.value) == "COMMAND_POLICY_PLAN_INVALID"


@pytest.mark.parametrize(
    "name",
    ("direct-cli", "read-pipeline", "compound-cli", "call-operator-cli"),
)
def test_normalized_command_validator_accepts_frozen_task4_fixtures(
    name: str,
) -> None:
    fixture_path = (
        SKILLS_ROOT
        / "fixtures"
        / "complete-suite-command-plan"
        / f"{name}.json"
    )
    fixture_bytes = fixture_path.read_bytes()
    fixture = json.loads(fixture_bytes.decode("utf-8", errors="strict"))
    assert _canonical_bytes(fixture) == fixture_bytes
    pipelines = command_policy._validate_normalized_command(
        {"command": fixture["normalized_plan"], "namespaces": []}
    )
    assert pipelines


def test_literal_extraction_accepts_factory_bound_task4_namespace_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import test_complete_suite_command_plan as task4_tests

    observer, _calls = task4_tests._task4_namespace_observer(command_plan)
    monkeypatch.setattr(
        command_plan,
        "_observe_namespace_root",
        observer,
        raising=True,
    )
    namespaces = command_plan.bind_path_namespaces(
        (
            command_plan.PathNamespaceRequest(
                raw_root=r"D:\Raw Workspace",
                retained_root=r"D:\Retained Workspace",
                label="workspace",
            ),
        )
    )
    raw_payload = (
        "Get-Content -LiteralPath "
        "'D:\\Raw Workspace\\inputs\\request.json' -Raw"
    )
    retained_payload = (
        "Get-Content -LiteralPath "
        "'D:\\Retained Workspace\\inputs\\request.json' -Raw"
    )
    raw_bytes = raw_payload.encode("utf-8")
    retained_bytes = retained_payload.encode("utf-8")
    decoded_by_payload = {
        raw_bytes: task4_tests._task4_real_decoded_payload(
            command_plan,
            raw_bytes,
            decoder_test_root=tmp_path,
        ),
        retained_bytes: task4_tests._task4_real_decoded_payload(
            command_plan,
            retained_bytes,
            decoder_test_root=tmp_path,
        ),
    }

    def fake_decode(candidate: bytes, **_kwargs: object) -> object:
        return decoded_by_payload[candidate]

    monkeypatch.setattr(
        command_plan,
        "decode_powershell_payload",
        fake_decode,
        raising=True,
    )
    shell = task4_tests._task4_real_shell(command_plan)
    bound = command_plan.bind_raw_and_retained_plans(
        task4_tests._task4_render(command_plan, shell, raw_payload),
        task4_tests._task4_render(command_plan, shell, retained_payload),
        shell=shell,
        decoder_path=task4_tests.DECODER_PATH,
        decoder_sha256=sha256(task4_tests.DECODER_PATH.read_bytes()).hexdigest(),
        namespaces=namespaces,
    )
    document = json.loads(bound.normalized_plan_bytes)
    pipelines = command_policy._validate_normalized_command(document)
    assert pipelines == ((3,),)
    assert command_policy._literal_command(
        bound.normalized_plan_bytes,
        pipelines[0][0],
    ) == (
        (
            "Get-Content",
            "-LiteralPath",
            r"D:\Retained Workspace\inputs\request.json",
            "-Raw",
        ),
        "none",
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "negative-pipeline-and-parent",
        "negative-stage",
        "negative-child",
        "non-dict-root",
        "non-dict-pipeline",
        "non-dict-command",
    ),
)
def test_public_authorizer_rejects_negative_ast_indices_and_non_dict_nodes(
    tmp_path: Path,
    mutation: str,
) -> None:
    context = _context(tmp_path)
    plan = _bound_plan("Get-Content", r".\inputs\request.json")
    document = json.loads(plan.normalized_plan_bytes)
    nodes = document["command"]["nodes"]
    assert isinstance(nodes, list)
    if mutation == "negative-pipeline-and-parent":
        appended_pipeline = dict(nodes[2])
        appended_pipeline["index"] = len(nodes)
        nodes.append(appended_pipeline)
        nodes[1]["child_indices"] = [-1]
        nodes[3]["parent_index"] = -1
    elif mutation == "negative-stage":
        nodes[2]["child_indices"] = [-1]
    elif mutation == "negative-child":
        nodes[3]["child_indices"][0] = -1
    elif mutation == "non-dict-root":
        nodes[0] = None
    elif mutation == "non-dict-pipeline":
        nodes[2] = None
    else:
        nodes[3] = None
    forged_bytes = _canonical_bytes(document)
    object.__setattr__(plan, "normalized_plan_bytes", forged_bytes)
    object.__setattr__(
        plan,
        "normalized_plan_sha256",
        sha256(forged_bytes).hexdigest(),
    )
    with pytest.raises(RuntimeError) as caught:
        command_policy.authorize_command_plan(plan, context=context)
    assert str(caught.value) == "COMMAND_POLICY_PLAN_INVALID"


def test_public_authorizer_rejects_unowned_nodes(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    plan = _bound_plan("Get-Content", r".\inputs\request.json")

    def mutate(command: dict[str, object]) -> None:
        nodes = command["nodes"]
        assert isinstance(nodes, list)
        nodes.append(
            {
                "index": len(nodes),
                "ast_type": "SyntheticUnclassifiedAst",
                "role": "expression",
                "parent_index": 3,
                "child_indices": [],
                "invocation_operator": None,
                "literal": None,
            }
        )
        metrics = command["metrics"]
        assert isinstance(metrics, dict)
        metrics["ast_nodes"] += 1

    _forge_normalized_command_plan(plan, mutate)
    with pytest.raises(RuntimeError) as caught:
        command_policy.authorize_command_plan(plan, context=context)
    assert str(caught.value) == "COMMAND_POLICY_PLAN_INVALID"


@pytest.mark.parametrize(
    "token_kind",
    ("Comment", "LineContinuation"),
)
def test_public_authorizer_rejects_standalone_ignored_tokens(
    tmp_path: Path,
    token_kind: str,
) -> None:
    context = _context(tmp_path / token_kind)
    plan = _bound_plan("Get-Content", r".\inputs\request.json")

    def mutate(command: dict[str, object]) -> None:
        tokens = command["tokens"]
        assert isinstance(tokens, list)
        tokens.insert(
            len(tokens) - 1,
            {
                "flags": [],
                "index": -1,
                "kind": token_kind,
                "literal": None,
                "text": (
                    "kokoro pack validate synthetic --json"
                    if token_kind == "Comment"
                    else "`\r\n"
                ),
            },
        )
        for index, token in enumerate(tokens):
            token["index"] = index

    _forge_normalized_command_plan(plan, mutate)
    with pytest.raises(RuntimeError) as caught:
        command_policy.authorize_command_plan(plan, context=context)
    assert str(caught.value) == "COMMAND_POLICY_PLAN_INVALID"


@pytest.mark.parametrize(
    ("separator", "placement"),
    tuple(
        pytest.param(separator, placement, id=f"{separator}-{placement}")
        for separator in ("Pipe", "Semi", "NewLine")
        for placement in ("duplicate", "trailing")
    ),
)
def test_public_authorizer_rejects_empty_or_trailing_token_segments(
    tmp_path: Path,
    separator: str,
    placement: str,
) -> None:
    if separator == "Pipe" and placement == "duplicate":
        statements = (
            (
                (("Get-Content", r".\inputs\request.json"), "none"),
                (("Select-Object", "-First", "1"), "none"),
            ),
        )
    elif separator != "Pipe" and placement == "duplicate":
        statements = (
            ((("Get-Content", r".\inputs\request.json"), "none"),),
            ((("Get-Content", r".\inputs\request.json"), "none"),),
        )
    else:
        statements = (((("Get-Content", r".\inputs\request.json"), "none"),),)
    plan = _bound_plan(statements=statements)

    def mutate(command: dict[str, object]) -> None:
        tokens = command["tokens"]
        assert isinstance(tokens, list)
        text = {"Pipe": "|", "Semi": ";", "NewLine": "\r\n"}[separator]
        if placement == "duplicate":
            position = next(
                index
                for index, token in enumerate(tokens)
                if token["kind"] in ("Pipe", "Semi")
            )
            tokens[position]["kind"] = separator
            tokens[position]["text"] = text
            insertion = position + 1
        else:
            insertion = len(tokens) - 1
        tokens.insert(
            insertion,
            {
                "flags": [],
                "index": -1,
                "kind": separator,
                "literal": None,
                "text": text,
            },
        )
        for index, token in enumerate(tokens):
            token["index"] = index

    _forge_normalized_command_plan(plan, mutate)
    with pytest.raises(RuntimeError) as caught:
        command_policy.authorize_command_plan(
            plan,
            context=_context(tmp_path / f"{separator}-{placement}"),
        )
    assert str(caught.value) == "COMMAND_POLICY_PLAN_INVALID"


@pytest.mark.parametrize(
    "metric",
    ("ast_depth", "ast_nodes", "operations", "pipeline_stages", "statements"),
)
def test_public_authorizer_recomputes_every_normalized_command_metric(
    tmp_path: Path,
    metric: str,
) -> None:
    plan = _bound_plan("Get-Content", r".\inputs\request.json")

    def mutate(command: dict[str, object]) -> None:
        metrics = command["metrics"]
        assert isinstance(metrics, dict)
        metrics[metric] += 1

    _forge_normalized_command_plan(plan, mutate)
    with pytest.raises(RuntimeError) as caught:
        command_policy.authorize_command_plan(
            plan,
            context=_context(tmp_path / metric),
        )
    assert str(caught.value) == "COMMAND_POLICY_PLAN_INVALID"


def test_public_authorizer_rejects_self_consistent_plan_interposition_before_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    plan = _bound_plan("kokoro", "pack", "validate", "--help")
    replacement = _bound_plan("kokoro", "runtime", "plan", "--help")
    revalidate = command_policy._revalidate_retained_namespaces
    calls = 0

    def interpose(namespaces: tuple[object, ...]) -> None:
        nonlocal calls
        revalidate(namespaces)
        calls += 1
        if calls == 2:
            object.__setattr__(
                plan,
                "normalized_plan_bytes",
                replacement.normalized_plan_bytes,
            )
            object.__setattr__(
                plan,
                "normalized_plan_sha256",
                replacement.normalized_plan_sha256,
            )

    monkeypatch.setattr(
        command_policy,
        "_revalidate_retained_namespaces",
        interpose,
        raising=True,
    )
    with pytest.raises(RuntimeError) as caught:
        command_policy.authorize_command_plan(plan, context=context)
    assert str(caught.value) == "COMMAND_POLICY_PLAN_INVALID"


def test_public_authorizer_rejects_context_identity_interposition_before_silent_join(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = r"outputs\run"
    output = r"outputs\run\result.json"
    context = _context(
        tmp_path,
        post_extra=[_entry(target, None, 940), _entry(output, b"{}", 941)],
        created=(f"workspace\\{target}", f"workspace\\{output}"),
    )
    statements = (
        ((
            ((
                "New-Item",
                "-ItemType",
                "Directory",
                "-LiteralPath",
                f".\\{target}",
                "-ErrorAction",
                "Stop",
            ), "none"),
            (("Out-Null",), "none"),
        )),
        ((_pack_export_argv(f".\\{output}"), "none"),),
    )
    plan = _bound_plan(statements=statements)
    revalidate = command_policy._revalidate_retained_namespaces
    calls = 0

    def interpose(namespaces: tuple[object, ...]) -> None:
        nonlocal calls
        revalidate(namespaces)
        calls += 1
        if calls == 2:
            replacement = Path(str(context.workspace_root))
            assert replacement == context.workspace_root
            assert replacement is not context.workspace_root
            object.__setattr__(context, "workspace_root", replacement)

    monkeypatch.setattr(
        command_policy,
        "_revalidate_retained_namespaces",
        interpose,
        raising=True,
    )
    with pytest.raises(RuntimeError) as caught:
        command_policy.authorize_command_plan(plan, context=context)
    assert str(caught.value) == "COMMAND_POLICY_PLAN_INVALID"


def test_authorization_view_detaches_registered_index_before_interposition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    relative = r"workspace\inputs\request.json"
    cached_index = command_policy._registered_snapshot_index(
        context.filesystem,
        "post",
    )
    cached_record = command_policy._snapshot_lookup(cached_index, relative)
    assert cached_record is not None
    original_inode = cached_record[4].inode
    evidence_entry = next(
        entry
        for root in context.filesystem.post_roots
        for entry in root.entries
        if command_policy._windows_path_equal(
            str(PureWindowsPath(root.relative_root) / entry.relative_path),
            relative,
        )
    )
    authorize_read_only = command_policy._authorize_read_only
    observed_local_inodes: list[tuple[int, int]] = []

    def interpose(
        argv: tuple[str, ...],
        policy_context: object,
    ) -> tuple[str, ...]:
        local_record = command_policy._snapshot_lookup(
            command_policy._context_snapshot_index(policy_context, "post"),
            relative,
        )
        assert local_record is not None
        object.__setattr__(evidence_entry.identity, "inode", original_inode + 1000)
        object.__setattr__(cached_record[4], "inode", original_inode + 2000)
        local_after = command_policy._snapshot_lookup(
            command_policy._context_snapshot_index(policy_context, "post"),
            relative,
        )
        assert local_after is not None
        observed_local_inodes.append(
            (local_record[4].inode, local_after[4].inode)
        )
        return authorize_read_only(argv, policy_context)

    monkeypatch.setattr(
        command_policy,
        "_authorize_read_only",
        interpose,
        raising=True,
    )
    with pytest.raises(RuntimeError) as caught:
        command_policy.authorize_command_plan(
            _bound_plan("Get-Content", r".\inputs\request.json"),
            context=context,
        )
    assert str(caught.value) == "COMMAND_POLICY_PLAN_INVALID", observed_local_inodes
    assert observed_local_inodes == [(original_inode, original_inode)]


def test_fail_monotonic_error_never_echoes_literal_content(tmp_path: Path) -> None:
    secret = "synthetic-sensitive-literal"

    def expression(document: dict[str, object]) -> None:
        nodes = document["nodes"]
        nodes[4]["ast_type"] = "SubExpressionAst"

    with pytest.raises(RuntimeError) as caught:
        command_policy.authorize_command_plan(
            _bound_plan("Get-Content", secret, mutate_command=expression),
            context=_context(tmp_path),
        )
    assert str(caught.value) in {
        "COMMAND_POLICY_PLAN_INVALID",
        "COMMAND_POLICY_LITERAL_REQUIRED",
        "COMMAND_POLICY_OPERATION_REJECTED",
    }
    assert secret not in str(caught.value)
    assert type(caught.value) is RuntimeError
    assert caught.value.args == (str(caught.value),)
    assert vars(caught.value) == {}
    assert "SubExpressionAst" not in str(caught.value)
    assert "read_only" not in str(caught.value)
