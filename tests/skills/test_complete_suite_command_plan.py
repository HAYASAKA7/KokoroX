from __future__ import annotations

from collections.abc import Sequence
from dataclasses import FrozenInstanceError, fields, replace
from hashlib import sha256
import importlib
import inspect
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import sys
import threading
import tracemalloc
from typing import Any, get_type_hints
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator


SKILLS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILLS_ROOT))

import run_complete_suite_campaign as runner  # noqa: E402


LEGACY_PROVENANCE = "legacy-shell-words-v1"
COMMAND_PLAN_PROVENANCE = "powershell-command-plan-v1"
SHELL_PATH = r"C:\Program Files\PowerShell\7\pwsh.exe"
WRAPPER_ARGUMENTS = b" -NoLogo -NoProfile -NonInteractive -Command "

POWERSHELL_SOURCE_AUDIT_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3.0
$utf8 = [System.Text.UTF8Encoding]::new($false, $true)
$inputStream = [Console]::OpenStandardInput()
$reader = [System.IO.StreamReader]::new(
    $inputStream,
    $utf8,
    $false,
    4096,
    $true
)
$source = $reader.ReadToEnd()
$tokens = $null
$parseErrors = $null
$root = [System.Management.Automation.Language.Parser]::ParseInput(
    $source,
    [ref]$tokens,
    [ref]$parseErrors
)

function Get-NearestFunctionName {
    param([System.Management.Automation.Language.Ast]$Node)

    $ancestor = $Node.Parent
    while ($null -ne $ancestor) {
        if ($ancestor -is [System.Management.Automation.Language.FunctionDefinitionAst]) {
            return [string]$ancestor.Name
        }
        $ancestor = $ancestor.Parent
    }
    return $null
}

$members = @(
    foreach ($candidate in @($root.FindAll({
        param($item)
        $item -is [System.Management.Automation.Language.MemberExpressionAst]
    }, $true))) {
        $memberName = $null
        if (
            $candidate.Member -is
                [System.Management.Automation.Language.StringConstantExpressionAst]
        ) {
            $memberName = [string]$candidate.Member.Value
        }
        [ordered]@{
            function_name = Get-NearestFunctionName $candidate
            invoking = [bool](
                $candidate -is
                    [System.Management.Automation.Language.InvokeMemberExpressionAst]
            )
            member_kind = [string]$candidate.Member.GetType().FullName
            member_name = $memberName
        }
    }
)

$commands = @(
    foreach ($candidate in @($root.FindAll({
        param($item)
        $item -is [System.Management.Automation.Language.CommandAst]
    }, $true))) {
        $commandName = $candidate.GetCommandName()
        if ([string]::IsNullOrEmpty($commandName)) {
            $commandName = $null
        }
        [ordered]@{
            command_name = $commandName
            function_name = Get-NearestFunctionName $candidate
            invocation_operator = [string]$candidate.InvocationOperator
        }
    }
)

$types = @(
    foreach ($candidate in @($root.FindAll({
        param($item)
        ($item -is [System.Management.Automation.Language.TypeExpressionAst]) -or
            ($item -is [System.Management.Automation.Language.TypeConstraintAst])
    }, $true))) {
        [ordered]@{
            type_name = [string]$candidate.TypeName.FullName
        }
    }
)

