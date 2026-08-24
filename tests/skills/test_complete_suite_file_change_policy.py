from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from hashlib import sha256
import importlib
import inspect
import json
import os
from pathlib import Path, PureWindowsPath
import subprocess
from typing import Literal, get_type_hints

import pytest
from jsonschema import Draft202012Validator


SKILLS = Path(__file__).resolve().parent
FIXTURES = SKILLS / "fixtures" / "complete-suite-file-change"
SCHEMA = SKILLS / "complete-suite-file-change-ledger.schema.json"
ZERO_SHA256 = "0" * 64
ROOT = r"C:\synthetic\workspace"
TOKEN = "<workspace>"
REQUEST_PATH = ROOT + r"\data\authoring\mika-moongear\request.json"


def _policy():
    return importlib.import_module("complete_suite_file_change_policy")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _jsonl(events: list[dict[str, object]]) -> bytes:
    return b"".join(_canonical(event) + b"\n" for event in events)


def _change_item(
    event_id: str,
    status: str,
    changes: list[dict[str, str]],
) -> dict[str, object]:
    return {
        "type": "file_change",
        "id": event_id,
        "status": status,
        "changes": changes,
    }


def _paired_events(
    changes: list[dict[str, str]] | None = None,
    *,
    event_id: str = "fc-1",
) -> list[dict[str, object]]:
    selected = changes or [{"path": REQUEST_PATH, "kind": "add"}]
    return [
        {
            "type": "item.started",
            "item": _change_item(event_id, "in_progress", selected),
        },
        {
            "type": "item.completed",
            "item": _change_item(event_id, "completed", selected),
        },
    ]


def _binding():
    policy = _policy()
    return policy.FileChangeRootBinding(token=TOKEN, literal_root=ROOT)


def _decode(
    events: list[dict[str, object]],
    *,
    domain: str = "raw",
):
    return _policy().decode_file_change_lifecycles(
        _jsonl(events),
        domain=domain,
        root_bindings=(_binding(),),
    )


def test_fixture_matrix_is_synthetic_canonical_jsonl() -> None:
    expected = {
        "original-authoring.jsonl": (
            "fc-authoring-1",
            [
                {
                    "path": (
                        ROOT
                        + r"\data\authoring\mika-moongear\request.json"
                    ),
                    "kind": "add",
                }
            ],
        ),
        "workspace-override.jsonl": (
            "fc-workspace-1",
            [
                {"path": ROOT + "\\data\\" + name, "kind": "add"}
                for name in (
                    "policy-workspace-demo-input.json",
                    "semantic-workspace-demo.json",
                    "policy-workspace-demo.json",
                    "plan-workspace-demo.json",
                    "rendered-workspace-demo.json",
                )
            ],
        ),
    }
    for name, (event_id, changes) in expected.items():
        payload = (FIXTURES / name).read_bytes()
        assert payload == _jsonl(_paired_events(changes, event_id=event_id))
        assert payload.endswith(b"\n")
        assert b"\r" not in payload
        assert not payload.startswith(b"\xef\xbb\xbf")
        lines = payload.splitlines()
        documents = [json.loads(line, object_pairs_hook=_unique_pairs) for line in lines]
        assert len(documents) == 2
        assert all(_canonical(document) == line for document, line in zip(documents, lines))
        assert len(documents[0]["item"]["changes"]) == len(changes)
        assert documents[0]["item"]["changes"] == documents[1]["item"]["changes"]
        assert "Approved" not in payload.decode("utf-8")


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def test_closed_ledger_schema_contract() -> None:
    schema = json.loads(SCHEMA.read_bytes(), object_pairs_hook=_unique_pairs)
    Draft202012Validator.check_schema(schema)
    assert {name: value for name, value in schema.items() if name != "$defs"} == {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "https://kokoroarc.local/schemas/"
            "complete-suite-file-change-ledger.schema.json"
        ),
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "records"],
        "properties": {
            "version": {
                "const": "complete-suite-file-change-sanitizer-ledger-v1"
            },
            "records": {
                "type": "array",
                "maxItems": 128,
                "uniqueItems": True,
                "items": {"$ref": "#/$defs/record"},
            },
        },
    }
    assert {name: schema["$defs"][name] for name in ("sha256", "boundedPath", "record")} == {
        "sha256": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
        "boundedPath": {
            "type": "string",
            "minLength": 1,
            "maxLength": 4096,
            "pattern": "^[^\\u0000\\r\\n]+$",
        },
        "record": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "normalized_path",
                "sanitizer_record_path",
                "sanitizer_record_sha256",
            ],
            "properties": {
                "normalized_path": {"$ref": "#/$defs/boundedPath"},
                "sanitizer_record_path": {"$ref": "#/$defs/boundedPath"},
                "sanitizer_record_sha256": {"$ref": "#/$defs/sha256"},
            },
        },
    }
    assert set(schema["$defs"]) == {
        "sha256",
        "boundedPath",
        "record",
        "nonNegativeInteger",
        "boundedIdentifier",
        "filesystemIdentity",
        "sessionIdentity",
        "snapshotEntry",
        "snapshotRoot",
        "filesystemEvidenceRecord",
        "filesystemEvidenceWrapper",
        "decisionChange",
        "decisionContent",
        "decisionRecord",
        "decisionWrapper",
        "pathsBinding",
        "deltaPartition",
        "aggregateTransition",
        "retainedCounts",
        "postState",
        "retainedContent",
        "operationBindingRecord",
        "operationBindingWrapper",
        "filesystemViewRecord",
        "filesystemViewWrapper",
        "adjudicationCommandRecord",
        "integrityOperationBinding",
        "integrityFilesystemView",
        "integrityRecord",
        "integrityWrapper",
        "filePlanChange",
        "filePlanDomain",
        "filePlanRecord",
        "entrySource",
        "entryPolicy",
        "entryCounts",
        "retainedFileChangeLedgerEntry",
        "retainedEvidencePaths",
        "retainedFileChangeLedger",
    }
    for definition in schema["$defs"].values():
        if definition.get("type") == "object":
            assert definition["additionalProperties"] is False
            assert set(definition["required"]) == set(definition["properties"])


def test_policy_model_has_exact_immutable_public_shape() -> None:
    policy = _policy()
    expected = {
        "FileChangePathRule": {
            "normalized_path": str,
            "role": Literal[
                "authoring_request",
                "authoring_source",
                "authoring_validation_result",
                "policy_input",
                "semantic_result",
                "language_policy",
                "render_plan",
                "rendered_output",
            ],
            "required_schema": str | None,
            "producer_action": tuple[str, ...] | None,
            "consumer_actions": tuple[tuple[str, ...], ...],
            "result_selector": tuple[str, ...] | None,
        },
        "FileChangeContentSource": {
            "normalized_path": str,
            "raw_path": Path,
            "retained_path": Path,
            "sanitizer_record_path": Path,
        },
        "FileChangeRootBinding": {
            "token": str,
            "literal_root": str,
        },
        "DecodedFileChange": {
            "lifecycle_index": int,
            "event_id": str,
            "started_event_ordinal": int,
            "completed_event_ordinal": int,
            "change_ordinal": int,
            "path": str,
            "normalized_path": str,
            "kind": Literal["add", "update"],
            "started_sha256": str,
            "completed_sha256": str,
        },
        "DecodedFileChangePlan": {
            "domain": Literal["raw", "retained", "preflight"],
            "lifecycles": int,
            "transition_entries": int,
            "changes": tuple[policy.DecodedFileChange, ...],
            "topology_sha256": str,
            "canonical_sha256": str,
        },
        "BoundFileChange": {
            "started_event_ordinal": int,
            "completed_event_ordinal": int,
            "event_id": str,
            "change_ordinal": int,
            "normalized_path": str,
            "kind": Literal["add", "update"],
            "role": str,
        },
        "BoundFileChangeContent": {
            "normalized_path": str,
            "raw_size": int,
            "raw_sha256": str,
            "retained_size": int,
            "retained_sha256": str,
            "retained_bytes": bytes,
            "raw_document_sha256": str,
            "retained_document_sha256": str,
            "sanitizer_record_sha256": str,
            "role_validation_sha256": str,
        },
        "FileChangePolicyContext": {
            "variant": Literal["baseline", "suite-enabled"],
            "case_id": str,
            "case_root": Path,
            "workspace_root": Path,
            "rules": tuple[policy.FileChangePathRule, ...],
            "filesystem": policy.BoundFilesystemEvidence,
            "sanitizer_ledger_path": Path,
            "sanitizer_ledger_identity": policy.FilesystemObjectIdentity,
            "sanitizer_ledger_sha256": str,
        },
        "FileChangePolicyDecision": {
            "version": str,
            "variant": str,
            "case_id": str,
            "changes": tuple[policy.BoundFileChange, ...],
            "contents": tuple[policy.BoundFileChangeContent, ...],
            "implicit_ancestor_paths": tuple[str, ...],
            "unique_final_paths": tuple[str, ...],
            "transition_entries": int,
            "raw_content_bytes": int,
            "retained_content_bytes": int,
            "normalized_plan_sha256": str,
            "aggregate_transition_sha256": str,
            "content_inventory_sha256": str,
            "canonical_sha256": str,
        },
    }
    for class_name, annotations in expected.items():
        cls = getattr(policy, class_name)
        assert tuple(field.name for field in fields(cls)) == tuple(annotations)
        assert get_type_hints(cls) == annotations
        assert cls.__dataclass_params__.frozen is True


def test_public_api_signatures_are_closed() -> None:
    policy = _policy()
    decode = inspect.signature(policy.decode_file_change_lifecycles)
    authorize = inspect.signature(policy.authorize_file_change_events)
    assert tuple(decode.parameters) == (
        "session_bytes",
        "domain",
        "root_bindings",
    )
    assert decode.parameters["domain"].kind is inspect.Parameter.KEYWORD_ONLY
    assert decode.parameters["root_bindings"].kind is inspect.Parameter.KEYWORD_ONLY
    assert tuple(authorize.parameters) == (
        "raw_session_bytes",
        "retained_session_bytes",
        "content_sources",
        "context",
    )
    assert authorize.parameters["context"].kind is inspect.Parameter.KEYWORD_ONLY
    assert get_type_hints(policy.decode_file_change_lifecycles) == {
        "session_bytes": bytes,
        "domain": Literal["raw", "retained", "preflight"],
        "root_bindings": tuple[policy.FileChangeRootBinding, ...],
        "return": policy.DecodedFileChangePlan,
    }
    assert get_type_hints(policy.authorize_file_change_events) == {
        "raw_session_bytes": bytes,
        "retained_session_bytes": bytes,
        "content_sources": tuple[policy.FileChangeContentSource, ...],
        "context": policy.FileChangePolicyContext,
        "return": policy.FileChangePolicyDecision,
    }


def test_direct_internal_bound_object_construction_rejects() -> None:
    policy = _policy()
    with pytest.raises((TypeError, RuntimeError)):
        policy.BoundFileChangeContent()
    with pytest.raises((TypeError, RuntimeError)):
        policy.FileChangePolicyDecision()


def test_lifecycle_decoder_binds_order_hashes_and_normalized_paths() -> None:
    events = _paired_events()
    plan = _decode(events)
    assert plan.domain == "raw"
    assert plan.lifecycles == 1
    assert plan.transition_entries == 1
    assert len(plan.changes) == 1
    change = plan.changes[0]
    assert change.lifecycle_index == 0
    assert change.event_id == "fc-1"
    assert (change.started_event_ordinal, change.completed_event_ordinal) == (0, 1)
    assert change.change_ordinal == 0
    assert change.path == REQUEST_PATH
    assert change.normalized_path == TOKEN + r"\data\authoring\mika-moongear\request.json"
    assert change.kind == "add"
    assert change.started_sha256 == sha256(_canonical(events[0]["item"])).hexdigest()
    assert change.completed_sha256 == sha256(_canonical(events[1]["item"])).hexdigest()
    assert len(plan.topology_sha256) == 64
    assert len(plan.canonical_sha256) == 64


def test_zero_event_and_explicit_inert_item_types_are_permitted() -> None:
    events = [
        {"type": "thread.started", "thread_id": "synthetic"},
        {
            "type": "item.completed",
            "item": {"id": "m-1", "type": "agent_message", "text": "done"},
        },
        {
            "type": "item.completed",
            "item": {"id": "r-1", "type": "reasoning", "text": "bounded"},
        },
        {"type": "turn.completed", "usage": {}},
    ]
    plan = _decode(events, domain="retained")
    assert plan.domain == "retained"
    assert plan.lifecycles == plan.transition_entries == 0
    assert plan.changes == ()


def test_add_then_update_retains_every_ordered_transition_entry() -> None:
    changes = [
        {"path": REQUEST_PATH, "kind": "add"},
        {"path": REQUEST_PATH, "kind": "update"},
    ]
    plan = _decode(_paired_events(changes))
    assert [(entry.change_ordinal, entry.kind) for entry in plan.changes] == [
        (0, "add"),
        (1, "update"),
    ]


def test_lifecycle_rejects_reverse_completion_of_interleaved_starts() -> None:
    first = _paired_events(event_id="fc-a")
    second = _paired_events(
        [{"path": ROOT + r"\data\second.json", "kind": "add"}],
        event_id="fc-b",
    )
    reordered = [first[0], second[0], second[1], first[1]]
    with pytest.raises(RuntimeError, match="FILE_CHANGE_LIFECYCLE_INVALID"):
        _decode(reordered)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda events: events[:1],
        lambda events: [events[1], events[0]],
        lambda events: events + [events[1]],
        lambda events: [events[0], {**events[1], "item": {**events[1]["item"], "id": "other"}}],
        lambda events: [events[0], {**events[1], "item": {**events[1]["item"], "changes": [{"path": REQUEST_PATH, "kind": "update"}]}}],
        lambda events: [events[0], {**events[1], "item": {**events[1]["item"], "status": "failed"}}],
    ],
)
def test_lifecycle_rejects_missing_duplicate_reordered_or_mismatched_terminal_items(mutator) -> None:
    with pytest.raises(RuntimeError, match="FILE_CHANGE_LIFECYCLE_INVALID"):
        _decode(mutator(_paired_events()))


@pytest.mark.parametrize("kind", ["delete", "move", "rename", "chmod", "unknown"])
def test_path_policy_rejects_every_non_add_update_kind(kind: str) -> None:
    with pytest.raises(RuntimeError, match="FILE_CHANGE_KIND_INVALID"):
        _decode(_paired_events([{"path": REQUEST_PATH, "kind": kind}]))