$document = [ordered]@{
    parse_error_ids = @($parseErrors | ForEach-Object { [string]$_.ErrorId })
    members = $members
    commands = $commands
    types = $types
}
$json = $document | ConvertTo-Json -Depth 5 -Compress
$outputBytes = $utf8.GetBytes($json)
$outputStream = [Console]::OpenStandardOutput()
$outputStream.Write($outputBytes, 0, $outputBytes.Length)
$outputStream.Flush()
"""
PAYLOAD_LIMIT_BYTES = 256 * 1024
PLAN_LIMIT_BYTES = 4 * 1024 * 1024
PIPE_LIMIT_BYTES = PLAN_LIMIT_BYTES + 1
STDERR_LIMIT_BYTES = 64 * 1024
DOCUMENT_BUDGET_COMPLEX_PAYLOAD = (
    "(((Get-Item '.\\a\\b' | "
    + " | ".join(f"Write-Output a{index}" for index in range(8))
    + " | Write-Output 'hé')))"
).encode("utf-8")
DECODER_RELATIVE_PATH = "tests/skills/complete_suite_command_plan_decoder.ps1"
SCHEMA_PATH = SKILLS_ROOT / "complete-suite-command-plan.schema.json"
DECODER_PATH = SKILLS_ROOT / "complete_suite_command_plan_decoder.ps1"
DECODER_SCHEMA_VERSION = "complete-suite-command-plan-decoder-v1"
TOKEN_KINDS = (
    "Unknown", "Variable", "SplattedVariable", "Parameter", "Number", "Label",
    "Identifier", "Generic", "NewLine", "LineContinuation", "Comment",
    "EndOfInput", "StringLiteral", "StringExpandable", "HereStringLiteral",
    "HereStringExpandable", "LParen", "RParen", "LCurly", "RCurly",
    "LBracket", "RBracket", "AtParen", "AtCurly", "DollarParen", "Semi",
    "AndAnd", "OrOr", "Ampersand", "Pipe", "Comma", "MinusMinus",
    "PlusPlus", "DotDot", "ColonColon", "Dot", "Exclaim", "Multiply",
    "Divide", "Rem", "Plus", "Minus", "Equals", "PlusEquals", "MinusEquals",
    "MultiplyEquals", "DivideEquals", "RemainderEquals", "Redirection",
    "RedirectInStd", "Format", "Not", "Bnot", "And", "Or", "Xor", "Band",
    "Bor", "Bxor", "Join", "Ieq", "Ine", "Ige", "Igt", "Ilt", "Ile",
    "Ilike", "Inotlike", "Imatch", "Inotmatch", "Ireplace", "Icontains",
    "Inotcontains", "Iin", "Inotin", "Isplit", "Ceq", "Cne", "Cge", "Cgt",
    "Clt", "Cle", "Clike", "Cnotlike", "Cmatch", "Cnotmatch", "Creplace",
    "Ccontains", "Cnotcontains", "Cin", "Cnotin", "Csplit", "Is", "IsNot",
    "As", "PostfixPlusPlus", "PostfixMinusMinus", "Shl", "Shr", "Colon",
    "QuestionMark", "QuestionQuestionEquals", "QuestionQuestion", "QuestionDot",
    "QuestionLBracket", "Begin", "Break", "Catch", "Class", "Continue", "Data",
    "Define", "Do", "Dynamicparam", "Else", "ElseIf", "End", "Exit", "Filter",
    "Finally", "For", "Foreach", "From", "Function", "If", "In", "Param",
    "Process", "Return", "Switch", "Throw", "Trap", "Try", "Until", "Using",
    "Var", "While", "Workflow", "Parallel", "Sequence", "InlineScript",
    "Configuration", "DynamicKeyword", "Public", "Private", "Static",
    "Interface", "Enum", "Namespace", "Module", "Type", "Assembly", "Command",
    "Hidden", "Base", "Default", "Clean",
)
TOKEN_FLAGS = (
    "None", "BinaryPrecedenceLogical", "BinaryPrecedenceBitwise",
    "BinaryPrecedenceComparison", "BinaryPrecedenceCoalesce",
    "BinaryPrecedenceAdd", "BinaryPrecedenceMultiply", "BinaryPrecedenceFormat",
    "BinaryPrecedenceRange", "BinaryPrecedenceMask", "Keyword",
    "ScriptBlockBlockName", "BinaryOperator", "UnaryOperator",
    "CaseSensitiveOperator", "TernaryOperator", "SpecialOperator",
    "AssignmentOperator", "ParseModeInvariant", "TokenInError",
    "DisallowedInRestrictedMode", "PrefixOrPostfixOperator", "CommandName",
    "MemberName", "TypeName", "AttributeName", "CanConstantFold",
    "StatementDoesntSupportAttributes",
)
AST_TYPES = (
    "ArrayExpressionAst", "ArrayLiteralAst", "AssignmentStatementAst",
    "AttributeAst", "AttributeBaseAst", "AttributedExpressionAst",
    "BaseCtorInvokeMemberExpressionAst", "BinaryExpressionAst", "BlockStatementAst",
    "BreakStatementAst", "CatchClauseAst", "ChainableAst", "CommandAst",
    "CommandBaseAst", "CommandElementAst", "CommandExpressionAst",
    "CommandParameterAst", "CompilerGeneratedMemberFunctionAst",
    "ConfigurationDefinitionAst", "ConstantExpressionAst", "ContinueStatementAst",
    "ConvertExpressionAst", "DataStatementAst", "DoUntilStatementAst",
    "DoWhileStatementAst", "DynamicKeywordStatementAst", "ErrorExpressionAst",
    "ErrorStatementAst", "ExitStatementAst", "ExpandableStringExpressionAst",
    "ExpressionAst", "FileRedirectionAst", "ForEachStatementAst",
    "ForStatementAst", "FunctionDefinitionAst", "FunctionMemberAst", "HashtableAst",
    "IfStatementAst", "IndexExpressionAst", "InvokeMemberExpressionAst",
    "LabeledStatementAst", "LoopStatementAst", "MemberAst", "MemberExpressionAst",
    "MergingRedirectionAst", "NamedAttributeArgumentAst", "NamedBlockAst",
    "ParamBlockAst", "ParameterAst", "ParenExpressionAst", "PipelineAst",
    "PipelineBaseAst", "PipelineChainAst", "PropertyMemberAst", "RedirectionAst",
    "ReturnStatementAst", "ScriptBlockAst", "ScriptBlockExpressionAst",
    "SequencePointAst", "StatementAst", "StatementBlockAst",
    "StringConstantExpressionAst", "SubExpressionAst", "SwitchStatementAst",
    "TernaryExpressionAst", "ThrowStatementAst", "TrapStatementAst",
    "TryStatementAst", "TypeConstraintAst", "TypeDefinitionAst",
    "TypeExpressionAst", "UnaryExpressionAst", "UsingExpressionAst",
    "UsingStatementAst", "AssignmentTarget", "VariableExpressionAst",
    "WhileStatementAst",
)
AST_ROLES = (
    "script_block", "statement", "pipeline", "command", "command_element",
    "redirection", "control_flow", "expression",
)
AST_TYPES_BY_ROLE = {
    "script_block": ("ScriptBlockAst",),
    "pipeline": ("PipelineAst", "PipelineChainAst"),
    "command": ("CommandAst", "CommandExpressionAst"),
    "command_element": ("CommandElementAst", "CommandParameterAst"),
    "redirection": (
        "FileRedirectionAst",
        "MergingRedirectionAst",
        "RedirectionAst",
    ),
    "control_flow": (
        "BlockStatementAst",
        "BreakStatementAst",
        "CatchClauseAst",
        "ContinueStatementAst",
        "DoUntilStatementAst",
        "DoWhileStatementAst",
        "ExitStatementAst",
        "ForEachStatementAst",
        "ForStatementAst",
        "IfStatementAst",
        "LabeledStatementAst",
        "LoopStatementAst",
        "ReturnStatementAst",
        "SwitchStatementAst",
        "ThrowStatementAst",
        "TrapStatementAst",
        "TryStatementAst",
        "WhileStatementAst",
    ),
    "expression": (
        "ArrayExpressionAst",
        "ArrayLiteralAst",
        "AssignmentTarget",
        "AttributedExpressionAst",
        "BaseCtorInvokeMemberExpressionAst",
        "BinaryExpressionAst",
        "ConstantExpressionAst",
        "ConvertExpressionAst",
        "ErrorExpressionAst",
        "ExpandableStringExpressionAst",
        "ExpressionAst",
        "HashtableAst",
        "IndexExpressionAst",
        "InvokeMemberExpressionAst",
        "MemberExpressionAst",
        "ParenExpressionAst",
        "ScriptBlockExpressionAst",
        "StringConstantExpressionAst",
        "SubExpressionAst",
        "TernaryExpressionAst",
        "TypeExpressionAst",
        "UnaryExpressionAst",
        "UsingExpressionAst",
        "VariableExpressionAst",
    ),
    "statement": (
        "AssignmentStatementAst",
        "AttributeAst",
        "AttributeBaseAst",
        "ChainableAst",
        "CommandBaseAst",
        "CompilerGeneratedMemberFunctionAst",
        "ConfigurationDefinitionAst",
        "DataStatementAst",
        "DynamicKeywordStatementAst",
        "ErrorStatementAst",
        "FunctionDefinitionAst",
        "FunctionMemberAst",
        "MemberAst",
        "NamedAttributeArgumentAst",
        "NamedBlockAst",
        "ParamBlockAst",
        "ParameterAst",
        "PipelineBaseAst",
        "PropertyMemberAst",
        "SequencePointAst",
        "StatementAst",
        "StatementBlockAst",
        "TypeConstraintAst",
        "TypeDefinitionAst",
        "UsingStatementAst",
    ),
}
AST_ROLE_BY_TYPE = {
    ast_type: role
    for role, ast_types in AST_TYPES_BY_ROLE.items()
    for ast_type in ast_types
}
CONCRETE_STATEMENT_AST_TYPES = (
    "AssignmentStatementAst",
    "BlockStatementAst",
    "BreakStatementAst",
    "CommandAst",
    "CommandExpressionAst",
    "ConfigurationDefinitionAst",
    "ContinueStatementAst",
    "DataStatementAst",
    "DoUntilStatementAst",
    "DoWhileStatementAst",
    "DynamicKeywordStatementAst",
    "ErrorStatementAst",
    "ExitStatementAst",
    "ForEachStatementAst",
    "ForStatementAst",
    "FunctionDefinitionAst",
    "IfStatementAst",
    "PipelineAst",
    "PipelineChainAst",
    "ReturnStatementAst",
    "SwitchStatementAst",
    "ThrowStatementAst",
    "TrapStatementAst",
    "TryStatementAst",
    "TypeDefinitionAst",
    "UsingStatementAst",
    "WhileStatementAst",
)
OPERATION_AST_TYPES = ("CommandAst",)
PIPELINE_STAGE_AST_TYPES = ("CommandAst", "CommandExpressionAst")


@pytest.fixture
def decoder_test_root() -> object:
    parent = SKILLS_ROOT.parent.parent / ".c6-pytest-tmp"
    assert parent.is_dir()
    root = parent / f"task03-runtime-{uuid4().hex}"
    assert root.exists() is False
    root.mkdir()
    try:
        yield root
    finally:
        if root.exists():
            retained = tuple(root.iterdir())
            if retained:
                names = tuple(path.name for path in retained)
                raise AssertionError(
                    f"decoder test root retained unexpected entries: {names!r}"
                )
            root.rmdir()
ACCEPTED_UTF8_BOUNDARIES = (
    ("u0080", b"\xc2\x80", "\u0080"),
    ("u07ff", b"\xdf\xbf", "\u07ff"),
    ("u0800", b"\xe0\xa0\x80", "\u0800"),
    ("before-surrogates", b"\xed\x9f\xbf", "\ud7ff"),
    ("after-surrogates", b"\xee\x80\x80", "\ue000"),
    ("uffff", b"\xef\xbf\xbf", "\uffff"),
    ("u10000", b"\xf0\x90\x80\x80", "\U00010000"),
    ("interior-f1", b"\xf1\x80\x80\x80", "\U00040000"),
    ("before-max", b"\xf4\x8f\xbf\xbe", "\U0010fffe"),
    ("max", b"\xf4\x8f\xbf\xbf", "\U0010ffff"),
)
REJECTED_UTF8_BOUNDARIES = (
    ("stray-continuation", b"\x80"),
    ("overlong-2", b"\xc0\xaf"),
    ("overlong-3", b"\xe0\x80\xaf"),
    ("overlong-4", b"\xf0\x80\x80\xaf"),
    ("surrogate-first", b"\xed\xa0\x80"),
    ("surrogate-last", b"\xed\xbf\xbf"),
    ("truncated-2", b"\xc2"),
    ("truncated-3", b"\xe1\x80"),
    ("truncated-4", b"\xf1\x80\x80"),
    ("bad-continuation-2", b"\xc2A"),
    ("bad-continuation-3-second", b"\xe1A\x80"),
    ("bad-continuation-3", b"\xe1\x80A"),
    ("bad-continuation-4-second", b"\xf1A\x80\x80"),
    ("bad-continuation-4-third", b"\xf1\x80A\x80"),
    ("bad-continuation-4", b"\xf1\x80\x80A"),
    ("above-unicode-max", b"\xf4\x90\x80\x80"),
)
LEGITIMATE_V1_PAYLOADS = (
    (
        "Test-Path -LiteralPath '.\\data\\request.json'; "
        "& '.tools\\kokoro.cmd' character request validate "
        "--input '.\\data\\request.json' --json"
    ),
    (
        "& '.tools\\kokoro.cmd' research workspace validate "
        "--workspace '.\\workspace' --json"
    ),
)


def _command_plan_module() -> object:
    try:
        return importlib.import_module("complete_suite_command_plan")
    except ModuleNotFoundError:
        pytest.fail(
            "Task 2 complete_suite_command_plan implementation is missing",
            pytrace=False,
        )


def _shell(path: str = SHELL_PATH) -> object:
    command_plan = _command_plan_module()
    return command_plan.ShellIdentity(
        path=path,
        sha256="1" * 64,
        file_version="7.6.0.0",
        product_version="7.6.0",
        edition="Core",
        parser_version="7.6.0",
    )


def _raw_wrapper(payload_field: bytes, *, shell_path: str = SHELL_PATH) -> bytes:
    return b'"' + shell_path.encode("utf-8") + b'"' + WRAPPER_ARGUMENTS + payload_field


def _assert_stable_code(expected: str, action: object) -> None:
    with pytest.raises(RuntimeError) as exc_info:
        action()
    assert exc_info.value.args == (expected,)


def _assert_extracted_metrics(
    extracted: object,
    *,
    rendered: bytes,
    payload_field: bytes,
    payload: str,
) -> None:
    payload_bytes = payload.encode("utf-8")
    assert extracted.rendered_utf8_bytes == len(rendered)
    assert extracted.rendered_sha256 == sha256(rendered).hexdigest()
    assert extracted.payload_field_utf8_bytes == len(payload_field)
    assert extracted.payload_field_sha256 == sha256(payload_field).hexdigest()
    assert extracted.payload_utf8_bytes == len(payload_bytes)
    assert extracted.payload_sha256 == sha256(payload_bytes).hexdigest()
    assert extracted.payload == payload


def _install_guarded_bytearray(
    monkeypatch: pytest.MonkeyPatch,
    command_plan: object,
) -> list[int]:
    observed_sizes: list[int] = []
    builtin_bytearray = bytearray

    class GuardedBytearray(builtin_bytearray):
        def append(self, value: int) -> None:
            target_size = len(self) + 1
            observed_sizes.append(target_size)
            if target_size > PAYLOAD_LIMIT_BYTES:
                raise AssertionError("decoded payload allocation exceeded limit")
            super().append(value)

        def extend(self, values: object) -> None:
            detached_values = bytes(values)
            target_size = len(self) + len(detached_values)
            observed_sizes.append(target_size)
            if target_size > PAYLOAD_LIMIT_BYTES:
                raise AssertionError("decoded payload allocation exceeded limit")
            super().extend(detached_values)

    monkeypatch.setattr(command_plan, "bytearray", GuardedBytearray, raising=False)
    return observed_sizes


def _legacy_record(payload: str) -> dict[str, object]:
    from complete_suite_adjudication import _command_records

    rendered = (
        r'"C:\Program Files\PowerShell\7\pwsh.exe" -Command '
        + json.dumps(payload)
    )
    started = {
        "id": "command-1",
        "type": "command_execution",
        "command": rendered,
        "aggregated_output": "",
        "exit_code": None,
        "status": "in_progress",
    }
    completed = {
        **started,
        "aggregated_output": '{"ok":true}\n',
        "exit_code": 0,
        "status": "completed",
    }
    records, valid = _command_records(
        [
            {"type": "item.started", "item": started},
            {"type": "item.completed", "item": completed},
        ]
    )
    assert valid is True
    assert len(records) == 1
    return records[0]


def select_version(document: dict[str, object]) -> str:
    from complete_suite_adjudication import command_provenance_version

    campaign_bytes = runner.canonical_bytes(document)
    return command_provenance_version(
        campaign_bytes,
        expected_campaign_sha256=sha256(campaign_bytes).hexdigest(),
    )


def _utf16_units(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _independent_utf16_to_utf8_boundaries(value: str) -> dict[int, int]:
    utf16_offset = 0
    utf8_offset = 0
    boundaries = {0: 0}
    for character in value:
        scalar = ord(character)
        assert not 0xD800 <= scalar <= 0xDFFF
        utf16_offset += 2 if scalar > 0xFFFF else 1
        utf8_offset += len(character.encode("utf-8"))
        boundaries[utf16_offset] = utf8_offset
    return boundaries


def _decoder_document(
    payload: bytes,
    *,
    shell: object | None = None,
    decoder_sha256: str = "2" * 64,
    parse_errors: list[dict[str, object]] | None = None,
    tokens: list[dict[str, object]] | None = None,
    nodes: list[dict[str, object]] | None = None,
    metrics: dict[str, int] | None = None,
) -> dict[str, object]:
    if shell is None:
        shell = _shell()
    payload_text = payload.decode("utf-8")
    payload_utf16 = _utf16_units(payload_text)
    if nodes is None:
        nodes = [
            {
                "index": 0,
                "ast_type": "ScriptBlockAst",
                "role": "script_block",
                "parent_index": None,
                "child_indices": [],
                "start_utf16": 0,
                "end_utf16": payload_utf16,
                "start_utf8": 0,
                "end_utf8": len(payload),
                "invocation_operator": None,
                "literal": None,
            }
        ]
    if metrics is None:
        metrics = {
            "ast_nodes": len(nodes),
            "ast_depth": 1 if nodes else 0,
            "statements": 0,
            "operations": 0,
            "pipeline_stages": 0,
        }
    return {
        "schema_version": DECODER_SCHEMA_VERSION,
        "payload": {
            "utf8_bytes": len(payload),
            "sha256": sha256(payload).hexdigest(),
        },
        "powershell": {
            "path": shell.path,
            "sha256": shell.sha256,
            "file_version": shell.file_version,
            "product_version": shell.product_version,
            "edition": shell.edition,
            "parser_version": shell.parser_version,
        },
        "decoder": {
            "path": DECODER_RELATIVE_PATH,
            "sha256": decoder_sha256,
        },
        "parse_errors": [] if parse_errors is None else parse_errors,
        "tokens": [] if tokens is None else tokens,
        "nodes": nodes,
        "metrics": metrics,
    }


def _empty_decoder_document(payload: bytes = b"") -> dict[str, object]:
    return _decoder_document(
        payload,
        nodes=[],
        metrics={
            "ast_nodes": 0,
            "ast_depth": 0,
            "statements": 0,
            "operations": 0,
            "pipeline_stages": 0,
        },
    )


def _ascii_token_entry(
    payload: bytes,
    *,
    index: int,
    start: int,
    end: int,
    kind: str = "Generic",
    flags: list[str] | None = None,
    literal: dict[str, object] | None = None,
    text_sha256: str | None = None,
) -> dict[str, object]:
    assert payload.isascii()
    return {
        "index": index,
        "kind": kind,
        "flags": [] if flags is None else flags,
        "start_utf16": start,
        "end_utf16": end,
        "start_utf8": start,
        "end_utf8": end,
        "text_sha256": (
            sha256(payload[start:end]).hexdigest()
            if text_sha256 is None
            else text_sha256
        ),
        "literal": literal,
    }


def _end_of_input_token_entry(
    payload: bytes,
    *,
    index: int,
    start_utf8: int | None = None,
) -> dict[str, object]:
    payload_text = payload.decode("utf-8", errors="strict")
    payload_end_utf16 = _utf16_units(payload_text)
    if start_utf8 is None:
        start_utf8 = len(payload)
    start_utf16 = (
        payload_end_utf16 if start_utf8 == len(payload) else start_utf8
    )
    return {
        "index": index,
        "kind": "EndOfInput",
        "flags": ["ParseModeInvariant"],
        "start_utf16": start_utf16,
        "end_utf16": start_utf16,
        "start_utf8": start_utf8,
        "end_utf8": start_utf8,
        "text_sha256": sha256(b"").hexdigest(),
        "literal": None,
    }


def _literal_entry(kind: str, value: str) -> dict[str, object]:
    value_bytes = value.encode("utf-8")
    return {
        "kind": kind,
        "value": value,
        "utf8_bytes": len(value_bytes),
        "sha256": sha256(value_bytes).hexdigest(),
    }


def _synthetic_parse_error_document() -> tuple[bytes, dict[str, object]]:
    payload = b"x"
    document = _decoder_document(
        payload,
        parse_errors=[
            {
                "index": 0,
                "error_id": "Synthetic.ParseError",
                "incomplete_input": False,
                "start_utf16": 0,
                "end_utf16": 1,
                "start_utf8": 0,
                "end_utf8": 1,
                "message_sha256": sha256(
                    b"synthetic parser message"
                ).hexdigest(),
            }
        ],
        tokens=[_end_of_input_token_entry(payload, index=0)],
    )
    return payload, document


def _ascii_node_entry(
    *,
    index: int,
    ast_type: str,
    parent_index: int | None,
    child_indices: list[int],
    start: int,
    end: int,
    invocation_operator: str | None = None,
    literal: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "index": index,
        "ast_type": ast_type,
        "role": AST_ROLE_BY_TYPE[ast_type],
        "parent_index": parent_index,
        "child_indices": child_indices,
        "start_utf16": start,
        "end_utf16": end,
        "start_utf8": start,
        "end_utf8": end,
        "invocation_operator": invocation_operator,
        "literal": literal,
    }


def _ast_parent_baseline_document() -> tuple[bytes, dict[str, object]]:
    payload = b"a;b"
    tokens = [
        _ascii_token_entry(
            payload,
            index=0,
            start=0,
            end=1,
            kind="Identifier",
            literal=_literal_entry("bare", "a"),
        ),
        _ascii_token_entry(
            payload,
            index=1,
            start=1,
            end=2,
            kind="Semi",
        ),
        _ascii_token_entry(
            payload,
            index=2,
            start=2,
            end=3,
            kind="Identifier",
            literal=_literal_entry("bare", "b"),
        ),
        _end_of_input_token_entry(payload, index=3),
    ]
    nodes = [
        _ascii_node_entry(
            index=0,
            ast_type="ScriptBlockAst",
            parent_index=None,
            child_indices=[1],
            start=0,
            end=3,
        ),
        _ascii_node_entry(
            index=1,
            ast_type="NamedBlockAst",
            parent_index=0,
            child_indices=[2, 5],
            start=0,
            end=3,
        ),
        _ascii_node_entry(
            index=2,
            ast_type="PipelineAst",
            parent_index=1,
            child_indices=[3],
            start=0,
            end=1,
        ),
        _ascii_node_entry(
            index=3,
            ast_type="CommandAst",
            parent_index=2,
            child_indices=[4],
            start=0,
            end=1,
            invocation_operator="none",
        ),
        _ascii_node_entry(
            index=4,
            ast_type="StringConstantExpressionAst",
            parent_index=3,
            child_indices=[],
            start=0,
            end=1,
            literal=_literal_entry("bare", "a"),
        ),
        _ascii_node_entry(
            index=5,
            ast_type="PipelineAst",
            parent_index=1,
            child_indices=[6],
            start=2,
            end=3,
        ),
        _ascii_node_entry(
            index=6,
            ast_type="CommandAst",
            parent_index=5,
            child_indices=[7],
            start=2,
            end=3,
            invocation_operator="none",
        ),
        _ascii_node_entry(
            index=7,
            ast_type="StringConstantExpressionAst",
            parent_index=6,
            child_indices=[],
            start=2,
            end=3,
            literal=_literal_entry("bare", "b"),
        ),
    ]
    return payload, _decoder_document(
        payload,
        tokens=tokens,
        nodes=nodes,
        metrics={
            "ast_nodes": 8,
            "ast_depth": 5,
            "statements": 4,
            "operations": 2,
            "pipeline_stages": 2,
        },
    )


def _ast_tree_projection(document: dict[str, object]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            node["ast_type"],
            node["role"],
            node["parent_index"],
            tuple(node["child_indices"]),
            node["invocation_operator"],
        )
        for node in document["nodes"]
    )


def _compact_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _independent_incremental_document_size(
    document: dict[str, object],
) -> tuple[int, int]:
    parse_errors = document["parse_errors"]
    tokens = document["tokens"]
    nodes = document["nodes"]
    metrics = document["metrics"]
    assert isinstance(parse_errors, list)
    assert isinstance(tokens, list)
    assert isinstance(nodes, list)
    assert isinstance(metrics, dict)

    empty_document = dict(document)
    empty_document["parse_errors"] = []
    empty_document["tokens"] = []
    empty_document["nodes"] = []
    empty_document["metrics"] = {name: 0 for name in metrics}
    total = len(_compact_json(empty_document))

    for entries in (parse_errors, tokens):
        for index, entry in enumerate(entries):
            assert isinstance(entry, dict)
            total += len(_compact_json(entry)) + (1 if index else 0)

    child_index_bytes = 0
    for index, entry in enumerate(nodes):
        assert isinstance(entry, dict)
        child_indices = entry["child_indices"]
        assert isinstance(child_indices, list)
        entry_without_children = dict(entry)
        entry_without_children["child_indices"] = []
        total += len(_compact_json(entry_without_children)) + (1 if index else 0)
        for child_offset, child_index in enumerate(child_indices):
            assert type(child_index) is int
            assert child_index >= 0
            delta = len(str(child_index)) + (1 if child_offset else 0)
            child_index_bytes += delta
            total += delta

    for value in metrics.values():
        assert type(value) is int
        assert value >= 0
        total += len(str(value)) - 1
    return total, child_index_bytes


def _strict_powershell_string_array(
    source: str,
    variable_name: str,
) -> tuple[tuple[str, ...], int]:
    declaration = (
        "$"
        + variable_name
        + " = [string[]]@("  # exact PowerShell declaration prefix
    )
    assert declaration.endswith("@(")
    assert source.count(declaration) == 1
    cursor = source.index(declaration) + len(declaration)

    def skip_whitespace(offset: int) -> int:
        while offset < len(source) and source[offset] in " \t\n":
            offset += 1
        return offset

    values: list[str] = []
    cursor = skip_whitespace(cursor)
    while True:
        assert cursor < len(source) and source[cursor] == "'"
        cursor += 1
        value: list[str] = []
        while True:
            assert cursor < len(source)
            character = source[cursor]
            if character != "'":
                value.append(character)
                cursor += 1
                continue
            if cursor + 1 < len(source) and source[cursor + 1] == "'":
                value.append("'")
                cursor += 2
                continue
            cursor += 1
            break
        values.append("".join(value))
        cursor = skip_whitespace(cursor)
        assert cursor < len(source)
        if source[cursor] == ",":
            cursor = skip_whitespace(cursor + 1)
            assert cursor < len(source) and source[cursor] == "'"
            continue
        assert source[cursor] == ")"
        cursor += 1
        assert cursor < len(source) and source[cursor] == "\n"
        return tuple(values), cursor + 1


class _FakeReader:
    def __init__(self, value: bytes) -> None:
        self._value = value
        self._cursor = 0
        self.read_sizes: list[int] = []

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        if self._cursor >= len(self._value):
            return b""
        end = min(self._cursor + size, len(self._value))
        result = self._value[self._cursor:end]
        self._cursor = end
        return result

    def close(self) -> None:
        return None


class _FakeWriter:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []
        self.closed = False

    def write(self, value: bytes) -> int:
        assert type(value) is bytes
        self.chunks.append(value)
        return len(value)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _PartialWriter(_FakeWriter):
    def write(self, value: bytes) -> int:
        assert type(value) is bytes
        retained = value[: max(1, len(value) // 2)]
        self.chunks.append(retained)
        return len(retained)


class _FakeDecoderProcess:
    def __init__(
        self,
        stdout: bytes,
        *,
        stderr: bytes = b"",
        exit_code: int = 0,
    ) -> None:
        self.stdin = _FakeWriter()
        self.stdout = _FakeReader(stdout)
        self.stderr = _FakeReader(stderr)
        self.returncode: int | None = None
        self._exit_code = exit_code
        self.wait_timeouts: list[float | None] = []
        self.killed = False

    def wait(self, timeout: float | None = None) -> int:
        self.wait_timeouts.append(timeout)
        self.returncode = self._exit_code
        return self._exit_code

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.killed = True
        self.returncode = self._exit_code

    def kill(self) -> None:
        self.killed = True
        self.returncode = self._exit_code


class _BlockingReader:
    def __init__(self, released: object) -> None:
        self._released = released
        self.read_sizes: list[int] = []
        self.closed = False

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        self._released.wait(5)
        return b""

    def close(self) -> None:
        self.closed = True


class _BlockingWriter:
    def __init__(self, released: threading.Event) -> None:
        self._released = released
        self.entered = threading.Event()
        self.closed = False

    def write(self, value: bytes) -> int:
        assert type(value) is bytes
        self.entered.set()
        self._released.wait(5)
        raise BrokenPipeError("decoder stdin released after termination")

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _TimeoutDecoderProcess:
    def __init__(self) -> None:
        self.released = threading.Event()
        self.stdin = _FakeWriter()
        self.stdout = _BlockingReader(self.released)
        self.stderr = _BlockingReader(self.released)
        self.returncode: int | None = None
        self.wait_calls = 0
        self.killed = False

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        if not self.killed:
            raise subprocess.TimeoutExpired("decoder", timeout)
        self.returncode = 1
        return 1

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.released.set()

    def terminate(self) -> None:
        self.kill()


class _FullyBlockingDecoderProcess(_TimeoutDecoderProcess):
    def __init__(self) -> None:
        super().__init__()
        self.stdin = _BlockingWriter(self.released)


class _RetryingTerminationDecoderProcess(_FullyBlockingDecoderProcess):
    def __init__(self) -> None:
        super().__init__()
        self.kill_calls = 0

    def kill(self) -> None:
        self.kill_calls += 1
        if self.kill_calls == 1:
            raise OSError("synthetic first kill failure")
        super().kill()


def _install_fake_decoder(
    monkeypatch: pytest.MonkeyPatch,
    *,
    payload: bytes,
    stdout: bytes | None = None,
    stderr: bytes = b"",
    exit_code: int = 0,
    identity_sequence: list[object] | None = None,
) -> tuple[object, _FakeDecoderProcess, list[tuple[tuple[object, ...], dict[str, object]]]]:
    command_plan = _command_plan_module()
    decoder_sha256 = "2" * 64
    if stdout is None:
        stdout = _compact_json(
            _decoder_document(
                payload,
                decoder_sha256=decoder_sha256,
                tokens=[_end_of_input_token_entry(payload, index=0)],
            )
        )
    process = _FakeDecoderProcess(stdout, stderr=stderr, exit_code=exit_code)
    popen_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_popen(*args: object, **kwargs: object) -> _FakeDecoderProcess:
        popen_calls.append((args, kwargs))
        return process

    identities = list(identity_sequence or [object()] * 4)
    identity_calls: list[tuple[Path, str]] = []

    def fake_observe(path: Path, expected_sha256: str) -> object:
        identity_calls.append((path, expected_sha256))
        if not identities:
            raise AssertionError("unexpected identity observation")
        return identities.pop(0)

    temp_root = Path(r"D:\tmp\kokoroarc-command-decoder-test-0001")
    monkeypatch.setattr(command_plan, "_POPEN", fake_popen, raising=True)
    monkeypatch.setattr(
        command_plan,
        "_observe_plain_file",
        fake_observe,
        raising=True,
    )
    monkeypatch.setattr(
        command_plan,
        "_make_decoder_temp_root",
        lambda: temp_root,
        raising=True,
    )
    monkeypatch.setattr(
        command_plan,
        "_remove_decoder_temp_root",
        lambda path: None,
        raising=True,
    )
    process.identity_calls = identity_calls  # type: ignore[attr-defined]
    return command_plan, process, popen_calls


def _decode_with_fake(
    command_plan: object,
    payload: bytes,
    *,
    decoder_sha256: str = "2" * 64,
) -> object:
    return command_plan.decode_powershell_payload(
        payload,
        shell=_shell(),
        decoder_path=DECODER_PATH,
        decoder_sha256=decoder_sha256,
    )


def _decode_fake_document(
    monkeypatch: pytest.MonkeyPatch,
    *,
    payload: bytes,
    document: dict[str, object],
) -> object:
    command_plan, _, _ = _install_fake_decoder(
        monkeypatch,
        payload=payload,
        stdout=_compact_json(document),
    )
    return _decode_with_fake(command_plan, payload)


def _run_decoder_path(
    payload: bytes,
    *,
    decoder_path: Path,
    temp_root: Path,
) -> subprocess.CompletedProcess[bytes]:
    assert Path(SHELL_PATH).is_file()
    assert decoder_path.is_file()
    assert temp_root.is_dir()
    system_root = os.environ["SYSTEMROOT"]
    windir = os.environ["WINDIR"]
    comspec = os.environ["COMSPEC"]
    environment = {
        "SYSTEMROOT": system_root,
        "WINDIR": windir,
        "COMSPEC": comspec,
        "PATHEXT": ".COM;.EXE;.BAT;.CMD",
        "TEMP": str(temp_root),
        "TMP": str(temp_root),
        "POWERSHELL_TELEMETRY_OPTOUT": "1",
        "POWERSHELL_UPDATECHECK": "Off",
    }
    assert set(environment) == {
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "POWERSHELL_TELEMETRY_OPTOUT",
        "POWERSHELL_UPDATECHECK",
    }
    assert environment["TEMP"] == str(temp_root)
    assert environment["TMP"] == str(temp_root)
    return subprocess.run(
        [
            SHELL_PATH,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(decoder_path),
        ],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        env=environment,
        timeout=30,
        check=False,
    )


def _run_real_decoder(
    payload: bytes,
    *,
    temp_root: Path,
) -> subprocess.CompletedProcess[bytes]:
    return _run_decoder_path(
        payload,
        decoder_path=DECODER_PATH,
        temp_root=temp_root,
    )


def _run_decoder_source(
    payload: bytes,
    source: bytes,
    *,
    temp_root: Path,
) -> subprocess.CompletedProcess[bytes]:
    candidate = temp_root / f"decoder-budget-{uuid4().hex}.ps1"
    assert candidate.exists() is False
    try:
        candidate.write_bytes(source)
        return _run_decoder_path(
            payload,
            decoder_path=candidate,
            temp_root=temp_root,
        )
    finally:
        candidate.unlink(missing_ok=True)


def _assert_decoder_document_budget_source_contract(source: str) -> None:
    assert source.count("$documentByteLimit = 4194304") == 1
    assert source.count("function Get-CompactJsonUtf8Length {") == 1
    assert source.count("function Assert-DocumentBudgetDelta {") == 1
    assert source.count("function Get-DocumentArrayEntryDelta {") == 1
    assert source.count("function Add-BudgetedDocumentEntry {") == 1
    assert "$separatorByteCount = 1" in source
    assert "$parentChildDelta++" in source
    assert "$metricDelta = (" in source
    assert (
        "$documentBudget = [ordered]@{\n"
        "    bytes = Get-CompactJsonUtf8Length $document\n"
        "}"
    ) in source
    assert (
        "if ([long]$outputBytes.Length -ne [long]$documentBudget.bytes) {\n"
        "    throw 'COMMAND_DECODER_PARSE_INVALID'\n"
        "}"
    ) in source

    append_start = source.index("function Add-BudgetedDocumentEntry {")
    append_end = source.index("\nfunction ", append_start + 1)
    append_source = source[append_start:append_end]
    append_guard = append_source.index(
        "Assert-DocumentBudgetDelta $Budget $entryDelta"
    )
    assert append_guard < append_source.index("[void]$Entries.Add($Entry)")

    ast_start = source.index("function Convert-AstTree {")
    ast_end = source.index("\nAssert-EndOfInputExtentContract", ast_start)
    ast_source = source[ast_start:ast_end]
    ast_guard = ast_source.index(
        "Assert-DocumentBudgetDelta $DocumentBudget $nodeDocumentDelta"
    )
    for mutation in (
        "[void]$NodeEntries.Add($nodeEntry)",
        ".child_indices.Add($nodeIndex)",
        "$Metrics.ast_nodes = $nodeIndex + 1",
        "$Metrics.ast_depth = $nextAstDepth",
        "$Metrics.statements = $nextStatementCount",
        "$Metrics.operations = $nextOperationCount",
        "$Metrics.pipeline_stages = $nextPipelineStageCount",
    ):
        assert ast_guard < ast_source.index(mutation)

    main_source = source[ast_end:]
    budget_init = main_source.index("$documentBudget = [ordered]@{")
    token_append = (
        "Add-BudgetedDocumentEntry $tokenEntries $tokenEntry $documentBudget"
    )
    error_append = (
        "Add-BudgetedDocumentEntry (\n"
        "        $parseErrorEntries\n"
        "    ) $parseErrorEntry $documentBudget"
    )
    ast_conversion = "$astTree = Convert-AstTree "
    for retention in (token_append, error_append, ast_conversion):
        assert budget_init < main_source.index(retention)

    output_start = source.index("$json = ConvertTo-Json -InputObject $document")
    output_source = source[output_start:]
    encode_at = output_source.index("$outputBytes = $utf8.GetBytes($json)")
    size_guard_at = output_source.index(
        "if ($outputBytes.Length -gt $documentByteLimit)"
    )
    equality_guard_at = output_source.index(
        "if ([long]$outputBytes.Length -ne [long]$documentBudget.bytes)"
    )
    open_at = output_source.index("[Console]::OpenStandardOutput()")
    write_at = output_source.index("$outputStream.Write(")
    assert encode_at < size_guard_at < equality_guard_at < open_at < write_at
    assert output_source.count("[Console]::OpenStandardOutput()") == 1
    assert output_source.count("$outputStream.Write(") == 1
    assert "Write-Output" not in output_source
    assert "Out-File" not in output_source


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while chunk := source.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _independent_native_argument(value: str) -> str:
    assert "\0" not in value
    value.encode("utf-16-le", errors="strict")
    if value and not any(character in '" \t' for character in value):
        return value
    output = '"'
    cursor = 0
    while cursor < len(value):
        slash_start = cursor
        while cursor < len(value) and value[cursor] == "\\":
            cursor += 1
        slash_count = cursor - slash_start
        if cursor == len(value):
            output += "\\" * (2 * slash_count)
            break
        if value[cursor] == '"':
            output += "\\" * (2 * slash_count + 1) + '"'
        else:
            output += "\\" * slash_count + value[cursor]
        cursor += 1
    return output + '"'


def _independent_native_vector(
    executable: str,
    arguments: tuple[str, ...],
) -> tuple[str, int, str]:
    command_line = " ".join(
        _independent_native_argument(value)
        for value in (executable, *arguments)
    )
    encoded = (command_line + "\0").encode("utf-16-le", errors="strict")
    return command_line, len(encoded) // 2, sha256(encoded).hexdigest()


def test_legacy_compound_shape_cannot_recover_operational_invocation() -> None:
    from complete_suite_adjudication import _cli_arguments, _structured_command

    payload = LEGITIMATE_V1_PAYLOADS[0]
    rendered = (
        r'"C:\Program Files\PowerShell\7\pwsh.exe" -Command '
        + json.dumps(payload)
    )

    assert _structured_command(rendered, 0) is not None
    assert _cli_arguments(_legacy_record(payload)) is None


def test_legacy_call_operator_shape_cannot_recover_operational_invocation() -> None:
    from complete_suite_adjudication import _cli_arguments, _structured_command

    payload = LEGITIMATE_V1_PAYLOADS[1]
    rendered = (
        r'"C:\Program Files\PowerShell\7\pwsh.exe" -Command '
        + json.dumps(payload)
    )

    assert _structured_command(rendered, 0) is not None
    assert _cli_arguments(_legacy_record(payload)) is None


def test_missing_command_provenance_uses_legacy_path() -> None:
    assert select_version({}) == LEGACY_PROVENANCE


def test_campaign6_command_provenance_requires_exact_version() -> None:
    assert select_version(
        {"command_provenance": {"version": COMMAND_PLAN_PROVENANCE}}
    ) == COMMAND_PLAN_PROVENANCE


@pytest.mark.parametrize(
    "value",
    [None, "", "powershell-command-plan-v0", "powershell-command-plan-v2", 1],
)
def test_unknown_explicit_command_provenance_fails_closed(value: object) -> None:
    with pytest.raises(RuntimeError, match="command_provenance_version"):
        select_version({"command_provenance": {"version": value}})


def test_command_provenance_rejects_changed_expected_hash() -> None:
    from complete_suite_adjudication import command_provenance_version

    campaign_bytes = runner.canonical_bytes({})
    with pytest.raises(RuntimeError, match="canonical campaign bytes"):
        command_provenance_version(
            campaign_bytes,
            expected_campaign_sha256="0" * 64,
        )


@pytest.mark.parametrize(
    "campaign_bytes",
    (
        b'{"command_provenance": {"version": "powershell-command-plan-v1"}}',
        (
            b'{"command_provenance":{"version":"powershell-command-plan-v1",'
            b'"version":"powershell-command-plan-v1"}}'
        ),
        runner.canonical_bytes({}) + b"\n",
    ),
    ids=("noncanonical", "duplicate-key", "trailing-bytes"),
)
def test_command_provenance_rejects_noncanonical_campaign_bytes(
    campaign_bytes: bytes,
) -> None:
    from complete_suite_adjudication import command_provenance_version

    with pytest.raises(RuntimeError, match="canonical campaign bytes"):
        command_provenance_version(
            campaign_bytes,
            expected_campaign_sha256=sha256(campaign_bytes).hexdigest(),
        )


def test_command_provenance_rejects_mutable_caller_buffer_before_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import complete_suite_adjudication as adjudication

    campaign_bytes = bytearray(runner.canonical_bytes({}))
    canonicalizer_called = False

    def unexpected_canonicalizer(value: object) -> bytes:
        nonlocal canonicalizer_called
        canonicalizer_called = True
        campaign_bytes[:] = b'{"command_provenance":null}'
        return runner.canonical_bytes(value)

    monkeypatch.setattr(adjudication.runner, "canonical_bytes", unexpected_canonicalizer)
    with pytest.raises(RuntimeError, match="canonical campaign bytes"):
        adjudication.command_provenance_version(  # type: ignore[arg-type]
            campaign_bytes,
            expected_campaign_sha256=sha256(campaign_bytes).hexdigest(),
        )
    assert canonicalizer_called is False


def test_command_provenance_selector_rejects_mapping_input() -> None:
    from complete_suite_adjudication import command_provenance_version

    with pytest.raises(RuntimeError, match="canonical campaign bytes"):
        command_provenance_version(  # type: ignore[arg-type]
            {},
            expected_campaign_sha256=sha256(b"{}").hexdigest(),
        )


@pytest.mark.parametrize(
    "value",
    (bytearray(b"{}"), memoryview(b"{}"), "{}"),
    ids=("bytearray", "memoryview", "text"),
)
def test_command_provenance_selector_accepts_only_exact_bytes(
    value: object,
) -> None:
    from complete_suite_adjudication import command_provenance_version

    with pytest.raises(RuntimeError, match="canonical campaign bytes"):
        command_provenance_version(  # type: ignore[arg-type]
            value,
            expected_campaign_sha256=sha256(b"{}").hexdigest(),
        )


def test_wrapper_models_are_exact_and_frozen() -> None:
    command_plan = _command_plan_module()
    assert tuple(command_plan.ShellIdentity.__dataclass_fields__) == (
        "path",
        "sha256",
        "file_version",
        "product_version",
        "edition",
        "parser_version",
    )
    assert tuple(command_plan.ExtractedPowerShellPayload.__dataclass_fields__) == (
        "rendered_utf8_bytes",
        "rendered_sha256",
        "payload_field_utf8_bytes",
        "payload_field_sha256",
        "payload_utf8_bytes",
        "payload_sha256",
        "payload",
    )

    shell = _shell()
    rendered = command_plan.render_powershell_argv(
        "",
        shell_path=SHELL_PATH,
        quote_style="single",
    )
    extracted = command_plan.extract_powershell_payload(rendered, shell=shell)

    with pytest.raises(FrozenInstanceError):
        shell.path = r"C:\alternate\pwsh.exe"
    with pytest.raises(FrozenInstanceError):
        extracted.payload = "changed"


def test_wrapper_single_quote_renderer_and_extractor_are_byte_exact() -> None:
    command_plan = _command_plan_module()
    payload = "Write-Output 'café'; " + "\\" * 2
    payload_field = b"'Write-Output ''caf\xc3\xa9''; " + b"\\" * 2 + b"'"
    expected = _raw_wrapper(payload_field)

    rendered = command_plan.render_powershell_argv(
        payload,
        shell_path=SHELL_PATH,
        quote_style="single",
    )
    assert rendered == expected

    extracted = command_plan.extract_powershell_payload(rendered, shell=_shell())
    _assert_extracted_metrics(
        extracted,
        rendered=rendered,
        payload_field=payload_field,
        payload=payload,
    )


def test_wrapper_double_quote_renderer_and_extractor_are_byte_exact() -> None:
    command_plan = _command_plan_module()
    payload = "alpha" + "\\" * 2 + '"café' + "\\" * 3
    payload_field = (
        b'"alpha' + b"\\" * 5 + b'"caf\xc3\xa9' + b"\\" * 6 + b'"'
    )
    expected = _raw_wrapper(payload_field)

    rendered = command_plan.render_powershell_argv(
        payload,
        shell_path=SHELL_PATH,
        quote_style="double",
    )
    assert rendered == expected

    extracted = command_plan.extract_powershell_payload(rendered, shell=_shell())
    _assert_extracted_metrics(
        extracted,
        rendered=rendered,
        payload_field=payload_field,
        payload=payload,
    )


def test_wrapper_double_quote_preserves_ordinary_path_backslashes() -> None:
    command_plan = _command_plan_module()
    payload = r"Get-Item C:\ordinary\path\file.txt"
    payload_field = rb'"Get-Item C:\ordinary\path\file.txt"'
    expected = _raw_wrapper(payload_field)

    rendered = command_plan.render_powershell_argv(
        payload,
        shell_path=SHELL_PATH,
        quote_style="double",
    )

    assert rendered == expected
    extracted = command_plan.extract_powershell_payload(rendered, shell=_shell())
    _assert_extracted_metrics(
        extracted,
        rendered=rendered,
        payload_field=payload_field,
        payload=payload,
    )


def test_wrapper_payload_may_contain_inner_command_metacharacters() -> None:
    command_plan = _command_plan_module()
    payload = "Write-Output ok | Out-String; & '.\\tool.ps1' > '.\\out.txt'"

    rendered = command_plan.render_powershell_argv(
        payload,
        shell_path=SHELL_PATH,
        quote_style="single",
    )

    assert command_plan.extract_powershell_payload(
        rendered,
        shell=_shell(),
    ).payload == payload


def test_wrapper_rendering_and_extraction_are_deterministic() -> None:
    command_plan = _command_plan_module()
    payload = "Get-Item " + "\\" * 4 + '"quoted"' + "\\" * 5
    shell = _shell()

    rendered_first = command_plan.render_powershell_argv(
        payload,
        shell_path=SHELL_PATH,
        quote_style="double",
    )
    rendered_second = command_plan.render_powershell_argv(
        payload,
        shell_path=SHELL_PATH,
        quote_style="double",
    )
    extracted_first = command_plan.extract_powershell_payload(
        rendered_first,
        shell=shell,
    )
    extracted_second = command_plan.extract_powershell_payload(
        rendered_second,
        shell=shell,
    )

    assert rendered_first == rendered_second
    assert extracted_first == extracted_second
    assert hash(extracted_first) == hash(extracted_second)


def test_payload_limit_accepts_exact_256_kib_of_decoded_utf8() -> None:
    command_plan = _command_plan_module()
    payload = "é" * (256 * 1024 // 2)

    rendered = command_plan.render_powershell_argv(
        payload,
        shell_path=SHELL_PATH,
        quote_style="single",
    )
    extracted = command_plan.extract_powershell_payload(rendered, shell=_shell())

    assert extracted.payload_utf8_bytes == 256 * 1024
    assert extracted.payload == payload


def test_payload_limit_rejects_one_decoded_utf8_byte_over_256_kib() -> None:
    command_plan = _command_plan_module()
    payload = "é" * (256 * 1024 // 2) + "x"

    _assert_stable_code(
        "COMMAND_PAYLOAD_LIMIT_EXCEEDED",
        lambda: command_plan.render_powershell_argv(
            payload,
            shell_path=SHELL_PATH,
            quote_style="single",
        ),
    )

    rendered = _raw_wrapper(b"'" + payload.encode("utf-8") + b"'")
    _assert_stable_code(
        "COMMAND_PAYLOAD_LIMIT_EXCEEDED",
        lambda: command_plan.extract_powershell_payload(rendered, shell=_shell()),
    )


def test_payload_limit_renderer_does_not_encode_multi_mibibyte_input() -> None:
    command_plan = _command_plan_module()
    payload = "a" * (4 * 1024 * 1024)

    if tracemalloc.is_tracing():
        pytest.skip("requires isolated tracemalloc state")
    tracemalloc.start()
    try:
        _assert_stable_code(
            "COMMAND_PAYLOAD_LIMIT_EXCEEDED",
            lambda: command_plan.render_powershell_argv(
                payload,
                shell_path=SHELL_PATH,
                quote_style="single",
            ),
        )
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak_bytes < len(payload) // 4


def test_payload_limit_renderer_validates_late_surrogate_before_limit() -> None:
    command_plan = _command_plan_module()
    payload = "a" * (PAYLOAD_LIMIT_BYTES + 1) + "\ud800"

    _assert_stable_code(
        "COMMAND_WRAPPER_INVALID",
        lambda: command_plan.render_powershell_argv(
            payload,
            shell_path=SHELL_PATH,
            quote_style="single",
        ),
    )


@pytest.mark.parametrize("quote_style", ("single", "double"))
def test_payload_limit_is_checked_before_decoded_buffer_allocation(
    quote_style: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_plan = _command_plan_module()
    delimiter = b"'" if quote_style == "single" else b'"'
    rendered = _raw_wrapper(
        delimiter + b"a" * (PAYLOAD_LIMIT_BYTES + 1) + delimiter
    )
    observed_sizes = _install_guarded_bytearray(monkeypatch, command_plan)

    _assert_stable_code(
        "COMMAND_PAYLOAD_LIMIT_EXCEEDED",
        lambda: command_plan.extract_powershell_payload(rendered, shell=_shell()),
    )
    assert not observed_sizes or max(observed_sizes) <= PAYLOAD_LIMIT_BYTES


@pytest.mark.parametrize(
    ("quote_style", "counter_name"),
    (
        ("single", "_count_single_quoted"),
        ("double", "_count_double_quoted"),
    ),
)
def test_wrapper_count_pass_receives_zero_copy_read_only_payload_view(
    quote_style: str,
    counter_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_plan = _command_plan_module()
    payload = r"Get-Item C:\ordinary\path\file.txt"
    rendered = command_plan.render_powershell_argv(
        payload,
        shell_path=SHELL_PATH,
        quote_style=quote_style,
    )
    original_counter = getattr(command_plan, counter_name)
    counter_called = False

    def guarded_counter(field: object) -> int:
        nonlocal counter_called
        counter_called = True
        assert type(field) is memoryview
        assert field.readonly is True
        assert field.obj is rendered
        return original_counter(field)

    monkeypatch.setattr(command_plan, counter_name, guarded_counter)

    extracted = command_plan.extract_powershell_payload(rendered, shell=_shell())

    assert counter_called is True
    assert extracted.payload == payload


@pytest.mark.parametrize("quote_style", ("single", "double"))
def test_wrapper_malformed_oversize_field_is_rejected_before_allocation(
    quote_style: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_plan = _command_plan_module()
    delimiter = b"'" if quote_style == "single" else b'"'
    rendered = _raw_wrapper(
        delimiter
        + b"a" * (PAYLOAD_LIMIT_BYTES + 1)
        + delimiter
        + b" trailing"
    )
    observed_sizes = _install_guarded_bytearray(monkeypatch, command_plan)

    _assert_stable_code(
        "COMMAND_WRAPPER_INVALID",
        lambda: command_plan.extract_powershell_payload(rendered, shell=_shell()),
    )
    assert not observed_sizes or max(observed_sizes) <= PAYLOAD_LIMIT_BYTES


@pytest.mark.parametrize(
    ("case", "payload_bytes", "expected"),
    ACCEPTED_UTF8_BOUNDARIES,
    ids=[case for case, _, _ in ACCEPTED_UTF8_BOUNDARIES],
)
@pytest.mark.parametrize("quote_style", ("single", "double"))
def test_wrapper_accepts_strict_utf8_boundary_table(
    case: str,
    payload_bytes: bytes,
    expected: str,
    quote_style: str,
) -> None:
    del case
    command_plan = _command_plan_module()
    delimiter = b"'" if quote_style == "single" else b'"'
    rendered = _raw_wrapper(delimiter + payload_bytes + delimiter)

    extracted = command_plan.extract_powershell_payload(rendered, shell=_shell())

    assert extracted.payload == expected
    assert extracted.payload_utf8_bytes == len(payload_bytes)
    assert extracted.payload_sha256 == sha256(payload_bytes).hexdigest()


@pytest.mark.parametrize(
    ("case", "payload_bytes"),
    REJECTED_UTF8_BOUNDARIES,
    ids=[case for case, _ in REJECTED_UTF8_BOUNDARIES],
)
def test_wrapper_rejects_strict_utf8_boundary_table(
    case: str,
    payload_bytes: bytes,
) -> None:
    del case
    command_plan = _command_plan_module()
    rendered = _raw_wrapper(b"'" + payload_bytes + b"'")

    _assert_stable_code(
        "COMMAND_WRAPPER_INVALID",
        lambda: command_plan.extract_powershell_payload(rendered, shell=_shell()),
    )


@pytest.mark.parametrize(
    "rendered",
    (
        b'"' + SHELL_PATH.encode("utf-8") + b'" -NoProfile -NonInteractive -Command \'\'',
        b'"' + SHELL_PATH.encode("utf-8") + b'" -NoProfile -NoLogo -NonInteractive -Command \'\'',
        b'"' + SHELL_PATH.encode("utf-8") + b'" -NoLogo -NoLogo -NoProfile -NonInteractive -Command \'\'',
        b'"' + SHELL_PATH.encode("utf-8") + b'" -NoLogo -NoProfile -NonInteractive -EncodedCommand \'AA==\'',
        b'"' + SHELL_PATH.encode("utf-8") + b'" -NoLogo -NoProfile -NonInteractive -File \'script.ps1\'',
        b'"' + SHELL_PATH.encode("utf-8") + b'" -NoLogo -NoProfile -NonInteractive -Command -',
        _raw_wrapper(b"''") + b" extra",
        _raw_wrapper(b"''") + b"; wrapper",
        _raw_wrapper(b"''") + b" | wrapper",
        _raw_wrapper(b"''") + b" > out.txt",
        _raw_wrapper(b"''") + b" &",
        b"wrapper " + _raw_wrapper(b"''"),
        _raw_wrapper(b"'unterminated"),
        _raw_wrapper(b'"unterminated'),
        _raw_wrapper(b"'can\\'t'"),
        _raw_wrapper(b'"say ""hello"""'),
        _raw_wrapper(b'"say `"hello`""'),
        _raw_wrapper(b"unquoted"),
        _raw_wrapper(b"'nul\x00byte'"),
        _raw_wrapper(b"'carriage\rreturn'"),
        _raw_wrapper(b"'invalid-\xff-utf8'"),
        _raw_wrapper(b"''") + b"\n",
        b"\xef\xbb\xbf" + _raw_wrapper(b"''"),
        _raw_wrapper(b"''", shell_path="pwsh.exe"),
    ),
    ids=(
        "missing-flag",
        "reordered-flags",
        "duplicated-flag",
        "encoded-command",
        "file",
        "stdin-script",
        "extra-argv",
        "outer-semicolon",
        "outer-pipeline",
        "outer-redirection",
        "outer-background",
        "outer-wrapper-text",
        "unterminated-single",
        "unterminated-double",
        "alternate-single-escape",
        "alternate-double-doubling",
        "alternate-double-backtick",
        "unquoted-payload",
        "nul",
        "carriage-return",
        "invalid-utf8",
        "terminal-newline",
        "bom",
        "relative-shell",
    ),
)
def test_wrapper_rejects_every_noncanonical_outer_shape(rendered: bytes) -> None:
    command_plan = _command_plan_module()
    _assert_stable_code(
        "COMMAND_WRAPPER_INVALID",
        lambda: command_plan.extract_powershell_payload(rendered, shell=_shell()),
    )


def test_wrapper_rejects_a_rendered_path_different_from_observed_identity() -> None:
    command_plan = _command_plan_module()
    alternate_path = r"D:\Frozen\PowerShell\pwsh.exe"
    rendered = command_plan.render_powershell_argv(
        "Get-Date",
        shell_path=alternate_path,
        quote_style="single",
    )

    _assert_stable_code(
        "COMMAND_WRAPPER_IDENTITY_MISMATCH",
        lambda: command_plan.extract_powershell_payload(rendered, shell=_shell()),
    )


def test_wrapper_rejects_invalid_utf8_before_identity_comparison() -> None:
    command_plan = _command_plan_module()
    rendered = _raw_wrapper(
        b"'invalid-\xff-utf8'",
        shell_path=r"D:\Frozen\PowerShell\pwsh.exe",
    )

    _assert_stable_code(
        "COMMAND_WRAPPER_INVALID",
        lambda: command_plan.extract_powershell_payload(rendered, shell=_shell()),
    )


def test_wrapper_validation_precedes_shell_identity_mismatch() -> None:
    command_plan = _command_plan_module()
    rendered = _raw_wrapper(
        b'"say ""hello"""',
        shell_path=r"D:\Frozen\PowerShell\pwsh.exe",
    )

    _assert_stable_code(
        "COMMAND_WRAPPER_INVALID",
        lambda: command_plan.extract_powershell_payload(rendered, shell=_shell()),
    )


def test_payload_limit_precedes_shell_identity_mismatch() -> None:
    command_plan = _command_plan_module()
    rendered = _raw_wrapper(
        b"'" + b"a" * (256 * 1024 + 1) + b"'",
        shell_path=r"D:\Frozen\PowerShell\pwsh.exe",
    )

    _assert_stable_code(
        "COMMAND_PAYLOAD_LIMIT_EXCEEDED",
        lambda: command_plan.extract_powershell_payload(rendered, shell=_shell()),
    )


@pytest.mark.parametrize(
    ("payload", "shell_path", "quote_style"),
    (
        ("nul\x00byte", SHELL_PATH, "single"),
        ("carriage\rreturn", SHELL_PATH, "single"),
        ("lone-surrogate-\ud800", SHELL_PATH, "single"),
        ("payload", "pwsh.exe", "single"),
        ("payload", "relative\\pwsh.exe", "double"),
        ("payload", 'C:\\bad"path\\pwsh.exe', "single"),
        ("payload", SHELL_PATH, "alternate"),
    ),
    ids=(
        "nul",
        "carriage-return",
        "lone-surrogate",
        "bare-relative-shell",
        "nested-relative-shell",
        "quoted-shell",
        "unsupported-quote-style",
    ),
)
def test_wrapper_renderer_rejects_invalid_inputs(
    payload: str,
    shell_path: str,
    quote_style: str,
) -> None:
    command_plan = _command_plan_module()
    _assert_stable_code(
        "COMMAND_WRAPPER_INVALID",
        lambda: command_plan.render_powershell_argv(
            payload,
            shell_path=shell_path,
            quote_style=quote_style,
        ),
    )


@pytest.mark.parametrize(
    "rendered",
    (bytearray(_raw_wrapper(b"''")), memoryview(_raw_wrapper(b"''")), "text"),
    ids=("bytearray", "memoryview", "text"),
)
def test_wrapper_extractor_accepts_only_exact_bytes(rendered: object) -> None:
    command_plan = _command_plan_module()
    _assert_stable_code(
        "COMMAND_WRAPPER_INVALID",
        lambda: command_plan.extract_powershell_payload(rendered, shell=_shell()),
    )


def test_wrapper_extractor_requires_exact_shell_identity_type() -> None:
    command_plan = _command_plan_module()
    base_shell = _shell()

    class ShellIdentitySubclass(command_plan.ShellIdentity):
        pass

    subclass_shell = ShellIdentitySubclass(
        path=base_shell.path,
        sha256=base_shell.sha256,
        file_version=base_shell.file_version,
        product_version=base_shell.product_version,
        edition=base_shell.edition,
        parser_version=base_shell.parser_version,
    )
    rendered = command_plan.render_powershell_argv(
        "Get-Date",
        shell_path=SHELL_PATH,
        quote_style="single",
    )

    _assert_stable_code(
        "COMMAND_WRAPPER_INVALID",
        lambda: command_plan.extract_powershell_payload(
            rendered,
            shell=subclass_shell,
        ),
    )


def test_wrapper_renderer_requires_exact_quote_style_type() -> None:
    command_plan = _command_plan_module()
    comparisons: list[object] = []

    class EqualToDouble:
        def __eq__(self, other: object) -> bool:
            comparisons.append(other)
            return other == "double"

    _assert_stable_code(
        "COMMAND_WRAPPER_INVALID",
        lambda: command_plan.render_powershell_argv(
            "Get-Date",
            shell_path=SHELL_PATH,
            quote_style=EqualToDouble(),
        ),
    )
    assert comparisons == []


def test_decoder_models_are_exact_closed_and_frozen() -> None:
    command_plan = _command_plan_module()
    assert tuple(command_plan.DecoderLimits.__dataclass_fields__) == (
        "payload_bytes",
        "tokens",
        "parse_errors",
        "ast_nodes",
        "ast_depth",
        "statements",
        "operations",
        "pipeline_stages",
        "plan_bytes",
    )
    assert command_plan.DecoderLimits() == command_plan.DecoderLimits(
        payload_bytes=256 * 1024,
        tokens=8192,
        parse_errors=256,
        ast_nodes=8192,
        ast_depth=64,
        statements=256,
        operations=256,
        pipeline_stages=256,
        plan_bytes=4 * 1024 * 1024,
    )
    assert tuple(command_plan.DecodedPowerShellPayload.__dataclass_fields__) == (
        "schema_version",
        "canonical_bytes",
        "canonical_sha256",
        "token_count",
        "parse_error_count",
    )
    canonical = _compact_json(_decoder_document(b""))
    decoded = command_plan.DecodedPowerShellPayload(
        schema_version=DECODER_SCHEMA_VERSION,
        canonical_bytes=canonical,
        canonical_sha256=sha256(canonical).hexdigest(),
        token_count=0,
        parse_error_count=0,
    )
    assert repr(decoded).find("canonical_bytes") == -1
    with pytest.raises(FrozenInstanceError):
        decoded.token_count = 1
    with pytest.raises(FrozenInstanceError):
        command_plan.DecoderLimits().tokens = 1


def test_decoder_document_version_is_distinct_from_command_provenance() -> None:
    command_plan = _command_plan_module()
    canonical = _compact_json(_decoder_document(b""))
    _assert_stable_code(
        "COMMAND_PLAN_SCHEMA_INVALID",
        lambda: command_plan.DecodedPowerShellPayload(
            schema_version=COMMAND_PLAN_PROVENANCE,
            canonical_bytes=canonical,
            canonical_sha256=sha256(canonical).hexdigest(),
            token_count=0,
            parse_error_count=0,
        ),
    )


def test_decoder_public_api_signature_is_exact_and_has_no_runtime_limits() -> None:
    command_plan = _command_plan_module()
    signature = inspect.signature(command_plan.decode_powershell_payload)
    assert tuple(signature.parameters) == (
        "payload",
        "shell",
        "decoder_path",
        "decoder_sha256",
    )
    assert signature.parameters["payload"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    for name in ("shell", "decoder_path", "decoder_sha256"):
        assert signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
    assert get_type_hints(command_plan.decode_powershell_payload) == {
        "payload": bytes,
        "shell": command_plan.ShellIdentity,
        "decoder_path": Path,
        "decoder_sha256": str,
        "return": command_plan.DecodedPowerShellPayload,
    }
    assert "limits" not in signature.parameters


def test_decoder_nondefault_limits_cannot_describe_the_v1_contract() -> None:
    command_plan = _command_plan_module()
    _assert_stable_code(
        "COMMAND_DECODER_LIMIT_EXCEEDED",
        lambda: command_plan.DecoderLimits(tokens=1),
    )


@pytest.mark.parametrize(
    "mutation",
    ("missing-required", "recursive-extra"),
)
def test_decoder_decoded_payload_embedded_document_must_validate_the_full_schema(
    mutation: str,
) -> None:
    command_plan = _command_plan_module()
    document = _empty_decoder_document()
    if mutation == "missing-required":
        del document["metrics"]
    else:
        document["payload"]["invented"] = True
    canonical = _compact_json(document)
    _assert_stable_code(
        "COMMAND_PLAN_SCHEMA_INVALID",
        lambda: command_plan.DecodedPowerShellPayload(
            schema_version=DECODER_SCHEMA_VERSION,
            canonical_bytes=canonical,
            canonical_sha256=sha256(canonical).hexdigest(),
            token_count=0,
            parse_error_count=0,
        ),
    )


@pytest.mark.parametrize(
    ("token_count", "parse_error_count"),
    ((1, 0), (0, 1)),
    ids=("token-count", "parse-error-count"),
)
def test_decoder_decoded_payload_counts_cohere_with_embedded_arrays(
    token_count: int,
    parse_error_count: int,
) -> None:
    command_plan = _command_plan_module()
    canonical = _compact_json(_empty_decoder_document())
    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan.DecodedPowerShellPayload(
            schema_version=DECODER_SCHEMA_VERSION,
            canonical_bytes=canonical,
            canonical_sha256=sha256(canonical).hexdigest(),
            token_count=token_count,
            parse_error_count=parse_error_count,
        ),
    )


def test_decoder_public_result_and_shell_fields_require_exact_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_plan, _, _ = _install_fake_decoder(monkeypatch, payload=b"")
    decoded = _decode_with_fake(command_plan, b"")
    assert type(decoded) is command_plan.DecodedPowerShellPayload

    command_plan, _, calls = _install_fake_decoder(monkeypatch, payload=b"")

    class CoreSubclass(str):
        pass

    shell = _shell()
    nonexact = command_plan.ShellIdentity(
        path=shell.path,
        sha256=shell.sha256,
        file_version=shell.file_version,
        product_version=shell.product_version,
        edition=CoreSubclass("Core"),
        parser_version=shell.parser_version,
    )
    _assert_stable_code(
        "COMMAND_DECODER_IDENTITY_MISMATCH",
        lambda: command_plan.decode_powershell_payload(
            b"",
            shell=nonexact,
            decoder_path=DECODER_PATH,
            decoder_sha256="2" * 64,
        ),
    )
    assert calls == []


def test_decoder_decoded_payload_constructor_revalidates_embedded_version_and_hash(
) -> None:
    command_plan = _command_plan_module()
    document = _empty_decoder_document()
    document["schema_version"] = COMMAND_PLAN_PROVENANCE
    canonical = _compact_json(document)
    _assert_stable_code(
        "COMMAND_PLAN_SCHEMA_INVALID",
        lambda: command_plan.DecodedPowerShellPayload(
            schema_version=DECODER_SCHEMA_VERSION,
            canonical_bytes=canonical,
            canonical_sha256=sha256(canonical).hexdigest(),
            token_count=0,
            parse_error_count=0,
        ),
    )
    valid = _compact_json(_empty_decoder_document())
    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan.DecodedPowerShellPayload(
            schema_version=DECODER_SCHEMA_VERSION,
            canonical_bytes=valid,
            canonical_sha256="0" * 64,
            token_count=0,
            parse_error_count=0,
        ),
    )