@pytest.mark.parametrize(
    "path",
    [
        r"C:\synthetic\outside\request.json",
        ROOT + r"\..\outside.json",
        ROOT + r"\data\*.json",
        ROOT + r"\data\request.json.",
        ROOT + r"\data\request.json ",
        "relative.json",
        "Registry::HKEY_CURRENT_USER\\x",
    ],
)
def test_path_policy_rejects_outside_traversal_wildcard_and_nonliteral_paths(path: str) -> None:
    with pytest.raises(RuntimeError, match="FILE_CHANGE_PATH_INVALID"):
        _decode(_paired_events([{"path": path, "kind": "add"}]))


def test_path_policy_rejects_ambiguous_or_mismatched_absolute_root() -> None:
    policy = _policy()
    bindings = (
        policy.FileChangeRootBinding(token=TOKEN, literal_root=ROOT),
        policy.FileChangeRootBinding(
            token="<nested>", literal_root=ROOT + r"\data"
        ),
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_ROOT_BINDING_INVALID"):
        policy.decode_file_change_lifecycles(
            _jsonl(_paired_events()), domain="raw", root_bindings=bindings
        )

    case_aliases = (
        policy.FileChangeRootBinding(token=TOKEN, literal_root=ROOT),
        policy.FileChangeRootBinding(
            token="<case-alias>",
            literal_root=r"c:\SYNTHETIC\WORKSPACE",
        ),
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_ROOT_BINDING_INVALID"):
        policy.decode_file_change_lifecycles(
            _jsonl(_paired_events()),
            domain="raw",
            root_bindings=case_aliases,
        )


def test_path_policy_does_not_apply_unicode_full_casefold_aliases() -> None:
    policy = _policy()
    literal_root = r"C:\synthetic\straße"
    binding = (
        policy.FileChangeRootBinding(
            token=TOKEN,
            literal_root=literal_root,
        ),
    )
    exact = _paired_events(
        [{"path": literal_root + r"\data\request.json", "kind": "add"}]
    )
    decoded = policy.decode_file_change_lifecycles(
        _jsonl(exact), domain="raw", root_bindings=binding
    )
    assert decoded.changes[0].normalized_path == TOKEN + r"\data\request.json"

    folded_alias = _paired_events(
        [
            {
                "path": r"C:\synthetic\strasse\data\request.json",
                "kind": "add",
            }
        ]
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_PATH_INVALID"):
        policy.decode_file_change_lifecycles(
            _jsonl(folded_alias), domain="raw", root_bindings=binding
        )


def test_event_type_classifier_rejects_unknown_state_changing_items() -> None:
    event = {
        "type": "item.completed",
        "item": {"id": "unsafe-1", "type": "mcp_tool_call", "status": "completed"},
    }
    with pytest.raises(RuntimeError, match="FILE_CHANGE_EVENT_TYPE_INVALID"):
        _decode([event])


def test_duplicate_key_invalid_utf8_and_nonobject_lines_reject() -> None:
    policy = _policy()
    binding = (_binding(),)
    bad_payloads = (
        b'{"type":"turn.completed","type":"turn.completed"}\n',
        b"\xff\n",
        b"[]\n",
        b"\n",
    )
    for payload in bad_payloads:
        with pytest.raises(RuntimeError, match="FILE_CHANGE_SESSION_INVALID"):
            policy.decode_file_change_lifecycles(
                payload, domain="raw", root_bindings=binding
            )


def test_resource_limit_rejects_lifecycle_and_transition_entry_overflow() -> None:
    exact_lifecycle_events: list[dict[str, object]] = []
    for index in range(64):
        exact_lifecycle_events.extend(_paired_events(event_id=f"exact-{index}"))
    exact_lifecycles = _decode(exact_lifecycle_events)
    assert exact_lifecycles.lifecycles == 64
    assert exact_lifecycles.transition_entries == 64

    lifecycle_events: list[dict[str, object]] = []
    for index in range(65):
        lifecycle_events.extend(_paired_events(event_id=f"fc-{index}"))
    with pytest.raises(RuntimeError, match="FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED"):
        _decode(lifecycle_events)

    exact_changes = [
        {"path": ROOT + rf"\data\exact-{index}.json", "kind": "add"}
        for index in range(256)
    ]
    exact_entries = _decode(_paired_events(exact_changes))
    assert exact_entries.transition_entries == 256

    changes = [
        {"path": ROOT + rf"\data\f-{index}.json", "kind": "add"}
        for index in range(257)
    ]
    with pytest.raises(RuntimeError, match="FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED"):
        _decode(_paired_events(changes))


@pytest.mark.parametrize(
    ("unique_documents", "raw_bytes", "retained_bytes"),
    (
        (129, 0, 0),
        (128, 32 * 1024 * 1024 + 1, 0),
        (128, 0, 32 * 1024 * 1024 + 1),
        (128, 32 * 1024 * 1024, 32 * 1024 * 1024 + 1),
    ),
    ids=(
        "unique-documents-one-over",
        "raw-total-one-over",
        "retained-total-one-over",
        "combined-total-one-over",
    ),
)
def test_content_account_exact_at_and_one_over(
    unique_documents: int,
    raw_bytes: int,
    retained_bytes: int,
) -> None:
    policy = _policy()
    policy._enforce_content_account(
        unique_documents=128,
        raw_bytes=32 * 1024 * 1024,
        retained_bytes=32 * 1024 * 1024,
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED"):
        policy._enforce_content_account(
            unique_documents=unique_documents,
            raw_bytes=raw_bytes,
            retained_bytes=retained_bytes,
        )


@pytest.mark.parametrize(
    "files",
    (
        {f"file-{index}.yaml": b"" for index in range(129)},
        {"file.yaml": b"x" * 256_001},
        {
            **{f"file-{index}.yaml": b"x" * 250_000 for index in range(8)},
            "one-over.yaml": b"x",
        },
        {"a/b/c/d/e/f/g.yaml": b""},
        {"tests/positive.yaml": b"x" * 64_001},
        {
            "tests/one.yaml": b"x" * 64_000,
            "tests/two.yaml": b"x" * 64_000,
            "tests/three.yaml": b"x" * 64_000,
            "tests/four.yaml": b"x",
        },
    ),
    ids=(
        "source-file-count-one-over",
        "source-per-file-one-over",
        "source-total-one-over",
        "source-depth-one-over",
        "corpus-per-file-one-over",
        "corpus-total-one-over",
    ),
)
def test_source_pack_account_exact_at_and_one_over(
    files: dict[str, bytes],
) -> None:
    policy = _policy()
    exact_accounts = (
        {f"file-{index}.yaml": b"" for index in range(128)},
        {"file.yaml": b"x" * 256_000},
        {f"file-{index}.yaml": b"x" * 250_000 for index in range(8)},
        {"a/b/c/d/e/f.yaml": b""},
        {"tests/positive.yaml": b"x" * 64_000},
        {
            "tests/one.yaml": b"x" * 64_000,
            "tests/two.yaml": b"x" * 64_000,
            "tests/three.yaml": b"x" * 64_000,
        },
    )
    for exact in exact_accounts:
        policy._enforce_source_pack_account(exact)
    with pytest.raises(RuntimeError, match="FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED"):
        policy._enforce_source_pack_account(files)


def test_source_pack_totals_reject_from_bound_sizes_before_sibling_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy, context, source, session = _authorized_partial_pack_setup(
        tmp_path,
        changed_relative="identity.yaml",
    )
    original_entry = policy._bound_post_file_entry
    original_read = policy._read_bound_post_file
    read_calls = 0

    def inflated_entry(path: Path, *, context, post_index):
        entry = original_entry(
            path,
            context=context,
            post_index=post_index,
        )
        relative = str(path).replace("/", "\\")
        size = 64_000 if "\\tests\\" in relative else 256_000
        return replace(entry, size=size)

    def observed_read(*args, **kwargs):
        nonlocal read_calls
        read_calls += 1
        return original_read(*args, **kwargs)

    monkeypatch.setattr(policy, "_bound_post_file_entry", inflated_entry)
    monkeypatch.setattr(policy, "_read_bound_post_file", observed_read)
    with pytest.raises(RuntimeError, match="FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED"):
        policy.authorize_file_change_events(
            session, session, (source,), context=context
        )
    assert read_calls == 0


def _nested_value_at_depth(depth: int) -> object:
    value: object = 0
    for _index in range(depth - 1):
        value = [value]
    return value


def test_generic_semantic_account_exact_at_and_one_over() -> None:
    policy = _policy()
    exact_nodes = [
        *([0] * 1024 for _index in range(7)),
        [0] * 1015,
    ]
    policy._enforce_semantic_bounds(_nested_value_at_depth(64))
    policy._enforce_semantic_bounds(exact_nodes)
    policy._enforce_semantic_bounds([0] * 1024)
    policy._enforce_semantic_bounds("x" * 16_384)

    over_values = (
        _nested_value_at_depth(65),
        [*exact_nodes[:-1], [0] * 1016],
        [0] * 1025,
        "x" * 16_385,
    )
    for value in over_values:
        with pytest.raises(
            RuntimeError, match="FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED"
        ):
            policy._enforce_semantic_bounds(value)


def test_corpus_semantic_and_case_accounts_exact_at_and_one_over() -> None:
    policy = _policy()
    strict = {
        "max_depth": 16,
        "max_nodes": 4096,
        "max_members": 256,
        "max_scalar_chars": 4096,
    }
    exact_nodes = [
        *([0] * 255 for _index in range(15)),
        [0] * 254,
    ]
    policy._enforce_semantic_bounds(_nested_value_at_depth(16), **strict)
    policy._enforce_semantic_bounds(exact_nodes, **strict)
    policy._enforce_semantic_bounds([0] * 256, **strict)
    policy._enforce_semantic_bounds("x" * 4096, **strict)
    for value in (
        _nested_value_at_depth(17),
        [*exact_nodes[:-1], [0] * 255],
        [0] * 257,
        "x" * 4097,
    ):
        with pytest.raises(
            RuntimeError, match="FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED"
        ):
            policy._enforce_semantic_bounds(value, **strict)

    corpus_rule = next(
        rule
        for rule in policy._file_change_rules_for_case(
            "original-authoring-route", variant="baseline"
        )
        if rule.required_schema == "test-corpus"
        and rule.normalized_path.endswith(r"tests\positive.yaml")
    )
    policy._validate_role_document(
        _canonical({"cases": [{} for _index in range(128)]}),
        rule=corpus_rule,
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED"):
        policy._validate_role_document(
            _canonical({"cases": [{} for _index in range(129)]}),
            rule=corpus_rule,
        )


def test_decoder_is_detached_immutable_and_domain_bound() -> None:
    events = _paired_events()
    raw = _decode(events, domain="raw")
    retained = _decode(events, domain="retained")
    events[0]["item"]["changes"][0]["path"] = "mutated"
    assert raw.changes[0].path == REQUEST_PATH
    assert raw.topology_sha256 == retained.topology_sha256
    assert raw.canonical_sha256 != retained.canonical_sha256
    with pytest.raises(FrozenInstanceError):
        raw.domain = "preflight"


def test_decoder_rejects_invalid_domain_and_mutable_root_bindings() -> None:
    policy = _policy()
    payload = _jsonl(_paired_events())
    with pytest.raises(RuntimeError, match="FILE_CHANGE_DOMAIN_INVALID"):
        policy.decode_file_change_lifecycles(
            payload, domain="other", root_bindings=(_binding(),)
        )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_ROOT_BINDING_INVALID"):
        policy.decode_file_change_lifecycles(
            payload, domain="raw", root_bindings=[_binding()]
        )


def test_case_policy_rule_values_are_exact_and_symmetric_across_variants() -> None:
    policy = _policy()
    baseline = policy._file_change_rules_for_case(
        "original-authoring-route", variant="baseline"
    )
    enabled = policy._file_change_rules_for_case(
        "original-authoring-route", variant="suite-enabled"
    )
    assert baseline == enabled
    assert len(baseline) == 21
    assert {rule.role for rule in baseline} >= {
        "authoring_request",
        "authoring_source",
        "authoring_validation_result",
    }
    baseline_workspace = policy._file_change_rules_for_case(
        "workspace-override-explicit-activation", variant="baseline"
    )
    enabled_workspace = policy._file_change_rules_for_case(
        "workspace-override-explicit-activation", variant="suite-enabled"
    )
    assert baseline_workspace == enabled_workspace
    assert len(baseline_workspace) == 5
    assert policy._file_change_rules_for_case(
        "archive-overwrite-pressure", variant="baseline"
    ) == ()


def test_authoring_source_rules_follow_the_real_directory_consumers() -> None:
    policy = _policy()
    rules = policy._file_change_rules_for_case(
        "original-authoring-route",
        variant="baseline",
    )

    source_rules = tuple(rule for rule in rules if rule.role == "authoring_source")

    assert len(source_rules) == 16
    assert {
        rule.consumer_actions for rule in source_rules
    } == {
        (
            ("character", "draft", "validate"),
            ("character", "draft", "compile"),
        )
    }


def test_language_policy_rule_is_consumed_by_exact_runtime_plan_action() -> None:
    policy = _policy()
    rules = policy._file_change_rules_for_case(
        "workspace-override-explicit-activation",
        variant="baseline",
    )
    language_policy = next(rule for rule in rules if rule.role == "language_policy")
    assert language_policy.producer_action == ("policy", "compile")
    assert language_policy.consumer_actions == (("runtime", "plan"),)
    assert language_policy.result_selector == ("policy",)


def test_zero_event_authorization_returns_factory_decision_without_content(
    tmp_path: Path,
) -> None:
    policy = _policy()
    command_policy = importlib.import_module("complete_suite_command_policy")
    case_root = tmp_path / "case"
    workspace = case_root / "workspace"
    workspace.mkdir(parents=True)
    root_payload = {
        "root_index": 0,
        "relative_root": "workspace",
        "present": True,
        "root_identity": _identity_record(_identity(workspace)),
        "ancestor_identities": [],
        "entries": [],
    }
    root_record = {
        **root_payload,
        "manifest_sha256": sha256(_canonical(root_payload)).hexdigest(),
    }
    pre = {
        "schema_version": "complete-suite-policy-filesystem-state-v1",
        "policy_filesystem_roots": [root_record],
    }
    post = {
        **pre,
        "created_paths": [],
        "changed_paths": [],
        "removed_paths": [],
    }
    filesystem = command_policy.bind_filesystem_evidence(
        _canonical(pre), _canonical(post), case_root=case_root
    )
    ledger_path = tmp_path / "sanitizer-ledger.json"
    ledger_path.write_bytes(
        _canonical(
            {
                "version": "complete-suite-file-change-sanitizer-ledger-v1",
                "records": [],
            }
        )
    )
    context = policy.FileChangePolicyContext(
        variant="baseline",
        case_id="archive-overwrite-pressure",
        case_root=case_root,
        workspace_root=workspace,
        rules=(),
        filesystem=filesystem,
        sanitizer_ledger_path=ledger_path,
        sanitizer_ledger_identity=_identity(ledger_path),
        sanitizer_ledger_sha256=sha256(ledger_path.read_bytes()).hexdigest(),
    )
    decision = policy.authorize_file_change_events(
        b"", b"", (), context=context
    )
    assert decision.version == "complete-suite-file-change-policy-v1"
    assert decision.changes == decision.contents == ()
    assert decision.unique_final_paths == ()
    assert decision.transition_entries == 0
    assert decision.raw_content_bytes == decision.retained_content_bytes == 0
    assert "raw" not in repr(decision).casefold()


def test_raw_bytes_never_leak_through_bound_repr_or_policy_errors() -> None:
    policy = _policy()
    marker = "SYNTHETIC-PRIVATE-MARKER"
    assert marker not in repr(policy.BoundFileChangeContent)
    with pytest.raises(RuntimeError) as caught:
        policy.decode_file_change_lifecycles(
            marker.encode("utf-8"), domain="raw", root_bindings=(_binding(),)
        )
    assert marker not in str(caught.value)


def test_authorization_schema_failure_never_echoes_raw_content(
    tmp_path: Path,
) -> None:
    marker = "SYNTHETIC-PRIVATE-AUTHORIZATION-MARKER"
    policy, context, source, session, _target = _authorized_setup(
        tmp_path,
        payload=_canonical({"private": marker}),
    )
    with pytest.raises(RuntimeError) as caught:
        policy.authorize_file_change_events(
            session,
            session,
            (source,),
            context=context,
        )
    assert marker not in str(caught.value)
    assert marker not in repr(caught.value)
    assert marker not in repr(context)
    assert marker not in repr(source)


def test_factory_token_object_setattr_forge_is_not_authenticated() -> None:
    policy = _policy()
    forged = policy.BoundFileChangeContent(policy._BOUND_FACTORY_TOKEN)
    values = {
        "normalized_path": TOKEN + r"\data\forged.json",
        "raw_size": 1,
        "raw_sha256": ZERO_SHA256,
        "retained_size": 1,
        "retained_sha256": ZERO_SHA256,
        "retained_bytes": b"x",
        "raw_document_sha256": ZERO_SHA256,
        "retained_document_sha256": ZERO_SHA256,
        "sanitizer_record_sha256": ZERO_SHA256,
        "role_validation_sha256": ZERO_SHA256,
    }
    for name, value in values.items():
        object.__setattr__(forged, name, value)
    with pytest.raises(RuntimeError, match="FILE_CHANGE_BOUND_VALUE_INVALID"):
        policy._authenticate_bound_content(forged)


def _request_document() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "artifact_id": "request/synthetic",
        "created_by": {"component": "kokoroarc", "version": "1.0.0"},
        "mode": "original",
        "namespace": "original",
        "character_id": "mika-moongear",
        "display_name": "Mika Moongear",
        "character_version": "1.0.0",
        "requested_locales": ["en-US", "ja-JP", "zh-CN"],
        "intended_use_cases": ["synthetic validation"],
        "user_constraints": ["local only"],
        "inputs": [{"type": "creative_brief", "content": "Synthetic fixture."}],
    }


def _synthetic_authoring_pack() -> dict[str, bytes]:
    documents: dict[str, object] = {
        "character.yaml": {
            "schema_version": "1.0",
            "artifact_id": "original/mika-moongear/source",
            "created_by": {"component": "kokoroarc", "version": "1.0.0"},
            "character_id": "mika-moongear",
            "character_version": "1.0.0",
            "namespace": "original",
            "files": {
                "identity": "identity.yaml",
                "evidence": "evidence.yaml",
                "derived_profile": "derived-profile.yaml",
                "overrides": "overrides.yaml",
                "behavior": "behavior.yaml",
                "growth": "growth.yaml",
                "expressions": "expressions.yaml",
            },
            "locale_files": {
                "en-US": "locales/en-US.yaml",
                "ja-JP": "locales/ja-JP.yaml",
                "zh-CN": "locales/zh-CN.yaml",
            },
            "scenario_files": {"debugging": "scenarios/debugging.yaml"},
        },
        "identity.yaml": {
            "display_name": "Synthetic Mika",
            "declared_age": "adult",
            "role": "debugging partner",
            "non_negotiables": ["evidence first"],
        },
        "evidence.yaml": {"authored_original": True, "claims": []},
        "derived-profile.yaml": {
            "method_version": "1.0",
            "traits": {"curiosity": 0.7},
        },
        "overrides.yaml": {},
        "behavior.yaml": {"default_intensity": "balanced"},
        "growth.yaml": {"dimensions": ["trust"]},
        "expressions.yaml": {"greeting": {"en-US": ["Hello."]}},
        "locales/en-US.yaml": {},
        "locales/ja-JP.yaml": {},
        "locales/zh-CN.yaml": {},
        "scenarios/debugging.yaml": {},
        "tests/positive.yaml": {
            "scenario": "debugging",
            "cases": [
                {
                    "case_id": "positive-one",
                    "user_need": "Explain the synthetic failure.",
                    "expected_behavior": ["inspect_evidence"],
                    "expected_locales": {"en-US": "Use English."},
                }
            ],
        },
        "tests/negative.yaml": {
            "scenario": "debugging",
            "cases": [
                {
                    "case_id": "negative-one",
                    "user_need": "Skip verification.",
                    "forbidden_behavior": ["invent_evidence"],
                    "safe_alternative": "Inspect evidence first.",
                }
            ],
        },
        "tests/multilingual.yaml": {
            "intent": "explain_failure",
            "semantic_key": "explanation",
            "expected_locales": ["en-US", "ja-JP", "zh-CN"],
        },
        "tests/protected-spans.yaml": {
            "immutable_spans": ["FILE_CHANGE_CONTENT_INVALID"],
            "required_warning_id": "preserve_error",
        },
    }
    return {relative: _canonical(document) for relative, document in documents.items()}


def _synthetic_runtime_documents() -> dict[str, bytes]:
    created_by = {"component": "kokoroarc", "version": "1.0.0"}
    semantic = {
        "schema_version": "1.0",
        "artifact_id": "semantic/workspace-demo",
        "created_by": created_by,
        "scenario": "debugging",
        "conclusion": "Synthetic conclusion.",
        "explanation": ["Synthetic explanation."],
        "recommendations": ["Inspect the synthetic evidence."],
        "warnings": [],
        "immutable_spans": ["FILE_CHANGE_CONTENT_INVALID"],
        "format_constraints": [],
    }
    plan_segments = [
        {
            "id": "s1",
            "channel": "technical_explanation",
            "target_language": "en-US",
            "semantic_keys": ["conclusion", "explanation"],
        },
        {
            "id": "s2",
            "channel": "recommendations",
            "target_language": "en-US",
            "semantic_keys": ["recommendations"],
        },
    ]
    render_plan = {
        "schema_version": "1.0",
        "artifact_id": "plan/workspace-demo",
        "created_by": created_by,
        "primary_language": "en-US",
        "segments": plan_segments,
        "protected_spans": ["FILE_CHANGE_CONTENT_INVALID"],
        "max_switches": 0,
    }
    rendered = {
        "text": (
            "Synthetic conclusion. Synthetic explanation. "
            "Inspect the synthetic evidence. FILE_CHANGE_CONTENT_INVALID"
        ),
        "segments": plan_segments,
        "switch_count": 0,
    }
    language_policy = {
        "schema_version": "1.0",
        "artifact_id": "policy/workspace-demo",
        "created_by": created_by,
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
        "mixing": {"max_switches": 0, "min_primary_ratio": 1},
        "subtitles": {"enabled": False, "language": None},
    }
    return {
        "policy_input": _canonical({}),
        "semantic_result": _canonical(semantic),
        "language_policy": _canonical(language_policy),
        "render_plan": _canonical(render_plan),
        "rendered_output": _canonical(rendered),
    }


def _synthetic_validation_result() -> bytes:
    return _canonical(
        {
            "schema_version": "1.0",
            "artifact_id": "validation/synthetic-request",
            "created_by": {"component": "kokoroarc", "version": "1.0"},
            "valid": True,
            "violations": [],
            "fallback_level": None,
        }
    )


def _identity(path: Path):
    plan_module = importlib.import_module("complete_suite_command_plan")
    if os.name == "nt":
        if path.is_dir():
            return plan_module._observe_namespace_root(str(path))[1]
        payload_sha256 = sha256(path.read_bytes()).hexdigest()
        observed = plan_module._observe_plain_file(path, payload_sha256)
        return plan_module.FilesystemObjectIdentity(
            device=observed.volume_serial,
            inode=observed.file_index,
            file_type=1,
            reparse_tag=0,
            link_count=observed.link_count,
        )
    value = os.lstat(path)
    return plan_module.FilesystemObjectIdentity(
        device=value.st_dev,
        inode=value.st_ino,
        file_type=1,
        reparse_tag=getattr(value, "st_reparse_tag", 0),
        link_count=value.st_nlink,
    )


def _identity_record(identity) -> dict[str, int]:
    return {
        "device": identity.device,
        "inode": identity.inode,
        "file_type": identity.file_type,
        "reparse_tag": identity.reparse_tag,
        "link_count": identity.link_count,
    }


def _file_entry_record(
    relative: str,
    path: Path,
    payload: bytes,
    *,
    identity=None,
) -> dict[str, object]:
    selected_identity = identity if identity is not None else _identity(path)
    return {
        "relative_path": relative,
        "kind": "file",
        "size": len(payload),
        "sha256": sha256(payload).hexdigest(),
        "link_count": 1,
        "identity": _identity_record(selected_identity),
    }


def _directory_entry_record(relative: str, path: Path) -> dict[str, object]:
    return {
        "relative_path": relative,
        "kind": "directory",
        "size": 0,
        "sha256": None,
        "link_count": 1,
        "identity": _identity_record(_identity(path)),
    }


def _root_record(
    *,
    workspace: Path,
    entries: list[dict[str, object]],
    root_index: int = 0,
    relative_root: str = "workspace",
) -> dict[str, object]:
    if os.name == "nt":
        plan_module = importlib.import_module("complete_suite_command_plan")
        _observed, root_identity, ancestor_identities, _case_sensitive = (
            plan_module._observe_namespace_root(str(workspace))
        )
    else:
        root_identity = _identity(workspace)
        ancestors = []
        current = workspace.parent
        while True:
            ancestors.append(_identity(current))
            parent = current.parent
            if parent == current:
                break
            current = parent
        ancestor_identities = tuple(reversed(ancestors))
    payload = {
        "root_index": root_index,
        "relative_root": relative_root,
        "present": True,
        "root_identity": _identity_record(root_identity),
        "ancestor_identities": [
            _identity_record(identity) for identity in ancestor_identities
        ],
        "entries": sorted(entries, key=lambda value: str(value["relative_path"]).casefold()),
    }
    return {
        **payload,
        "manifest_sha256": sha256(_canonical(payload)).hexdigest(),
    }


def _filesystem_for_document(
    *,
    case_root: Path,
    workspace: Path,
    relative: str,
    final_payload: bytes,
    kind: str,
    prior_payload: bytes | None = None,
    implicit_ancestors: tuple[str, ...] = (),
    extra_created: tuple[str, ...] = (),
    override_post_identity=None,
    override_post_sha256: str | None = None,
    implicit_pre_wrong_kind: str | None = None,
    implicit_pre_reparse: str | None = None,
    omit_post_ancestor: str | None = None,
    overlapping_roots: bool = False,
    overlapping_root_case_alias: bool = False,
    overlapping_root_separator_alias: bool = False,
):
    command_policy = importlib.import_module("complete_suite_command_policy")
    target = workspace.joinpath(*PureWindowsPath(relative).parts)
    directory_relatives: list[str] = []
    current = PureWindowsPath(relative).parent
    while str(current) not in {".", ""}:
        directory_relatives.append(str(current))
        current = current.parent
    directory_relatives.reverse()
    post_entries: list[dict[str, object]] = [
        _directory_entry_record(
            value, workspace.joinpath(*PureWindowsPath(value).parts)
        )
        for value in directory_relatives
        if value != omit_post_ancestor
    ]
    post_file = _file_entry_record(
        relative,
        target,
        final_payload,
        identity=override_post_identity,
    )
    if override_post_sha256 is not None:
        post_file = {**post_file, "sha256": override_post_sha256}
    post_entries.append(post_file)
    pre_entries = [
        entry
        for entry in post_entries
        if entry["kind"] == "directory"
        and entry["relative_path"] not in implicit_ancestors
    ]
    if implicit_pre_wrong_kind is not None:
        wrong_kind_path = workspace.joinpath(
            *PureWindowsPath(implicit_pre_wrong_kind).parts
        )
        pre_entries.append(
            _file_entry_record(implicit_pre_wrong_kind, wrong_kind_path, b"")
        )
    if implicit_pre_reparse is not None:
        reparse_path = workspace.joinpath(*PureWindowsPath(implicit_pre_reparse).parts)
        reparse_entry = _directory_entry_record(implicit_pre_reparse, reparse_path)
        reparse_entry["identity"] = {
            **reparse_entry["identity"],
            "reparse_tag": 0xA0000003,
        }
        pre_entries.append(reparse_entry)
    if kind == "update":
        assert prior_payload is not None
        pre_entries.append(_file_entry_record(relative, target, prior_payload))
    global_path = "workspace\\" + relative
    for global_extra in extra_created:
        prefix = "workspace\\"
        assert global_extra.startswith(prefix)
        extra_relative = global_extra[len(prefix) :]
        extra_path = workspace.joinpath(*PureWindowsPath(extra_relative).parts)
        extra_path.parent.mkdir(parents=True, exist_ok=True)
        extra_payload = b"synthetic extra"
        extra_path.write_bytes(extra_payload)
        post_entries.append(
            _file_entry_record(extra_relative, extra_path, extra_payload)
        )
    created = tuple(
        "workspace\\" + value
        for value in implicit_ancestors
        if value
        not in {
            implicit_pre_wrong_kind,
            implicit_pre_reparse,
            omit_post_ancestor,
        }
    )
    if kind == "add":
        created += (global_path,)
    created += extra_created
    pre_roots = [_root_record(workspace=workspace, entries=pre_entries)]
    post_roots = [_root_record(workspace=workspace, entries=post_entries)]
    if overlapping_roots:
        def _below_data(
            entries: list[dict[str, object]],
        ) -> list[dict[str, object]]:
            prefix = "data\\"
            rebased: list[dict[str, object]] = []
            for entry in entries:
                relative_path = str(entry["relative_path"])
                if relative_path.startswith(prefix):
                    rebased.append(
                        {**entry, "relative_path": relative_path[len(prefix) :]}
                    )
            return rebased

        pre_roots.append(
            _root_record(
                workspace=workspace / "data",
                entries=_below_data(pre_entries),
                root_index=1,
                relative_root=(
                    "workspace/data"
                    if overlapping_root_separator_alias
                    else (
                        r"WORKSPACE\data"
                        if overlapping_root_case_alias
                        else r"workspace\data"
                    )
                ),
            )
        )
        post_roots.append(
            _root_record(
                workspace=workspace / "data",
                entries=_below_data(post_entries),
                root_index=1,
                relative_root=(
                    "workspace/data"
                    if overlapping_root_separator_alias
                    else (
                        r"WORKSPACE\data"
                        if overlapping_root_case_alias
                        else r"workspace\data"
                    )
                ),
            )
        )
    pre = {
        "schema_version": "complete-suite-policy-filesystem-state-v1",
        "policy_filesystem_roots": pre_roots,
    }
    changed = []
    if implicit_pre_wrong_kind is not None:
        changed.append("workspace\\" + implicit_pre_wrong_kind)
    if implicit_pre_reparse is not None:
        changed.append("workspace\\" + implicit_pre_reparse)
    if kind == "update":
        changed.append(global_path)
    post = {
        "schema_version": "complete-suite-policy-filesystem-state-v1",
        "policy_filesystem_roots": post_roots,
        "created_paths": sorted(created, key=str.casefold),
        "changed_paths": sorted(changed, key=str.casefold),
        "removed_paths": [],
    }
    return command_policy.bind_filesystem_evidence(
        _canonical(pre),
        _canonical(post),
        case_root=case_root,
    )


def _write_sanitizer_ledger(
    *,
    tmp_path: Path,
    normalized_path: str,
    raw_path: Path,
    retained_path: Path,
    raw_payload: bytes,
    retained_payload: bytes,
    redaction_count: int = 0,
    redaction_classes: list[str] | None = None,
) -> tuple[Path, Path]:
    record = {
        "version": "complete-suite-file-change-sanitizer-record-v1",
        "normalized_path": normalized_path,
        "raw_path_sha256": sha256(str(raw_path).encode("utf-8")).hexdigest(),
        "retained_path_sha256": sha256(
            str(retained_path).encode("utf-8")
        ).hexdigest(),
        "raw_size": len(raw_payload),
        "raw_sha256": sha256(raw_payload).hexdigest(),
        "retained_size": len(retained_payload),
        "retained_sha256": sha256(retained_payload).hexdigest(),
        "redaction_count": redaction_count,
        "redaction_classes": redaction_classes or [],
    }
    record_bytes = _canonical(record)
    record_path = tmp_path / "sanitizer-record.json"
    record_path.write_bytes(record_bytes)
    ledger = {
        "version": "complete-suite-file-change-sanitizer-ledger-v1",
        "records": [
            {
                "normalized_path": normalized_path,
                "sanitizer_record_path": str(record_path),
                "sanitizer_record_sha256": sha256(record_bytes).hexdigest(),
            }
        ],
    }
    ledger_path = tmp_path / "sanitizer-ledger.json"
    ledger_path.write_bytes(_canonical(ledger))
    return ledger_path, record_path


def _authorized_setup(
    tmp_path: Path,
    *,
    kind: str = "add",
    payload: bytes | None = None,
    prior_payload: bytes | None = None,
    relative: str = r"data\authoring\mika-moongear\request.json",
    implicit_ancestors: tuple[str, ...] = (),
    extra_created: tuple[str, ...] = (),
    override_post_identity=None,
    override_post_sha256: str | None = None,
    implicit_pre_wrong_kind: str | None = None,
    implicit_pre_reparse: str | None = None,
    omit_post_ancestor: str | None = None,
    overlapping_roots: bool = False,
    overlapping_root_case_alias: bool = False,
    overlapping_root_separator_alias: bool = False,
):
    policy = _policy()
    case_root = tmp_path / "case"
    workspace = case_root / "workspace"
    target = workspace.joinpath(*PureWindowsPath(relative).parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    final_payload = payload if payload is not None else _canonical(_request_document())
    target.write_bytes(final_payload)
    normalized = TOKEN + "\\" + relative
    ledger_path, record_path = _write_sanitizer_ledger(
        tmp_path=tmp_path,
        normalized_path=normalized,
        raw_path=target,
        retained_path=target,
        raw_payload=final_payload,
        retained_payload=final_payload,
    )
    filesystem = _filesystem_for_document(
        case_root=case_root,
        workspace=workspace,
        relative=relative,
        final_payload=final_payload,
        kind=kind,
        prior_payload=prior_payload,
        implicit_ancestors=implicit_ancestors,
        extra_created=extra_created,
        override_post_identity=override_post_identity,
        override_post_sha256=override_post_sha256,
        implicit_pre_wrong_kind=implicit_pre_wrong_kind,
        implicit_pre_reparse=implicit_pre_reparse,
        omit_post_ancestor=omit_post_ancestor,
        overlapping_roots=overlapping_roots,
        overlapping_root_case_alias=overlapping_root_case_alias,
        overlapping_root_separator_alias=overlapping_root_separator_alias,
    )
    context = policy.FileChangePolicyContext(
        variant="baseline",
        case_id="original-authoring-route",
        case_root=case_root,
        workspace_root=workspace,
        rules=policy._file_change_rules_for_case(
            "original-authoring-route", variant="baseline"
        ),
        filesystem=filesystem,
        sanitizer_ledger_path=ledger_path,
        sanitizer_ledger_identity=_identity(ledger_path),
        sanitizer_ledger_sha256=sha256(ledger_path.read_bytes()).hexdigest(),
    )
    source = policy.FileChangeContentSource(
        normalized_path=normalized,
        raw_path=target,
        retained_path=target,
        sanitizer_record_path=record_path,
    )
    changes = [{"path": str(target), "kind": kind}]
    return policy, context, source, _jsonl(_paired_events(changes)), target


def _authorized_partial_pack_setup(
    tmp_path: Path,
    *,
    changed_relative: str,
    changed_payload: bytes | None = None,
):
    policy = _policy()
    command_policy = importlib.import_module("complete_suite_command_policy")
    case_root = tmp_path / "case"
    workspace = case_root / "workspace"
    authoring_root = workspace / "data" / "authoring" / "mika-moongear"
    pack = _synthetic_authoring_pack()
    final_payload = (
        changed_payload
        if changed_payload is not None
        else pack[changed_relative]
    )
    prior_payload = pack[changed_relative]
    if final_payload == prior_payload:
        if changed_relative == "identity.yaml":
            prior_payload = _canonical(
                {
                    "display_name": "Prior Synthetic Mika",
                    "declared_age": "adult",
                    "role": "debugging partner",
                    "non_negotiables": ["evidence first"],
                }
            )
        else:
            prior_document = json.loads(prior_payload)
            prior_document["synthetic_prior_marker"] = True
            prior_payload = _canonical(prior_document)
    pack[changed_relative] = final_payload

    directories: set[str] = set()
    for relative in pack:
        current = PureWindowsPath(relative.replace("/", "\\")).parent
        while str(current) not in {".", ""}:
            directories.add(str(current))
            current = current.parent
    for relative in sorted(directories, key=lambda value: (value.count("\\"), value)):
        authoring_root.joinpath(*PureWindowsPath(relative).parts).mkdir(
            parents=True,
            exist_ok=True,
        )
    for relative, payload in pack.items():
        target = authoring_root.joinpath(
            *PureWindowsPath(relative.replace("/", "\\")).parts
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    directory_entries = [
        _directory_entry_record(
            str(PureWindowsPath("data", "authoring", "mika-moongear", relative)),
            authoring_root.joinpath(*PureWindowsPath(relative).parts),
        )
        for relative in sorted(directories, key=str.casefold)
    ]
    for fixed_relative in ("data", r"data\authoring", r"data\authoring\mika-moongear"):
        directory_entries.append(
            _directory_entry_record(
                fixed_relative,
                workspace.joinpath(*PureWindowsPath(fixed_relative).parts),
            )
        )
    post_files: list[dict[str, object]] = []
    pre_files: list[dict[str, object]] = []
    for relative, payload in pack.items():
        local = relative.replace("/", "\\")
        global_relative = str(
            PureWindowsPath("data", "authoring", "mika-moongear", local)
        )
        target = workspace.joinpath(*PureWindowsPath(global_relative).parts)
        post_files.append(_file_entry_record(global_relative, target, payload))
        pre_files.append(
            _file_entry_record(
                global_relative,
                target,
                prior_payload if relative == changed_relative else payload,
            )
        )
    pre = {
        "schema_version": "complete-suite-policy-filesystem-state-v1",
        "policy_filesystem_roots": [
            _root_record(
                workspace=workspace,
                entries=directory_entries + pre_files,
            )
        ],
    }
    changed_global = str(
        PureWindowsPath(
            "workspace",
            "data",
            "authoring",
            "mika-moongear",
            changed_relative.replace("/", "\\"),
        )
    )
    post = {
        "schema_version": "complete-suite-policy-filesystem-state-v1",
        "policy_filesystem_roots": [
            _root_record(
                workspace=workspace,
                entries=directory_entries + post_files,
            )
        ],
        "created_paths": [],
        "changed_paths": [changed_global],
        "removed_paths": [],
    }
    filesystem = command_policy.bind_filesystem_evidence(
        _canonical(pre), _canonical(post), case_root=case_root
    )
    normalized = str(
        PureWindowsPath(
            TOKEN,
            "data",
            "authoring",
            "mika-moongear",
            changed_relative.replace("/", "\\"),
        )
    )
    target = authoring_root.joinpath(
        *PureWindowsPath(changed_relative.replace("/", "\\")).parts
    )
    ledger_path, record_path = _write_sanitizer_ledger(
        tmp_path=tmp_path,
        normalized_path=normalized,
        raw_path=target,
        retained_path=target,
        raw_payload=final_payload,
        retained_payload=final_payload,
    )
    context = policy.FileChangePolicyContext(
        variant="baseline",
        case_id="original-authoring-route",
        case_root=case_root,
        workspace_root=workspace,
        rules=policy._file_change_rules_for_case(
            "original-authoring-route", variant="baseline"
        ),
        filesystem=filesystem,
        sanitizer_ledger_path=ledger_path,
        sanitizer_ledger_identity=_identity(ledger_path),
        sanitizer_ledger_sha256=sha256(ledger_path.read_bytes()).hexdigest(),
    )
    source = policy.FileChangeContentSource(
        normalized_path=normalized,
        raw_path=target,
        retained_path=target,
        sanitizer_record_path=record_path,
    )
    session = _jsonl(
        _paired_events([{"path": str(target), "kind": "update"}])
    )
    return policy, context, source, session


def _authorized_runtime_setup(
    tmp_path: Path,
    *,
    changed_role: str,
    present_roles: tuple[str, ...],
    changed_payload: bytes | None = None,
    variant: str = "baseline",
):
    policy = _policy()
    command_policy = importlib.import_module("complete_suite_command_policy")
    case_root = tmp_path / "case"
    workspace = case_root / "workspace"
    data_root = workspace / "data"
    data_root.mkdir(parents=True)
    documents = _synthetic_runtime_documents()
    rules = {
        rule.role: rule
        for rule in policy._file_change_rules_for_case(
            "workspace-override-explicit-activation",
            variant=variant,
        )
    }
    assert changed_role in present_roles
    final_payload = (
        changed_payload
        if changed_payload is not None
        else documents[changed_role]
    )
    prior_payload = (
        _canonical({"mode": "mixed"})
        if changed_role == "policy_input"
        else documents[changed_role]
    )
    if prior_payload == final_payload:
        prior_document = json.loads(prior_payload)
        if changed_role == "rendered_output":
            prior_document["text"] = (
                "Prior synthetic output. FILE_CHANGE_CONTENT_INVALID"
            )
        else:
            prior_document["artifact_id"] = (
                str(prior_document["artifact_id"]) + "-prior"
            )
        prior_payload = _canonical(prior_document)

    directory_entry = _directory_entry_record("data", data_root)
    pre_files: list[dict[str, object]] = []
    post_files: list[dict[str, object]] = []
    changed_target: Path | None = None
    for role in present_roles:
        rule = rules[role]
        relative = rule.normalized_path[len(TOKEN + "\\") :]
        target = workspace.joinpath(*PureWindowsPath(relative).parts)
        payload = final_payload if role == changed_role else documents[role]
        target.write_bytes(payload)
        post_files.append(_file_entry_record(relative, target, payload))
        pre_files.append(
            _file_entry_record(
                relative,
                target,
                prior_payload if role == changed_role else payload,
            )
        )
        if role == changed_role:
            changed_target = target
    assert changed_target is not None
    changed_rule = rules[changed_role]
    changed_relative = changed_rule.normalized_path[len(TOKEN + "\\") :]
    global_path = "workspace\\" + changed_relative
    pre = {
        "schema_version": "complete-suite-policy-filesystem-state-v1",
        "policy_filesystem_roots": [
            _root_record(
                workspace=workspace,
                entries=[directory_entry, *pre_files],
            )
        ],
    }
    post = {
        "schema_version": "complete-suite-policy-filesystem-state-v1",
        "policy_filesystem_roots": [
            _root_record(
                workspace=workspace,
                entries=[directory_entry, *post_files],
            )
        ],
        "created_paths": [],
        "changed_paths": [global_path],
        "removed_paths": [],
    }
    filesystem = command_policy.bind_filesystem_evidence(
        _canonical(pre),
        _canonical(post),
        case_root=case_root,
    )
    ledger_path, record_path = _write_sanitizer_ledger(
        tmp_path=tmp_path,
        normalized_path=changed_rule.normalized_path,
        raw_path=changed_target,
        retained_path=changed_target,
        raw_payload=final_payload,
        retained_payload=final_payload,
    )
    context = policy.FileChangePolicyContext(
        variant=variant,
        case_id="workspace-override-explicit-activation",
        case_root=case_root,
        workspace_root=workspace,
        rules=tuple(rules.values()),
        filesystem=filesystem,
        sanitizer_ledger_path=ledger_path,
        sanitizer_ledger_identity=_identity(ledger_path),
        sanitizer_ledger_sha256=sha256(ledger_path.read_bytes()).hexdigest(),
    )
    source = policy.FileChangeContentSource(
        normalized_path=changed_rule.normalized_path,
        raw_path=changed_target,
        retained_path=changed_target,
        sanitizer_record_path=record_path,
    )
    session = _jsonl(
        _paired_events([{"path": str(changed_target), "kind": "update"}])
    )
    return policy, context, source, session


def _authorized_schema_role_setup(
    tmp_path: Path,
    *,
    role: str,
    payload: bytes,
):
    if role == "authoring_validation_result":
        return _authorized_setup(
            tmp_path,
            relative=(
                r"data\authoring\mika-moongear\validation"
                r"\request-validate-1.json"
            ),
            payload=payload,
        )[:4]
    return _authorized_runtime_setup(
        tmp_path,
        changed_role=role,
        present_roles=(role,),
        changed_payload=payload,
    )


def test_filesystem_transition_and_authoring_content_binding(tmp_path: Path) -> None:
    policy, context, source, session, _target = _authorized_setup(tmp_path)
    decision = policy.authorize_file_change_events(
        session, session, (source,), context=context
    )
    assert decision.version == "complete-suite-file-change-policy-v1"
    assert decision.transition_entries == 1
    assert decision.unique_final_paths == (source.normalized_path,)
    assert [change.role for change in decision.changes] == ["authoring_request"]
    assert len(decision.contents) == 1
    content = decision.contents[0]
    assert content.normalized_path == source.normalized_path
    assert content.retained_bytes == source.retained_path.read_bytes()
    assert content.raw_size == content.retained_size == len(content.retained_bytes)
    assert content.raw_sha256 == content.retained_sha256
    assert len(content.role_validation_sha256) == 64
    assert "Synthetic fixture" not in repr(content)
    assert context.filesystem.created_paths == (
        r"workspace\data\authoring\mika-moongear\request.json",
    )


@pytest.mark.parametrize(
    "role",
    (
        "authoring_validation_result",
        "semantic_result",
        "language_policy",
        "render_plan",
    ),
)
def test_public_authorizer_accepts_each_schema_bound_result_role(
    tmp_path: Path,
    role: str,
) -> None:
    documents = _synthetic_runtime_documents()
    payload = (
        _synthetic_validation_result()
        if role == "authoring_validation_result"
        else documents[role]
    )
    policy, context, source, session = _authorized_schema_role_setup(
        tmp_path,
        role=role,
        payload=payload,
    )
    decision = policy.authorize_file_change_events(
        session,
        session,
        (source,),
        context=context,
    )
    assert tuple(change.role for change in decision.changes) == (role,)
    assert decision.contents[0].normalized_path == source.normalized_path


@pytest.mark.parametrize(
    "role",
    (
        "authoring_validation_result",
        "semantic_result",
        "language_policy",
        "render_plan",
    ),
)
def test_public_authorizer_rejects_invalid_schema_bound_result_role(
    tmp_path: Path,
    role: str,
) -> None:
    policy, context, source, session = _authorized_schema_role_setup(
        tmp_path,
        role=role,
        payload=_canonical({}),
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_SCHEMA_ROLE_INVALID"):
        policy.authorize_file_change_events(
            session,
            session,
            (source,),
            context=context,
        )


def _authorized_distinct_setup(
    tmp_path: Path,
    *,
    payloads: tuple[bytes, bytes] | None = None,
):
    policy = _policy()
    command_policy = importlib.import_module("complete_suite_command_policy")
    sanitization = importlib.import_module("complete_suite_sanitization")
    case_root = tmp_path / "case"
    raw_workspace = case_root / "raw-workspace"
    retained_workspace = case_root / "retained-workspace"
    relative = r"data\authoring\mika-moongear\request.json"
    raw_target = raw_workspace.joinpath(*PureWindowsPath(relative).parts)
    retained_target = retained_workspace.joinpath(*PureWindowsPath(relative).parts)
    raw_target.parent.mkdir(parents=True)
    retained_target.parent.mkdir(parents=True)
    if payloads is None:
        raw_document = _request_document()
        raw_document["inputs"][0]["content"] = (
            r"Read the synthetic local note at C:\Users\SyntheticUser\note.txt."
        )
        raw_payload = _canonical(raw_document)
        retained_payload, summary = sanitization.sanitize_artifact(raw_payload)
        assert raw_payload != retained_payload
        assert summary == {
            "redaction_count": 1,
            "redaction_classes": ["user_profile"],
        }
    else:
        raw_payload, retained_payload = payloads
        summary = {"redaction_count": 0, "redaction_classes": []}
    raw_target.write_bytes(raw_payload)
    retained_target.write_bytes(retained_payload)

    relative_directories: list[str] = []
    current = PureWindowsPath(relative).parent
    while str(current) not in {".", ""}:
        relative_directories.append(str(current))
        current = current.parent
    relative_directories.reverse()
    raw_directories = [
        _directory_entry_record(
            value, raw_workspace.joinpath(*PureWindowsPath(value).parts)
        )
        for value in relative_directories
    ]
    retained_directories = [
        _directory_entry_record(
            value, retained_workspace.joinpath(*PureWindowsPath(value).parts)
        )
        for value in relative_directories
    ]
    pre_roots = [
        _root_record(
            workspace=raw_workspace,
            entries=raw_directories,
            root_index=0,
            relative_root="raw-workspace",
        ),
        _root_record(
            workspace=retained_workspace,
            entries=retained_directories,
            root_index=1,
            relative_root="retained-workspace",
        ),
    ]
    post_roots = [
        _root_record(
            workspace=raw_workspace,
            entries=raw_directories
            + [_file_entry_record(relative, raw_target, raw_payload)],
            root_index=0,
            relative_root="raw-workspace",
        ),
        _root_record(
            workspace=retained_workspace,
            entries=retained_directories
            + [
                _file_entry_record(
                    relative, retained_target, retained_payload
                )
            ],
            root_index=1,
            relative_root="retained-workspace",
        ),
    ]
    created = [
        "raw-workspace\\" + relative,
        "retained-workspace\\" + relative,
    ]
    pre = {
        "schema_version": "complete-suite-policy-filesystem-state-v1",
        "policy_filesystem_roots": pre_roots,
    }
    post = {
        "schema_version": "complete-suite-policy-filesystem-state-v1",
        "policy_filesystem_roots": post_roots,
        "created_paths": sorted(created, key=str.casefold),
        "changed_paths": [],
        "removed_paths": [],
    }
    filesystem = command_policy.bind_filesystem_evidence(
        _canonical(pre), _canonical(post), case_root=case_root
    )
    normalized = TOKEN + "\\" + relative
    ledger_path, record_path = _write_sanitizer_ledger(
        tmp_path=tmp_path,
        normalized_path=normalized,
        raw_path=raw_target,
        retained_path=retained_target,
        raw_payload=raw_payload,
        retained_payload=retained_payload,
        redaction_count=summary["redaction_count"],
        redaction_classes=summary["redaction_classes"],
    )
    context = policy.FileChangePolicyContext(
        variant="suite-enabled",
        case_id="original-authoring-route",
        case_root=case_root,
        workspace_root=raw_workspace,
        rules=policy._file_change_rules_for_case(
            "original-authoring-route", variant="suite-enabled"
        ),
        filesystem=filesystem,
        sanitizer_ledger_path=ledger_path,
        sanitizer_ledger_identity=_identity(ledger_path),
        sanitizer_ledger_sha256=sha256(ledger_path.read_bytes()).hexdigest(),
    )
    source = policy.FileChangeContentSource(
        normalized_path=normalized,
        raw_path=raw_target,
        retained_path=retained_target,
        sanitizer_record_path=record_path,
    )
    raw_session = _jsonl(
        _paired_events([{"path": str(raw_target), "kind": "add"}])
    )
    retained_session = _jsonl(
        _paired_events([{"path": str(retained_target), "kind": "add"}])
    )
    return (
        policy,
        context,
        source,
        raw_session,
        retained_session,
        raw_payload,
        retained_payload,
    )


def test_distinct_raw_retained_mirrors_bind_both_snapshots_and_sanitization(
    tmp_path: Path,
) -> None:
    (
        policy,
        context,
        source,
        raw_session,
        retained_session,
        raw_payload,
        retained_payload,
    ) = _authorized_distinct_setup(tmp_path)
    decision = policy.authorize_file_change_events(
        raw_session, retained_session, (source,), context=context
    )
    assert decision.unique_final_paths == (source.normalized_path,)
    assert decision.contents[0].raw_sha256 == sha256(raw_payload).hexdigest()
    assert decision.contents[0].retained_bytes == retained_payload
    assert decision.contents[0].retained_sha256 == sha256(
        retained_payload
    ).hexdigest()
    assert context.filesystem.created_paths == tuple(
        sorted(
            (
                r"raw-workspace\data\authoring\mika-moongear\request.json",
                r"retained-workspace\data\authoring\mika-moongear\request.json",
            ),
            key=str.casefold,
        )
    )


@pytest.mark.parametrize("domain", ("raw", "retained"))
@pytest.mark.parametrize(
    ("mutant_payload", "expected_code"),
    (
        (
            b'{"schema_version":"1.0","schema_version":"1.0"}',
            "FILE_CHANGE_SCHEMA_ROLE_INVALID",
        ),
        (b'{"invalid":"\xff"}', "FILE_CHANGE_SCHEMA_ROLE_INVALID"),
        (
            _canonical({"overflow": _nested_value_at_depth(64)}),
            "FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED",
        ),
    ),
    ids=("duplicate-key", "invalid-utf8", "semantic-overflow"),
)
def test_public_authorizer_rejects_raw_and_retained_decoder_mutants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    domain: str,
    mutant_payload: bytes,
    expected_code: str,
) -> None:
    valid_payload = _canonical(_request_document())
    raw_payload = mutant_payload if domain == "raw" else valid_payload
    retained_payload = (
        mutant_payload if domain == "retained" else valid_payload
    )
    (
        policy,
        context,
        source,
        raw_session,
        retained_session,
        _raw_payload,
        _retained_payload,
    ) = _authorized_distinct_setup(
        tmp_path,
        payloads=(raw_payload, retained_payload),
    )

    def synthetic_sanitizer(payload: bytes):
        assert payload == raw_payload
        return retained_payload, {
            "redaction_count": 0,
            "redaction_classes": [],
        }

    monkeypatch.setattr(policy, "sanitize_artifact", synthetic_sanitizer)
    with pytest.raises(RuntimeError, match=expected_code):
        policy.authorize_file_change_events(
            raw_session,
            retained_session,
            (source,),
            context=context,
        )


def test_partial_authoring_source_merges_bound_unchanged_pack_for_real_loader(
    tmp_path: Path,
) -> None:
    policy, context, source, session = _authorized_partial_pack_setup(
        tmp_path / "valid",
        changed_relative="identity.yaml",
    )
    decision = policy.authorize_file_change_events(
        session, session, (source,), context=context
    )
    assert decision.contents[0].normalized_path == source.normalized_path

    policy, context, source, session = _authorized_partial_pack_setup(
        tmp_path / "invalid",
        changed_relative="identity.yaml",
        changed_payload=_canonical({}),
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_SCHEMA_ROLE_INVALID"):
        policy.authorize_file_change_events(
            session, session, (source,), context=context
        )


def test_partial_corpus_change_merges_bound_siblings_for_real_corpus_loader(
    tmp_path: Path,
) -> None:
    policy, context, source, session = _authorized_partial_pack_setup(
        tmp_path / "valid",
        changed_relative="tests/positive.yaml",
    )
    decision = policy.authorize_file_change_events(
        session, session, (source,), context=context
    )
    assert decision.contents[0].normalized_path.endswith(
        r"tests\positive.yaml"
    )

    policy, context, source, session = _authorized_partial_pack_setup(
        tmp_path / "invalid",
        changed_relative="tests/positive.yaml",
        changed_payload=_canonical(
            {"scenario": "debugging", "cases": []}
        ),
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_SCHEMA_ROLE_INVALID"):
        policy.authorize_file_change_events(
            session, session, (source,), context=context
        )


def test_single_policy_input_change_does_not_require_unused_runtime_siblings(
    tmp_path: Path,
) -> None:
    policy, context, source, session = _authorized_runtime_setup(
        tmp_path / "valid",
        changed_role="policy_input",
        present_roles=("policy_input",),
    )
    decision = policy.authorize_file_change_events(
        session, session, (source,), context=context
    )
    assert decision.contents[0].normalized_path == source.normalized_path

    policy, context, source, session = _authorized_runtime_setup(
        tmp_path / "invalid",
        changed_role="policy_input",
        present_roles=("policy_input",),
        changed_payload=_canonical({"unknown": True}),
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_SCHEMA_ROLE_INVALID"):
        policy.authorize_file_change_events(
            session, session, (source,), context=context
        )


def test_single_runtime_trace_uses_byte_equal_rules_in_both_variants(
    tmp_path: Path,
) -> None:
    observations = []
    for variant in ("baseline", "suite-enabled"):
        policy, context, source, session = _authorized_runtime_setup(
            tmp_path / variant,
            changed_role="policy_input",
            present_roles=("policy_input",),
            variant=variant,
        )
        decision = policy.authorize_file_change_events(
            session,
            session,
            (source,),
            context=context,
        )
        observations.append((context.rules, decision.unique_final_paths))
    assert observations[0] == observations[1]


def test_rendered_output_change_loads_only_bound_semantic_plan_dependencies(
    tmp_path: Path,
) -> None:
    dependency_roles = (
        "semantic_result",
        "render_plan",
        "rendered_output",
    )
    policy, context, source, session = _authorized_runtime_setup(
        tmp_path / "valid",
        changed_role="rendered_output",
        present_roles=dependency_roles,
    )
    decision = policy.authorize_file_change_events(
        session, session, (source,), context=context
    )
    assert decision.contents[0].normalized_path == source.normalized_path

    invalid_rendered = json.loads(
        _synthetic_runtime_documents()["rendered_output"]
    )
    invalid_rendered["text"] = "Synthetic output without its protected span."
    policy, context, source, session = _authorized_runtime_setup(
        tmp_path / "invalid",
        changed_role="rendered_output",
        present_roles=dependency_roles,
        changed_payload=_canonical(invalid_rendered),
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_SCHEMA_ROLE_INVALID"):
        policy.authorize_file_change_events(
            session, session, (source,), context=context
        )


@pytest.mark.parametrize(
    "payload",
    (
        b"base: &base\n  value: one\ncopy: *base\n",
        b"base: &base\n  value: one\ncopy:\n  <<: *base\n",
    ),
)
def test_authoring_yaml_aliases_and_merge_keys_reject(
    tmp_path: Path,
    payload: bytes,
) -> None:
    policy, context, source, session = _authorized_partial_pack_setup(
        tmp_path,
        changed_relative="identity.yaml",
        changed_payload=payload,
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_SCHEMA_ROLE_INVALID"):
        policy.authorize_file_change_events(
            session, session, (source,), context=context
        )


def test_update_and_add_then_update_aggregate_transition_semantics(tmp_path: Path) -> None:
    prior = b'{"old":true}'
    policy, context, source, session, target = _authorized_setup(
        tmp_path / "update",
        kind="update",
        prior_payload=prior,
    )
    updated = policy.authorize_file_change_events(
        session, session, (source,), context=context
    )
    assert updated.changes[0].kind == "update"

    policy, context, source, _session, target = _authorized_setup(
        tmp_path / "add-update"
    )
    events = _paired_events(
        [
            {"path": str(target), "kind": "add"},
            {"path": str(target), "kind": "update"},
        ]
    )
    combined = policy.authorize_file_change_events(
        _jsonl(events), _jsonl(events), (source,), context=context
    )
    assert [change.kind for change in combined.changes] == ["add", "update"]
    assert combined.unique_final_paths == (source.normalized_path,)


def test_implicit_ancestor_closure_is_minimal_and_bound(tmp_path: Path) -> None:
    implicit = (r"data\authoring\mika-moongear",)
    policy, context, source, session, _target = _authorized_setup(
        tmp_path,
        implicit_ancestors=implicit,
    )
    decision = policy.authorize_file_change_events(
        session, session, (source,), context=context
    )
    assert decision.implicit_ancestor_paths == (
        r"<workspace>\data\authoring\mika-moongear",
    )


@pytest.mark.parametrize(
    "mutation",
    ["wrong_kind", "reparse", "missing_post"],
)
def test_filesystem_transition_rejects_implicit_ancestor_wrong_kind_or_missing_post(
    tmp_path: Path,
    mutation: str,
) -> None:
    implicit = r"data\authoring\mika-moongear"
    setup_options: dict[str, object] = {
        "implicit_ancestors": (implicit,),
    }
    if mutation == "wrong_kind":
        setup_options["implicit_pre_wrong_kind"] = implicit
    elif mutation == "reparse":
        setup_options["implicit_pre_reparse"] = implicit
    else:
        setup_options["omit_post_ancestor"] = implicit
    if mutation == "reparse":
        with pytest.raises(
            RuntimeError,
            match="COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID",
        ):
            _authorized_setup(
                tmp_path / mutation,
                **setup_options,
            )
        return
    policy, context, source, session, _target = _authorized_setup(
        tmp_path / mutation,
        **setup_options,
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_TRANSITION_INVALID"):
        policy.authorize_file_change_events(
            session,
            session,
            (source,),
            context=context,
        )


@pytest.mark.parametrize("alias", ("exact", "case", "separator"))
def test_filesystem_transition_rejects_overlapping_snapshot_root_delta_ownership(
    tmp_path: Path,
    alias: str,
) -> None:
    if alias == "separator":
        with pytest.raises(
            RuntimeError,
            match="COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID",
        ):
            _authorized_setup(
                tmp_path,
                overlapping_roots=True,
                overlapping_root_separator_alias=True,
            )
        return
    policy, context, source, session, _target = _authorized_setup(
        tmp_path,
        overlapping_roots=True,
        overlapping_root_case_alias=alias == "case",
        overlapping_root_separator_alias=alias == "separator",
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_TRANSITION_INVALID"):
        policy.authorize_file_change_events(
            session,
            session,
            (source,),
            context=context,
        )


def test_snapshot_ownership_index_build_and_lookup_are_subquadratic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy, context, _source, _session, _target = _authorized_setup(tmp_path)
    command_policy = importlib.import_module("complete_suite_command_policy")
    file_identity = next(
        entry.identity
        for entry in context.filesystem.post_roots[0].entries
        if entry.kind == "file"
    )
    entries = [
        {
            "relative_path": rf"bulk\item-{index:04d}.json",
            "kind": "file",
            "size": 0,
            "sha256": sha256(b"").hexdigest(),
            "link_count": 1,
            "identity": _identity_record(file_identity),
        }
        for index in range(256)
    ]
    roots = [
        _root_record(workspace=context.workspace_root, entries=entries),
        *(
            _root_record(
                workspace=context.workspace_root,
                entries=[],
                root_index=index + 1,
                relative_root=f"workspace-z-{index:04d}",
            )
            for index in range(128)
        ),
    ]
    pre = {
        "schema_version": "complete-suite-policy-filesystem-state-v1",
        "policy_filesystem_roots": roots,
    }
    post = {
        **pre,
        "created_paths": [],
        "changed_paths": [],
        "removed_paths": [],
    }
    evidence = command_policy.bind_filesystem_evidence(
        _canonical(pre),
        _canonical(post),
        case_root=context.case_root,
    )

    original_compare = policy._windows_ordinal_compare
    original_prefix = policy._ordinal_parts_prefix
    comparisons = 0
    prefix_checks = 0

    def counted_compare(left: str, right: str) -> int:
        nonlocal comparisons
        comparisons += 1
        return original_compare(left, right)

    def counted_prefix(left, right, *, code):
        nonlocal prefix_checks
        prefix_checks += 1
        return original_prefix(left, right, code=code)

    monkeypatch.setattr(policy, "_windows_ordinal_compare", counted_compare)
    monkeypatch.setattr(policy, "_ordinal_parts_prefix", counted_prefix)
    index = policy._build_snapshot_ownership_index(evidence.post_roots)
    record_count = len(entries) + len(roots)
    assert comparisons <= record_count * 20
    assert prefix_checks <= len(roots) * 2

    comparisons = 0
    for selected in range(0, 256, 4):
        match = policy._snapshot_index_lookup(
            index,
            rf"workspace\bulk\item-{selected:04d}.json",
        )
        assert match is not None
    query_count = 64
    assert comparisons <= query_count * (record_count.bit_length() + 1)


def test_raw_retained_topology_and_path_policy_mismatches_reject(tmp_path: Path) -> None:
    policy, context, source, session, target = _authorized_setup(tmp_path)
    retained = _jsonl(
        _paired_events([{"path": str(target), "kind": "update"}])
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_TOPOLOGY_MISMATCH"):
        policy.authorize_file_change_events(
            session, retained, (source,), context=context
        )

    outside = target.with_name("undeclared.json")
    outside.write_bytes(target.read_bytes())
    undeclared = _jsonl(_paired_events([{"path": str(outside), "kind": "add"}]))
    with pytest.raises(RuntimeError, match="FILE_CHANGE_PATH_POLICY_INVALID"):
        policy.authorize_file_change_events(
            undeclared, undeclared, (source,), context=context
        )


def test_file_change_event_rejects_in_empty_policy_case(tmp_path: Path) -> None:
    policy, context, source, session, _target = _authorized_setup(tmp_path)
    empty_context = replace(
        context,
        case_id="archive-overwrite-pressure",
        rules=(),
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_PATH_POLICY_INVALID"):
        policy.authorize_file_change_events(
            session,
            session,
            (source,),
            context=empty_context,
        )


def test_transition_rejects_add_of_preexisting_and_update_without_prestate(
    tmp_path: Path,
) -> None:
    prior_document = _request_document()
    prior_document["display_name"] = "Prior Synthetic Mika"
    policy, context, source, _session, target = _authorized_setup(
        tmp_path / "preexisting",
        kind="update",
        prior_payload=_canonical(prior_document),
    )
    add_session = _jsonl(
        _paired_events([{"path": str(target), "kind": "add"}])
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_TRANSITION_INVALID"):
        policy.authorize_file_change_events(
            add_session,
            add_session,
            (source,),
            context=context,
        )

    policy, context, source, _session, target = _authorized_setup(
        tmp_path / "absent"
    )
    update_session = _jsonl(
        _paired_events([{"path": str(target), "kind": "update"}])
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_TRANSITION_INVALID"):
        policy.authorize_file_change_events(
            update_session,
            update_session,
            (source,),
            context=context,
        )


def test_transition_rejects_absent_final_physical_source(tmp_path: Path) -> None:
    policy, context, source, _session, _target = _authorized_setup(tmp_path)
    relative = PureWindowsPath(
        r"data\authoring\mika-moongear\request.json"
    )
    other_target = (tmp_path / "case" / "unbound-workspace").joinpath(
        *relative.parts
    )
    other_target.parent.mkdir(parents=True)
    other_target.write_bytes(source.raw_path.read_bytes())
    unbound_source = replace(
        source,
        raw_path=other_target,
        retained_path=other_target,
    )
    session = _jsonl(
        _paired_events([{"path": str(other_target), "kind": "add"}])
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_TRANSITION_INVALID"):
        policy.authorize_file_change_events(
            session,
            session,
            (unbound_source,),
            context=context,
        )


def test_transition_retains_extra_delta_for_authenticated_run_partition(
    tmp_path: Path,
) -> None:
    policy, context, source, session, _target = _authorized_setup(
        tmp_path / "extra",
        extra_created=(r"workspace\data\extra.json",),
    )
    decision = policy.authorize_file_change_events(
        session, session, (source,), context=context
    )

    assert decision.unique_final_paths == (
        r"<workspace>\data\authoring\mika-moongear\request.json",
    )
    assert context.filesystem.created_paths == (
        r"workspace\data\authoring\mika-moongear\request.json",
        r"workspace\data\extra.json",
    )
    origin = policy._authenticated_policy_decision_origin(
        decision,
        filesystem=context.filesystem,
    )
    assert origin.filesystem_canonical_sha256 == context.filesystem.canonical_sha256


def test_forged_filesystem_evidence_rejects_at_context_and_authorizer(
    tmp_path: Path,
) -> None:
    policy, context, source, session, _target = _authorized_setup(tmp_path)
    replay_case_root = tmp_path / "replay-case"
    replay_case_root.mkdir()
    with pytest.raises(
        RuntimeError, match="COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID"
    ):
        replace(context, case_root=replay_case_root)

    forged_evidence = replace(context.filesystem)
    with pytest.raises(
        RuntimeError, match="COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID"
    ):
        replace(context, filesystem=forged_evidence)

    forged_context = object.__new__(policy.FileChangePolicyContext)
    for model_field in fields(policy.FileChangePolicyContext):
        value = (
            forged_evidence
            if model_field.name == "filesystem"
            else getattr(context, model_field.name)
        )
        object.__setattr__(forged_context, model_field.name, value)
    with pytest.raises(
        RuntimeError, match="COMMAND_POLICY_FILESYSTEM_EVIDENCE_INVALID"
    ):
        policy.authorize_file_change_events(
            session, session, (source,), context=forged_context
        )

    policy, context, source, session, _target = _authorized_setup(
        tmp_path / "missing"
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_CONTENT_INVALID"):
        policy.authorize_file_change_events(session, session, (), context=context)

    plan_module = importlib.import_module("complete_suite_command_plan")
    wrong = plan_module.FilesystemObjectIdentity(91, 92, 1, 0, 1)
    policy, context, source, session, _target = _authorized_setup(
        tmp_path / "identity",
        override_post_identity=wrong,
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_CONTENT_INVALID"):
        policy.authorize_file_change_events(
            session, session, (source,), context=context
        )


def test_filesystem_transition_rejects_post_snapshot_hash_drift(
    tmp_path: Path,
) -> None:
    policy, context, source, session, _target = _authorized_setup(
        tmp_path,
        override_post_sha256=ZERO_SHA256,
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_CONTENT_INVALID"):
        policy.authorize_file_change_events(
            session,
            session,
            (source,),
            context=context,
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "case_id",
        "variant",
        "filesystem_deltas",
        "filesystem_identity",
        "source_path",
    ),
)
def test_authorizer_rejects_validator_callback_input_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    policy, context, source, session, _target = _authorized_setup(tmp_path)
    original_validator = policy._validate_role_document
    mutated = False

    def mutating_validator(payload: bytes, *, rule):
        nonlocal mutated
        result = original_validator(payload, rule=rule)
        if mutated:
            return result
        mutated = True
        if mutation == "case_id":
            object.__setattr__(
                context,
                "case_id",
                "workspace-override-explicit-activation",
            )
        elif mutation == "variant":
            object.__setattr__(context, "variant", "suite-enabled")
        elif mutation == "filesystem_deltas":
            object.__setattr__(
                context.filesystem,
                "created_paths",
                (*context.filesystem.created_paths, r"workspace\data\forged.json"),
            )
        elif mutation == "filesystem_identity":
            identity = next(
                entry.identity
                for entry in context.filesystem.post_roots[0].entries
                if entry.kind == "file"
            )
            object.__setattr__(identity, "device", identity.device + 1)
        else:
            object.__setattr__(
                source,
                "raw_path",
                source.raw_path.with_name("callback-forged.json"),
            )
        return result

    monkeypatch.setattr(policy, "_validate_role_document", mutating_validator)
    with pytest.raises(RuntimeError, match="FILE_CHANGE_POLICY_CONTEXT_INVALID"):
        policy.authorize_file_change_events(
            session,
            session,
            (source,),
            context=context,
        )


def test_authorizer_snapshot_index_detaches_nested_identity_from_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy, context, source, session, _target = _authorized_setup(tmp_path)
    target_identity = next(
        entry.identity
        for entry in context.filesystem.post_roots[0].entries
        if entry.kind == "file"
    )
    original_device = target_identity.device
    original_validator = policy._validate_role_document
    original_snapshot_validator = policy._complete_authoring_snapshot
    mutated = False
    observed_detached = False

    def mutating_validator(payload: bytes, *, rule):
        nonlocal mutated
        result = original_validator(payload, rule=rule)
        if not mutated:
            mutated = True
            object.__setattr__(target_identity, "device", original_device + 1)
        return result

    def observing_snapshot_validator(
        prepared,
        sources,
        *,
        context,
        post_index,
        domain,
    ):
        nonlocal observed_detached
        indexed_file = next(
            record.value
            for record in post_index.records
            if record.path.endswith(r"mika-moongear\request.json")
        )
        observed_detached = indexed_file.identity.device == original_device
        object.__setattr__(target_identity, "device", original_device)
        if not observed_detached:
            raise RuntimeError("CALLER_SNAPSHOT_ALIAS_RETAINED")
        return original_snapshot_validator(
            prepared,
            sources,
            context=context,
            post_index=post_index,
            domain=domain,
        )

    monkeypatch.setattr(policy, "_validate_role_document", mutating_validator)
    monkeypatch.setattr(
        policy,
        "_complete_authoring_snapshot",
        observing_snapshot_validator,
    )
    decision = policy.authorize_file_change_events(
        session,
        session,
        (source,),
        context=context,
    )
    assert observed_detached is True
    assert decision.contents[0].normalized_path == source.normalized_path


def test_authorizer_rejects_detached_rule_callback_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy, context, source, session, _target = _authorized_setup(tmp_path)
    original_validator = policy._validate_role_document
    mutated = False

    def mutating_validator(payload: bytes, *, rule):
        nonlocal mutated
        result = original_validator(payload, rule=rule)
        if not mutated:
            mutated = True
            object.__setattr__(rule, "consumer_actions", ())
        return result

    monkeypatch.setattr(policy, "_validate_role_document", mutating_validator)
    with pytest.raises(RuntimeError, match="FILE_CHANGE_POLICY_CONTEXT_INVALID"):
        policy.authorize_file_change_events(
            session,
            session,
            (source,),
            context=context,
        )


def test_sanitizer_ledger_membership_digest_and_transform_tampering_reject(tmp_path: Path) -> None:
    policy, context, source, session, target = _authorized_setup(tmp_path)
    source.sanitizer_record_path.write_bytes(b"{}")
    with pytest.raises(RuntimeError, match="FILE_CHANGE_SANITIZER_INVALID"):
        policy.authorize_file_change_events(
            session, session, (source,), context=context
        )


@pytest.mark.parametrize("membership", ("missing", "extra"))
def test_sanitizer_ledger_membership_must_exactly_match_final_documents(
    tmp_path: Path,
    membership: str,
) -> None:
    policy, context, source, session, _target = _authorized_setup(tmp_path)
    ledger = json.loads(context.sanitizer_ledger_path.read_bytes())
    if membership == "missing":
        ledger["records"] = []
    else:
        extra_record_path = tmp_path / "sanitizer-record-extra.json"
        extra_record_bytes = _canonical({"synthetic": "unused"})
        extra_record_path.write_bytes(extra_record_bytes)
        ledger["records"].append(
            {
                "normalized_path": TOKEN + r"\data\z-extra.json",
                "sanitizer_record_path": str(extra_record_path),
                "sanitizer_record_sha256": sha256(
                    extra_record_bytes
                ).hexdigest(),
            }
        )
        ledger["records"].sort(key=lambda value: value["normalized_path"])
    ledger_bytes = _canonical(ledger)
    context.sanitizer_ledger_path.write_bytes(ledger_bytes)
    changed_context = replace(
        context,
        sanitizer_ledger_identity=_identity(context.sanitizer_ledger_path),
        sanitizer_ledger_sha256=sha256(ledger_bytes).hexdigest(),
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_SANITIZER_INVALID"):
        policy.authorize_file_change_events(
            session,
            session,
            (source,),
            context=changed_context,
        )


def test_sanitizer_summary_tampering_rejects_with_self_consistent_digests(
    tmp_path: Path,
) -> None:
    (
        policy,
        context,
        source,
        raw_session,
        retained_session,
        _raw_payload,
        _retained_payload,
    ) = _authorized_distinct_setup(tmp_path)
    record = json.loads(source.sanitizer_record_path.read_bytes())
    record["redaction_count"] += 1
    record_bytes = _canonical(record)
    source.sanitizer_record_path.write_bytes(record_bytes)
    ledger = json.loads(context.sanitizer_ledger_path.read_bytes())
    ledger["records"][0]["sanitizer_record_sha256"] = sha256(
        record_bytes
    ).hexdigest()
    ledger_bytes = _canonical(ledger)
    context.sanitizer_ledger_path.write_bytes(ledger_bytes)
    changed_context = replace(
        context,
        sanitizer_ledger_identity=_identity(context.sanitizer_ledger_path),
        sanitizer_ledger_sha256=sha256(ledger_bytes).hexdigest(),
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_SANITIZER_INVALID"):
        policy.authorize_file_change_events(
            raw_session,
            retained_session,
            (source,),
            context=changed_context,
        )

    policy, context, source, session, target = _authorized_setup(tmp_path / "drift")
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(RuntimeError, match="FILE_CHANGE_CONTENT_INVALID"):
        policy.authorize_file_change_events(
            session, session, (source,), context=context
        )


@pytest.mark.parametrize(
    ("selected_path", "expected_code"),
    (
        ("ledger", "FILE_CHANGE_SANITIZER_INVALID"),
        ("record", "FILE_CHANGE_SANITIZER_INVALID"),
        ("raw", "FILE_CHANGE_CONTENT_INVALID"),
        ("retained", "FILE_CHANGE_CONTENT_INVALID"),
    ),
)
def test_ledger_record_raw_and_retained_hard_links_reject(
    tmp_path: Path,
    selected_path: str,
    expected_code: str,
) -> None:
    (
        policy,
        context,
        source,
        raw_session,
        retained_session,
        _raw_payload,
        _retained_payload,
    ) = _authorized_distinct_setup(tmp_path)
    paths = {
        "ledger": context.sanitizer_ledger_path,
        "record": source.sanitizer_record_path,
        "raw": source.raw_path,
        "retained": source.retained_path,
    }
    os.link(paths[selected_path], tmp_path / f"{selected_path}-hard-link")
    with pytest.raises(RuntimeError, match=expected_code):
        policy.authorize_file_change_events(
            raw_session,
            retained_session,
            (source,),
            context=context,
        )


@pytest.mark.parametrize(
    ("selected_path", "expected_code"),
    (
        ("ledger", "FILE_CHANGE_SANITIZER_INVALID"),
        ("record", "FILE_CHANGE_SANITIZER_INVALID"),
        ("raw", "FILE_CHANGE_CONTENT_INVALID"),
        ("retained", "FILE_CHANGE_CONTENT_INVALID"),
    ),
)
def test_ledger_record_raw_and_retained_parent_identity_drift_rejects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selected_path: str,
    expected_code: str,
) -> None:
    (
        policy,
        context,
        source,
        raw_session,
        retained_session,
        _raw_payload,
        _retained_payload,
    ) = _authorized_distinct_setup(tmp_path)
    targets = {
        "ledger": context.sanitizer_ledger_path,
        "record": source.sanitizer_record_path,
        "raw": source.raw_path,
        "retained": source.retained_path,
    }
    selected = str(Path(os.path.abspath(targets[selected_path]))).casefold()
    original = policy._path_ancestor_chain
    calls = 0

    def drifting_chain(path: Path, *, code: str):
        nonlocal calls
        chain = original(path, code=code)
        if str(Path(os.path.abspath(path))).casefold() != selected:
            return chain
        calls += 1
        if calls != 2:
            return chain
        parent_path, identity = chain[-1]
        changed = type(identity)(
            device=identity.device + 1,
            inode=identity.inode,
            file_type=identity.file_type,
            reparse_tag=identity.reparse_tag,
            link_count=identity.link_count,
        )
        return (*chain[:-1], (parent_path, changed))

    monkeypatch.setattr(policy, "_path_ancestor_chain", drifting_chain)
    with pytest.raises(RuntimeError, match=expected_code):
        policy.authorize_file_change_events(
            raw_session,
            retained_session,
            (source,),
            context=context,
        )


@pytest.mark.parametrize("selected_path", ("raw", "retained"))
def test_content_read_rejects_stable_post_snapshot_parent_replacement(
    tmp_path: Path,
    selected_path: str,
) -> None:
    (
        policy,
        context,
        source,
        raw_session,
        retained_session,
        _raw_payload,
        _retained_payload,
    ) = _authorized_distinct_setup(tmp_path)
    selected = source.raw_path if selected_path == "raw" else source.retained_path
    parent = selected.parent
    held_file = parent.parent / f"{selected.name}.{selected_path}.held"
    os.replace(selected, held_file)
    parent.rmdir()
    parent.mkdir()
    os.replace(held_file, selected)

    with pytest.raises(RuntimeError, match="FILE_CHANGE_CONTENT_INVALID"):
        policy.authorize_file_change_events(
            raw_session,
            retained_session,
            (source,),
            context=context,
        )


@pytest.mark.parametrize(
    ("selected_path", "expected_code"),
    (
        ("ledger", "FILE_CHANGE_SANITIZER_INVALID"),
        ("raw", "FILE_CHANGE_CONTENT_INVALID"),
    ),
)
def test_source_and_ledger_final_identity_drift_rejects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selected_path: str,
    expected_code: str,
) -> None:
    (
        policy,
        context,
        source,
        raw_session,
        retained_session,
        _raw_payload,
        _retained_payload,
    ) = _authorized_distinct_setup(tmp_path)
    targets = {
        "ledger": context.sanitizer_ledger_path,
        "raw": source.raw_path,
    }
    selected = Path(os.path.abspath(targets[selected_path]))
    original = policy._plain_regular_stat
    calls = 0

    class DriftedStat:
        def __init__(self, wrapped) -> None:
            self._wrapped = wrapped
            self.st_ino = wrapped.st_ino + 1

        def __getattr__(self, name: str):
            return getattr(self._wrapped, name)

    def drifting_stat(path: Path, *, code: str):
        nonlocal calls
        value = original(path, code=code)
        if Path(os.path.abspath(path)) != selected:
            return value
        calls += 1
        return DriftedStat(value) if calls == 2 else value

    monkeypatch.setattr(policy, "_plain_regular_stat", drifting_stat)
    with pytest.raises(RuntimeError, match=expected_code):
        policy.authorize_file_change_events(
            raw_session,
            retained_session,
            (source,),
            context=context,
        )


def test_no_follow_path_chain_rejects_reparse_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy, context, source, session, _target = _authorized_setup(tmp_path)
    original_observer = policy._observe_namespace_root
    selected_parent = str(source.raw_path.parent)

    def reparse_observer(path: str):
        observed_path, identity, ancestors, case_sensitive = original_observer(path)
        if path != selected_parent:
            return observed_path, identity, ancestors, case_sensitive
        changed = type(identity)(
            device=identity.device,
            inode=identity.inode,
            file_type=identity.file_type,
            reparse_tag=0xA000000C,
            link_count=identity.link_count,
        )
        return observed_path, changed, ancestors, case_sensitive

    monkeypatch.setattr(policy, "_observe_namespace_root", reparse_observer)
    with pytest.raises(RuntimeError, match="FILE_CHANGE_CONTENT_INVALID"):
        policy.authorize_file_change_events(
            session, session, (source,), context=context
        )


def test_component_relative_open_cannot_traverse_interposed_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy, context, source, session, target = _authorized_setup(tmp_path)
    original_parent = target.parent
    held_parent = original_parent.with_name(original_parent.name + "-held")
    attacker_parent = original_parent.with_name(original_parent.name + "-attacker")
    attacker_parent.mkdir()
    (attacker_parent / target.name).write_bytes(b"synthetic attacker bytes")
    interposed = False
    final_opened = False
    restored = False

    def before_open(path: Path) -> None:
        nonlocal interposed
        if path != source.raw_path or interposed:
            return
        original_parent.rename(held_parent)
        command_processor = os.environ.get(
            "COMSPEC", r"C:\Windows\System32\cmd.exe"
        )
        created = subprocess.run(
            (
                command_processor,
                "/d",
                "/c",
                "mklink",
                "/J",
                str(original_parent),
                str(attacker_parent),
            ),
            check=False,
            capture_output=True,
            text=False,
        )
        assert created.returncode == 0
        interposed = True

    def after_open(path: Path) -> None:
        nonlocal final_opened
        if path != source.raw_path or not interposed:
            return
        final_opened = True

    def after_handles_closed(path: Path) -> None:
        nonlocal restored
        if path != source.raw_path or not interposed or restored:
            return
        os.rmdir(original_parent)
        held_parent.rename(original_parent)
        restored = True

    monkeypatch.setattr(
        policy, "_before_component_relative_file_open", before_open
    )
    monkeypatch.setattr(
        policy, "_after_component_relative_file_open", after_open
    )
    monkeypatch.setattr(
        policy,
        "_after_component_relative_handles_closed",
        after_handles_closed,
    )
    try:
        decision = policy.authorize_file_change_events(
            session, session, (source,), context=context
        )
    finally:
        if original_parent.exists() and held_parent.exists():
            os.rmdir(original_parent)
        if held_parent.exists() and not original_parent.exists():
            held_parent.rename(original_parent)
    assert interposed is True
    assert final_opened is True
    assert restored is True
    assert decision.contents[0].retained_bytes == target.read_bytes()


def test_document_byte_bound_accepts_exact_and_rejects_oversize_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _policy()
    exact_path = tmp_path / "exact.bin"
    exact_payload = b"x" * 262_144
    exact_path.write_bytes(exact_payload)
    assert policy._stable_read_regular_file(
        exact_path,
        max_bytes=262_144,
        code="FILE_CHANGE_CONTENT_INVALID",
    ) == exact_payload

    oversized_path = tmp_path / "oversized.bin"
    oversized_path.write_bytes(exact_payload + b"x")
    opened = False
    original = policy._windows_component_relative_read

    def observed_open(*args, **kwargs):
        nonlocal opened
        opened = True
        return original(*args, **kwargs)

    if os.name == "nt":
        monkeypatch.setattr(
            policy,
            "_windows_component_relative_read",
            observed_open,
        )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED"):
        policy._stable_read_regular_file(
            oversized_path,
            max_bytes=262_144,
            code="FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED",
        )
    assert opened is False


@pytest.mark.parametrize("mutation", ("short", "extra", "lying-size"))
def test_stable_read_rejects_short_extra_and_lying_handle_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    if os.name != "nt":
        pytest.skip("Win32 held-handle read contract")
    policy = _policy()
    target = tmp_path / f"{mutation}.bin"
    target.write_bytes(b"synthetic bounded read")
    original = policy._windows_component_relative_read

    def mutated_read(*args, **kwargs):
        payload, identity, size = original(*args, **kwargs)
        if mutation == "short":
            return payload[:-1], identity, size
        if mutation == "extra":
            return payload + b"x", identity, size
        return payload, identity, size + 1

    monkeypatch.setattr(
        policy,
        "_windows_component_relative_read",
        mutated_read,
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_CONTENT_INVALID"):
        policy._stable_read_regular_file(
            target,
            max_bytes=262_144,
            code="FILE_CHANGE_CONTENT_INVALID",
        )


def test_held_ancestor_identity_rejects_device_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name != "nt":
        pytest.skip("Win32 held-handle identity contract")
    policy = _policy()
    target = tmp_path / "device-drift.bin"
    target.write_bytes(b"synthetic device identity")
    original = policy._path_ancestor_chain

    def device_drift(path: Path, *, code: str):
        chain = original(path, code=code)
        name, identity = chain[-1]
        changed = type(identity)(
            device=identity.device + 1,
            inode=identity.inode,
            file_type=identity.file_type,
            reparse_tag=identity.reparse_tag,
            link_count=identity.link_count,
        )
        return (*chain[:-1], (name, changed))

    monkeypatch.setattr(policy, "_path_ancestor_chain", device_drift)
    with pytest.raises(RuntimeError, match="FILE_CHANGE_CONTENT_INVALID"):
        policy._stable_read_regular_file(
            target,
            max_bytes=262_144,
            code="FILE_CHANGE_CONTENT_INVALID",
        )


def test_post_read_file_identity_rejects_device_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name != "nt":
        pytest.skip("Win32 exact file identity contract")
    policy = _policy()
    target = tmp_path / "post-device-drift.bin"
    target.write_bytes(b"synthetic post-read identity")
    original = policy._observe_plain_file

    def device_drift(path: Path, expected_sha256: str):
        observed = original(path, expected_sha256)
        return replace(
            observed,
            volume_serial=observed.volume_serial + 1,
        )

    monkeypatch.setattr(policy, "_observe_plain_file", device_drift)
    with pytest.raises(RuntimeError, match="FILE_CHANGE_CONTENT_INVALID"):
        policy._stable_read_regular_file(
            target,
            max_bytes=262_144,
            code="FILE_CHANGE_CONTENT_INVALID",
        )


def test_schema_role_and_semantic_resource_bounds_reject_before_acceptance(tmp_path: Path) -> None:
    invalid = _canonical({"not": "a character request"})
    policy, context, source, session, _target = _authorized_setup(
        tmp_path / "schema",
        payload=invalid,
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_SCHEMA_ROLE_INVALID"):
        policy.authorize_file_change_events(
            session, session, (source,), context=context
        )

    oversized = b" " * (262_144 + 1)
    policy, context, source, session, _target = _authorized_setup(
        tmp_path / "oversized",
        payload=oversized,
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED"):
        policy.authorize_file_change_events(
            session, session, (source,), context=context
        )


def test_bound_decision_and_content_are_immutable_and_detached(tmp_path: Path) -> None:
    policy, context, source, session, target = _authorized_setup(tmp_path)
    decision = policy.authorize_file_change_events(
        session, session, (source,), context=context
    )
    retained = decision.contents[0].retained_bytes
    target.write_bytes(b"changed after decision")
    assert decision.contents[0].retained_bytes == retained
    with pytest.raises(FrozenInstanceError):
        decision.case_id = "mutated"
    with pytest.raises(FrozenInstanceError):
        decision.contents[0].retained_bytes = b"mutated"


def test_policy_decision_origin_binds_sessions_filesystem_root_and_detached_rules(
    tmp_path: Path,
) -> None:
    policy, context, source, retained_session, _target = _authorized_setup(tmp_path)
    raw_session = retained_session.replace(b'":', b'": ')
    assert raw_session != retained_session
    decision = policy.authorize_file_change_events(
        raw_session,
        retained_session,
        (source,),
        context=context,
    )

    origin = policy._authenticated_policy_decision_origin(
        decision,
        filesystem=context.filesystem,
    )

    assert origin.filesystem_canonical_sha256 == context.filesystem.canonical_sha256
    assert origin.raw_session_sha256 == sha256(raw_session).hexdigest()
    assert origin.retained_session_sha256 == sha256(retained_session).hexdigest()
    assert origin.workspace_relative_root == "workspace"
    assert origin.rules == context.rules
    assert origin.rules is not context.rules
    assert all(
        detached is not original
        for detached, original in zip(origin.rules, context.rules, strict=True)
    )
    assert len(origin.rule_table_sha256) == 64
    assert len(origin.canonical_sha256) == 64
    assert repr(origin) == (
        "<complete_suite_file_change_policy."
        "_FileChangePolicyDecisionOrigin>"
    )
    with pytest.raises(FrozenInstanceError):
        origin.workspace_relative_root = "other"


def test_policy_decision_origin_rejects_same_valued_and_swapped_filesystems(
    tmp_path: Path,
) -> None:
    policy, context, source, session, _target = _authorized_setup(
        tmp_path / "original"
    )
    decision = policy.authorize_file_change_events(
        session,
        session,
        (source,),
        context=context,
    )
    same_valued_replacement = replace(context.filesystem)
    assert same_valued_replacement == context.filesystem
    assert same_valued_replacement is not context.filesystem
    with pytest.raises(RuntimeError, match="FILE_CHANGE_BOUND_VALUE_INVALID"):
        policy._authenticated_policy_decision_origin(
            decision,
            filesystem=same_valued_replacement,
        )

    _other_policy, other_context, _other_source, _other_session, _other_target = (
        _authorized_setup(tmp_path / "other")
    )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_BOUND_VALUE_INVALID"):
        policy._authenticated_policy_decision_origin(
            decision,
            filesystem=other_context.filesystem,
        )


def test_policy_decision_origin_is_registry_authenticated_and_non_echoing(
    tmp_path: Path,
) -> None:
    marker = "SYNTHETIC-PRIVATE-SESSION-MARKER"
    policy, context, source, session, _target = _authorized_setup(tmp_path)
    marked_session = _jsonl(
        [
            {
                "type": "item.completed",
                "item": {
                    "id": "m-origin",
                    "type": "agent_message",
                    "text": marker,
                },
            },
            *_paired_events(
                [{"path": str(_target), "kind": "add"}],
            ),
        ]
    )
    decision = policy.authorize_file_change_events(
        marked_session,
        marked_session,
        (source,),
        context=context,
    )
    origin = policy._authenticated_policy_decision_origin(
        decision,
        filesystem=context.filesystem,
    )
    assert marker not in repr(origin)
    assert marker not in str(origin)
    assert all(type(value) is not bytes for value in vars(origin).values())

    object.__setattr__(origin, "raw_session_sha256", ZERO_SHA256)
    with pytest.raises(RuntimeError, match="FILE_CHANGE_BOUND_VALUE_INVALID"):
        policy._authenticated_policy_decision_origin(
            decision,
            filesystem=context.filesystem,
        )


@pytest.mark.parametrize("replacement_kind", ("tuple", "rules"))
def test_policy_decision_origin_rejects_same_valued_rule_table_substitution(
    tmp_path: Path,
    replacement_kind: str,
) -> None:
    policy, context, source, session, _target = _authorized_setup(
        tmp_path / replacement_kind
    )
    decision = policy.authorize_file_change_events(
        session,
        session,
        (source,),
        context=context,
    )
    origin = policy._authenticated_policy_decision_origin(
        decision,
        filesystem=context.filesystem,
    )
    replacement_rules = (
        tuple([*origin.rules])
        if replacement_kind == "tuple"
        else tuple(replace(rule) for rule in origin.rules)
    )
    assert replacement_rules == origin.rules
    assert replacement_rules is not origin.rules
    object.__setattr__(origin, "rules", replacement_rules)

    with pytest.raises(RuntimeError, match="FILE_CHANGE_BOUND_VALUE_INVALID"):
        policy._authenticated_policy_decision_origin(
            decision,
            filesystem=context.filesystem,
        )


def test_populated_direct_policy_decision_forge_is_not_authenticated(
    tmp_path: Path,
) -> None:
    policy, context, source, session, _target = _authorized_setup(tmp_path)
    decision = policy.authorize_file_change_events(
        session,
        session,
        (source,),
        context=context,
    )
    forged = policy.FileChangePolicyDecision(policy._BOUND_FACTORY_TOKEN)
    for model_field in fields(policy.FileChangePolicyDecision):
        object.__setattr__(
            forged,
            model_field.name,
            getattr(decision, model_field.name),
        )
    with pytest.raises(RuntimeError, match="FILE_CHANGE_BOUND_VALUE_INVALID"):
        policy._authenticate_policy_decision(forged)


@pytest.mark.parametrize(
    "field_name",
    (
        "changes",
        "contents",
        "implicit_ancestor_paths",
        "unique_final_paths",
    ),
)
def test_policy_decision_rejects_value_equivalent_list_substitutions(
    tmp_path: Path,
    field_name: str,
) -> None:
    policy, context, source, session, _target = _authorized_setup(tmp_path)
    decision = policy.authorize_file_change_events(
        session,
        session,
        (source,),
        context=context,
    )
    object.__setattr__(decision, field_name, list(getattr(decision, field_name)))
    with pytest.raises(RuntimeError, match="FILE_CHANGE_BOUND_VALUE_INVALID"):
        policy._authenticate_policy_decision(decision)


def test_policy_decision_rejects_custom_and_exact_class_forged_changes(
    tmp_path: Path,
) -> None:
    class CustomChange:
        pass

    class IntegerLookalike(int):
        pass

    policy, context, source, session, _target = _authorized_setup(
        tmp_path / "custom"
    )
    decision = policy.authorize_file_change_events(
        session,
        session,
        (source,),
        context=context,
    )
    original = decision.changes[0]
    custom = CustomChange()
    for model_field in fields(policy.BoundFileChange):
        object.__setattr__(
            custom,
            model_field.name,
            getattr(original, model_field.name),
        )
    object.__setattr__(decision, "changes", (custom,))
    with pytest.raises(RuntimeError, match="FILE_CHANGE_BOUND_VALUE_INVALID"):
        policy._authenticate_policy_decision(decision)

    policy, context, source, session, _target = _authorized_setup(
        tmp_path / "exact-class"
    )
    decision = policy.authorize_file_change_events(
        session,
        session,
        (source,),
        context=context,
    )
    original = decision.changes[0]
    forged = object.__new__(policy.BoundFileChange)
    for model_field in fields(policy.BoundFileChange):
        value = getattr(original, model_field.name)
        if model_field.name == "started_event_ordinal":
            value = IntegerLookalike(value)
        object.__setattr__(forged, model_field.name, value)
    object.__setattr__(decision, "changes", (forged,))
    with pytest.raises(RuntimeError, match="FILE_CHANGE_BOUND_VALUE_INVALID"):
        policy._authenticate_policy_decision(decision)


@pytest.mark.parametrize(
    "field_name",
    (
        "version",
        "variant",
        "case_id",
        "transition_entries",
        "raw_content_bytes",
        "retained_content_bytes",
        "normalized_plan_sha256",
        "aggregate_transition_sha256",
        "content_inventory_sha256",
        "canonical_sha256",
    ),
)
def test_policy_decision_rejects_exact_value_scalar_subclasses(
    tmp_path: Path,
    field_name: str,
) -> None:
    class IntegerLookalike(int):
        pass

    class TextLookalike(str):
        pass

    policy, context, source, session, _target = _authorized_setup(tmp_path)
    decision = policy.authorize_file_change_events(
        session,
        session,
        (source,),
        context=context,
    )
    original = getattr(decision, field_name)
    replacement = (
        IntegerLookalike(original)
        if field_name
        in {
            "transition_entries",
            "raw_content_bytes",
            "retained_content_bytes",
        }
        else TextLookalike(original)
    )
    object.__setattr__(decision, field_name, replacement)
    with pytest.raises(RuntimeError, match="FILE_CHANGE_BOUND_VALUE_INVALID"):
        policy._authenticate_policy_decision(decision)


def test_policy_decision_rejects_scalar_hash_and_count_invariant_drift(
    tmp_path: Path,
) -> None:
    mutations = (
        ("version", "complete-suite-file-change-policy-v2"),
        ("transition_entries", 0),
        ("raw_content_bytes", 0),
        ("normalized_plan_sha256", "f" * 63),
    )
    for index, (field_name, replacement) in enumerate(mutations):
        policy, context, source, session, _target = _authorized_setup(
            tmp_path / str(index)
        )
        decision = policy.authorize_file_change_events(
            session,
            session,
            (source,),
            context=context,
        )
        object.__setattr__(decision, field_name, replacement)
        with pytest.raises(
            RuntimeError,
            match="FILE_CHANGE_BOUND_VALUE_INVALID",
        ):
            policy._authenticate_policy_decision(decision)


def test_authorizer_rejects_129_sources_before_element_or_field_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy, context, source, session, _target = _authorized_setup(tmp_path)
    with pytest.raises(
        RuntimeError,
        match="FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED",
    ):
        policy.authorize_file_change_events(
            session,
            session,
            (source,) * 128 + (object(),),
            context=context,
        )

    def unexpected_source_access(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("oversized content sources were accessed")

    monkeypatch.setattr(
        policy.FileChangeContentSource,
        "__post_init__",
        unexpected_source_access,
    )
    monkeypatch.setattr(policy, "_source_fingerprint", unexpected_source_access)
    monkeypatch.setattr(policy, "_detach_source", unexpected_source_access)
    with pytest.raises(
        RuntimeError,
        match="FILE_CHANGE_RESOURCE_LIMIT_EXCEEDED",
    ):
        policy.authorize_file_change_events(
            session,
            session,
            (source,) * 129,
            context=context,
        )