@pytest.mark.parametrize(
    "payload",
    (bytearray(b""), memoryview(b""), ""),
    ids=("bytearray", "memoryview", "text"),
)
def test_decoder_public_boundary_accepts_only_exact_payload_bytes(
    payload: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_plan, _, calls = _install_fake_decoder(monkeypatch, payload=b"")
    _assert_stable_code(
        "COMMAND_DECODER_PARSE_INVALID",
        lambda: command_plan.decode_powershell_payload(
            payload,
            shell=_shell(),
            decoder_path=DECODER_PATH,
            decoder_sha256="2" * 64,
        ),
    )
    assert calls == []


def test_decoder_public_boundary_rejects_shell_subclass_and_digest_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_plan, _, calls = _install_fake_decoder(monkeypatch, payload=b"")
    base = _shell()

    class ShellSubclass(command_plan.ShellIdentity):
        pass

    subclass = ShellSubclass(
        path=base.path,
        sha256=base.sha256,
        file_version=base.file_version,
        product_version=base.product_version,
        edition=base.edition,
        parser_version=base.parser_version,
    )
    for shell, digest in ((subclass, "2" * 64), (base, "A" * 64)):
        _assert_stable_code(
            "COMMAND_DECODER_IDENTITY_MISMATCH",
            lambda shell=shell, digest=digest: command_plan.decode_powershell_payload(
                b"",
                shell=shell,
                decoder_path=DECODER_PATH,
                decoder_sha256=digest,
            ),
        )
    assert calls == []


def test_decoder_schema_accepts_the_exact_minimal_closed_document() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    document = _empty_decoder_document()
    validator.validate(document)
    assert document["nodes"] == []
    assert document["metrics"] == {
        "ast_nodes": 0,
        "ast_depth": 0,
        "statements": 0,
        "operations": 0,
        "pipeline_stages": 0,
    }


def test_decoder_literal_decoder_schema_accepts_populated_token_error_literal_and_node() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    payload = b"'x'"
    literal = {
        "kind": "single_quoted",
        "value": "x",
        "utf8_bytes": 1,
        "sha256": sha256(b"x").hexdigest(),
    }
    document = _decoder_document(
        payload,
        parse_errors=[
            {
                "index": 0,
                "error_id": "Representative.Parser.Error",
                "incomplete_input": False,
                "start_utf16": 3,
                "end_utf16": 3,
                "start_utf8": 3,
                "end_utf8": 3,
                "message_sha256": sha256(b"message").hexdigest(),
            }
        ],
        tokens=[
            {
                "index": 0,
                "kind": "StringLiteral",
                "flags": ["CommandName"],
                "start_utf16": 0,
                "end_utf16": 3,
                "start_utf8": 0,
                "end_utf8": 3,
                "text_sha256": sha256(payload).hexdigest(),
                "literal": dict(literal),
            }
        ],
        nodes=[
            {
                "index": 0,
                "ast_type": "StringConstantExpressionAst",
                "role": "expression",
                "parent_index": None,
                "child_indices": [],
                "start_utf16": 0,
                "end_utf16": 3,
                "start_utf8": 0,
                "end_utf8": 3,
                "invocation_operator": None,
                "literal": dict(literal),
            }
        ],
        metrics={
            "ast_nodes": 1,
            "ast_depth": 1,
            "statements": 0,
            "operations": 0,
            "pipeline_stages": 0,
        },
    )

    validator.validate(document)


def test_decoder_schema_exact_property_sets_are_frozen() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    properties = schema["properties"]
    definitions = schema["$defs"]
    assert set(properties) == {
        "schema_version",
        "payload",
        "powershell",
        "decoder",
        "parse_errors",
        "tokens",
        "nodes",
        "metrics",
    }
    assert set(properties["payload"]["properties"]) == {
        "utf8_bytes",
        "sha256",
    }
    assert set(properties["powershell"]["properties"]) == {
        "path",
        "sha256",
        "file_version",
        "product_version",
        "edition",
        "parser_version",
    }
    assert set(properties["decoder"]["properties"]) == {"path", "sha256"}
    assert set(properties["metrics"]["properties"]) == {
        "ast_nodes",
        "ast_depth",
        "statements",
        "operations",
        "pipeline_stages",
    }
    assert set(definitions) == {
        "sha256",
        "nonempty_identity",
        "token_kind",
        "token_flag",
        "ast_type",
        "role",
        "literal",
        "nullable_literal",
        "token",
        "node",
        "parse_error",
        "utf16_offset",
        "utf8_offset",
    }
    assert set(definitions["literal"]["properties"]) == {
        "kind",
        "value",
        "utf8_bytes",
        "sha256",
    }
    assert set(definitions["token"]["properties"]) == {
        "index",
        "kind",
        "flags",
        "start_utf16",
        "end_utf16",
        "start_utf8",
        "end_utf8",
        "text_sha256",
        "literal",
    }
    assert set(definitions["node"]["properties"]) == {
        "index",
        "ast_type",
        "role",
        "parent_index",
        "child_indices",
        "start_utf16",
        "end_utf16",
        "start_utf8",
        "end_utf8",
        "invocation_operator",
        "literal",
    }
    assert set(definitions["parse_error"]["properties"]) == {
        "index",
        "error_id",
        "incomplete_input",
        "start_utf16",
        "end_utf16",
        "start_utf8",
        "end_utf8",
        "message_sha256",
    }


def test_decoder_schema_rejects_provenance_version_and_recursive_extras() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    document = _decoder_document(b"")
    mutations = []
    wrong_version = json.loads(json.dumps(document))
    wrong_version["schema_version"] = COMMAND_PLAN_PROVENANCE
    mutations.append(wrong_version)
    for trail in (
        (),
        ("payload",),
        ("powershell",),
        ("decoder",),
        ("metrics",),
        ("nodes", 0),
    ):
        mutant = json.loads(json.dumps(document))
        target: Any = mutant
        for part in trail:
            target = target[part]
        target["invented"] = True
        mutations.append(mutant)

    for mutant in mutations:
        assert not validator.is_valid(mutant)


def test_schema_recursive_closure_covers_every_object_definition() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    pending: list[object] = [schema]
    object_schemas = 0
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if value.get("type") == "object":
                object_schemas += 1
                assert value.get("additionalProperties") is False
                assert set(value.get("required", [])) == set(
                    value.get("properties", {})
                )
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    assert object_schemas == 9


def test_decoder_enum_drift_schema_enum_sets_are_exact_unique_and_literal() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    definitions = schema["$defs"]
    expected = {
        "token_kind": TOKEN_KINDS,
        "token_flag": TOKEN_FLAGS,
        "ast_type": AST_TYPES,
        "role": AST_ROLES,
    }
    for name, values in expected.items():
        observed = tuple(definitions[name]["enum"])
        assert observed == values
        assert len(observed) == len(set(observed))
        assert all(type(value) is str and value for value in observed)


def test_decoder_enum_drift_token_enum_contract_is_exact_across_schema_python_and_powershell() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    command_plan = _command_plan_module()
    source = DECODER_PATH.read_text(encoding="utf-8")
    powershell_kinds, kinds_end = _strict_powershell_string_array(
        source,
        "closedTokenKinds",
    )
    powershell_flags, flags_end = _strict_powershell_string_array(
        source,
        "closedTokenFlags",
    )

    assert source[kinds_end:].startswith(
        "$closedTokenFlags = [string[]]@(\n"
    )
    assert source[flags_end:].startswith(
        "$closedTokenKindSet = [System.Collections.Generic.HashSet[string]]"
    )
    assert tuple(schema["$defs"]["token_kind"]["enum"]) == TOKEN_KINDS
    assert tuple(schema["$defs"]["token_flag"]["enum"]) == TOKEN_FLAGS
    assert type(command_plan._TOKEN_KINDS) is frozenset
    assert type(command_plan._TOKEN_FLAGS) is frozenset
    assert command_plan._TOKEN_KINDS == frozenset(TOKEN_KINDS)
    assert command_plan._TOKEN_FLAGS == frozenset(TOKEN_FLAGS)
    assert powershell_kinds == TOKEN_KINDS
    assert powershell_flags == TOKEN_FLAGS
    assert len(powershell_kinds) == len(set(powershell_kinds))
    assert len(powershell_flags) == len(set(powershell_flags))
    assert command_plan._SAFE_TOKEN_LITERAL_KINDS == frozenset(
        {"Identifier", "Number", "StringLiteral"}
    )


def test_decoder_schema_entry_arrays_have_exact_closed_limits() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    properties = schema["properties"]
    assert properties["tokens"]["maxItems"] == 8192
    assert properties["parse_errors"]["maxItems"] == 256
    assert properties["nodes"]["maxItems"] == 8192
    assert properties["tokens"]["items"] == {"$ref": "#/$defs/token"}
    assert properties["parse_errors"]["items"] == {
        "$ref": "#/$defs/parse_error"
    }
    assert properties["nodes"]["items"] == {"$ref": "#/$defs/node"}


def test_decoder_schema_fragments_bind_exact_digest_index_and_offset_bounds() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    definitions = schema["$defs"]
    assert definitions["sha256"] == {
        "type": "string",
        "pattern": "^[0-9a-f]{64}$",
    }
    assert definitions["utf16_offset"] == {
        "type": "integer",
        "minimum": 0,
        "maximum": 262144,
    }
    assert definitions["utf8_offset"] == definitions["utf16_offset"]
    assert definitions["token"]["properties"]["index"] == {
        "type": "integer",
        "minimum": 0,
        "maximum": 8191,
    }
    assert definitions["parse_error"]["properties"]["index"] == {
        "type": "integer",
        "minimum": 0,
        "maximum": 255,
    }
    assert definitions["literal"]["additionalProperties"] is False
    assert definitions["node"]["properties"]["invocation_operator"] == {
        "enum": [None, "none", "call", "dot"]
    }


def test_decoder_schema_every_digest_and_adjacent_entry_fragment_is_exact() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    properties = schema["properties"]
    definitions = schema["$defs"]
    digest_fragments = (
        properties["payload"]["properties"]["sha256"],
        properties["powershell"]["properties"]["sha256"],
        properties["decoder"]["properties"]["sha256"],
        definitions["literal"]["properties"]["sha256"],
        definitions["token"]["properties"]["text_sha256"],
        definitions["parse_error"]["properties"]["message_sha256"],
    )
    assert digest_fragments
    assert all(
        fragment == {"$ref": "#/$defs/sha256"}
        for fragment in digest_fragments
    )
    assert definitions["literal"]["properties"]["kind"] == {
        "enum": ["bare", "single_quoted", "double_quoted"]
    }
    assert definitions["literal"]["properties"]["value"] == {
        "type": "string",
        "maxLength": 262144,
    }
    assert definitions["literal"]["properties"]["utf8_bytes"] == {
        "type": "integer",
        "minimum": 0,
        "maximum": 262144,
    }
    assert definitions["nullable_literal"] == {
        "oneOf": [
            {"type": "null"},
            {"$ref": "#/$defs/literal"},
        ]
    }
    assert definitions["token"]["properties"]["flags"] == {
        "type": "array",
        "maxItems": 28,
        "uniqueItems": True,
        "items": {"$ref": "#/$defs/token_flag"},
    }
    assert definitions["node"]["properties"]["child_indices"] == {
        "type": "array",
        "maxItems": 8192,
        "uniqueItems": True,
        "items": {
            "type": "integer",
            "minimum": 1,
            "maximum": 8191,
        },
    }
    for definition, maximum in (
        ("token", 8191),
        ("node", 8191),
        ("parse_error", 255),
    ):
        assert definitions[definition]["properties"]["index"] == {
            "type": "integer",
            "minimum": 0,
            "maximum": maximum,
        }


@pytest.mark.parametrize(
    ("trail", "value"),
    (
        (("payload", "utf8_bytes"), 262145),
        (("payload", "sha256"), "A" * 64),
        (("nodes", 0, "index"), 8192),
        (("nodes", 0, "start_utf16"), -1),
        (("nodes", 0, "end_utf8"), 262145),
        (("nodes", 0, "child_indices"), [1, 1]),
        (("metrics", "ast_depth"), 65),
        (("metrics", "operations"), 257),
    ),
    ids=(
        "payload-byte-over",
        "uppercase-digest",
        "node-index-over",
        "negative-utf16",
        "utf8-over",
        "duplicate-child",
        "depth-over",
        "operation-over",
    ),
)
def test_decoder_schema_rejects_exact_boundary_mutants(
    trail: tuple[object, ...],
    value: object,
) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    document = _decoder_document(b"")
    target: Any = document
    for part in trail[:-1]:
        target = target[part]
    target[trail[-1]] = value
    assert validator.is_valid(document) is False


def test_decoder_process_boundary_uses_exact_argv_bytes_and_pipes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"Get-Date"
    command_plan, process, calls = _install_fake_decoder(
        monkeypatch,
        payload=payload,
    )

    decoded = _decode_with_fake(command_plan, payload)

    assert decoded.schema_version == DECODER_SCHEMA_VERSION
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (
        [
            SHELL_PATH,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(DECODER_PATH),
        ],
    )
    assert set(kwargs) == {
        "shell",
        "stdin",
        "stdout",
        "stderr",
        "text",
        "env",
        "close_fds",
        "bufsize",
    }
    assert kwargs["shell"] is False
    assert kwargs["stdin"] is subprocess.PIPE
    assert kwargs["stdout"] is subprocess.PIPE
    assert kwargs["stderr"] is subprocess.PIPE
    assert kwargs["text"] is False
    assert kwargs["close_fds"] is True
    assert kwargs["bufsize"] == 0
    assert b"".join(process.stdin.chunks) == payload
    assert process.stdin.closed is True
    assert process.stdout.read_sizes and set(process.stdout.read_sizes) == {65536}
    assert process.stderr.read_sizes and set(process.stderr.read_sizes) == {65536}
    assert process.wait_timeouts and 0 < process.wait_timeouts[0] <= 30


def test_decoder_environment_is_the_exact_closed_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"Get-Date"
    command_plan, _, calls = _install_fake_decoder(monkeypatch, payload=payload)
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    monkeypatch.setenv("WINDIR", r"C:\Windows")
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")
    monkeypatch.setenv("PATH", r"D:\attacker")
    monkeypatch.setenv("PSModulePath", r"D:\attacker\modules")
    monkeypatch.setenv("HTTP_PROXY", "http://attacker.invalid")

    _decode_with_fake(command_plan, payload)

    child_environment = calls[0][1]["env"]
    temp_root = r"D:\tmp\kokoroarc-command-decoder-test-0001"
    assert child_environment == {
        "SYSTEMROOT": r"C:\Windows",
        "WINDIR": r"C:\Windows",
        "COMSPEC": r"C:\Windows\System32\cmd.exe",
        "PATHEXT": ".COM;.EXE;.BAT;.CMD",
        "TEMP": temp_root,
        "TMP": temp_root,
        "POWERSHELL_TELEMETRY_OPTOUT": "1",
        "POWERSHELL_UPDATECHECK": "Off",
    }
    assert set(child_environment).isdisjoint(
        {
            "PATH",
            "PSModulePath",
            "USERPROFILE",
            "HOME",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "SSL_CERT_FILE",
            "OPENAI_API_KEY",
        }
    )
    assert Path(child_environment["TEMP"]).is_relative_to(Path(r"D:\tmp"))
    assert child_environment["TMP"] == child_environment["TEMP"]


def test_decoder_identity_rechecks_shell_and_decoder_before_and_after_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"Get-Date"
    shell_pre = object()
    decoder_pre = object()
    command_plan, process, _ = _install_fake_decoder(
        monkeypatch,
        payload=payload,
        identity_sequence=[shell_pre, decoder_pre, shell_pre, decoder_pre],
    )

    _decode_with_fake(command_plan, payload)

    assert process.identity_calls == [
        (Path(SHELL_PATH), "1" * 64),
        (DECODER_PATH, "2" * 64),
        (Path(SHELL_PATH), "1" * 64),
        (DECODER_PATH, "2" * 64),
    ]


@pytest.mark.parametrize(
    "drift_target",
    ("shell", "decoder"),
    ids=("shell-postcheck", "decoder-postcheck"),
)
def test_decoder_identity_drift_fails_closed(
    drift_target: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"Get-Date"
    stable_shell = object()
    stable_decoder = object()
    if drift_target == "shell":
        sequence = [stable_shell, stable_decoder, object(), stable_decoder]
    else:
        sequence = [stable_shell, stable_decoder, stable_shell, object()]
    command_plan, _, _ = _install_fake_decoder(
        monkeypatch,
        payload=payload,
        identity_sequence=sequence,
    )

    _assert_stable_code(
        "COMMAND_DECODER_IDENTITY_MISMATCH",
        lambda: _decode_with_fake(command_plan, payload),
    )


@pytest.mark.parametrize(
    ("trail", "mutated"),
    (
        (("powershell", "path"), r"D:\Pinned\PowerShell\pwsh.exe"),
        (("powershell", "sha256"), "3" * 64),
        (("powershell", "file_version"), "7.6.0.1"),
        (("powershell", "product_version"), "7.6.0-preview.1"),
        (("powershell", "parser_version"), "7.6.1"),
        (("decoder", "path"), "tests/skills/other_decoder.ps1"),
        (("decoder", "sha256"), "4" * 64),
    ),
    ids=(
        "powershell-path",
        "powershell-sha256",
        "powershell-file-version",
        "powershell-product-version",
        "powershell-parser-version",
        "decoder-path",
        "decoder-sha256",
    ),
)
def test_decoder_valid_schema_identity_drift_reaches_parent_rejection(
    trail: tuple[str, str],
    mutated: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"Get-Date"
    document = _decoder_document(
        payload,
        tokens=[_end_of_input_token_entry(payload, index=0)],
    )
    command_plan = _command_plan_module()
    assert command_plan._validate_decoder_parent_document(
        document,
        payload=payload,
        shell=_shell(),
        decoder_sha256="2" * 64,
    ) == (1, 0)
    document[trail[0]][trail[1]] = mutated
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert Draft202012Validator(schema).is_valid(document)
    command_plan, _, _ = _install_fake_decoder(
        monkeypatch,
        payload=payload,
        stdout=_compact_json(document),
    )

    _assert_stable_code(
        "COMMAND_DECODER_IDENTITY_MISMATCH",
        lambda: _decode_with_fake(command_plan, payload),
    )


def test_decoder_boundary_orders_vector_prechecks_spawn_and_postchecks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"Get-Date"
    command_plan = _command_plan_module()
    events: list[str] = []
    original_vector = command_plan._windows_native_vector
    process = _FakeDecoderProcess(
        _compact_json(
            _decoder_document(
                payload,
                tokens=[_end_of_input_token_entry(payload, index=0)],
            )
        )
    )
    observations = ["shell", "decoder", "shell", "decoder"]

    def vector(*args: object, **kwargs: object) -> object:
        events.append("native-vector")
        return original_vector(*args, **kwargs)

    def observe(path: Path, digest: str) -> str:
        del path, digest
        value = observations.pop(0)
        events.append(f"identity-{value}-{'pre' if len(observations) >= 2 else 'post'}")
        return value

    def make_temp() -> Path:
        events.append("temp-root")
        return Path(r"D:\tmp\ordered-decoder-root")

    def popen(*args: object, **kwargs: object) -> _FakeDecoderProcess:
        del args, kwargs
        events.append("popen")
        return process

    monkeypatch.setattr(command_plan, "_windows_native_vector", vector)
    monkeypatch.setattr(command_plan, "_observe_plain_file", observe)
    monkeypatch.setattr(command_plan, "_make_decoder_temp_root", make_temp)
    monkeypatch.setattr(
        command_plan,
        "_remove_decoder_temp_root",
        lambda path: events.append("cleanup"),
    )
    monkeypatch.setattr(command_plan, "_POPEN", popen)

    _decode_with_fake(command_plan, payload)

    assert events == [
        "native-vector",
        "identity-shell-pre",
        "identity-decoder-pre",
        "temp-root",
        "popen",
        "identity-shell-post",
        "identity-decoder-post",
        "cleanup",
    ]


def test_decoder_precheck_failure_never_prepares_temp_or_spawns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_plan = _command_plan_module()
    events: list[str] = []
    original_vector = command_plan._windows_native_vector
    monkeypatch.setattr(
        command_plan,
        "_windows_native_vector",
        lambda *args, **kwargs: (
            events.append("native-vector") or original_vector(*args, **kwargs)
        ),
    )

    def reject_precheck(path: Path, digest: str) -> object:
        del path, digest
        events.append("identity-pre")
        raise RuntimeError("COMMAND_DECODER_IDENTITY_MISMATCH")

    monkeypatch.setattr(command_plan, "_observe_plain_file", reject_precheck)
    monkeypatch.setattr(
        command_plan,
        "_make_decoder_temp_root",
        lambda: (_ for _ in ()).throw(AssertionError("temp prepared")),
    )
    monkeypatch.setattr(
        command_plan,
        "_POPEN",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("spawned")),
    )

    _assert_stable_code(
        "COMMAND_DECODER_IDENTITY_MISMATCH",
        lambda: _decode_with_fake(command_plan, b""),
    )
    assert events == ["native-vector", "identity-pre"]


def test_decoder_timeout_kills_reaps_closes_pipes_and_cleans_temp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_plan = _command_plan_module()
    process = _TimeoutDecoderProcess()
    events: list[str] = []
    identities = ["shell", "decoder", "shell", "decoder"]
    monkeypatch.setattr(
        command_plan,
        "_observe_plain_file",
        lambda path, digest: identities.pop(0),
    )
    monkeypatch.setattr(
        command_plan,
        "_make_decoder_temp_root",
        lambda: Path(r"D:\tmp\timeout-decoder-root"),
    )
    monkeypatch.setattr(
        command_plan,
        "_remove_decoder_temp_root",
        lambda path: events.append("cleanup"),
    )
    monkeypatch.setattr(command_plan, "_POPEN", lambda *args, **kwargs: process)

    _assert_stable_code(
        "COMMAND_DECODER_PARSE_INVALID",
        lambda: _decode_with_fake(command_plan, b"Get-Date"),
    )
    assert process.killed is True
    assert process.wait_calls >= 2
    assert process.stdin.closed is True
    assert process.stdout.closed is True
    assert process.stderr.closed is True
    assert events == ["cleanup"]
    assert identities == []


@pytest.mark.parametrize("retry_termination", (False, True))
def test_decoder_blocking_writer_is_timed_out_joined_and_reaped(
    retry_termination: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_plan = _command_plan_module()
    process = (
        _RetryingTerminationDecoderProcess()
        if retry_termination
        else _FullyBlockingDecoderProcess()
    )
    identities = ["shell", "decoder", "shell", "decoder"]
    cleanup: list[Path] = []
    monkeypatch.setattr(command_plan, "_DECODER_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(
        command_plan,
        "_observe_plain_file",
        lambda path, digest: identities.pop(0),
    )
    monkeypatch.setattr(
        command_plan,
        "_make_decoder_temp_root",
        lambda: Path(r"D:\tmp\blocking-writer-decoder-root"),
    )
    monkeypatch.setattr(
        command_plan,
        "_remove_decoder_temp_root",
        lambda path: cleanup.append(path),
    )
    monkeypatch.setattr(command_plan, "_POPEN", lambda *args, **kwargs: process)
    outcomes: list[BaseException | object] = []

    def invoke() -> None:
        try:
            outcomes.append(_decode_with_fake(command_plan, b"Get-Date"))
        except BaseException as exc:
            outcomes.append(exc)

    worker = threading.Thread(target=invoke, daemon=True)
    worker.start()
    assert process.stdin.entered.wait(1)
    worker.join(0.5)
    completed_within_bound = worker.is_alive() is False
    if not completed_within_bound:
        process.released.set()
        worker.join(2)

    assert completed_within_bound
    assert worker.is_alive() is False
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], RuntimeError)
    assert outcomes[0].args == ("COMMAND_DECODER_PARSE_INVALID",)
    assert process.killed is True
    assert process.wait_calls >= 2
    if retry_termination:
        assert process.kill_calls >= 2
    assert process.poll() is not None
    assert process.stdin.closed is True
    assert process.stdout.closed is True
    assert process.stderr.closed is True
    assert identities == []
    assert cleanup == [Path(r"D:\tmp\blocking-writer-decoder-root")]


def test_decoder_partial_stdin_writes_advance_until_the_payload_is_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"Write-Output 'partial pipe writes'"
    command_plan, process, _ = _install_fake_decoder(
        monkeypatch,
        payload=payload,
    )
    process.stdin = _PartialWriter()

    decoded = _decode_with_fake(command_plan, payload)

    assert type(decoded) is command_plan.DecodedPowerShellPayload
    assert b"".join(process.stdin.chunks) == payload
    assert process.stdin.closed is True
    assert process.killed is False


@pytest.mark.parametrize(
    "failing_postcheck",
    ("shell", "decoder"),
)
def test_decoder_postcheck_cleanup_runs_when_identity_observation_raises(
    failing_postcheck: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"Get-Date"
    command_plan = _command_plan_module()
    process = _FakeDecoderProcess(
        _compact_json(
            _decoder_document(
                payload,
                tokens=[_end_of_input_token_entry(payload, index=0)],
            )
        )
    )
    observations = iter(("shell-pre", "decoder-pre", "shell-post", "decoder-post"))
    events: list[str] = []

    def observe(path: Path, digest: str) -> str:
        del path, digest
        event = next(observations)
        events.append(event)
        if event == f"{failing_postcheck}-post":
            raise RuntimeError("COMMAND_DECODER_IDENTITY_MISMATCH")
        return event.split("-")[0]

    monkeypatch.setattr(command_plan, "_observe_plain_file", observe)
    monkeypatch.setattr(
        command_plan,
        "_make_decoder_temp_root",
        lambda: Path(r"D:\tmp\postcheck-decoder-root"),
    )
    monkeypatch.setattr(
        command_plan,
        "_remove_decoder_temp_root",
        lambda path: events.append("cleanup"),
    )
    monkeypatch.setattr(command_plan, "_POPEN", lambda *args, **kwargs: process)

    _assert_stable_code(
        "COMMAND_DECODER_IDENTITY_MISMATCH",
        lambda: _decode_with_fake(command_plan, payload),
    )
    assert events[-1] == "cleanup"
    assert events.count("cleanup") == 1


def test_decoder_path_is_lexically_absolute_without_resolve_following(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"Get-Date"
    command_plan, _, calls = _install_fake_decoder(monkeypatch, payload=payload)

    def unexpected_resolve(*args: object, **kwargs: object) -> Path:
        del args, kwargs
        raise AssertionError("decoder path resolution followed filesystem state")

    monkeypatch.setattr(type(DECODER_PATH), "resolve", unexpected_resolve)

    _decode_with_fake(command_plan, payload)

    assert calls[0][0][0][-1] == str(DECODER_PATH)


def test_decoder_path_must_equal_the_module_sibling_before_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"Get-Date"
    command_plan, _, calls = _install_fake_decoder(monkeypatch, payload=payload)
    alternate = (
        SKILLS_ROOT.parent.parent
        / ".c6-task03-other-module"
        / "tests"
        / "skills"
        / "complete_suite_command_plan_decoder.ps1"
    )
    _assert_stable_code(
        "COMMAND_DECODER_IDENTITY_MISMATCH",
        lambda: command_plan.decode_powershell_payload(
            payload,
            shell=_shell(),
            decoder_path=alternate,
            decoder_sha256="2" * 64,
        ),
    )
    assert calls == []


def test_decoder_temp_roots_are_fresh_unique_children_of_d_tmp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_plan = _command_plan_module()
    roots = iter((r"D:\tmp\decoder-a", r"D:\tmp\decoder-b"))
    calls: list[dict[str, object]] = []

    def mkdtemp(**kwargs: object) -> str:
        calls.append(kwargs)
        return next(roots)

    monkeypatch.setattr(command_plan.tempfile, "mkdtemp", mkdtemp)
    monkeypatch.setattr(type(Path()), "is_dir", lambda self: True)

    first = command_plan._make_decoder_temp_root()
    second = command_plan._make_decoder_temp_root()

    assert first != second
    assert first.parent == Path(r"D:\tmp")
    assert second.parent == Path(r"D:\tmp")
    assert calls == [
        {"prefix": "kokoroarc-command-decoder-", "dir": r"D:\tmp"},
        {"prefix": "kokoroarc-command-decoder-", "dir": r"D:\tmp"},
    ]


def test_decoder_identity_rejects_an_intermediate_reparse_ancestor(
    decoder_test_root: Path,
) -> None:
    command_plan = _command_plan_module()
    target = decoder_test_root / "plain-target"
    alias = decoder_test_root / "reparse-alias"
    target.mkdir()
    observed = target / "decoder.ps1"
    value = b"decoder"
    observed.write_bytes(value)
    try:
        os.symlink(target, alias, target_is_directory=True)
    except OSError as exc:
        observed.unlink()
        target.rmdir()
        pytest.skip(f"directory symlink unavailable: {exc.winerror}")
    try:
        _assert_stable_code(
            "COMMAND_DECODER_IDENTITY_MISMATCH",
            lambda: command_plan._observe_plain_file(
                alias / observed.name,
                sha256(value).hexdigest(),
            ),
        )
    finally:
        alias.unlink(missing_ok=True)
        observed.unlink(missing_ok=True)
        target.rmdir()


def test_decoder_nonexecution_keeps_stdin_out_of_the_native_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = SKILLS_ROOT.parent.parent / ".c6-task03-fake-sentinel-never-created"
    payload = (
        "[System.IO.File]::WriteAllText(" + repr(str(sentinel)) + ", 'owned')"
    ).encode("utf-8")
    command_plan, process, calls = _install_fake_decoder(
        monkeypatch,
        payload=payload,
    )

    _decode_with_fake(command_plan, payload)

    assert sentinel.exists() is False
    assert b"".join(process.stdin.chunks) == payload
    serialized_argv = "\0".join(calls[0][0][0]).encode("utf-8")
    assert payload not in serialized_argv


def test_decoder_single_json_stdout_and_stderr_are_exactly_one_clean_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"Get-Date"
    clean = _compact_json(
        _decoder_document(
            payload,
            tokens=[_end_of_input_token_entry(payload, index=0)],
        )
    )
    cases = (
        (clean + b"\n{}", b"", 0),
        (clean, b"parser detail", 0),
        (clean, b"", 1),
        (b'{"schema_version":"x","schema_version":"x"}', b"", 0),
    )
    for stdout, stderr, exit_code in cases:
        command_plan, _, _ = _install_fake_decoder(
            monkeypatch,
            payload=payload,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
        )
        _assert_stable_code(
            "COMMAND_DECODER_PARSE_INVALID",
            lambda: _decode_with_fake(command_plan, payload),
        )


def test_decoder_document_budget_source_contract_rejects_mutants() -> None:
    source = DECODER_PATH.read_text(encoding="utf-8")
    _assert_decoder_document_budget_source_contract(source)

    replacements = (
        ("$separatorByteCount = 1", "$separatorByteCount = 0"),
        ("$parentChildDelta++", "$parentChildDelta += 0"),
        ("$metricDelta = (", "$metricDelta = [long]0 # ("),
        (
            "bytes = Get-CompactJsonUtf8Length $document",
            "bytes = 0 # omitted empty-document envelope",
        ),
        (
            "if ([long]$outputBytes.Length -ne [long]$documentBudget.bytes)",
            "if ($false)",
        ),
    )
    for original, replacement in replacements:
        assert source.count(original) == 1
        mutant = source.replace(original, replacement, 1)
        with pytest.raises(AssertionError):
            _assert_decoder_document_budget_source_contract(mutant)

    guard = "Assert-DocumentBudgetDelta $DocumentBudget $nodeDocumentDelta"
    assert source.count(guard) == 1
    moved_guard_mutant = source.replace(
        guard,
        (
            "[void]$NodeEntries.Add($nodeEntry)\n"
            "        " + guard
        ),
        1,
    )
    with pytest.raises(AssertionError):
        _assert_decoder_document_budget_source_contract(moved_guard_mutant)


@pytest.mark.parametrize(
    ("payload", "expects_parse_error"),
    (
        (
            DOCUMENT_BUDGET_COMPLEX_PAYLOAD,
            False,
        ),
        (b"if (", True),
    ),
    ids=("compound-multidigit-edges", "parse-error"),
)
def test_decoder_document_budget_independent_exact_cost_oracle(
    payload: bytes,
    expects_parse_error: bool,
    decoder_test_root: Path,
) -> None:
    result = _run_real_decoder(payload, temp_root=decoder_test_root)
    assert result.returncode == 0, result.stderr
    assert result.stderr == b""
    assert result.stdout.startswith(b"{")
    assert result.stdout.endswith(b"}")
    assert b"\n" not in result.stdout
    assert not result.stdout.startswith(b"\xef\xbb\xbf")
    document = json.loads(result.stdout.decode("utf-8", errors="strict"))
    expected_size, child_index_bytes = _independent_incremental_document_size(
        document
    )

    assert expected_size == len(result.stdout)
    assert bool(document["parse_errors"]) is expects_parse_error
    assert child_index_bytes > 0
    if not expects_parse_error:
        child_indices = [
            child_index
            for node in document["nodes"]
            for child_index in node["child_indices"]
        ]
        assert any(child_index >= 10 for child_index in child_indices)
        assert all(value >= 10 for value in document["metrics"].values())


def test_decoder_document_budget_exact_at_and_one_over_pre_retention(
    decoder_test_root: Path,
) -> None:
    payload = DOCUMENT_BUDGET_COMPLEX_PAYLOAD
    baseline = _run_real_decoder(payload, temp_root=decoder_test_root)
    assert baseline.returncode == 0, baseline.stderr
    exact_size = len(baseline.stdout)
    assert 0 < exact_size < PLAN_LIMIT_BYTES

    source = DECODER_PATH.read_bytes()
    declaration = b"$documentByteLimit = 4194304\n"
    final_guard = b"if ($outputBytes.Length -gt $documentByteLimit) {\n"
    assert source.count(declaration) == 1
    assert source.count(final_guard) == 1

    exact_source = source.replace(
        declaration,
        f"$documentByteLimit = {exact_size}\n".encode("ascii"),
        1,
    )
    exact = _run_decoder_source(
        payload,
        exact_source,
        temp_root=decoder_test_root,
    )
    assert exact.returncode == 0, exact.stderr
    assert exact.stderr == b""
    assert len(exact.stdout) == exact_size

    one_over_source = source.replace(
        declaration,
        f"$documentByteLimit = {exact_size - 1}\n".encode("ascii"),
        1,
    ).replace(
        final_guard,
        b"if ($outputBytes.Length -gt 4194304) {\n",
        1,
    )
    one_over = _run_decoder_source(
        payload,
        one_over_source,
        temp_root=decoder_test_root,
    )
    assert one_over.returncode == 1
    assert one_over.stdout == b""
    assert one_over.stderr == b"COMMAND_DECODER_LIMIT_EXCEEDED"


@pytest.mark.parametrize(
    "code",
    ("COMMAND_DECODER_LIMIT_EXCEEDED", "COMMAND_PAYLOAD_LIMIT_EXCEEDED"),
)
def test_decoder_child_exact_stable_code_is_preserved_without_raw_stderr(
    code: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"Get-Date"
    command_plan, _, _ = _install_fake_decoder(
        monkeypatch,
        payload=payload,
        stdout=b"",
        stderr=code.encode("ascii"),
        exit_code=1,
    )
    _assert_stable_code(
        code,
        lambda: _decode_with_fake(command_plan, payload),
    )

    command_plan, _, _ = _install_fake_decoder(
        monkeypatch,
        payload=payload,
        stdout=b"",
        stderr=("detail:" + code).encode("ascii"),
        exit_code=1,
    )
    _assert_stable_code(
        "COMMAND_DECODER_PARSE_INVALID",
        lambda: _decode_with_fake(command_plan, payload),
    )


@pytest.mark.parametrize(
    "location",
    ("top-level", "nested"),
)
def test_decoder_rejects_same_valued_duplicate_keys_in_otherwise_valid_document(
    location: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"Get-Date"
    clean = _compact_json(
        _decoder_document(
            payload,
            tokens=[_end_of_input_token_entry(payload, index=0)],
        )
    )
    if location == "top-level":
        duplicate = (
            b'{"schema_version":"complete-suite-command-plan-decoder-v1",'
            + clean[1:]
        )
    else:
        needle = b'"payload":{"sha256":"' + sha256(payload).hexdigest().encode() + b'",'
        replacement = needle + b'"sha256":"' + sha256(payload).hexdigest().encode() + b'",'
        duplicate = clean.replace(needle, replacement, 1)
        assert duplicate != clean
    command_plan, _, _ = _install_fake_decoder(
        monkeypatch,
        payload=payload,
        stdout=duplicate,
    )
    _assert_stable_code(
        "COMMAND_DECODER_PARSE_INVALID",
        lambda: _decode_with_fake(command_plan, payload),
    )


@pytest.mark.parametrize(
    "stdout",
    (
        b"\xef\xbb\xbf{}",
        b'{"x":"\xff"}',
    ),
    ids=("bom", "invalid-utf8"),
)
def test_decoder_rejects_bom_and_invalid_utf8_stdout(
    stdout: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_plan, _, _ = _install_fake_decoder(
        monkeypatch,
        payload=b"",
        stdout=stdout,
    )
    _assert_stable_code(
        "COMMAND_DECODER_PARSE_INVALID",
        lambda: _decode_with_fake(command_plan, b""),
    )


def test_decoder_canonicalizes_valid_noncanonical_property_order_privately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"Get-Date"
    document = _decoder_document(
        payload,
        tokens=[_end_of_input_token_entry(payload, index=0)],
    )
    noncanonical = json.dumps(
        document,
        ensure_ascii=False,
        separators=(", ", ": "),
        sort_keys=False,
    ).encode("utf-8")
    assert noncanonical != _compact_json(document)
    command_plan, _, _ = _install_fake_decoder(
        monkeypatch,
        payload=payload,
        stdout=noncanonical,
    )

    decoded = _decode_with_fake(command_plan, payload)

    assert decoded.canonical_bytes == _compact_json(document)
    assert decoded.canonical_sha256 == sha256(decoded.canonical_bytes).hexdigest()


def test_decoder_recursion_failures_are_converted_to_stable_boundary_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_plan = _command_plan_module()

    def recursive_decode(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RecursionError("synthetic decoder recursion")

    monkeypatch.setattr(
        command_plan.json.JSONDecoder,
        "raw_decode",
        recursive_decode,
        raising=True,
    )
    _assert_stable_code(
        "COMMAND_DECODER_PARSE_INVALID",
        lambda: command_plan._decode_single_json_object(b"{}"),
    )

    monkeypatch.undo()

    def recursive_encode(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RecursionError("synthetic canonical recursion")

    monkeypatch.setattr(
        command_plan.json,
        "dumps",
        recursive_encode,
        raising=True,
    )
    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan._canonical_json_bytes({}),
    )


def test_decoder_stdout_limit_rejects_four_mib_plus_one_while_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b""
    command_plan, process, _ = _install_fake_decoder(
        monkeypatch,
        payload=payload,
        stdout=b"x" * PIPE_LIMIT_BYTES,
    )

    _assert_stable_code(
        "COMMAND_DECODER_LIMIT_EXCEEDED",
        lambda: _decode_with_fake(command_plan, payload),
    )
    assert process.killed is True
    assert process.stdout._cursor <= PIPE_LIMIT_BYTES


def test_decoder_output_cap_rejects_stderr_over_64_kib_while_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b""
    command_plan, process, _ = _install_fake_decoder(
        monkeypatch,
        payload=payload,
        stdout=b"{}",
        stderr=b"x" * (STDERR_LIMIT_BYTES + 1),
    )

    _assert_stable_code(
        "COMMAND_DECODER_LIMIT_EXCEEDED",
        lambda: _decode_with_fake(command_plan, payload),
    )
    assert process.killed is True


@pytest.mark.parametrize(
    ("size", "accepted"),
    ((PAYLOAD_LIMIT_BYTES, True), (PAYLOAD_LIMIT_BYTES + 1, False)),
    ids=("exact-at", "one-over"),
)
def test_decoder_payload_limit(
    size: int,
    accepted: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"a" * size
    command_plan, process, calls = _install_fake_decoder(
        monkeypatch,
        payload=payload[:PAYLOAD_LIMIT_BYTES],
    )
    if accepted:
        _decode_with_fake(command_plan, payload)
        assert b"".join(process.stdin.chunks) == payload
        assert len(calls) == 1
    else:
        _assert_stable_code(
            "COMMAND_PAYLOAD_LIMIT_EXCEEDED",
            lambda: _decode_with_fake(command_plan, payload),
        )
        assert calls == []


@pytest.mark.parametrize(
    ("size", "accepted"),
    ((PLAN_LIMIT_BYTES, True), (PLAN_LIMIT_BYTES + 1, False)),
    ids=("exact-at", "one-over"),
)
def test_decoder_document_limit(size: int, accepted: bool) -> None:
    command_plan = _command_plan_module()
    prefix = b'{"padding":"'
    suffix = b'"}'
    assert size >= len(prefix) + len(suffix)
    value = prefix + b"x" * (size - len(prefix) - len(suffix)) + suffix
    assert len(value) == size
    parsed = json.loads(value.decode("utf-8", errors="strict"))
    assert _compact_json(parsed) == value
    if accepted:
        assert command_plan._enforce_decoder_document_limit(value) is value
    else:
        _assert_stable_code(
            "COMMAND_DECODER_LIMIT_EXCEEDED",
            lambda: command_plan._enforce_decoder_document_limit(value),
        )


def test_decoder_token_limit_rejects_one_over_before_semantic_retention() -> None:
    command_plan = _command_plan_module()
    _assert_stable_code(
        "COMMAND_DECODER_LIMIT_EXCEEDED",
        lambda: command_plan._check_decoder_count(8193, limit=8192),
    )
    assert command_plan._check_decoder_count(8192, limit=8192) == 8192


def test_decoder_parse_error_limit_rejects_one_over_before_semantic_retention() -> None:
    command_plan = _command_plan_module()
    _assert_stable_code(
        "COMMAND_DECODER_LIMIT_EXCEEDED",
        lambda: command_plan._check_decoder_count(257, limit=256),
    )
    assert command_plan._check_decoder_count(256, limit=256) == 256


@pytest.mark.parametrize(
    "vector",
    (
        (r"C:\tool.exe", ("", "plain", "has space", 'a"b', "tail\\")),
        (SHELL_PATH, ("-NoLogo", "-File", str(DECODER_PATH))),
    ),
)
def test_decoder_native_vector_is_deterministic_and_null_terminated(
    vector: tuple[str, tuple[str, ...]],
) -> None:
    command_plan = _command_plan_module()
    first = command_plan._windows_native_vector(*vector)
    second = command_plan._windows_native_vector(*vector)
    assert first == second
    assert first.contract == "complete-suite-windows-native-vector-v1"
    assert first.utf16_units == len(first.command_line.encode("utf-16-le")) // 2 + 1
    expected_bytes = (first.command_line + "\0").encode("utf-16-le")
    assert first.utf16le_sha256 == sha256(expected_bytes).hexdigest()


def test_decoder_native_vector_matches_independent_exact_command_line_oracle() -> None:
    command_plan = _command_plan_module()
    executable = r"C:\Program Files\PowerShell\7\pwsh.exe"
    arguments = (
        "-NoLogo",
        "",
        "plain",
        "has space",
        'embedded"quote',
        r"trailing\\",
        r"slashes\\\"quote",
    )
    expected_line, expected_units, expected_hash = _independent_native_vector(
        executable,
        arguments,
    )

    observed = command_plan._windows_native_vector(executable, arguments)

    assert observed.command_line == expected_line
    assert observed.utf16_units == expected_units
    assert observed.utf16le_sha256 == expected_hash


def test_decoder_run_binds_the_exact_native_vector_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"Get-Date"
    command_plan, _, _ = _install_fake_decoder(monkeypatch, payload=payload)
    stdout, observation = command_plan._run_decoder(
        payload,
        shell=_shell(),
        decoder_path=DECODER_PATH,
        decoder_sha256="2" * 64,
    )
    expected_line, expected_units, expected_hash = _independent_native_vector(
        SHELL_PATH,
        (
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(DECODER_PATH),
        ),
    )
    assert stdout
    assert observation.command_line == expected_line
    assert observation.utf16_units == expected_units
    assert observation.utf16le_sha256 == expected_hash


def test_decoder_parent_native_vector_accepts_30000_rejects_30001() -> None:
    command_plan = _command_plan_module()
    executable = r"C:\x.exe"
    fixed_units = len((executable + " ").encode("utf-16-le")) // 2 + 1
    exact_argument = "a" * (30000 - fixed_units)
    exact = command_plan._windows_native_vector(executable, (exact_argument,))
    assert exact.utf16_units == 30000
    _assert_stable_code(
        "COMMAND_DECODER_LIMIT_EXCEEDED",
        lambda: command_plan._windows_native_vector(
            executable,
            (exact_argument + "a",),
        ),
    )


@pytest.mark.parametrize(
    "value",
    ("nul\0", "high\ud800", "low\udfff"),
    ids=("nul", "unpaired-high", "unpaired-low"),
)
def test_decoder_parent_rejects_native_vector_budget_bypass(value: str) -> None:
    command_plan = _command_plan_module()
    _assert_stable_code(
        "COMMAND_DECODER_IDENTITY_MISMATCH",
        lambda: command_plan._windows_native_vector(r"C:\x.exe", (value,)),
    )


@pytest.mark.parametrize(
    "executable",
    ("", "pwsh.exe", "nul\0.exe", "high\ud800.exe", "low\udfff.exe"),
    ids=("empty", "relative", "nul", "unpaired-high", "unpaired-low"),
)
def test_decoder_native_vector_rejects_invalid_executable(executable: str) -> None:
    command_plan = _command_plan_module()
    _assert_stable_code(
        "COMMAND_DECODER_IDENTITY_MISMATCH",
        lambda: command_plan._windows_native_vector(executable, ("-NoLogo",)),
    )


def test_decoder_stdout_limit_stream_accepts_exact_four_mib_before_json_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b""
    command_plan, process, _ = _install_fake_decoder(
        monkeypatch,
        payload=payload,
        stdout=b"x" * PLAN_LIMIT_BYTES,
    )
    stdout, _ = command_plan._run_decoder(
        payload,
        shell=_shell(),
        decoder_path=DECODER_PATH,
        decoder_sha256="2" * 64,
    )
    assert len(stdout) == PLAN_LIMIT_BYTES
    assert process.killed is False


def test_decoder_parse_boundary_starts_with_the_frozen_bounded_prefix() -> None:
    expected_prefix = (
        "$ErrorActionPreference = 'Stop'\n"
        "$ProgressPreference = 'SilentlyContinue'\n"
        "$utf8 = [System.Text.UTF8Encoding]::new($false, $true)\n"
        "$inputStream = [Console]::OpenStandardInput()\n"
        "$inputBuffer = [byte[]]::new(65536)\n"
        "$payloadStream = [System.IO.MemoryStream]::new()\n"
        "while (($read = $inputStream.Read($inputBuffer, 0, $inputBuffer.Length)) -gt 0) {\n"
        "    if (($payloadStream.Length + $read) -gt 262144) {\n"
        "        throw 'COMMAND_PAYLOAD_LIMIT_EXCEEDED'\n"
        "    }\n"
        "    $payloadStream.Write($inputBuffer, 0, $read)\n"
        "}\n"
        "$payloadBytes = $payloadStream.ToArray()\n"
        "$payload = $utf8.GetString($payloadBytes)\n"
        "$tokens = $null\n"
        "$parseErrors = $null\n"
        "$ast = [System.Management.Automation.Language.Parser]::ParseInput(\n"
        "    $payload,\n"
        "    [ref]$tokens,\n"
        "    [ref]$parseErrors\n"
        ")\n"
    ).encode("utf-8")
    assert DECODER_PATH.read_bytes().startswith(expected_prefix)


def test_decoder_identity_missing_real_decoder_fails_before_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_plan = _command_plan_module()
    shell_path = Path(SHELL_PATH)
    missing_decoder = (
        SKILLS_ROOT.parent.parent
        / ".c6-task03-lexically-absent"
        / "missing"
        / "tests"
        / "skills"
        / "complete_suite_command_plan_decoder.ps1"
    )
    shell = command_plan.ShellIdentity(
        path=str(shell_path),
        sha256=_hash_file(shell_path),
        file_version="pinned-but-not-reached",
        product_version="pinned-but-not-reached",
        edition="Core",
        parser_version="pinned-but-not-reached",
    )
    spawned = False

    def unexpected_popen(*args: object, **kwargs: object) -> object:
        nonlocal spawned
        spawned = True
        raise AssertionError("missing decoder reached process spawn")

    monkeypatch.setattr(command_plan, "_POPEN", unexpected_popen)

    _assert_stable_code(
        "COMMAND_DECODER_IDENTITY_MISMATCH",
        lambda: command_plan.decode_powershell_payload(
            b"Get-Date",
            shell=shell,
            decoder_path=missing_decoder,
            decoder_sha256="0" * 64,
        ),
    )
    assert spawned is False


def test_decoder_identity_rejects_hardlinked_plain_file(
    decoder_test_root: Path,
) -> None:
    command_plan = _command_plan_module()
    original = decoder_test_root / "decoder.ps1"
    alternate = decoder_test_root / "decoder-hardlink.ps1"
    value = b"decoder"
    original.write_bytes(value)
    try:
        os.link(original, alternate)
    except OSError as exc:
        pytest.skip(f"hard-link creation unavailable: {exc.winerror}")
    try:
        _assert_stable_code(
            "COMMAND_DECODER_IDENTITY_MISMATCH",
            lambda: command_plan._observe_plain_file(
                original,
                sha256(value).hexdigest(),
            ),
        )
    finally:
        alternate.unlink(missing_ok=True)
        original.unlink(missing_ok=True)


def test_decoder_win32_observer_uses_no_follow_flags_and_rejects_final_reparse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_plan = _command_plan_module()
    open_calls: list[tuple[str, int]] = []
    observed_attributes: dict[int, int] = {}
    closed_handles: list[int] = []
    ancestor_handle = 101
    final_handle = 202
    directory_attribute = 0x00000010
    reparse_attribute = 0x00000400
    open_reparse_flag = 0x00200000
    backup_semantics_flag = 0x02000000

    class FakeFunction:
        def __init__(self, callback: object) -> None:
            self.callback = callback
            self.argtypes: object = None
            self.restype: object = None

        def __call__(self, *args: object) -> object:
            return self.callback(*args)

    def create_file(
        path: str,
        access: int,
        sharing: int,
        security: object,
        disposition: int,
        flags: int,
        template: object,
    ) -> int:
        del access, sharing, security, disposition, template
        open_calls.append((path, flags))
        return ancestor_handle if len(open_calls) == 1 else final_handle

    def get_information(handle: int, pointer: object) -> int:
        information = pointer._obj
        attributes = (
            directory_attribute if handle == ancestor_handle else reparse_attribute
        )
        information.file_attributes = attributes
        information.number_of_links = 1
        observed_attributes[handle] = attributes
        return 1

    normalized = r"\\?\D:\safe\decoder.ps1"

    def get_final_path(
        handle: int,
        buffer: object,
        length: int,
        flags: int,
    ) -> int:
        del handle, flags
        if buffer is None:
            return len(normalized)
        assert length > len(normalized)
        buffer.value = normalized
        return len(normalized)

    def close_handle(handle: int) -> int:
        closed_handles.append(handle)
        return 1

    class FakeKernel32:
        def __init__(self) -> None:
            self.CreateFileW = FakeFunction(create_file)
            self.GetFileInformationByHandle = FakeFunction(get_information)
            self.GetFinalPathNameByHandleW = FakeFunction(get_final_path)
            self.CloseHandle = FakeFunction(close_handle)

    monkeypatch.setattr(
        command_plan.ctypes,
        "WinDLL",
        lambda name, use_last_error: FakeKernel32(),
        raising=True,
    )
    monkeypatch.setattr(
        command_plan.msvcrt,
        "open_osfhandle",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("reparse file reached byte reading")
        ),
        raising=True,
    )

    _assert_stable_code(
        "COMMAND_DECODER_IDENTITY_MISMATCH",
        lambda: command_plan._observe_plain_file(
            Path(r"D:\safe\decoder.ps1"),
            "0" * 64,
        ),
    )

    assert [path for path, _flags in open_calls] == [
        r"D:\safe",
        r"D:\safe\decoder.ps1",
    ]
    assert all(flags & open_reparse_flag for _path, flags in open_calls)
    assert open_calls[0][1] & backup_semantics_flag
    assert not open_calls[1][1] & backup_semantics_flag
    assert observed_attributes[ancestor_handle] == directory_attribute
    assert observed_attributes[final_handle] == reparse_attribute
    assert not observed_attributes[final_handle] & directory_attribute
    assert closed_handles == [ancestor_handle, final_handle]


def test_decoder_parse_boundary_emits_one_closed_json_document(
    decoder_test_root: Path,
) -> None:
    result = _run_real_decoder(b"Get-Date", temp_root=decoder_test_root)
    assert result.returncode == 0
    assert result.stderr == b""
    document = json.loads(
        result.stdout.decode("utf-8"),
        object_pairs_hook=lambda pairs: _reject_duplicate_test_keys(pairs),
    )
    assert tuple(document) == (
        "schema_version",
        "payload",
        "powershell",
        "decoder",
        "parse_errors",
        "tokens",
        "nodes",
        "metrics",
    )
    assert document["schema_version"] == DECODER_SCHEMA_VERSION


def _reject_duplicate_test_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AssertionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def test_decoder_payload_hash_uses_the_exact_original_stdin_bytes(
    decoder_test_root: Path,
) -> None:
    payload = "Write-Output 'café-😀'".encode("utf-8")
    result = _run_real_decoder(payload, temp_root=decoder_test_root)
    assert result.returncode == 0
    assert result.stderr == b""
    document = json.loads(result.stdout)
    assert document["payload"] == {
        "utf8_bytes": len(payload),
        "sha256": sha256(payload).hexdigest(),
    }


def test_decoder_nonexecution_real_parser_does_not_create_sentinel(
    decoder_test_root: Path,
) -> None:
    sentinel = decoder_test_root / "must-not-be-created.txt"
    assert sentinel.exists() is False
    literal_path = str(sentinel).replace("'", "''")
    payload = (
        f"[System.IO.File]::WriteAllText('{literal_path}', 'owned')"
    ).encode("utf-8")

    result = _run_real_decoder(payload, temp_root=decoder_test_root)

    assert result.returncode == 0
    assert result.stderr == b""
    assert sentinel.exists() is False
    assert json.loads(result.stdout)["payload"]["sha256"] == sha256(
        payload
    ).hexdigest()


def test_decoder_parse_error_decoder_non_echoing_is_digest_only_and_never_echoes_message(
    decoder_test_root: Path,
) -> None:
    payload = b"if ("
    result = _run_real_decoder(payload, temp_root=decoder_test_root)
    assert result.returncode == 0
    assert result.stderr == b""
    document = json.loads(result.stdout)
    assert document["parse_errors"]
    for index, error in enumerate(document["parse_errors"]):
        assert error["index"] == index
        assert set(error) == {
            "index",
            "error_id",
            "incomplete_input",
            "start_utf16",
            "end_utf16",
            "start_utf8",
            "end_utf8",
            "message_sha256",
        }
        assert len(error["message_sha256"]) == 64
        assert "message" not in error


def test_decoder_non_echoing_decoder_parse_error_full_fake_child_rejects_raw_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload, document = _synthetic_parse_error_document()
    baseline = _decode_fake_document(
        monkeypatch,
        payload=payload,
        document=document,
    )
    assert baseline.token_count == 1
    assert baseline.parse_error_count == 1

    mutant = json.loads(json.dumps(document))
    mutant["parse_errors"][0]["message"] = "synthetic raw parser message"
    _assert_stable_code(
        "COMMAND_PLAN_SCHEMA_INVALID",
        lambda: _decode_fake_document(
            monkeypatch,
            payload=payload,
            document=mutant,
        ),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("error_id", ""),
        ("error_id", "A" * 257),
        ("error_id", "bad error id!"),
        ("incomplete_input", 1),
        ("message_sha256", "g" * 64),
    ),
    ids=(
        "empty-error-id",
        "oversized-error-id",
        "invalid-error-id-character",
        "non-boolean-incomplete-input",
        "malformed-message-digest",
    ),
)
def test_decoder_parse_error_field_contract_rejects_schema_mutants_after_valid_baseline(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    payload, document = _synthetic_parse_error_document()
    baseline = _decode_fake_document(
        monkeypatch,
        payload=payload,
        document=document,
    )
    assert baseline.token_count == 1
    assert baseline.parse_error_count == 1

    mutant = json.loads(json.dumps(document))
    mutant["parse_errors"][0][field] = value
    _assert_stable_code(
        "COMMAND_PLAN_SCHEMA_INVALID",
        lambda: _decode_fake_document(
            monkeypatch,
            payload=payload,
            document=mutant,
        ),
    )


def test_decoder_utf16_utf8_boundary_maps_bmp_and_supplementary_error_extents(
    decoder_test_root: Path,
) -> None:
    payload = "Write-Output 'é😀'\nif (".encode("utf-8")
    result = _run_real_decoder(payload, temp_root=decoder_test_root)
    assert result.returncode == 0
    assert result.stderr == b""
    document = json.loads(result.stdout)
    errors = document["parse_errors"]
    assert errors
    boundaries = _independent_utf16_to_utf8_boundaries(
        payload.decode("utf-8")
    )
    for error in errors:
        assert error["start_utf16"] in boundaries
        assert error["end_utf16"] in boundaries
        assert error["start_utf8"] == boundaries[error["start_utf16"]]
        assert error["end_utf8"] == boundaries[error["end_utf16"]]
    assert any(
        error["start_utf16"] != error["start_utf8"]
        or error["end_utf16"] != error["end_utf8"]
        for error in errors
    )


@pytest.mark.parametrize(
    ("start_utf16", "end_utf16", "start_utf8", "end_utf8"),
    (
        (4, 4, 4, 4),
        (2, 2, 2, 2),
    ),
    ids=("wrong-utf8-offset", "between-surrogate-pair"),
)
def test_decoder_extent_boundary_parent_rejects_noncanonical_emitted_span(
    monkeypatch: pytest.MonkeyPatch,
    start_utf16: int,
    end_utf16: int,
    start_utf8: int,
    end_utf8: int,
) -> None:
    payload = "é😀(".encode("utf-8")
    parse_error = {
        "index": 0,
        "error_id": "MissingEndParenthesisInExpression",
        "incomplete_input": True,
        "start_utf16": 4,
        "end_utf16": 4,
        "start_utf8": len(payload),
        "end_utf8": len(payload),
        "message_sha256": "3" * 64,
    }
    document = _decoder_document(payload)
    document["parse_errors"] = [parse_error]
    document["tokens"] = [_end_of_input_token_entry(payload, index=0)]
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert Draft202012Validator(schema).is_valid(document)
    command_plan = _command_plan_module()
    assert command_plan._validate_decoder_parent_document(
        document,
        payload=payload,
        shell=_shell(),
        decoder_sha256="2" * 64,
    ) == (1, 1)

    parse_error.update(
        {
            "start_utf16": start_utf16,
            "end_utf16": end_utf16,
            "start_utf8": start_utf8,
            "end_utf8": end_utf8,
        }
    )
    assert Draft202012Validator(schema).is_valid(document)
    command_plan, _, _ = _install_fake_decoder(
        monkeypatch,
        payload=payload,
        stdout=_compact_json(document),
    )

    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: _decode_with_fake(command_plan, payload),
    )


@pytest.mark.parametrize(
    "payload",
    (b"\xed\xa0\x80", b"\xed\xbf\xbf"),
    ids=("unpaired-high", "unpaired-low"),
)
def test_surrogate_utf8_is_rejected_before_any_decoder_document(
    decoder_test_root: Path,
    payload: bytes,
) -> None:
    result = _run_real_decoder(payload, temp_root=decoder_test_root)
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr == b"COMMAND_DECODER_PARSE_INVALID"


def test_decoder_parse_boundary_malformed_utf8_emits_exact_stable_error(
    decoder_test_root: Path,
) -> None:
    result = _run_real_decoder(b"\x80", temp_root=decoder_test_root)
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr == b"COMMAND_DECODER_PARSE_INVALID"


def test_decoder_token_serializes_source_order_and_exact_payload_slices(
    decoder_test_root: Path,
) -> None:
    payload = "Write-Output 'café-😀'\n".encode("utf-8")
    result = _run_real_decoder(payload, temp_root=decoder_test_root)
    assert result.returncode == 0
    assert result.stderr == b""
    tokens = json.loads(result.stdout)["tokens"]
    assert tokens
    boundaries = _independent_utf16_to_utf8_boundaries(
        payload.decode("utf-8")
    )
    previous_end = 0
    for index, token in enumerate(tokens):
        assert token["index"] == index
        assert token["kind"] in TOKEN_KINDS
        assert token["flags"] == sorted(set(token["flags"]))
        assert set(token["flags"]).issubset(TOKEN_FLAGS)
        assert token["start_utf16"] in boundaries
        assert token["end_utf16"] in boundaries
        assert token["start_utf8"] == boundaries[token["start_utf16"]]
        assert token["end_utf8"] == boundaries[token["end_utf16"]]
        assert token["start_utf8"] >= previous_end
        assert token["end_utf8"] >= token["start_utf8"]
        token_bytes = payload[token["start_utf8"] : token["end_utf8"]]
        assert token["text_sha256"] == sha256(token_bytes).hexdigest()
        previous_end = token["end_utf8"]
    assert tokens[-1]["kind"] == "EndOfInput"


def test_decoder_literal_token_literal_emits_only_proven_noninterpolating_token_values(
    decoder_test_root: Path,
) -> None:
    payload = (
        "Write-Output identifier 42 'it''s safe' \"$unsafe\"\n"
        "@'\nhere\n'@\n"
    ).encode("utf-8")
    result = _run_real_decoder(payload, temp_root=decoder_test_root)
    assert result.returncode == 0
    assert result.stderr == b""
    tokens = json.loads(result.stdout)["tokens"]
    by_source = {
        payload[token["start_utf8"] : token["end_utf8"]]: token
        for token in tokens
    }
    single_quoted = by_source[b"'it''s safe'"]
    assert single_quoted["kind"] == "StringLiteral"
    assert single_quoted["literal"] == {
        "kind": "single_quoted",
        "value": "it's safe",
        "utf8_bytes": len(b"it's safe"),
        "sha256": sha256(b"it's safe").hexdigest(),
    }
    number = by_source[b"42"]
    assert number["kind"] == "Number"
    assert number["literal"] == {
        "kind": "bare",
        "value": "42",
        "utf8_bytes": 2,
        "sha256": sha256(b"42").hexdigest(),
    }
    assert by_source[b'"$unsafe"']["kind"] == "StringExpandable"
    assert by_source[b'"$unsafe"']["literal"] is None
    here_string = next(
        token for token in tokens if token["kind"] == "HereStringLiteral"
    )
    assert here_string["literal"] is None
    for token in tokens:
        if token["kind"] not in {"Identifier", "Number", "StringLiteral"}:
            assert token["literal"] is None


def test_decoder_literal_token_literal_parent_rejects_interpolated_value(
) -> None:
    payload = b'"$value"'
    token = _ascii_token_entry(
        payload,
        index=0,
        start=0,
        end=len(payload),
        kind="StringExpandable",
    )
    document = _decoder_document(
        payload,
        tokens=[token, _end_of_input_token_entry(payload, index=1)],
    )
    command_plan = _command_plan_module()
    assert command_plan._validate_decoder_parent_document(
        document,
        payload=payload,
        shell=_shell(),
        decoder_sha256="2" * 64,
    ) == (2, 0)

    token["literal"] = _literal_entry("double_quoted", "$value")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert Draft202012Validator(schema).is_valid(document)
    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan._validate_decoder_parent_document(
            document,
            payload=payload,
            shell=_shell(),
            decoder_sha256="2" * 64,
        ),
    )


def test_decoder_literal_token_literal_and_decoder_ast_literal_expandable_here_string_are_null(
    decoder_test_root: Path,
) -> None:
    payload = b'Write-Output @"\n$value\n"@'
    source = b'@"\n$value\n"@'
    result = _run_real_decoder(payload, temp_root=decoder_test_root)
    assert result.returncode == 0
    assert result.stderr == b""
    document = json.loads(result.stdout)

    matching_tokens = [
        token
        for token in document["tokens"]
        if payload[token["start_utf8"] : token["end_utf8"]] == source
    ]
    assert len(matching_tokens) == 1
    assert matching_tokens[0]["kind"] == "HereStringExpandable"
    assert matching_tokens[0]["literal"] is None

    matching_nodes = [
        node
        for node in document["nodes"]
        if payload[node["start_utf8"] : node["end_utf8"]] == source
    ]
    assert len(matching_nodes) == 1
    assert matching_nodes[0]["ast_type"] == "ExpandableStringExpressionAst"
    assert matching_nodes[0]["literal"] is None


def test_decoder_token_end_of_input_normalization_uses_a_closed_self_checked_seam(
    decoder_test_root: Path,
) -> None:
    source = DECODER_PATH.read_text(encoding="utf-8")
    assert source.count("function Convert-EndOfInputExtent {") == 1
    assert source.count("function Assert-EndOfInputExtentContract {") == 1
    assert source.count("\nAssert-EndOfInputExtentContract\n") == 1
    assert "$span = Convert-EndOfInputExtent (" in source

    for payload in (b"1", b"# terminal comment"):
        result = _run_real_decoder(payload, temp_root=decoder_test_root)
        assert result.returncode == 0
        assert result.stderr == b""
        tokens = json.loads(result.stdout)["tokens"]
        assert tokens[-1] == _end_of_input_token_entry(
            payload,
            index=len(tokens) - 1,
        )


def test_decoder_literal_token_literal_and_multi_flag_forms_match_the_pinned_parser(
    decoder_test_root: Path,
) -> None:
    payload = b"$value.Length -ceq 1"
    result = _run_real_decoder(payload, temp_root=decoder_test_root)
    assert result.returncode == 0
    assert result.stderr == b""
    tokens = json.loads(result.stdout)["tokens"]
    by_source = {
        payload[token["start_utf8"] : token["end_utf8"]]: token
        for token in tokens
    }

    identifier = by_source[b"Length"]
    assert identifier["kind"] == "Identifier"
    assert identifier["flags"] == ["MemberName"]
    assert identifier["literal"] == {
        "kind": "bare",
        "value": "Length",
        "utf8_bytes": 6,
        "sha256": sha256(b"Length").hexdigest(),
    }
    comparison = by_source[b"-ceq"]
    assert comparison["kind"] == "Ceq"
    assert comparison["flags"] == [
        "BinaryOperator",
        "BinaryPrecedenceComparison",
        "CaseSensitiveOperator",
    ]
    assert comparison["literal"] is None


@pytest.mark.parametrize(
    "mutation",
    (
        "nonconsecutive-index",
        "nonmonotone-span",
        "slice-digest",
        "unsorted-flags",
        "unsafe-literal",
        "literal-coherence",
    ),
)
def test_decoder_literal_token_span_literal_and_order_mutants_reject_in_parent(
    mutation: str,
) -> None:
    payload = b"abc def"
    tokens = [
        _ascii_token_entry(payload, index=0, start=0, end=3),
        _ascii_token_entry(payload, index=1, start=4, end=7),
        _end_of_input_token_entry(payload, index=2),
    ]
    document = _decoder_document(payload)
    document["tokens"] = tokens
    command_plan = _command_plan_module()
    assert command_plan._validate_decoder_parent_document(
        document,
        payload=payload,
        shell=_shell(),
        decoder_sha256="2" * 64,
    ) == (3, 0)

    if mutation == "nonmonotone-span":
        tokens[:2] = [
            _ascii_token_entry(payload, index=0, start=4, end=7),
            _ascii_token_entry(payload, index=1, start=0, end=3),
        ]
    else:
        token = tokens[0]
        if mutation == "nonconsecutive-index":
            token["index"] = 1
        elif mutation == "slice-digest":
            token["text_sha256"] = "3" * 64
        elif mutation == "unsorted-flags":
            token["flags"] = ["TypeName", "CommandName"]
        elif mutation == "unsafe-literal":
            token["literal"] = {
                "kind": "bare",
                "value": "abc",
                "utf8_bytes": 3,
                "sha256": sha256(b"abc").hexdigest(),
            }
        else:
            token["kind"] = "Number"
            token["literal"] = {
                "kind": "bare",
                "value": "124",
                "utf8_bytes": 3,
                "sha256": sha256(b"124").hexdigest(),
            }

    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan._validate_decoder_parent_document(
            document,
            payload=payload,
            shell=_shell(),
            decoder_sha256="2" * 64,
        ),
    )


@pytest.mark.parametrize("mutation", ("kind", "flag", "ast-type"))
def test_decoder_enum_drift_token_enum_membership_and_ast_type_are_independently_enforced_by_parent(
    mutation: str,
) -> None:
    payload = b"abc"
    token = _ascii_token_entry(payload, index=0, start=0, end=3)
    document = _decoder_document(payload)
    document["tokens"] = [
        token,
        _end_of_input_token_entry(payload, index=1),
    ]
    command_plan = _command_plan_module()
    assert command_plan._validate_decoder_parent_document(
        document,
        payload=payload,
        shell=_shell(),
        decoder_sha256="2" * 64,
    ) == (2, 0)

    if mutation == "kind":
        token["kind"] = "InventedTokenKind"
    elif mutation == "flag":
        token["flags"] = ["InventedTokenFlag"]
    else:
        document["nodes"][0]["ast_type"] = "InventedAstType"

    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan._validate_decoder_parent_document(
            document,
            payload=payload,
            shell=_shell(),
            decoder_sha256="2" * 64,
        ),
    )


@pytest.mark.parametrize(
    "mutation",
    ("missing", "nonfinal", "duplicate", "wrong-span"),
)
def test_decoder_token_end_of_input_invariant_is_independently_enforced_by_parent(
    mutation: str,
) -> None:
    if mutation == "wrong-span":
        payload = b"x"
        tokens = [_end_of_input_token_entry(payload, index=0, start_utf8=0)]
    else:
        payload = b""
        end_of_input = _end_of_input_token_entry(payload, index=0)
        if mutation == "missing":
            tokens = []
        elif mutation == "nonfinal":
            tokens = [
                end_of_input,
                _ascii_token_entry(payload, index=1, start=0, end=0),
            ]
        else:
            tokens = [
                end_of_input,
                _end_of_input_token_entry(payload, index=1),
            ]
    document = _decoder_document(payload)
    document["tokens"] = tokens
    command_plan = _command_plan_module()

    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan._validate_decoder_parent_document(
            document,
            payload=payload,
            shell=_shell(),
            decoder_sha256="2" * 64,
        ),
    )


def test_decoder_payload_limit_exact_at_and_one_over_in_child(
    decoder_test_root: Path,
) -> None:
    exact = b"#" + b"a" * (PAYLOAD_LIMIT_BYTES - 1)
    accepted = _run_real_decoder(exact, temp_root=decoder_test_root)
    assert accepted.returncode == 0
    assert accepted.stderr == b""
    assert json.loads(accepted.stdout)["payload"]["utf8_bytes"] == len(exact)

    rejected = _run_real_decoder(exact + b"a", temp_root=decoder_test_root)
    assert rejected.returncode != 0
    assert rejected.stderr == b"COMMAND_PAYLOAD_LIMIT_EXCEEDED"
    assert rejected.stdout == b""


def test_decoder_parse_error_limit_rejects_before_overflowing_error_is_emitted(
    decoder_test_root: Path,
) -> None:
    payload = b")\n" * 300
    result = _run_real_decoder(payload, temp_root=decoder_test_root)
    assert result.returncode != 0
    assert result.stderr == b"COMMAND_DECODER_LIMIT_EXCEEDED"
    assert result.stdout == b""


def test_decoder_token_limit_accepts_8192_and_rejects_8193_flat_tokens(
    decoder_test_root: Path,
) -> None:
    accepted_payload = b";" * 8191
    accepted = _run_real_decoder(accepted_payload, temp_root=decoder_test_root)
    assert accepted.returncode == 0
    assert accepted.stderr == b""
    accepted_document = json.loads(accepted.stdout)
    assert len(accepted_document["tokens"]) == 8192
    assert accepted_document["tokens"][-1]["kind"] == "EndOfInput"

    rejected_payload = b";" * 8192
    rejected = _run_real_decoder(rejected_payload, temp_root=decoder_test_root)
    assert rejected.returncode != 0
    assert rejected.stderr == b"COMMAND_DECODER_LIMIT_EXCEEDED"
    assert rejected.stdout == b""


def test_decoder_token_limit_guard_precedes_all_conversion_and_retention() -> None:
    source = DECODER_PATH.read_text(encoding="utf-8")
    guard = "if ($tokens.Count -gt 8192) {"
    allocation = (
        "$tokenEntries = [System.Collections.Generic.List[object]]::new()"
    )
    conversion = "$tokenEntry = Convert-Token ("
    retention = (
        "Add-BudgetedDocumentEntry $tokenEntries $tokenEntry $documentBudget"
    )

    assert source.count(guard) == 1
    assert source.count(allocation) == 1
    assert source.count(conversion) == 1
    assert source.count(retention) == 1
    assert (
        source.index(guard)
        < source.index(allocation)
        < source.index(conversion)
        < source.index(retention)
    )


AST_PREORDER_CASES = (
    (
        "direct",
        b"Write-Output hi",
        (
            ("ScriptBlockAst", None, 0, 15, None),
            ("NamedBlockAst", 0, 0, 15, None),
            ("PipelineAst", 1, 0, 15, None),
            ("CommandAst", 2, 0, 15, "none"),
            ("StringConstantExpressionAst", 3, 0, 12, None),
            ("StringConstantExpressionAst", 3, 13, 15, None),
        ),
        (6, 5, 2, 1, 1),
    ),
    (
        "call-operator",
        b"& $cmd arg",
        (
            ("ScriptBlockAst", None, 0, 10, None),
            ("NamedBlockAst", 0, 0, 10, None),
            ("PipelineAst", 1, 0, 10, None),
            ("CommandAst", 2, 0, 10, "call"),
            ("VariableExpressionAst", 3, 2, 6, None),
            ("StringConstantExpressionAst", 3, 7, 10, None),
        ),
        (6, 5, 2, 1, 1),
    ),
    (
        "dot-operator",
        b". $script",
        (
            ("ScriptBlockAst", None, 0, 9, None),
            ("NamedBlockAst", 0, 0, 9, None),
            ("PipelineAst", 1, 0, 9, None),
            ("CommandAst", 2, 0, 9, "dot"),
            ("VariableExpressionAst", 3, 2, 9, None),
        ),
        (5, 5, 2, 1, 1),
    ),
    (
        "dot-prefixed-command-name",
        b".x",
        (
            ("ScriptBlockAst", None, 0, 2, None),
            ("NamedBlockAst", 0, 0, 2, None),
            ("PipelineAst", 1, 0, 2, None),
            ("CommandAst", 2, 0, 2, "none"),
            ("StringConstantExpressionAst", 3, 0, 2, None),
        ),
        (5, 5, 2, 1, 1),
    ),
    (
        "dotdot-command-name",
        b"..",
        (
            ("ScriptBlockAst", None, 0, 2, None),
            ("NamedBlockAst", 0, 0, 2, None),
            ("PipelineAst", 1, 0, 2, None),
            ("CommandAst", 2, 0, 2, "none"),
            ("StringConstantExpressionAst", 3, 0, 2, None),
        ),
        (5, 5, 2, 1, 1),
    ),
    (
        "assignment-expression",
        b"$x = 1 + 2",
        (
            ("ScriptBlockAst", None, 0, 10, None),
            ("NamedBlockAst", 0, 0, 10, None),
            ("AssignmentStatementAst", 1, 0, 10, None),
            ("VariableExpressionAst", 2, 0, 2, None),
            ("CommandExpressionAst", 2, 5, 10, None),
            ("BinaryExpressionAst", 4, 5, 10, None),
            ("ConstantExpressionAst", 5, 5, 6, None),
            ("ConstantExpressionAst", 5, 9, 10, None),
        ),
        (8, 6, 2, 0, 1),
    ),
    (
        "compound",
        b"if ($x) { Get-Item x | Select-Object Name } else { return }",
        (
            ("ScriptBlockAst", None, 0, 59, None),
            ("NamedBlockAst", 0, 0, 59, None),
            ("IfStatementAst", 1, 0, 59, None),
            ("PipelineAst", 2, 4, 6, None),
            ("CommandExpressionAst", 3, 4, 6, None),
            ("VariableExpressionAst", 4, 4, 6, None),
            ("StatementBlockAst", 2, 8, 43, None),
            ("PipelineAst", 6, 10, 41, None),
            ("CommandAst", 7, 10, 20, "none"),
            ("StringConstantExpressionAst", 8, 10, 18, None),
            ("StringConstantExpressionAst", 8, 19, 20, None),
            ("CommandAst", 7, 23, 41, "none"),
            ("StringConstantExpressionAst", 11, 23, 36, None),
            ("StringConstantExpressionAst", 11, 37, 41, None),
            ("StatementBlockAst", 2, 49, 59, None),
            ("ReturnStatementAst", 14, 51, 57, None),
        ),
        (16, 7, 7, 2, 3),
    ),
    (
        "read-pipeline",
        b"Get-Content -LiteralPath '.\\input.json' | Select-Object Length",
        (
            ("ScriptBlockAst", None, 0, 62, None),
            ("NamedBlockAst", 0, 0, 62, None),
            ("PipelineAst", 1, 0, 62, None),
            ("CommandAst", 2, 0, 39, "none"),
            ("StringConstantExpressionAst", 3, 0, 11, None),
            ("CommandParameterAst", 3, 12, 24, None),
            ("StringConstantExpressionAst", 3, 25, 39, None),
            ("CommandAst", 2, 42, 62, "none"),
            ("StringConstantExpressionAst", 7, 42, 55, None),
            ("StringConstantExpressionAst", 7, 56, 62, None),
        ),
        (10, 5, 3, 2, 2),
    ),
    (
        "switch-tuples",
        b"switch ($x) { 1 { Write-Output one } default { break } }",
        (
            ("ScriptBlockAst", None, 0, 56, None),
            ("NamedBlockAst", 0, 0, 56, None),
            ("SwitchStatementAst", 1, 0, 56, None),
            ("PipelineAst", 2, 8, 10, None),
            ("CommandExpressionAst", 3, 8, 10, None),
            ("VariableExpressionAst", 4, 8, 10, None),
            ("ConstantExpressionAst", 2, 14, 15, None),
            ("StatementBlockAst", 2, 16, 36, None),
            ("PipelineAst", 7, 18, 34, None),
            ("CommandAst", 8, 18, 34, "none"),
            ("StringConstantExpressionAst", 9, 18, 30, None),
            ("StringConstantExpressionAst", 9, 31, 34, None),
            ("StatementBlockAst", 2, 45, 54, None),
            ("BreakStatementAst", 12, 47, 52, None),
        ),
        (14, 7, 6, 1, 2),
    ),
    (
        "hashtable-tuples",
        b"$h = @{ a = 1; b = 2 }",
        (
            ("ScriptBlockAst", None, 0, 22, None),
            ("NamedBlockAst", 0, 0, 22, None),
            ("AssignmentStatementAst", 1, 0, 22, None),
            ("VariableExpressionAst", 2, 0, 2, None),
            ("CommandExpressionAst", 2, 5, 22, None),
            ("HashtableAst", 4, 5, 22, None),
            ("StringConstantExpressionAst", 5, 8, 9, None),
            ("PipelineAst", 5, 12, 13, None),
            ("CommandExpressionAst", 7, 12, 13, None),
            ("ConstantExpressionAst", 8, 12, 13, None),
            ("StringConstantExpressionAst", 5, 15, 16, None),
            ("PipelineAst", 5, 19, 20, None),
            ("CommandExpressionAst", 11, 19, 20, None),
            ("ConstantExpressionAst", 12, 19, 20, None),
        ),
        (14, 8, 6, 0, 3),
    ),
    (
        "error-statement-flags",
        b"switch -file x {}",
        (
            ("ScriptBlockAst", None, 0, 17, None),
            ("NamedBlockAst", 0, 0, 16, None),
            ("ErrorStatementAst", 1, 0, 16, None),
            ("PipelineAst", 2, 13, 14, None),
            ("CommandExpressionAst", 3, 13, 14, None),
            ("StringConstantExpressionAst", 4, 13, 14, None),
        ),
        (6, 6, 3, 0, 1),
    ),
)


def _expected_ast_nodes(
    payload: bytes,
    preorder: tuple[tuple[object, ...], ...],
) -> list[dict[str, object]]:
    assert payload.isascii()
    child_indices = [[] for _ in preorder]
    for index, (_, parent_index, _, _, _) in enumerate(preorder):
        if parent_index is not None:
            child_indices[parent_index].append(index)
    expected = []
    for index, entry in enumerate(preorder):
        ast_type, parent_index, start, end, invocation_operator = entry
        literal = None
        if ast_type == "StringConstantExpressionAst":
            source = payload[start:end]
            if source.startswith(b"'") and source.endswith(b"'"):
                value = source[1:-1].replace(b"''", b"'").decode("utf-8")
                literal = _literal_entry("single_quoted", value)
            else:
                literal = _literal_entry("bare", source.decode("utf-8"))
        expected.append(
            _ascii_node_entry(
                index=index,
                ast_type=ast_type,
                parent_index=parent_index,
                child_indices=child_indices[index],
                start=start,
                end=end,
                invocation_operator=invocation_operator,
                literal=literal,
            )
        )
    return expected


@pytest.mark.parametrize(
    ("payload", "preorder", "metric_values"),
    tuple((payload, preorder, metrics) for _, payload, preorder, metrics in AST_PREORDER_CASES),
    ids=tuple(case[0] for case in AST_PREORDER_CASES),
)
def test_decoder_ast_emits_complete_calibrated_preorder_documents(
    decoder_test_root: Path,
    payload: bytes,
    preorder: tuple[tuple[object, ...], ...],
    metric_values: tuple[int, int, int, int, int],
) -> None:
    result = _run_real_decoder(payload, temp_root=decoder_test_root)
    assert result.returncode == 0
    assert result.stderr == b""
    document = json.loads(result.stdout)
    expected_nodes = _expected_ast_nodes(payload, preorder)
    expected_metrics = dict(
        zip(
            (
                "ast_nodes",
                "ast_depth",
                "statements",
                "operations",
                "pipeline_stages",
            ),
            metric_values,
            strict=True,
        )
    )
    assert document["nodes"] == expected_nodes
    assert document["metrics"] == expected_metrics
    expected_document = dict(document)
    expected_document["nodes"] = expected_nodes
    expected_document["metrics"] = expected_metrics
    command_plan = _command_plan_module()
    assert command_plan._canonical_json_bytes(document) == _compact_json(
        expected_document
    )


def test_decoder_ast_uses_independent_utf16_utf8_boundaries(
    decoder_test_root: Path,
) -> None:
    payload = "Write-Output 'café-😀'".encode("utf-8")
    result = _run_real_decoder(payload, temp_root=decoder_test_root)
    assert result.returncode == 0
    assert result.stderr == b""
    document = json.loads(result.stdout)
    nodes = document["nodes"]
    assert tuple(
        (
            node["ast_type"],
            node["parent_index"],
            tuple(node["child_indices"]),
            node["invocation_operator"],
        )
        for node in nodes
    ) == (
        ("ScriptBlockAst", None, (1,), None),
        ("NamedBlockAst", 0, (2,), None),
        ("PipelineAst", 1, (3,), None),
        ("CommandAst", 2, (4, 5), "none"),
        ("StringConstantExpressionAst", 3, (), None),
        ("StringConstantExpressionAst", 3, (), None),
    )
    expected_spans = (
        (0, 22, 0, 25),
        (0, 22, 0, 25),
        (0, 22, 0, 25),
        (0, 22, 0, 25),
        (0, 12, 0, 12),
        (13, 22, 13, 25),
    )
    for node, expected_span in zip(nodes, expected_spans, strict=True):
        assert (
            node["start_utf16"],
            node["end_utf16"],
            node["start_utf8"],
            node["end_utf8"],
        ) == expected_span
    assert nodes[4]["literal"] == _literal_entry("bare", "Write-Output")
    assert nodes[5]["literal"] == _literal_entry("single_quoted", "café-😀")
    assert document["metrics"] == {
        "ast_nodes": 6,
        "ast_depth": 5,
        "statements": 2,
        "operations": 1,
        "pipeline_stages": 1,
    }


@pytest.mark.parametrize(
    ("ast_type", "payload", "literal"),
    (
        (
            "VariableExpressionAst",
            b"$value",
            _literal_entry("bare", "$value"),
        ),
        (
            "ExpandableStringExpressionAst",
            b'"$value"',
            _literal_entry("double_quoted", "$value"),
        ),
    ),
    ids=("unsafe-non-string-constant", "interpolated-expandable-string"),
)
def test_decoder_literal_decoder_ast_literal_parent_rejects_invented_unsafe_value(
    ast_type: str,
    payload: bytes,
    literal: dict[str, object],
) -> None:
    nodes = [
        _ascii_node_entry(
            index=0,
            ast_type="ScriptBlockAst",
            parent_index=None,
            child_indices=[1],
            start=0,
            end=len(payload),
        ),
        _ascii_node_entry(
            index=1,
            ast_type=ast_type,
            parent_index=0,
            child_indices=[],
            start=0,
            end=len(payload),
        ),
    ]
    document = _decoder_document(
        payload,
        tokens=[_end_of_input_token_entry(payload, index=0)],
        nodes=nodes,
        metrics={
            "ast_nodes": 2,
            "ast_depth": 2,
            "statements": 0,
            "operations": 0,
            "pipeline_stages": 0,
        },
    )
    command_plan = _command_plan_module()
    assert command_plan._validate_decoder_parent_document(
        document,
        payload=payload,
        shell=_shell(),
        decoder_sha256="2" * 64,
    ) == (1, 0)

    nodes[1]["literal"] = literal
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert Draft202012Validator(schema).is_valid(document)
    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan._validate_decoder_parent_document(
            document,
            payload=payload,
            shell=_shell(),
            decoder_sha256="2" * 64,
        ),
    )


@pytest.mark.parametrize(
    ("payload", "source", "ast_type"),
    (
        (b"Write-Output foo` bar", b"foo` bar", "StringConstantExpressionAst"),
        (b'Write-Output "a`q"', b'"a`q"', "StringConstantExpressionAst"),
        (b'Write-Output "$value"', b'"$value"', "ExpandableStringExpressionAst"),
        (
            b"Write-Output @'\nhere\n'@",
            b"@'\nhere\n'@",
            "StringConstantExpressionAst",
        ),
    ),
)
def test_decoder_literal_decoder_ast_literal_omits_values_not_independently_reconstructable(
    decoder_test_root: Path,
    payload: bytes,
    source: bytes,
    ast_type: str,
) -> None:
    result = _run_real_decoder(payload, temp_root=decoder_test_root)
    assert result.returncode == 0
    assert result.stderr == b""
    nodes = json.loads(result.stdout)["nodes"]
    matching = [
        node
        for node in nodes
        if payload[node["start_utf8"] : node["end_utf8"]] == source
    ]
    assert len(matching) == 1
    assert matching[0]["ast_type"] == ast_type
    assert matching[0]["literal"] is None


def test_decoder_literal_decoder_ast_literal_reconstructs_a_closed_double_quote_escape(
    decoder_test_root: Path,
) -> None:
    payload = b'Write-Output "a`n"'
    result = _run_real_decoder(payload, temp_root=decoder_test_root)
    assert result.returncode == 0
    assert result.stderr == b""
    nodes = json.loads(result.stdout)["nodes"]
    literal_node = next(
        node
        for node in nodes
        if payload[node["start_utf8"] : node["end_utf8"]] == b'"a`n"'
    )
    assert literal_node["ast_type"] == "StringConstantExpressionAst"
    assert literal_node["literal"] == _literal_entry("double_quoted", "a\n")


def test_decoder_ast_role_partition_and_metric_tables_are_exact() -> None:
    assert set(AST_TYPES_BY_ROLE) == set(AST_ROLES)
    partition = tuple(
        ast_type
        for ast_types in AST_TYPES_BY_ROLE.values()
        for ast_type in ast_types
    )
    assert len(partition) == len(set(partition)) == len(AST_TYPES)
    assert set(partition) == set(AST_TYPES)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert tuple(schema["$defs"]["ast_type"]["enum"]) == AST_TYPES
    assert tuple(schema["$defs"]["role"]["enum"]) == AST_ROLES

    command_plan = _command_plan_module()
    assert getattr(command_plan, "_AST_ROLE_BY_TYPE", None) == AST_ROLE_BY_TYPE
    assert getattr(command_plan, "_CONCRETE_STATEMENT_AST_TYPES", None) == frozenset(
        CONCRETE_STATEMENT_AST_TYPES
    )
    assert getattr(command_plan, "_OPERATION_AST_TYPES", None) == frozenset(
        OPERATION_AST_TYPES
    )
    assert getattr(command_plan, "_PIPELINE_STAGE_AST_TYPES", None) == frozenset(
        PIPELINE_STAGE_AST_TYPES
    )


def test_decoder_ast_powershell_tables_cover_the_exact_closed_partition() -> None:
    source = DECODER_PATH.read_text(encoding="utf-8")
    assert _strict_powershell_string_array(source, "closedAstTypes")[0] == AST_TYPES
    powershell_partition = {}
    variable_by_role = {
        "script_block": "scriptBlockAstTypes",
        "statement": "statementRoleAstTypes",
        "pipeline": "pipelineAstTypes",
        "command": "commandAstTypes",
        "command_element": "commandElementAstTypes",
        "redirection": "redirectionAstTypes",
        "control_flow": "controlFlowAstTypes",
        "expression": "expressionAstTypes",
    }
    for role, variable_name in variable_by_role.items():
        values = _strict_powershell_string_array(source, variable_name)[0]
        assert values == AST_TYPES_BY_ROLE[role]
        for ast_type in values:
            assert ast_type not in powershell_partition
            powershell_partition[ast_type] = role
    assert powershell_partition == AST_ROLE_BY_TYPE
    assert _strict_powershell_string_array(
        source,
        "concreteStatementAstTypes",
    )[0] == CONCRETE_STATEMENT_AST_TYPES
    assert _strict_powershell_string_array(
        source,
        "operationAstTypes",
    )[0] == OPERATION_AST_TYPES
    assert _strict_powershell_string_array(
        source,
        "pipelineStageAstTypes",
    )[0] == PIPELINE_STAGE_AST_TYPES


def _assert_ast_parent_baseline(command_plan: object) -> tuple[bytes, dict[str, object]]:
    payload, document = _ast_parent_baseline_document()
    assert command_plan._validate_decoder_parent_document(
        document,
        payload=payload,
        shell=_shell(),
        decoder_sha256="2" * 64,
    ) == (4, 0)
    return payload, document


@pytest.mark.parametrize(
    "mutation",
    (
        "root-count",
        "root-type",
        "root-span",
        "preorder-index",
        "lower-parent",
        "disconnected",
        "repeated-ownership",
        "cycle",
        "containment",
        "role-drift",
    ),
)
def test_ast_parent_and_reachability_mutants_reject(
    mutation: str,
) -> None:
    command_plan = _command_plan_module()
    payload, baseline = _assert_ast_parent_baseline(command_plan)
    document = json.loads(json.dumps(baseline))
    nodes = document["nodes"]
    if mutation == "root-count":
        nodes[1]["parent_index"] = None
    elif mutation == "root-type":
        nodes[0]["ast_type"] = "NamedBlockAst"
        nodes[0]["role"] = "statement"
    elif mutation == "root-span":
        nodes[0]["end_utf16"] = 2
        nodes[0]["end_utf8"] = 2
    elif mutation == "preorder-index":
        nodes[3]["index"] = 4
    elif mutation == "lower-parent":
        nodes[1]["parent_index"] = 3
    elif mutation == "disconnected":
        nodes[1]["child_indices"] = [2]
    elif mutation == "repeated-ownership":
        nodes[0]["child_indices"] = [1, 5]
    elif mutation == "cycle":
        nodes[4]["child_indices"] = [1]
    elif mutation == "containment":
        nodes[1]["end_utf16"] = 1
        nodes[1]["end_utf8"] = 1
    else:
        nodes[2]["role"] = "statement"
    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan._validate_decoder_parent_document(
            document,
            payload=payload,
            shell=_shell(),
            decoder_sha256="2" * 64,
        ),
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "not-higher",
        "reversed",
        "duplicate",
        "reciprocity",
        "crossing-siblings",
    ),
)
def test_ast_child_order_and_ownership_mutants_reject(mutation: str) -> None:
    command_plan = _command_plan_module()
    payload, baseline = _assert_ast_parent_baseline(command_plan)
    document = json.loads(json.dumps(baseline))
    nodes = document["nodes"]
    if mutation == "not-higher":
        nodes[1]["child_indices"] = [1, 5]
    elif mutation == "reversed":
        nodes[1]["child_indices"] = [5, 2]
    elif mutation == "duplicate":
        nodes[1]["child_indices"] = [2, 2]
    elif mutation == "reciprocity":
        nodes[5]["parent_index"] = 0
    else:
        nodes[2]["end_utf16"] = 3
        nodes[2]["end_utf8"] = 3
        nodes[5]["start_utf16"] = 1
        nodes[5]["start_utf8"] = 1
    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan._validate_decoder_parent_document(
            document,
            payload=payload,
            shell=_shell(),
            decoder_sha256="2" * 64,
        ),
    )


def test_ast_parent_reaches_duplicate_owner_guard_with_balanced_edges() -> None:
    payload = b"ab"
    document = _decoder_document(
        payload,
        tokens=[_end_of_input_token_entry(payload, index=0)],
        nodes=[
            _ascii_node_entry(
                index=0,
                ast_type="ScriptBlockAst",
                parent_index=None,
                child_indices=[1, 2],
                start=0,
                end=2,
            ),
            _ascii_node_entry(
                index=1,
                ast_type="NamedBlockAst",
                parent_index=0,
                child_indices=[3],
                start=0,
                end=1,
            ),
            _ascii_node_entry(
                index=2,
                ast_type="NamedBlockAst",
                parent_index=0,
                child_indices=[3],
                start=1,
                end=2,
            ),
            _ascii_node_entry(
                index=3,
                ast_type="NamedBlockAst",
                parent_index=1,
                child_indices=[],
                start=1,
                end=1,
            ),
            _ascii_node_entry(
                index=4,
                ast_type="NamedBlockAst",
                parent_index=0,
                child_indices=[],
                start=2,
                end=2,
            ),
        ],
        metrics={
            "ast_nodes": 5,
            "ast_depth": 3,
            "statements": 0,
            "operations": 0,
            "pipeline_stages": 0,
        },
    )
    assert sum(len(node["child_indices"]) for node in document["nodes"]) == 4
    command_plan = _command_plan_module()
    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan._validate_decoder_parent_document(
            document,
            payload=payload,
            shell=_shell(),
            decoder_sha256="2" * 64,
        ),
    )


def test_ast_parent_rejects_connected_nonpreorder_topology() -> None:
    payload = b"ab"
    document = _decoder_document(
        payload,
        tokens=[_end_of_input_token_entry(payload, index=0)],
        nodes=[
            _ascii_node_entry(
                index=0,
                ast_type="ScriptBlockAst",
                parent_index=None,
                child_indices=[1, 2],
                start=0,
                end=2,
            ),
            _ascii_node_entry(
                index=1,
                ast_type="NamedBlockAst",
                parent_index=0,
                child_indices=[3],
                start=0,
                end=1,
            ),
            _ascii_node_entry(
                index=2,
                ast_type="NamedBlockAst",
                parent_index=0,
                child_indices=[],
                start=1,
                end=2,
            ),
            _ascii_node_entry(
                index=3,
                ast_type="NamedBlockAst",
                parent_index=1,
                child_indices=[],
                start=0,
                end=1,
            ),
        ],
        metrics={
            "ast_nodes": 4,
            "ast_depth": 3,
            "statements": 0,
            "operations": 0,
            "pipeline_stages": 0,
        },
    )
    command_plan = _command_plan_module()
    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan._validate_decoder_parent_document(
            document,
            payload=payload,
            shell=_shell(),
            decoder_sha256="2" * 64,
        ),
    )


@pytest.mark.parametrize(
    ("metric", "mutated"),
    (
        ("ast_nodes", 7),
        ("ast_depth", 4),
        ("statements", 3),
        ("operations", 1),
        ("pipeline_stages", 1),
    ),
)
def test_ast_metric_is_independently_recomputed_by_parent(
    metric: str,
    mutated: int,
) -> None:
    command_plan = _command_plan_module()
    payload, baseline = _assert_ast_parent_baseline(command_plan)
    document = json.loads(json.dumps(baseline))
    document["metrics"][metric] = mutated
    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan._validate_decoder_parent_document(
            document,
            payload=payload,
            shell=_shell(),
            decoder_sha256="2" * 64,
        ),
    )


def _ast_depth_limit_document(depth: int) -> tuple[bytes, dict[str, object]]:
    assert depth >= 1
    payload = b""
    nodes = [
        _ascii_node_entry(
            index=index,
            ast_type="ScriptBlockAst" if index == 0 else "NamedBlockAst",
            parent_index=None if index == 0 else index - 1,
            child_indices=[] if index + 1 == depth else [index + 1],
            start=0,
            end=0,
        )
        for index in range(depth)
    ]
    return payload, _decoder_document(
        payload,
        tokens=[_end_of_input_token_entry(payload, index=0)],
        nodes=nodes,
        metrics={
            "ast_nodes": depth,
            "ast_depth": depth,
            "statements": 0,
            "operations": 0,
            "pipeline_stages": 0,
        },
    )


def _flat_ast_node_limit_document(
    node_count: int,
) -> tuple[bytes, dict[str, object]]:
    assert node_count >= 1
    payload = b""
    nodes = [
        _ascii_node_entry(
            index=0,
            ast_type="ScriptBlockAst",
            parent_index=None,
            child_indices=list(range(1, node_count)),
            start=0,
            end=0,
        )
    ]
    nodes.extend(
        _ascii_node_entry(
            index=index,
            ast_type="NamedBlockAst",
            parent_index=0,
            child_indices=[],
            start=0,
            end=0,
        )
        for index in range(1, node_count)
    )
    return payload, _decoder_document(
        payload,
        tokens=[_end_of_input_token_entry(payload, index=0)],
        nodes=nodes,
        metrics={
            "ast_nodes": node_count,
            "ast_depth": 1 if node_count == 1 else 2,
            "statements": 0,
            "operations": 0,
            "pipeline_stages": 0,
        },
    )


def _flat_ast_metric_limit_document(
    *,
    count: int,
    ast_type: str,
    metric: str,
) -> tuple[bytes, dict[str, object]]:
    needs_tokens = ast_type in {"CommandAst", "CommandExpressionAst"}
    payload = b"a" * count if needs_tokens else b""
    tokens = []
    if needs_tokens:
        tokens = [
            _ascii_token_entry(
                payload,
                index=index,
                start=index,
                end=index + 1,
                kind="Identifier",
                literal=_literal_entry("bare", "a"),
            )
            for index in range(count)
        ]
    tokens.append(_end_of_input_token_entry(payload, index=len(tokens)))
    nodes = [
        _ascii_node_entry(
            index=0,
            ast_type="ScriptBlockAst",
            parent_index=None,
            child_indices=list(range(1, count + 1)),
            start=0,
            end=len(payload),
        )
    ]
    nodes.extend(
        _ascii_node_entry(
            index=index + 1,
            ast_type=ast_type,
            parent_index=0,
            child_indices=[],
            start=index if needs_tokens else 0,
            end=index + 1 if needs_tokens else 0,
            invocation_operator="none" if ast_type == "CommandAst" else None,
        )
        for index in range(count)
    )
    metrics = {
        "ast_nodes": count + 1,
        "ast_depth": 2,
        "statements": 0,
        "operations": 0,
        "pipeline_stages": 0,
    }
    metrics[metric] = count
    return payload, _decoder_document(
        payload,
        tokens=tokens,
        nodes=nodes,
        metrics=metrics,
    )


@pytest.mark.parametrize(
    ("metric", "ast_type"),
    (
        ("statements", "BreakStatementAst"),
        ("operations", "CommandAst"),
        ("pipeline_stages", "CommandExpressionAst"),
    ),
)
def test_ast_statement_limit_operation_limit_pipeline_stage_limit_parent_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    metric: str,
    ast_type: str,
) -> None:
    command_plan = _command_plan_module()
    if metric != "statements":
        monkeypatch.setattr(command_plan, "_CONCRETE_STATEMENT_AST_TYPES", frozenset())
    if metric != "operations":
        monkeypatch.setattr(command_plan, "_OPERATION_AST_TYPES", frozenset())
    if metric != "pipeline_stages":
        monkeypatch.setattr(command_plan, "_PIPELINE_STAGE_AST_TYPES", frozenset())

    payload, accepted = _flat_ast_metric_limit_document(
        count=256,
        ast_type=ast_type,
        metric=metric,
    )
    assert command_plan._validate_decoder_parent_document(
        accepted,
        payload=payload,
        shell=_shell(),
        decoder_sha256="2" * 64,
    ) == (len(accepted["tokens"]), 0)

    payload, rejected = _flat_ast_metric_limit_document(
        count=257,
        ast_type=ast_type,
        metric=metric,
    )
    _assert_stable_code(
        "COMMAND_DECODER_LIMIT_EXCEEDED",
        lambda: command_plan._validate_decoder_parent_document(
            rejected,
            payload=payload,
            shell=_shell(),
            decoder_sha256="2" * 64,
        ),
    )


def test_ast_depth_limit_parent_accepts_64_and_rejects_65() -> None:
    command_plan = _command_plan_module()
    payload, accepted = _ast_depth_limit_document(64)
    assert command_plan._validate_decoder_parent_document(
        accepted,
        payload=payload,
        shell=_shell(),
        decoder_sha256="2" * 64,
    ) == (1, 0)

    payload, rejected = _ast_depth_limit_document(65)
    _assert_stable_code(
        "COMMAND_DECODER_LIMIT_EXCEEDED",
        lambda: command_plan._validate_decoder_parent_document(
            rejected,
            payload=payload,
            shell=_shell(),
            decoder_sha256="2" * 64,
        ),
    )


def test_ast_node_limit_parent_accepts_8192_and_rejects_8193() -> None:
    command_plan = _command_plan_module()
    payload, accepted = _flat_ast_node_limit_document(8192)
    assert command_plan._validate_decoder_parent_document(
        accepted,
        payload=payload,
        shell=_shell(),
        decoder_sha256="2" * 64,
    ) == (1, 0)

    payload, rejected = _flat_ast_node_limit_document(8193)
    _assert_stable_code(
        "COMMAND_DECODER_LIMIT_EXCEEDED",
        lambda: command_plan._validate_decoder_parent_document(
            rejected,
            payload=payload,
            shell=_shell(),
            decoder_sha256="2" * 64,
        ),
    )


def test_decoder_ast_statement_limit_accepts_256_and_rejects_257(
    decoder_test_root: Path,
) -> None:
    accepted = _run_real_decoder(b"break;" * 256, temp_root=decoder_test_root)
    assert accepted.returncode == 0
    assert accepted.stderr == b""
    assert json.loads(accepted.stdout)["metrics"]["statements"] == 256

    rejected = _run_real_decoder(b"break;" * 257, temp_root=decoder_test_root)
    assert rejected.returncode != 0
    assert rejected.stderr == b"COMMAND_DECODER_LIMIT_EXCEEDED"
    assert rejected.stdout == b""


def test_decoder_ast_depth_limit_statement_limit_operation_limit_pipeline_stage_limit_guards_precede_retention(
) -> None:
    source = DECODER_PATH.read_text(encoding="utf-8")
    guards = (
        "if ($depth -gt 64) {",
        "if ($nextStatementCount -gt 256) {",
        "if ($nextOperationCount -gt 256) {",
        "if ($nextPipelineStageCount -gt 256) {",
    )
    literal = "$literal = Convert-SafeAstLiteral $node $BoundaryTable $PayloadBytes"
    retention = "[void]$NodeEntries.Add($nodeEntry)"
    for guard in guards:
        assert source.count(guard) == 1
        assert source.index(guard) < source.index(literal) < source.index(retention)


@pytest.mark.parametrize(
    ("guard", "original_limit", "metric", "exact_value"),
    (
        (
            "if (($nodeEntries.Count + 1) -gt 8192) {",
            8192,
            "ast_nodes",
            6,
        ),
        ("if ($depth -gt 64) {", 64, "ast_depth", 5),
        (
            "if ($nextStatementCount -gt 256) {",
            256,
            "statements",
            2,
        ),
        (
            "if ($nextOperationCount -gt 256) {",
            256,
            "operations",
            1,
        ),
        (
            "if ($nextPipelineStageCount -gt 256) {",
            256,
            "pipeline_stages",
            1,
        ),
    ),
    ids=(
        "ast-node-limit",
        "ast-depth-limit",
        "statement-limit",
        "operation-limit",
        "pipeline-stage-limit",
    ),
)
def test_ast_node_limit_ast_depth_limit_statement_limit_operation_limit_pipeline_stage_limit_child_guard_exact_at_and_one_over(
    guard: str,
    original_limit: int,
    metric: str,
    exact_value: int,
    decoder_test_root: Path,
) -> None:
    payload = b"Write-Output hi"
    source = DECODER_PATH.read_bytes()
    guard_bytes = guard.encode("ascii")
    assert source.count(guard_bytes) == 1
    original_bytes = str(original_limit).encode("ascii")
    assert guard_bytes.count(original_bytes) == 1

    exact_guard = guard_bytes.replace(
        original_bytes,
        str(exact_value).encode("ascii"),
        1,
    )
    exact_source = source.replace(guard_bytes, exact_guard, 1)
    exact = _run_decoder_source(
        payload,
        exact_source,
        temp_root=decoder_test_root,
    )
    assert exact.returncode == 0, exact.stderr
    assert exact.stderr == b""
    assert json.loads(exact.stdout)["metrics"][metric] == exact_value

    one_over_guard = guard_bytes.replace(
        original_bytes,
        str(exact_value - 1).encode("ascii"),
        1,
    )
    one_over_source = source.replace(guard_bytes, one_over_guard, 1)
    one_over = _run_decoder_source(
        payload,
        one_over_source,
        temp_root=decoder_test_root,
    )
    assert one_over.returncode == 1
    assert one_over.stdout == b""
    assert one_over.stderr == b"COMMAND_DECODER_LIMIT_EXCEEDED"


@pytest.mark.parametrize(
    "mutation",
    ("wrong-command", "null-command", "non-command"),
)
def test_decoder_invocation_operator_parent_rejects_semantic_drift(
    mutation: str,
) -> None:
    command_plan = _command_plan_module()
    payload, baseline = _assert_ast_parent_baseline(command_plan)
    document = json.loads(json.dumps(baseline))
    if mutation == "wrong-command":
        document["nodes"][3]["invocation_operator"] = "call"
    elif mutation == "null-command":
        document["nodes"][3]["invocation_operator"] = None
    else:
        document["nodes"][0]["invocation_operator"] = "none"
    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan._validate_decoder_parent_document(
            document,
            payload=payload,
            shell=_shell(),
            decoder_sha256="2" * 64,
        ),
    )


@pytest.mark.parametrize(
    ("token_kind", "operator", "mutated_operator"),
    (
        ("Ampersand", "call", "dot"),
        ("Dot", "dot", "call"),
    ),
)
def test_decoder_invocation_operator_parent_binds_the_exact_leading_token(
    token_kind: str,
    operator: str,
    mutated_operator: str,
) -> None:
    prefix = b"&" if token_kind == "Ampersand" else b"."
    payload = prefix + b" a"
    tokens = [
        _ascii_token_entry(
            payload,
            index=0,
            start=0,
            end=1,
            kind=token_kind,
        ),
        _ascii_token_entry(
            payload,
            index=1,
            start=2,
            end=3,
            kind="Identifier",
            literal=_literal_entry("bare", "a"),
        ),
        _end_of_input_token_entry(payload, index=2),
    ]
    nodes = [
        _ascii_node_entry(
            index=0,
            ast_type="ScriptBlockAst",
            parent_index=None,
            child_indices=[1],
            start=0,
            end=3,
        ),
        _ascii_node_entry(
            index=1,
            ast_type="NamedBlockAst",
            parent_index=0,
            child_indices=[2],
            start=0,
            end=3,
        ),
        _ascii_node_entry(
            index=2,
            ast_type="PipelineAst",
            parent_index=1,
            child_indices=[3],
            start=0,
            end=3,
        ),
        _ascii_node_entry(
            index=3,
            ast_type="CommandAst",
            parent_index=2,
            child_indices=[4],
            start=0,
            end=3,
            invocation_operator=operator,
        ),
        _ascii_node_entry(
            index=4,
            ast_type="StringConstantExpressionAst",
            parent_index=3,
            child_indices=[],
            start=2,
            end=3,
            literal=_literal_entry("bare", "a"),
        ),
    ]
    document = _decoder_document(
        payload,
        tokens=tokens,
        nodes=nodes,
        metrics={
            "ast_nodes": 5,
            "ast_depth": 5,
            "statements": 2,
            "operations": 1,
            "pipeline_stages": 1,
        },
    )
    command_plan = _command_plan_module()
    assert command_plan._validate_decoder_parent_document(
        document,
        payload=payload,
        shell=_shell(),
        decoder_sha256="2" * 64,
    ) == (3, 0)

    document["nodes"][3]["invocation_operator"] = mutated_operator
    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan._validate_decoder_parent_document(
            document,
            payload=payload,
            shell=_shell(),
            decoder_sha256="2" * 64,
        ),
    )


def test_decoder_invocation_operator_parent_rejects_token_outside_command_extent(
) -> None:
    payload = b"&"
    document = _decoder_document(
        payload,
        tokens=[
            _ascii_token_entry(
                payload,
                index=0,
                start=0,
                end=1,
                kind="Ampersand",
            ),
            _end_of_input_token_entry(payload, index=1),
        ],
        nodes=[
            _ascii_node_entry(
                index=0,
                ast_type="ScriptBlockAst",
                parent_index=None,
                child_indices=[1],
                start=0,
                end=1,
            ),
            _ascii_node_entry(
                index=1,
                ast_type="NamedBlockAst",
                parent_index=0,
                child_indices=[2],
                start=0,
                end=1,
            ),
            _ascii_node_entry(
                index=2,
                ast_type="PipelineAst",
                parent_index=1,
                child_indices=[3],
                start=0,
                end=1,
            ),
            _ascii_node_entry(
                index=3,
                ast_type="CommandAst",
                parent_index=2,
                child_indices=[],
                start=0,
                end=0,
                invocation_operator="call",
            ),
        ],
        metrics={
            "ast_nodes": 4,
            "ast_depth": 4,
            "statements": 2,
            "operations": 1,
            "pipeline_stages": 1,
        },
    )
    command_plan = _command_plan_module()
    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan._validate_decoder_parent_document(
            document,
            payload=payload,
            shell=_shell(),
            decoder_sha256="2" * 64,
        ),
    )


def test_decoder_invocation_operator_parent_rejects_wide_token_hiding_call_operator(
) -> None:
    payload = b"&x"
    document = _decoder_document(
        payload,
        tokens=[
            _ascii_token_entry(
                payload,
                index=0,
                start=0,
                end=2,
                kind="Identifier",
                literal=_literal_entry("bare", "&x"),
            ),
            _end_of_input_token_entry(payload, index=1),
        ],
        nodes=[
            _ascii_node_entry(
                index=0,
                ast_type="ScriptBlockAst",
                parent_index=None,
                child_indices=[1],
                start=0,
                end=2,
            ),
            _ascii_node_entry(
                index=1,
                ast_type="NamedBlockAst",
                parent_index=0,
                child_indices=[2],
                start=0,
                end=2,
            ),
            _ascii_node_entry(
                index=2,
                ast_type="PipelineAst",
                parent_index=1,
                child_indices=[3],
                start=0,
                end=2,
            ),
            _ascii_node_entry(
                index=3,
                ast_type="CommandAst",
                parent_index=2,
                child_indices=[],
                start=0,
                end=2,
                invocation_operator="none",
            ),
        ],
        metrics={
            "ast_nodes": 4,
            "ast_depth": 4,
            "statements": 2,
            "operations": 1,
            "pipeline_stages": 1,
        },
    )
    command_plan = _command_plan_module()
    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan._validate_decoder_parent_document(
            document,
            payload=payload,
            shell=_shell(),
            decoder_sha256="2" * 64,
        ),
    )


def test_decoder_invocation_operator_parent_does_not_reslice_validated_token_bytes(
) -> None:
    class ObservedBytes(bytes):
        def __new__(cls, value: bytes) -> "ObservedBytes":
            instance = super().__new__(cls, value)
            instance.slice_calls = []
            return instance

        def __getitem__(self, key: object) -> object:
            if isinstance(key, slice):
                self.slice_calls.append(key)
            return super().__getitem__(key)

    plain_payload = b"&"
    payload = ObservedBytes(plain_payload)
    document = _decoder_document(
        plain_payload,
        tokens=[
            _ascii_token_entry(
                plain_payload,
                index=0,
                start=0,
                end=1,
                kind="Ampersand",
            ),
            _end_of_input_token_entry(plain_payload, index=1),
        ],
        nodes=[
            _ascii_node_entry(
                index=0,
                ast_type="ScriptBlockAst",
                parent_index=None,
                child_indices=[1],
                start=0,
                end=1,
            ),
            _ascii_node_entry(
                index=1,
                ast_type="NamedBlockAst",
                parent_index=0,
                child_indices=[2],
                start=0,
                end=1,
            ),
            _ascii_node_entry(
                index=2,
                ast_type="PipelineAst",
                parent_index=1,
                child_indices=[3],
                start=0,
                end=1,
            ),
            _ascii_node_entry(
                index=3,
                ast_type="CommandAst",
                parent_index=2,
                child_indices=[],
                start=0,
                end=1,
                invocation_operator="call",
            ),
        ],
        metrics={
            "ast_nodes": 4,
            "ast_depth": 4,
            "statements": 2,
            "operations": 1,
            "pipeline_stages": 1,
        },
    )
    command_plan = _command_plan_module()
    assert command_plan._validate_decoder_parent_document(
        document,
        payload=payload,
        shell=_shell(),
        decoder_sha256="2" * 64,
    ) == (2, 0)
    assert [(item.start, item.stop) for item in payload.slice_calls] == [
        (0, 1),
        (1, 1),
    ]


def test_ast_parent_rejects_bad_topology_before_reconstructing_literals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"x" * 64
    literal = _literal_entry("bare", payload.decode("ascii"))
    document = _decoder_document(
        payload,
        tokens=[_end_of_input_token_entry(payload, index=0)],
        nodes=[
            _ascii_node_entry(
                index=0,
                ast_type="ScriptBlockAst",
                parent_index=None,
                child_indices=[1, 2],
                start=0,
                end=len(payload),
            ),
            _ascii_node_entry(
                index=1,
                ast_type="StringConstantExpressionAst",
                parent_index=0,
                child_indices=[],
                start=0,
                end=len(payload),
                literal=dict(literal),
            ),
            _ascii_node_entry(
                index=2,
                ast_type="StringConstantExpressionAst",
                parent_index=0,
                child_indices=[],
                start=0,
                end=len(payload),
                literal=dict(literal),
            ),
        ],
        metrics={
            "ast_nodes": 3,
            "ast_depth": 2,
            "statements": 0,
            "operations": 0,
            "pipeline_stages": 0,
        },
    )
    command_plan = _command_plan_module()
    original = command_plan._expected_string_ast_literal
    calls = 0

    def observe(source: bytes) -> tuple[str, str] | None:
        nonlocal calls
        calls += 1
        return original(source)

    monkeypatch.setattr(command_plan, "_expected_string_ast_literal", observe)
    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan._validate_decoder_parent_document(
            document,
            payload=payload,
            shell=_shell(),
            decoder_sha256="2" * 64,
        ),
    )
    assert calls == 0


def test_decoder_literal_decoder_ast_literal_kind_requires_an_exact_string() -> None:
    class StringSubclass(str):
        pass

    command_plan = _command_plan_module()
    payload, document = _ast_parent_baseline_document()
    document["nodes"][4]["literal"]["kind"] = StringSubclass("bare")
    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan._validate_decoder_parent_document(
            document,
            payload=payload,
            shell=_shell(),
            decoder_sha256="2" * 64,
        ),
    )


def _compact_powershell_source(source: str) -> str:
    return "".join(source.replace("`", "").casefold().split())


def _decode_powershell_source_without_execution(
    source: str,
    *,
    temp_root: Path,
) -> dict[str, Any]:
    assert type(source) is str
    assert temp_root.is_dir()
    audit_path = temp_root / "powershell-source-audit.ps1"
    assert audit_path.exists() is False
    audit_bytes = POWERSHELL_SOURCE_AUDIT_SCRIPT.encode(
        "utf-8",
        errors="strict",
    )
    with audit_path.open("xb") as audit_file:
        assert audit_file.write(audit_bytes) == len(audit_bytes)
    assert audit_path.is_file()
    assert audit_path.is_symlink() is False
    assert audit_path.read_bytes() == audit_bytes
    environment = {
        "SYSTEMROOT": os.environ["SYSTEMROOT"],
        "WINDIR": os.environ["WINDIR"],
        "COMSPEC": os.environ["COMSPEC"],
        "PATHEXT": ".COM;.EXE;.BAT;.CMD",
        "TEMP": str(temp_root),
        "TMP": str(temp_root),
        "POWERSHELL_TELEMETRY_OPTOUT": "1",
        "POWERSHELL_UPDATECHECK": "Off",
    }
    try:
        completed = subprocess.run(
            [
                SHELL_PATH,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(audit_path),
            ],
            input=source.encode("utf-8", errors="strict"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=environment,
            timeout=15,
            check=False,
        )
    finally:
        audit_path.unlink()
    assert audit_path.exists() is False
    assert completed.returncode == 0
    assert completed.stderr == b""
    document = json.loads(
        completed.stdout.decode("utf-8", errors="strict"),
        object_pairs_hook=lambda pairs: _reject_duplicate_test_keys(pairs),
    )
    assert type(document) is dict
    assert set(document) == {"parse_error_ids", "members", "commands", "types"}
    assert type(document["parse_error_ids"]) is list
    assert all(
        type(error_id) is str and error_id
        for error_id in document["parse_error_ids"]
    )
    for collection_name, expected_keys in (
        (
            "members",
            {"function_name", "invoking", "member_kind", "member_name"},
        ),
        (
            "commands",
            {"command_name", "function_name", "invocation_operator"},
        ),
        ("types", {"type_name"}),
    ):
        collection = document[collection_name]
        assert type(collection) is list
        assert all(
            type(entry) is dict and set(entry) == expected_keys
            for entry in collection
        )
    return document


def _assert_decoder_ast_getter_and_forbidden_source_contract(
    source: str,
    syntax_document: dict[str, Any],
) -> None:
    assert syntax_document["parse_error_ids"] == []
    members = syntax_document["members"]
    for member in members:
        assert type(member["invoking"]) is bool
        assert type(member["member_kind"]) is str and member["member_kind"]
        assert member["function_name"] is None or (
            type(member["function_name"]) is str and member["function_name"]
        )
        assert type(member["member_name"]) is str and member["member_name"]
    getter_members = [
        member
        for member in members
        if member["member_name"].casefold() == "getvalue"
    ]
    assert getter_members == [
        {
            "function_name": "Get-SafeAstPropertyValue",
            "invoking": True,
            "member_kind": (
                "System.Management.Automation.Language.StringConstantExpressionAst"
            ),
            "member_name": "GetValue",
        }
    ]
    forbidden_member_names = {
        "create",
        "findall",
        "getscriptblock",
        "psobject",
        "safegetvalue",
        "statictype",
        "visit",
    }
    assert all(
        member["member_name"].casefold() not in forbidden_member_names
        for member in members
    )

    commands = syntax_document["commands"]
    for command in commands:
        assert command["function_name"] is None or (
            type(command["function_name"]) is str and command["function_name"]
        )
        assert type(command["command_name"]) is str and command["command_name"]
        assert command["invocation_operator"] == "Unknown"
    assert all(
        command["command_name"].casefold()
        not in {"gcm", "get-command", "iex", "invoke-expression"}
        for command in commands
    )

    forbidden_type_names = {"astvisitor", "commanddiscovery"}
    for type_entry in syntax_document["types"]:
        type_name = type_entry["type_name"]
        assert type(type_name) is str and type_name
        assert type_name.rsplit(".", 1)[-1].casefold() not in forbidden_type_names

    safe_property_source = source[
        source.index("function Get-SafeAstPropertyValue {") : source.index(
            "function Add-DirectAstCandidate {"
        )
    ]
    direct_children_source = source[
        source.index("function Get-DirectAstChildren {") : source.index(
            "function Convert-SafeAstLiteral {"
        )
    ]
    member_spacing = r"(?:\s|`\r?\n)*"
    getter_pattern = re.compile(
        rf"\.{member_spacing}getvalue{member_spacing}\(",
        flags=re.IGNORECASE,
    )
    getter_source = source.replace("`", "")
    safe_getter_source = safe_property_source.replace("`", "")
    direct_getter_source = direct_children_source.replace("`", "")
    assert len(tuple(getter_pattern.finditer(getter_source))) == 1
    assert len(tuple(getter_pattern.finditer(safe_getter_source))) == 1
    assert getter_pattern.search(direct_getter_source) is None

    safe_compact = _compact_powershell_source(safe_property_source)
    direct_compact = _compact_powershell_source(direct_children_source)
    compact_source = _compact_powershell_source(source)
    assert compact_source.count(".getvalue(") == 1
    assert safe_compact.count(".getvalue(") == 1
    assert ".getvalue(" not in direct_compact
    assert (
        safe_compact.index("$propertytype=$property.propertytype")
        < safe_compact.index(
            "if($null-eq$verifiedkind-or$valuekind-cne$verifiedkind){"
        )
        < safe_compact.index("$result.value=$property.getvalue($node)")
    )
    assert (
        direct_compact.index("$propertytype=$property.propertytype")
        < direct_compact.index("if($null-eq$valuekind){")
        < direct_compact.index(
            "get-safeastpropertyvalue$node$property$valuekind"
            "([ref]$propertyvalue)"
        )
    )

    for forbidden in (
        ".FindAll(",
        ".Visit(",
        "AstVisitor",
        "StaticType",
        "SafeGetValue",
        ".PSObject.Properties",
        "Get-Command",
        "CommandDiscovery",
        "Invoke-Expression",
        "ScriptBlock.Create",
        "GetScriptBlock",
    ):
        assert _compact_powershell_source(forbidden) not in compact_source


def test_decoder_ast_node_limit_child_discovery_is_iterative_bounded_and_nonexecuting(
    decoder_test_root: Path,
) -> None:
    source = DECODER_PATH.read_text(encoding="utf-8")
    assert source.count("function Get-DirectAstChildren {") == 1
    assert source.count("function Get-SafeAstPropertyValue {") == 1
    assert source.count("function Convert-AstTree {") == 1
    assert _strict_powershell_string_array(
        source,
        "closedAstPropertyValueKinds",
    )[0] == ("ast", "ast_sequence", "tuple_sequence", "flag_map")
    assert "[System.Runtime.CompilerServices.ITuple]" in source
    assert "[System.Collections.Generic.Dictionary``2]" in source
    assert "[System.Management.Automation.Language.Token]" in source
    assert "$flagKeys.Sort([StringComparer]::Ordinal)" in source
    assert "[System.Collections.Generic.ReferenceEqualityComparer]::Instance" in source
    assert "$directChildIdentitySet" in source
    assert "$globalAstIdentitySet" in source
    assert "$closedAstTypeOrdinal" in source
    assert "$propertyOrdinal" in source
    assert "$discoveryOrdinal" in source
    candidate_source = source[
        source.index("function Add-DirectAstCandidate {") : source.index(
            "function Get-DirectAstChildren {"
        )
    ]
    ast_tree_start = source.index("function Convert-AstTree {")
    ast_tree_source = source[
        ast_tree_start : source.index(
            "\nAssert-EndOfInputExtentContract\n",
            ast_tree_start,
        )
    ]
    syntax_document = _decode_powershell_source_without_execution(
        source,
        temp_root=decoder_test_root,
    )
    _assert_decoder_ast_getter_and_forbidden_source_contract(
        source,
        syntax_document,
    )
    assert (
        candidate_source.index("if ($nextCount -gt 8192) {")
        < candidate_source.index("$DirectIdentitySet.Add($candidateAst)")
        < candidate_source.index("$GlobalIdentitySet.Add($candidateAst)")
        < candidate_source.index("$Candidates.Add([ordered]@{")
    )
    assert (
        ast_tree_source.index("if (($discoveredAstCount + 1) -gt 8192) {")
        < ast_tree_source.index("$globalAstIdentitySet.Add($Root)")
        < ast_tree_source.index("$astStack.Push([ordered]@{")
    )
    assert (
        "for ($childOffset = $children.Count - 1; "
        "$childOffset -ge 0; $childOffset--)"
    ) in source
    guard = "if (($nodeEntries.Count + 1) -gt 8192) {"
    allocation = "$nodeEntry = [ordered]@{"
    retention = "[void]$NodeEntries.Add($nodeEntry)"
    assert source.count(guard) == 1
    assert source.count(allocation) == 1
    assert source.count(retention) == 1
    assert source.index(guard) < source.index(allocation) < source.index(retention)


@pytest.mark.parametrize(
    ("marker", "insertion"),
    (
        (
            "        $propertyType = $property.PropertyType\n",
            "        $unsafe = ( $property ).gEtVaLuE( $Node )\n",
        ),
        (
            "    $candidates = [System.Collections.Generic.List[object]]::new()\n",
            "    gEt-CoMmAnD -Name ignored\n",
        ),
        (
            "        $propertyType = $property.PropertyType\n",
            '        $unsafe = $property."gEt`VaLuE"($Node)\n',
        ),
        (
            "    $candidates = [System.Collections.Generic.List[object]]::new()\n",
            "    gEt-`CoMmAnD -Name ignored\n",
        ),
        (
            "        $propertyType = $property.PropertyType\n",
            "        $unsafe = $property.`\nGetValue($Node)\n",
        ),
        (
            "        $propertyType = $property.PropertyType\n",
            "        $unsafe = $property.'gEtVaLuE'($Node)\n",
        ),
        (
            "        $propertyType = $property.PropertyType\n",
            '        $unsafe = $property."gEtVaLuE"($Node)\n',
        ),
        (
            "        $propertyType = $property.PropertyType\n",
            "        $memberName = 'GetValue'\n"
            "        $unsafe = $property.$memberName($Node)\n",
        ),
        (
            "    $candidates = [System.Collections.Generic.List[object]]::new()\n",
            "    iex $payload\n",
        ),
        (
            "    $candidates = [System.Collections.Generic.List[object]]::new()\n",
            "    gcm -Name ignored\n",
        ),
        (
            "    $candidates = [System.Collections.Generic.List[object]]::new()\n",
            "    & 'Write-Output' ignored\n",
        ),
        (
            "    $candidates = [System.Collections.Generic.List[object]]::new()\n",
            "    . '.\\ignored.ps1'\n",
        ),
    ),
    ids=(
        "eager-getter",
        "case-folded-command",
        "escaped-eager-getter",
        "escaped-command",
        "continued-eager-getter",
        "single-quoted-eager-getter",
        "double-quoted-eager-getter",
        "dynamic-eager-getter",
        "invoke-expression-alias",
        "get-command-alias",
        "static-call-operator",
        "static-dot-source",
    ),
)
def test_decoder_ast_source_contract_rejects_powershell_spelling_mutants(
    decoder_test_root: Path,
    marker: str,
    insertion: str,
) -> None:
    source = DECODER_PATH.read_text(encoding="utf-8")
    assert source.count(marker) == 1
    mutated = source.replace(marker, insertion + marker, 1)
    syntax_document = _decode_powershell_source_without_execution(
        mutated,
        temp_root=decoder_test_root,
    )
    assert syntax_document["parse_error_ids"] == []
    with pytest.raises(AssertionError):
        _assert_decoder_ast_getter_and_forbidden_source_contract(
            mutated,
            syntax_document,
        )


def test_decoder_ast_property_metadata_order_is_total_for_equal_names() -> None:
    source = DECODER_PATH.read_text(encoding="utf-8")
    sort_source = source[
        source.index("$properties.Sort(") : source.index(
            "    $astBaseType = [System.Management.Automation.Language.Ast]",
            source.index("$properties.Sort("),
        )
    ]
    tie_breakers = (
        "$left.DeclaringType.FullName",
        "$right.DeclaringType.FullName",
        "$left.PropertyType.AssemblyQualifiedName",
        "$right.PropertyType.AssemblyQualifiedName",
        "$left.MetadataToken.CompareTo($right.MetadataToken)",
    )
    for tie_breaker in tie_breakers:
        assert sort_source.count(tie_breaker) == 1
    assert sort_source.index("$left.Name") < sort_source.index(tie_breakers[0])
    assert sort_source.index(tie_breakers[0]) < sort_source.index(tie_breakers[2])
    assert sort_source.index(tie_breakers[2]) < sort_source.index(tie_breakers[4])


TASK4_DATACLASS_FIELDS = {
    "PathNamespaceRequest": (
        "raw_root",
        "retained_root",
        "label",
    ),
    "FilesystemObjectIdentity": (
        "device",
        "inode",
        "file_type",
        "reparse_tag",
        "link_count",
    ),
    "BoundPathNamespace": (
        "raw_root",
        "retained_root",
        "label",
        "raw_identity",
        "retained_identity",
        "raw_ancestor_identities",
        "retained_ancestor_identities",
        "raw_case_sensitive",
        "retained_case_sensitive",
        "canonical_sha256",
    ),
    "BoundCommandPlan": (
        "version",
        "raw_rendered_utf8_bytes",
        "raw_rendered_sha256",
        "retained_rendered_utf8_bytes",
        "retained_rendered_sha256",
        "raw_payload_field_utf8_bytes",
        "raw_payload_field_sha256",
        "raw_payload_utf8_bytes",
        "raw_payload_sha256",
        "retained_payload_field_utf8_bytes",
        "retained_payload_field_sha256",
        "retained_payload_utf8_bytes",
        "retained_payload_sha256",
        "namespaces",
        "namespace_manifest_sha256",
        "normalized_plan_sha256",
        "normalized_plan_bytes",
    ),
}


def _task4_decoded_payload(command_plan: object, payload: bytes) -> object:
    canonical_bytes = _compact_json(
        _decoder_document(
            payload,
            tokens=[_end_of_input_token_entry(payload, index=0)],
        )
    )
    return command_plan.DecodedPowerShellPayload(
        schema_version=DECODER_SCHEMA_VERSION,
        canonical_bytes=canonical_bytes,
        canonical_sha256=sha256(canonical_bytes).hexdigest(),
        token_count=1,
        parse_error_count=0,
    )


def test_canonical_normalized_binding_typed_api_is_exact_and_frozen() -> None:
    command_plan = _command_plan_module()
    expected_hints = {
        "PathNamespaceRequest": {
            "raw_root": str,
            "retained_root": str,
            "label": str,
        },
        "FilesystemObjectIdentity": {
            "device": int,
            "inode": int,
            "file_type": int,
            "reparse_tag": int,
            "link_count": int,
        },
        "BoundPathNamespace": {
            "raw_root": str,
            "retained_root": str,
            "label": str,
            "raw_identity": command_plan.FilesystemObjectIdentity,
            "retained_identity": command_plan.FilesystemObjectIdentity,
            "raw_ancestor_identities": tuple[
                command_plan.FilesystemObjectIdentity, ...
            ],
            "retained_ancestor_identities": tuple[
                command_plan.FilesystemObjectIdentity, ...
            ],
            "raw_case_sensitive": bool,
            "retained_case_sensitive": bool,
            "canonical_sha256": str,
        },
        "BoundCommandPlan": {
            "version": str,
            "raw_rendered_utf8_bytes": int,
            "raw_rendered_sha256": str,
            "retained_rendered_utf8_bytes": int,
            "retained_rendered_sha256": str,
            "raw_payload_field_utf8_bytes": int,
            "raw_payload_field_sha256": str,
            "raw_payload_utf8_bytes": int,
            "raw_payload_sha256": str,
            "retained_payload_field_utf8_bytes": int,
            "retained_payload_field_sha256": str,
            "retained_payload_utf8_bytes": int,
            "retained_payload_sha256": str,
            "namespaces": tuple[command_plan.BoundPathNamespace, ...],
            "namespace_manifest_sha256": str,
            "normalized_plan_sha256": str,
            "normalized_plan_bytes": bytes,
        },
    }
    for class_name, expected_fields in TASK4_DATACLASS_FIELDS.items():
        class_type = getattr(command_plan, class_name)
        assert tuple(field.name for field in fields(class_type)) == expected_fields
        assert get_type_hints(class_type) == expected_hints[class_name]
        assert class_type.__dataclass_params__.frozen is True

    request = command_plan.PathNamespaceRequest(
        raw_root=r"D:\raw",
        retained_root=r"D:\retained",
        label="workspace",
    )
    identity = command_plan.FilesystemObjectIdentity(
        device=1,
        inode=2,
        file_type=1,
        reparse_tag=0,
        link_count=1,
    )
    with pytest.raises(FrozenInstanceError):
        request.label = "changed"
    with pytest.raises(FrozenInstanceError):
        identity.inode = 3

    bind_signature = inspect.signature(command_plan.bind_raw_and_retained_plans)
    assert tuple(bind_signature.parameters) == (
        "raw_rendered",
        "retained_rendered",
        "shell",
        "decoder_path",
        "decoder_sha256",
        "namespaces",
    )
    assert tuple(
        parameter.kind for parameter in bind_signature.parameters.values()
    ) == (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
        inspect.Parameter.KEYWORD_ONLY,
        inspect.Parameter.KEYWORD_ONLY,
        inspect.Parameter.KEYWORD_ONLY,
    )
    assert get_type_hints(command_plan.bind_raw_and_retained_plans) == {
        "raw_rendered": bytes,
        "retained_rendered": bytes,
        "shell": command_plan.ShellIdentity,
        "decoder_path": Path,
        "decoder_sha256": str,
        "namespaces": tuple[command_plan.BoundPathNamespace, ...],
        "return": command_plan.BoundCommandPlan,
    }

    namespace_signature = inspect.signature(command_plan.bind_path_namespaces)
    assert tuple(namespace_signature.parameters) == ("requests",)
    assert namespace_signature.parameters["requests"].kind is (
        inspect.Parameter.POSITIONAL_OR_KEYWORD
    )
    assert get_type_hints(command_plan.bind_path_namespaces) == {
        "requests": Sequence[command_plan.PathNamespaceRequest],
        "return": tuple[command_plan.BoundPathNamespace, ...],
    }


def test_canonical_normalized_binding_is_closed_detached_and_self_consistent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_plan = _command_plan_module()
    shell = _shell()
    payload = b""
    rendered = command_plan.render_powershell_argv(
        "",
        shell_path=shell.path,
        quote_style="single",
    )
    decoded = _task4_decoded_payload(command_plan, payload)
    decode_calls: list[bytes] = []

    def fake_decode(
        candidate: bytes,
        *,
        shell: object,
        decoder_path: Path,
        decoder_sha256: str,
    ) -> object:
        assert type(candidate) is bytes
        assert shell is not None
        assert decoder_path == DECODER_PATH
        assert decoder_sha256 == "2" * 64
        decode_calls.append(candidate)
        return decoded

    monkeypatch.setattr(
        command_plan,
        "decode_powershell_payload",
        fake_decode,
        raising=True,
    )
    bound = command_plan.bind_raw_and_retained_plans(
        rendered,
        rendered,
        shell=shell,
        decoder_path=DECODER_PATH,
        decoder_sha256="2" * 64,
        namespaces=(),
    )
    assert type(bound) is command_plan.BoundCommandPlan
    assert bound.version == "complete-suite-bound-command-plan-v1"
    assert decode_calls == [payload, payload]
    assert bound.namespaces == ()
    assert bound.raw_rendered_utf8_bytes == len(rendered)
    assert bound.raw_rendered_sha256 == sha256(rendered).hexdigest()
    assert bound.retained_rendered_utf8_bytes == len(rendered)
    assert bound.retained_rendered_sha256 == sha256(rendered).hexdigest()
    assert bound.raw_payload_field_utf8_bytes == 2
    assert bound.raw_payload_field_sha256 == sha256(b"''").hexdigest()
    assert bound.raw_payload_utf8_bytes == 0
    assert bound.raw_payload_sha256 == sha256(payload).hexdigest()
    assert bound.retained_payload_field_utf8_bytes == 2
    assert bound.retained_payload_field_sha256 == sha256(b"''").hexdigest()
    assert bound.retained_payload_utf8_bytes == 0
    assert bound.retained_payload_sha256 == sha256(payload).hexdigest()
    assert type(bound.normalized_plan_bytes) is bytes
    assert bound.normalized_plan_sha256 == sha256(
        bound.normalized_plan_bytes
    ).hexdigest()
    normalized = json.loads(bound.normalized_plan_bytes)
    assert _compact_json(normalized) == bound.normalized_plan_bytes
    assert set(normalized) == {
        "bindings",
        "command",
        "decoder",
        "namespace_manifest_sha256",
        "namespaces",
        "shell",
        "version",
    }
    assert normalized["version"] == "complete-suite-bound-command-plan-v1"
    expected_binding = {
        "payload": {
            "sha256": sha256(payload).hexdigest(),
            "utf8_bytes": 0,
        },
        "payload_field": {
            "sha256": sha256(b"''").hexdigest(),
            "utf8_bytes": 2,
        },
        "rendered": {
            "sha256": sha256(rendered).hexdigest(),
            "utf8_bytes": len(rendered),
        },
    }
    assert normalized["bindings"] == {
        "raw": expected_binding,
        "retained": expected_binding,
    }
    assert normalized["namespaces"] == []
    manifest = {
        "namespaces": [],
        "version": "complete-suite-path-namespace-manifest-v1",
    }
    assert bound.namespace_manifest_sha256 == sha256(
        _compact_json(manifest)
    ).hexdigest()
    assert normalized["namespace_manifest_sha256"] == (
        bound.namespace_manifest_sha256
    )
    assert normalized["decoder"] == {
        "path": DECODER_RELATIVE_PATH,
        "sha256": "2" * 64,
    }
    assert normalized["shell"] == {
        "edition": shell.edition,
        "file_version": shell.file_version,
        "parser_version": shell.parser_version,
        "path": shell.path,
        "product_version": shell.product_version,
        "sha256": shell.sha256,
    }
    assert normalized["command"] == {
        "metrics": {
            "ast_depth": 1,
            "ast_nodes": 1,
            "operations": 0,
            "pipeline_stages": 0,
            "statements": 0,
        },
        "nodes": [
            {
                "ast_type": "ScriptBlockAst",
                "child_indices": [],
                "index": 0,
                "invocation_operator": None,
                "literal": None,
                "parent_index": None,
                "role": "script_block",
            }
        ],
        "tokens": [
            {
                "flags": ["ParseModeInvariant"],
                "index": 0,
                "kind": "EndOfInput",
                "literal": None,
                "text": "",
            }
        ],
    }

    detached = json.loads(bound.normalized_plan_bytes)
    detached["command"]["nodes"][0]["ast_type"] = "MutatedAst"
    detached["namespaces"].append({"label": "mutated"})
    assert sha256(bound.normalized_plan_bytes).hexdigest() == (
        bound.normalized_plan_sha256
    )
    assert json.loads(bound.normalized_plan_bytes)["command"]["nodes"][0][
        "ast_type"
    ] == "ScriptBlockAst"
    for mutation in (
        {"normalized_plan_sha256": "0" * 64},
        {"normalized_plan_bytes": bytearray(bound.normalized_plan_bytes)},
        {"namespace_manifest_sha256": "0" * 64},
        {"namespaces": []},
        {"version": "complete-suite-bound-command-plan-v2"},
    ):
        _assert_stable_code(
            "COMMAND_PLAN_CANONICAL_INVALID",
            lambda mutation=mutation: replace(bound, **mutation),
        )
    object.__setattr__(bound, "raw_payload_sha256", "0" * 64)
    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        bound.__post_init__,
    )


def _task4_identity(command_plan: object, seed: int) -> object:
    return command_plan.FilesystemObjectIdentity(
        device=10 + seed,
        inode=100 + seed,
        file_type=1,
        reparse_tag=0,
        link_count=1,
    )


def _task4_namespace_observer(
    command_plan: object,
    *,
    case_sensitive: bool = False,
) -> tuple[object, list[str]]:
    calls: list[str] = []

    def observe(path: str) -> tuple[str, object, tuple[object, ...], bool]:
        normalized = str(PureWindowsPath(path))
        calls.append(normalized)
        seed = sum(normalized.encode("utf-8"))
        return (
            normalized,
            _task4_identity(command_plan, seed),
            (
                _task4_identity(command_plan, seed + 1),
                _task4_identity(command_plan, seed + 2),
            ),
            case_sensitive,
        )

    return observe, calls


def _task4_real_shell(command_plan: object) -> object:
    shell_path = Path(SHELL_PATH)
    shell_digest = sha256(shell_path.read_bytes()).hexdigest()
    assert shell_digest == (
        "db6dd81183fe57d22e03b911ec9a30a2fd7c40542e97743615355a6fb44f458f"
    )
    return command_plan.ShellIdentity(
        path=SHELL_PATH,
        sha256=shell_digest,
        file_version="7.6.4.500",
        product_version=(
            "7.6.4 SHA: "
            "929d27f4e66dcfba8f5f74ff03105705e483a27d+"
            "929d27f4e66dcfba8f5f74ff03105705e483a27d"
        ),
        edition="Core",
        parser_version="7.6.4",
    )


def _task4_real_decoded_payload(
    command_plan: object,
    payload: bytes,
    *,
    decoder_test_root: Path,
) -> object:
    completed = _run_real_decoder(payload, temp_root=decoder_test_root)
    assert completed.returncode == 0
    assert completed.stderr == b""
    document = json.loads(completed.stdout)
    canonical_bytes = _compact_json(document)
    return command_plan.DecodedPowerShellPayload(
        schema_version=DECODER_SCHEMA_VERSION,
        canonical_bytes=canonical_bytes,
        canonical_sha256=sha256(canonical_bytes).hexdigest(),
        token_count=len(document["tokens"]),
        parse_error_count=len(document["parse_errors"]),
    )


def _task4_render(command_plan: object, shell: object, payload: str) -> bytes:
    return command_plan.render_powershell_argv(
        payload,
        shell_path=shell.path,
        quote_style="single",
    )


def test_canonical_retained_namespace_factory_is_sorted_stable_and_unforgeable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_plan = _command_plan_module()
    observer, calls = _task4_namespace_observer(command_plan)
    monkeypatch.setattr(
        command_plan,
        "_observe_namespace_root",
        observer,
        raising=False,
    )
    requests = [
        command_plan.PathNamespaceRequest(
            raw_root=r"D:/raw-b",
            retained_root=r"D:/retained-b",
            label="workspace-b",
        ),
        command_plan.PathNamespaceRequest(
            raw_root=r"D:\raw-a",
            retained_root=r"D:\retained-a",
            label="workspace-a",
        ),
    ]
    bound = command_plan.bind_path_namespaces(requests)
    assert type(bound) is tuple
    assert tuple(item.label for item in bound) == ("workspace-a", "workspace-b")
    assert all(type(item) is command_plan.BoundPathNamespace for item in bound)
    assert all(re.fullmatch(r"[0-9a-f]{64}", item.canonical_sha256) for item in bound)
    assert len(calls) == 8
    assert sorted(calls) == sorted(
        [
            str(PureWindowsPath(request.raw_root))
            for request in requests
            for _ in range(2)
        ]
        + [
            str(PureWindowsPath(request.retained_root))
            for request in requests
            for _ in range(2)
        ]
    )
    requests.reverse()
    requests[0] = command_plan.PathNamespaceRequest(
        raw_root=r"D:\mutated",
        retained_root=r"D:\mutated-retained",
        label="mutated",
    )
    assert tuple(item.label for item in bound) == ("workspace-a", "workspace-b")

    shell = _shell()
    rendered = _task4_render(command_plan, shell, "")
    decode_calls = 0

    def forbidden_decode(*args: object, **kwargs: object) -> object:
        nonlocal decode_calls
        decode_calls += 1
        raise AssertionError("forged namespace reached decoder")

    monkeypatch.setattr(
        command_plan,
        "decode_powershell_payload",
        forbidden_decode,
        raising=True,
    )
    rejected_namespace_sets = (
        tuple(reversed(bound)),
        (replace(bound[0]),),
        (
            replace(
                bound[0],
                raw_identity=_task4_identity(command_plan, 5000),
            ),
        ),
        (
            replace(
                bound[0],
                raw_ancestor_identities=(
                    _task4_identity(command_plan, 5001),
                ),
            ),
        ),
        (
            replace(
                bound[0],
                raw_case_sensitive=not bound[0].raw_case_sensitive,
            ),
        ),
        (replace(bound[0], canonical_sha256="0" * 64),),
    )
    for rejected_namespaces in rejected_namespace_sets:
        _assert_stable_code(
            "COMMAND_PLAN_CANONICAL_INVALID",
            lambda rejected_namespaces=rejected_namespaces: (
                command_plan.bind_raw_and_retained_plans(
                    rendered,
                    rendered,
                    shell=shell,
                    decoder_path=DECODER_PATH,
                    decoder_sha256="2" * 64,
                    namespaces=rejected_namespaces,
                )
            ),
        )
    assert decode_calls == 0
    object.__setattr__(
        bound[0],
        "raw_identity",
        _task4_identity(command_plan, 5002),
    )
    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan._authenticate_bound_namespaces(bound),
    )


@pytest.mark.parametrize(
    ("requests", "case_sensitive"),
    (
        (
            (
                (r"D:\raw", r"D:\retained", "same"),
                (r"D:\other", r"D:\elsewhere", "same"),
            ),
            False,
        ),
        (
            (
                (r"D:\raw", r"D:\retained", "outer"),
                (r"D:\raw\child", r"D:\elsewhere", "inner"),
            ),
            False,
        ),
        (
            (
                (r"D:\raw", r"D:\retained", "outer"),
                (r"D:\other", r"D:\retained\child", "inner"),
            ),
            False,
        ),
        (
            (
                (r"D:\Raw", r"D:\retained-a", "first"),
                (r"d:\raw", r"D:\retained-b", "second"),
            ),
            True,
        ),
    ),
    ids=(
        "duplicate-label",
        "overlapping-raw-root",
        "overlapping-retained-root",
        "case-only-root-alias",
    ),
)
def test_canonical_retained_namespace_factory_rejects_collisions(
    monkeypatch: pytest.MonkeyPatch,
    requests: tuple[tuple[str, str, str], ...],
    case_sensitive: bool,
) -> None:
    command_plan = _command_plan_module()
    observer, _ = _task4_namespace_observer(
        command_plan,
        case_sensitive=case_sensitive,
    )
    monkeypatch.setattr(
        command_plan,
        "_observe_namespace_root",
        observer,
        raising=False,
    )
    values = tuple(
        command_plan.PathNamespaceRequest(
            raw_root=raw,
            retained_root=retained,
            label=label,
        )
        for raw, retained, label in requests
    )
    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan.bind_path_namespaces(values),
    )


def test_normalized_raw_retained_accepts_only_declared_literal_path_substitution(
    monkeypatch: pytest.MonkeyPatch,
    decoder_test_root: Path,
) -> None:
    command_plan = _command_plan_module()
    observer, calls = _task4_namespace_observer(command_plan)
    monkeypatch.setattr(
        command_plan,
        "_observe_namespace_root",
        observer,
        raising=False,
    )
    namespace = command_plan.bind_path_namespaces(
        (
            command_plan.PathNamespaceRequest(
                raw_root=r"D:\Raw Workspace",
                retained_root=r"D:\Retained Workspace",
                label="workspace",
            ),
        )
    )
    factory_call_count = len(calls)
    raw_payload = (
        "kokoro character request validate --input "
        "'D:\\Raw Workspace\\INPUTS\\Request.JSON' --json"
    )
    retained_payload = (
        "kokoro character request validate --input "
        "'D:\\Retained Workspace\\inputs\\request.json' --json"
    )
    raw_bytes = raw_payload.encode("utf-8")
    retained_bytes = retained_payload.encode("utf-8")
    raw_decoded = _task4_real_decoded_payload(
        command_plan,
        raw_bytes,
        decoder_test_root=decoder_test_root,
    )
    retained_decoded = _task4_real_decoded_payload(
        command_plan,
        retained_bytes,
        decoder_test_root=decoder_test_root,
    )
    decoded_by_payload = {
        raw_bytes: raw_decoded,
        retained_bytes: retained_decoded,
    }

    def fake_decode(candidate: bytes, **kwargs: object) -> object:
        return decoded_by_payload[candidate]

    monkeypatch.setattr(
        command_plan,
        "decode_powershell_payload",
        fake_decode,
        raising=True,
    )
    raw_semantic = command_plan._semantic_command_view(
        json.loads(raw_decoded.canonical_bytes),
        payload=raw_bytes,
        shell=_task4_real_shell(command_plan),
        decoder_sha256=sha256(DECODER_PATH.read_bytes()).hexdigest(),
        namespaces=namespace,
        side="raw",
    )
    retained_semantic = command_plan._semantic_command_view(
        json.loads(retained_decoded.canonical_bytes),
        payload=retained_bytes,
        shell=_task4_real_shell(command_plan),
        decoder_sha256=sha256(DECODER_PATH.read_bytes()).hexdigest(),
        namespaces=namespace,
        side="retained",
    )
    assert raw_semantic != retained_semantic
    assert command_plan._semantic_command_values_equivalent(
        raw_semantic,
        retained_semantic,
        namespaces=namespace,
    )
    bound = command_plan.bind_raw_and_retained_plans(
        _task4_render(command_plan, _task4_real_shell(command_plan), raw_payload),
        _task4_render(
            command_plan,
            _task4_real_shell(command_plan),
            retained_payload,
        ),
        shell=_task4_real_shell(command_plan),
        decoder_path=DECODER_PATH,
        decoder_sha256=sha256(DECODER_PATH.read_bytes()).hexdigest(),
        namespaces=namespace,
    )
    assert bound.namespaces is namespace
    normalized = json.loads(bound.normalized_plan_bytes)
    normalized_text = bound.normalized_plan_bytes.decode("utf-8")
    assert "Raw Workspace" not in normalized_text
    assert normalized["command"]["metrics"]["operations"] == 1
    assert [item["label"] for item in normalized["namespaces"]] == [
        "workspace"
    ]
    binder_calls = calls[factory_call_count:]
    assert binder_calls == [
        str(PureWindowsPath(r"D:\Retained Workspace")),
        str(PureWindowsPath(r"D:\Retained Workspace")),
    ]


@pytest.mark.parametrize(
    ("raw_case_sensitive", "retained_case_sensitive"),
    ((True, False), (False, True), (True, True)),
    ids=("raw-sensitive", "retained-sensitive", "both-sensitive"),
)
def test_normalized_raw_retained_requires_exact_case_when_either_root_sensitive(
    monkeypatch: pytest.MonkeyPatch,
    decoder_test_root: Path,
    raw_case_sensitive: bool,
    retained_case_sensitive: bool,
) -> None:
    command_plan = _command_plan_module()

    def observe(path: str) -> tuple[str, object, tuple[object, ...], bool]:
        normalized = str(PureWindowsPath(path))
        seed = sum(normalized.encode("utf-8"))
        return (
            normalized,
            _task4_identity(command_plan, seed),
            (
                _task4_identity(command_plan, seed + 1),
                _task4_identity(command_plan, seed + 2),
            ),
            (
                raw_case_sensitive
                if normalized == str(PureWindowsPath(r"D:\Raw Workspace"))
                else retained_case_sensitive
            ),
        )

    monkeypatch.setattr(
        command_plan,
        "_observe_namespace_root",
        observe,
        raising=False,
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
        "kokoro character request validate --input "
        "'D:\\Raw Workspace\\INPUTS\\Request.JSON' --json"
    )
    retained_payload = (
        "kokoro character request validate --input "
        "'D:\\Retained Workspace\\inputs\\request.json' --json"
    )
    raw_bytes = raw_payload.encode("utf-8")
    retained_bytes = retained_payload.encode("utf-8")
    decoded_by_payload = {
        raw_bytes: _task4_real_decoded_payload(
            command_plan,
            raw_bytes,
            decoder_test_root=decoder_test_root,
        ),
        retained_bytes: _task4_real_decoded_payload(
            command_plan,
            retained_bytes,
            decoder_test_root=decoder_test_root,
        ),
    }

    def fake_decode(candidate: bytes, **kwargs: object) -> object:
        return decoded_by_payload[candidate]

    monkeypatch.setattr(
        command_plan,
        "decode_powershell_payload",
        fake_decode,
        raising=True,
    )
    shell = _task4_real_shell(command_plan)
    _assert_stable_code(
        "COMMAND_PLAN_RAW_RETAINED_MISMATCH",
        lambda: command_plan.bind_raw_and_retained_plans(
            _task4_render(command_plan, shell, raw_payload),
            _task4_render(command_plan, shell, retained_payload),
            shell=shell,
            decoder_path=DECODER_PATH,
            decoder_sha256=sha256(DECODER_PATH.read_bytes()).hexdigest(),
            namespaces=namespaces,
        ),
    )


@pytest.mark.parametrize(
    ("raw_root", "retained_root", "raw_path", "retained_path"),
    (
        (
            r"D:\RawRoot",
            r"D:\RetainedRoot",
            r"D:\RawRoot\ß.txt",
            r"D:\RetainedRoot\SS.txt",
        ),
        (
            r"D:\ß",
            r"D:\RetainedRoot",
            r"D:\SS\case.json",
            r"D:\RetainedRoot\case.json",
        ),
    ),
    ids=("suffix-expansion", "root-expansion"),
)
def test_normalized_raw_retained_uses_windows_ordinal_case_semantics(
    monkeypatch: pytest.MonkeyPatch,
    decoder_test_root: Path,
    raw_root: str,
    retained_root: str,
    raw_path: str,
    retained_path: str,
) -> None:
    command_plan = _command_plan_module()
    observer, _ = _task4_namespace_observer(command_plan)
    monkeypatch.setattr(
        command_plan,
        "_observe_namespace_root",
        observer,
        raising=False,
    )
    namespaces = command_plan.bind_path_namespaces(
        (
            command_plan.PathNamespaceRequest(
                raw_root=raw_root,
                retained_root=retained_root,
                label="workspace",
            ),
        )
    )
    raw_payload = f"Get-Content -LiteralPath '{raw_path}' -Raw"
    retained_payload = f"Get-Content -LiteralPath '{retained_path}' -Raw"
    raw_bytes = raw_payload.encode("utf-8")
    retained_bytes = retained_payload.encode("utf-8")
    decoded_by_payload = {
        raw_bytes: _task4_real_decoded_payload(
            command_plan,
            raw_bytes,
            decoder_test_root=decoder_test_root,
        ),
        retained_bytes: _task4_real_decoded_payload(
            command_plan,
            retained_bytes,
            decoder_test_root=decoder_test_root,
        ),
    }

    def fake_decode(candidate: bytes, **kwargs: object) -> object:
        return decoded_by_payload[candidate]

    monkeypatch.setattr(
        command_plan,
        "decode_powershell_payload",
        fake_decode,
        raising=True,
    )
    shell = _task4_real_shell(command_plan)
    _assert_stable_code(
        "COMMAND_PLAN_RAW_RETAINED_MISMATCH",
        lambda: command_plan.bind_raw_and_retained_plans(
            _task4_render(command_plan, shell, raw_payload),
            _task4_render(command_plan, shell, retained_payload),
            shell=shell,
            decoder_path=DECODER_PATH,
            decoder_sha256=sha256(DECODER_PATH.read_bytes()).hexdigest(),
            namespaces=namespaces,
        ),
    )


@pytest.mark.parametrize(
    "retained_payload",
    (
        "other character request validate --input "
        "'D:\\Retained Workspace\\inputs\\request.json' --json",
        "kokoro character request validate --output "
        "'D:\\Retained Workspace\\inputs\\request.json' --json",
        "kokoro character request validate --input "
        "'D:\\Retained Workspace\\inputs\\other.json' --json",
        "kokoro character request validate --input "
        "'D:\\Retained WorkspaceX\\inputs\\request.json' --json",
        "kokoro character request validate --input "
        "'D:\\Retained Workspace\\inputs\\request.json.secret' --json",
        "kokoro character request validate --input "
        "'C:\\Users\\private\\request.json' --json",
        "kokoro character request validate --input "
        "'D:\\Retained Workspace\\inputs\\request.json' --json | Out-Null",
    ),
    ids=(
        "changed-command",
        "changed-option",
        "changed-path-suffix",
        "mid-token-root",
        "placeholder-smuggling",
        "undeclared-private-root",
        "changed-pipeline",
    ),
)
def test_normalized_raw_retained_rejects_semantic_and_path_mutants(
    monkeypatch: pytest.MonkeyPatch,
    decoder_test_root: Path,
    retained_payload: str,
) -> None:
    command_plan = _command_plan_module()
    observer, _ = _task4_namespace_observer(command_plan)
    monkeypatch.setattr(
        command_plan,
        "_observe_namespace_root",
        observer,
        raising=False,
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
        "kokoro character request validate --input "
        "'D:\\Raw Workspace\\inputs\\request.json' --json"
    )
    raw_bytes = raw_payload.encode("utf-8")
    retained_bytes = retained_payload.encode("utf-8")
    decoded_by_payload = {
        raw_bytes: _task4_real_decoded_payload(
            command_plan,
            raw_bytes,
            decoder_test_root=decoder_test_root,
        ),
        retained_bytes: _task4_real_decoded_payload(
            command_plan,
            retained_bytes,
            decoder_test_root=decoder_test_root,
        ),
    }

    def fake_decode(candidate: bytes, **kwargs: object) -> object:
        return decoded_by_payload[candidate]

    monkeypatch.setattr(
        command_plan,
        "decode_powershell_payload",
        fake_decode,
        raising=True,
    )
    shell = _task4_real_shell(command_plan)
    _assert_stable_code(
        "COMMAND_PLAN_RAW_RETAINED_MISMATCH",
        lambda: command_plan.bind_raw_and_retained_plans(
            _task4_render(command_plan, shell, raw_payload),
            _task4_render(command_plan, shell, retained_payload),
            shell=shell,
            decoder_path=DECODER_PATH,
            decoder_sha256=sha256(DECODER_PATH.read_bytes()).hexdigest(),
            namespaces=namespaces,
        ),
    )


def test_canonical_retained_namespace_real_observer_is_no_follow_and_complete(
    decoder_test_root: Path,
) -> None:
    command_plan = _command_plan_module()
    raw_root = decoder_test_root / "raw-root"
    retained_root = decoder_test_root / "retained-root"
    raw_root.mkdir()
    retained_root.mkdir()
    try:
        namespaces = command_plan.bind_path_namespaces(
            (
                command_plan.PathNamespaceRequest(
                    raw_root=str(raw_root),
                    retained_root=str(retained_root),
                    label="workspace",
                ),
            )
        )
        assert len(namespaces) == 1
        namespace = namespaces[0]
        assert PureWindowsPath(namespace.raw_root) == PureWindowsPath(raw_root)
        assert PureWindowsPath(namespace.retained_root) == PureWindowsPath(
            retained_root
        )
        for identity in (
            namespace.raw_identity,
            namespace.retained_identity,
            *namespace.raw_ancestor_identities,
            *namespace.retained_ancestor_identities,
        ):
            assert type(identity) is command_plan.FilesystemObjectIdentity
            assert identity.device > 0
            assert identity.inode > 0
            assert identity.file_type == 1
            assert identity.reparse_tag == 0
            assert identity.link_count > 0
        assert type(namespace.raw_case_sensitive) is bool
        assert type(namespace.retained_case_sensitive) is bool
        source = inspect.getsource(command_plan._observe_namespace_root)
        for marker in (
            "CreateFileW",
            "GetFileInformationByHandle",
            "GetFileInformationByHandleEx",
            "GetFinalPathNameByHandleW",
            "file_flag_open_reparse_point",
            "file_flag_backup_semantics",
            "file_case_sensitive_info",
            "CloseHandle",
        ):
            assert marker in source
    finally:
        retained_root.rmdir()
        raw_root.rmdir()


def test_canonical_retained_namespace_traversal_holds_relative_parent_handles(
) -> None:
    command_plan = _command_plan_module()
    source = inspect.getsource(command_plan._observe_namespace_root)
    for marker in (
        "NtCreateFile",
        "root_directory",
        "file_open_reparse_point",
        "obj_dont_reparse",
        "for handle in reversed(handles)",
    ):
        assert marker in source


def test_canonical_retained_namespace_traversal_rejects_case_different_parent(
    decoder_test_root: Path,
) -> None:
    command_plan = _command_plan_module()
    raw_parent = decoder_test_root / "RawParent"
    raw_root = raw_parent / "RawRoot"
    retained_root = decoder_test_root / "RetainedRoot"
    raw_parent.mkdir()
    raw_root.mkdir()
    retained_root.mkdir()
    case_different_raw_root = (
        decoder_test_root / "rawparent" / raw_root.name
    )
    assert str(case_different_raw_root) != str(raw_root)
    try:
        _assert_stable_code(
            "COMMAND_PLAN_CANONICAL_INVALID",
            lambda: command_plan.bind_path_namespaces(
                (
                    command_plan.PathNamespaceRequest(
                        raw_root=str(case_different_raw_root),
                        retained_root=str(retained_root),
                        label="workspace",
                    ),
                )
            ),
        )
    finally:
        retained_root.rmdir()
        raw_root.rmdir()
        raw_parent.rmdir()


def test_canonical_retained_namespace_identity_recheck_brackets_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_plan = _command_plan_module()
    initial_observer, _ = _task4_namespace_observer(command_plan)
    monkeypatch.setattr(
        command_plan,
        "_observe_namespace_root",
        initial_observer,
        raising=False,
    )
    namespaces = command_plan.bind_path_namespaces(
        (
            command_plan.PathNamespaceRequest(
                raw_root=r"D:\raw-race",
                retained_root=r"D:\retained-race",
                label="workspace",
            ),
        )
    )
    decoded = _task4_decoded_payload(command_plan, b"")
    decoder_started = False
    observed_paths: list[str] = []

    def race_observer(
        path: str,
    ) -> tuple[str, object, tuple[object, ...], bool]:
        normalized = str(PureWindowsPath(path))
        observed_paths.append(normalized)
        if normalized != namespaces[0].retained_root:
            raise AssertionError("binder re-observed unavailable raw root")
        identity = namespaces[0].retained_identity
        if decoder_started:
            identity = _task4_identity(command_plan, 9999)
        return (
            normalized,
            identity,
            namespaces[0].retained_ancestor_identities,
            namespaces[0].retained_case_sensitive,
        )

    def fake_decode(candidate: bytes, **kwargs: object) -> object:
        nonlocal decoder_started
        decoder_started = True
        return decoded

    monkeypatch.setattr(
        command_plan,
        "_observe_namespace_root",
        race_observer,
        raising=True,
    )
    monkeypatch.setattr(
        command_plan,
        "decode_powershell_payload",
        fake_decode,
        raising=True,
    )
    shell = _shell()
    rendered = _task4_render(command_plan, shell, "")
    _assert_stable_code(
        "COMMAND_PLAN_CANONICAL_INVALID",
        lambda: command_plan.bind_raw_and_retained_plans(
            rendered,
            rendered,
            shell=shell,
            decoder_path=DECODER_PATH,
            decoder_sha256="2" * 64,
            namespaces=namespaces,
        ),
    )
    assert observed_paths == [
        namespaces[0].retained_root,
        namespaces[0].retained_root,
    ]


TASK4_FIXTURE_VERSION = "complete-suite-command-plan-fixture-v1"
TASK4_FIXTURE_ROOT = (
    SKILLS_ROOT / "fixtures" / "complete-suite-command-plan"
)
TASK4_FIXTURE_PAYLOADS = {
    "direct-cli": (
        "kokoro character request validate "
        "--input '.\\inputs\\request.json' --json"
    ),
    "call-operator-cli": (
        "& '.tools\\kokoro.cmd' pack validate "
        "'.\\source-packs\\rin' --json"
    ),
    "compound-cli": (
        "kokoro character request validate "
        "--input '.\\inputs\\request.json' --json; "
        "kokoro character draft validate "
        "--request '.\\inputs\\request.json' "
        "--pack '.\\source-packs\\rin' --json"
    ),
    "read-pipeline": (
        "Get-Content -LiteralPath '.\\case.json' -Raw | "
        "Select-Object -First 1"
    ),
}


def _task4_load_fixture(name: str) -> tuple[bytes, dict[str, object]]:
    path = TASK4_FIXTURE_ROOT / f"{name}.json"
    fixture_bytes = path.read_bytes()
    assert not fixture_bytes.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in fixture_bytes

    def reject_duplicates(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            assert key not in result
            result[key] = value
        return result

    document = json.loads(
        fixture_bytes.decode("utf-8", errors="strict"),
        object_pairs_hook=reject_duplicates,
    )
    assert type(document) is dict
    assert _compact_json(document) == fixture_bytes
    return fixture_bytes, document


@pytest.mark.parametrize("name", tuple(TASK4_FIXTURE_PAYLOADS))
def test_fixture_canonical_normalized_plan_matches_live_decoder(
    name: str,
    decoder_test_root: Path,
) -> None:
    command_plan = _command_plan_module()
    fixture_bytes, document = _task4_load_fixture(name)
    payload = TASK4_FIXTURE_PAYLOADS[name]
    payload_bytes = payload.encode("utf-8")
    assert set(document) == {
        "decoder_facts",
        "fixture_version",
        "name",
        "normalized_plan",
        "payload_sha256",
        "payload_utf8",
        "payload_utf8_bytes",
    }
    assert document["fixture_version"] == TASK4_FIXTURE_VERSION
    assert document["name"] == name
    assert document["payload_utf8"] == payload
    assert document["payload_utf8_bytes"] == len(payload_bytes)
    assert document["payload_sha256"] == sha256(payload_bytes).hexdigest()
    decoded = _task4_real_decoded_payload(
        command_plan,
        payload_bytes,
        decoder_test_root=decoder_test_root,
    )
    shell = _task4_real_shell(command_plan)
    decoder_digest = sha256(DECODER_PATH.read_bytes()).hexdigest()
    normalized = command_plan._semantic_command_view(
        json.loads(decoded.canonical_bytes),
        payload=payload_bytes,
        shell=shell,
        decoder_sha256=decoder_digest,
    )
    normalized_bytes = _compact_json(normalized)
    assert document["normalized_plan"] == normalized
    assert document["decoder_facts"] == {
        "decoder": {
            "path": DECODER_RELATIVE_PATH,
            "sha256": decoder_digest,
        },
        "decoder_plan_sha256": decoded.canonical_sha256,
        "normalized_plan_sha256": sha256(normalized_bytes).hexdigest(),
        "parse_error_count": 0,
        "schema_version": DECODER_SCHEMA_VERSION,
        "shell": {
            "edition": shell.edition,
            "file_version": shell.file_version,
            "parser_version": shell.parser_version,
            "product_version": shell.product_version,
            "sha256": shell.sha256,
        },
        "token_count": decoded.token_count,
    }
    forbidden = (
        b"Approved5",
        b'"prompt"',
        b'"final_response"',
        b'"outcome"',
        b"C:\\\\Users\\\\",
        str(decoder_test_root).encode("utf-8"),
    )
    for marker in forbidden:
        assert marker not in fixture_bytes


@pytest.mark.parametrize("name", tuple(TASK4_FIXTURE_PAYLOADS))
def test_fixture_repeatability_uses_ten_separate_decoder_processes(
    name: str,
    decoder_test_root: Path,
) -> None:
    command_plan = _command_plan_module()
    _fixture_bytes, fixture = _task4_load_fixture(name)
    payload = TASK4_FIXTURE_PAYLOADS[name].encode("utf-8")
    shell = _task4_real_shell(command_plan)
    decoder_digest = sha256(DECODER_PATH.read_bytes()).hexdigest()
    decoder_plan_bytes: list[bytes] = []
    normalized_plan_bytes: list[bytes] = []
    for _attempt in range(10):
        decoded = _task4_real_decoded_payload(
            command_plan,
            payload,
            decoder_test_root=decoder_test_root,
        )
        decoder_plan_bytes.append(decoded.canonical_bytes)
        normalized = command_plan._semantic_command_view(
            json.loads(decoded.canonical_bytes),
            payload=payload,
            shell=shell,
            decoder_sha256=decoder_digest,
        )
        normalized_plan_bytes.append(_compact_json(normalized))
    assert len(decoder_plan_bytes) == 10
    assert len(set(decoder_plan_bytes)) == 1
    assert len(set(normalized_plan_bytes)) == 1
    assert json.loads(normalized_plan_bytes[0]) == fixture["normalized_plan"]
    assert sha256(decoder_plan_bytes[0]).hexdigest() == fixture[
        "decoder_facts"
    ]["decoder_plan_sha256"]
    assert sha256(normalized_plan_bytes[0]).hexdigest() == fixture[
        "decoder_facts"
    ]["normalized_plan_sha256"]


def test_repeatability_mutation_changes_or_rejects_shell_decoder_payload(
    decoder_test_root: Path,
) -> None:
    command_plan = _command_plan_module()
    _fixture_bytes, fixture = _task4_load_fixture("direct-cli")
    payload = TASK4_FIXTURE_PAYLOADS["direct-cli"].encode("utf-8")
    shell = _task4_real_shell(command_plan)
    decoder_digest = sha256(DECODER_PATH.read_bytes()).hexdigest()
    decoded = _task4_real_decoded_payload(
        command_plan,
        payload,
        decoder_test_root=decoder_test_root,
    )
    document = json.loads(decoded.canonical_bytes)
    baseline = command_plan._semantic_command_view(
        document,
        payload=payload,
        shell=shell,
        decoder_sha256=decoder_digest,
    )
    assert baseline == fixture["normalized_plan"]

    mutated_payload = payload[:-1] + b"x"
    mutated_decoded = _task4_real_decoded_payload(
        command_plan,
        mutated_payload,
        decoder_test_root=decoder_test_root,
    )
    mutated_plan = command_plan._semantic_command_view(
        json.loads(mutated_decoded.canonical_bytes),
        payload=mutated_payload,
        shell=shell,
        decoder_sha256=decoder_digest,
    )
    assert _compact_json(mutated_plan) != _compact_json(baseline)

    changed_shell = replace(shell, parser_version="7.6.5")
    _assert_stable_code(
        "COMMAND_DECODER_IDENTITY_MISMATCH",
        lambda: command_plan._semantic_command_view(
            document,
            payload=payload,
            shell=changed_shell,
            decoder_sha256=decoder_digest,
        ),
    )
    changed_decoder_digest = (
        ("0" if decoder_digest[0] != "0" else "1") + decoder_digest[1:]
    )
    _assert_stable_code(
        "COMMAND_DECODER_IDENTITY_MISMATCH",
        lambda: command_plan._semantic_command_view(
            document,
            payload=payload,
            shell=shell,
            decoder_sha256=changed_decoder_digest,
        ),
    )
