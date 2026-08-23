from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
from hashlib import sha256
import json
import msvcrt
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import tempfile
import threading
import time
from typing import Any, Literal, NoReturn

from jsonschema import Draft202012Validator


COMMAND_WRAPPER_INVALID = "COMMAND_WRAPPER_INVALID"
COMMAND_WRAPPER_IDENTITY_MISMATCH = "COMMAND_WRAPPER_IDENTITY_MISMATCH"
COMMAND_PAYLOAD_LIMIT_EXCEEDED = "COMMAND_PAYLOAD_LIMIT_EXCEEDED"
COMMAND_DECODER_IDENTITY_MISMATCH = "COMMAND_DECODER_IDENTITY_MISMATCH"
COMMAND_DECODER_PARSE_INVALID = "COMMAND_DECODER_PARSE_INVALID"
COMMAND_DECODER_LIMIT_EXCEEDED = "COMMAND_DECODER_LIMIT_EXCEEDED"
COMMAND_PLAN_SCHEMA_INVALID = "COMMAND_PLAN_SCHEMA_INVALID"
COMMAND_PLAN_CANONICAL_INVALID = "COMMAND_PLAN_CANONICAL_INVALID"

_PAYLOAD_LIMIT_BYTES = 256 * 1024
_DECODER_SCHEMA_VERSION = "complete-suite-command-plan-decoder-v1"
_DECODER_RELATIVE_PATH = "tests/skills/complete_suite_command_plan_decoder.ps1"
_PIPE_CHUNK_BYTES = 64 * 1024
_STDERR_LIMIT_BYTES = 64 * 1024
_DECODER_TIMEOUT_SECONDS = 30.0
_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}")
_WRAPPER_ARGUMENTS = b" -NoLogo -NoProfile -NonInteractive -Command "
_APOSTROPHE = 0x27
_DOUBLE_QUOTE = 0x22
_BACKSLASH = 0x5C
_TOKEN_KINDS = frozenset(
    {
        "Unknown", "Variable", "SplattedVariable", "Parameter", "Number",
        "Label", "Identifier", "Generic", "NewLine", "LineContinuation",
        "Comment", "EndOfInput", "StringLiteral", "StringExpandable",
        "HereStringLiteral", "HereStringExpandable", "LParen", "RParen",
        "LCurly", "RCurly", "LBracket", "RBracket", "AtParen", "AtCurly",
        "DollarParen", "Semi", "AndAnd", "OrOr", "Ampersand", "Pipe",
        "Comma", "MinusMinus", "PlusPlus", "DotDot", "ColonColon", "Dot",
        "Exclaim", "Multiply", "Divide", "Rem", "Plus", "Minus", "Equals",
        "PlusEquals", "MinusEquals", "MultiplyEquals", "DivideEquals",
        "RemainderEquals", "Redirection", "RedirectInStd", "Format", "Not",
        "Bnot", "And", "Or", "Xor", "Band", "Bor", "Bxor", "Join", "Ieq",
        "Ine", "Ige", "Igt", "Ilt", "Ile", "Ilike", "Inotlike", "Imatch",
        "Inotmatch", "Ireplace", "Icontains", "Inotcontains", "Iin", "Inotin",
        "Isplit", "Ceq", "Cne", "Cge", "Cgt", "Clt", "Cle", "Clike",
        "Cnotlike", "Cmatch", "Cnotmatch", "Creplace", "Ccontains",
        "Cnotcontains", "Cin", "Cnotin", "Csplit", "Is", "IsNot", "As",
        "PostfixPlusPlus", "PostfixMinusMinus", "Shl", "Shr", "Colon",
        "QuestionMark", "QuestionQuestionEquals", "QuestionQuestion",
        "QuestionDot", "QuestionLBracket", "Begin", "Break", "Catch", "Class",
        "Continue", "Data", "Define", "Do", "Dynamicparam", "Else", "ElseIf",
        "End", "Exit", "Filter", "Finally", "For", "Foreach", "From",
        "Function", "If", "In", "Param", "Process", "Return", "Switch",
        "Throw", "Trap", "Try", "Until", "Using", "Var", "While", "Workflow",
        "Parallel", "Sequence", "InlineScript", "Configuration",
        "DynamicKeyword", "Public", "Private", "Static", "Interface", "Enum",
        "Namespace", "Module", "Type", "Assembly", "Command", "Hidden", "Base",
        "Default", "Clean",
    }
)
_TOKEN_FLAGS = frozenset(
    {
        "None", "BinaryPrecedenceLogical", "BinaryPrecedenceBitwise",
        "BinaryPrecedenceComparison", "BinaryPrecedenceCoalesce",
        "BinaryPrecedenceAdd", "BinaryPrecedenceMultiply",
        "BinaryPrecedenceFormat", "BinaryPrecedenceRange",
        "BinaryPrecedenceMask", "Keyword", "ScriptBlockBlockName",
        "BinaryOperator", "UnaryOperator", "CaseSensitiveOperator",
        "TernaryOperator", "SpecialOperator", "AssignmentOperator",
        "ParseModeInvariant", "TokenInError", "DisallowedInRestrictedMode",
        "PrefixOrPostfixOperator", "CommandName", "MemberName", "TypeName",
        "AttributeName", "CanConstantFold", "StatementDoesntSupportAttributes",
    }
)
_SAFE_TOKEN_LITERAL_KINDS = frozenset(
    {"Identifier", "Number", "StringLiteral"}
)
_AST_TYPES_BY_ROLE = {
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
_AST_ROLE_BY_TYPE = {
    ast_type: role
    for role, ast_types in _AST_TYPES_BY_ROLE.items()
    for ast_type in ast_types
}
_CONCRETE_STATEMENT_AST_TYPES = frozenset(
    {
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
    }
)
_OPERATION_AST_TYPES = frozenset({"CommandAst"})
_PIPELINE_STAGE_AST_TYPES = frozenset(
    {"CommandAst", "CommandExpressionAst"}
)
_AST_NODE_KEYS = frozenset(
    {
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
)
_AST_METRIC_KEYS = frozenset(
    {
        "ast_nodes",
        "ast_depth",
        "statements",
        "operations",
        "pipeline_stages",
    }
)


@dataclass(frozen=True)
class ShellIdentity:
    path: str
    sha256: str
    file_version: str
    product_version: str
    edition: str
    parser_version: str


@dataclass(frozen=True)
class ExtractedPowerShellPayload:
    rendered_utf8_bytes: int
    rendered_sha256: str
    payload_field_utf8_bytes: int
    payload_field_sha256: str
    payload_utf8_bytes: int
    payload_sha256: str
    payload: str


@dataclass(frozen=True)
class DecoderLimits:
    payload_bytes: int = 256 * 1024
    tokens: int = 8192
    parse_errors: int = 256
    ast_nodes: int = 8192
    ast_depth: int = 64
    statements: int = 256
    operations: int = 256
    pipeline_stages: int = 256
    plan_bytes: int = 4 * 1024 * 1024

    def __post_init__(self) -> None:
        values = (
            self.payload_bytes,
            self.tokens,
            self.parse_errors,
            self.ast_nodes,
            self.ast_depth,
            self.statements,
            self.operations,
            self.pipeline_stages,
            self.plan_bytes,
        )
        if any(type(value) is not int for value in values) or values != (
            256 * 1024,
            8192,
            256,
            8192,
            64,
            256,
            256,
            256,
            4 * 1024 * 1024,
        ):
            raise RuntimeError(COMMAND_DECODER_LIMIT_EXCEEDED)


_DECODER_LIMITS = DecoderLimits()


@dataclass(frozen=True, repr=False)
class DecodedPowerShellPayload:
    schema_version: Literal["complete-suite-command-plan-decoder-v1"]
    canonical_bytes: bytes = field(repr=False)
    canonical_sha256: str
    token_count: int
    parse_error_count: int

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not str
            or self.schema_version != _DECODER_SCHEMA_VERSION
        ):
            _reject(COMMAND_PLAN_SCHEMA_INVALID)
        if type(self.canonical_bytes) is not bytes:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        if not _is_sha256(self.canonical_sha256):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        if sha256(self.canonical_bytes).hexdigest() != self.canonical_sha256:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        _enforce_decoder_document_limit(self.canonical_bytes)
        try:
            embedded = _decode_single_json_object(self.canonical_bytes)
        except RuntimeError:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        if embedded.get("schema_version") != _DECODER_SCHEMA_VERSION:
            _reject(COMMAND_PLAN_SCHEMA_INVALID)
        schema = _load_decoder_schema()
        try:
            schema_errors = tuple(
                Draft202012Validator(schema).iter_errors(embedded)
            )
        except Exception:
            _reject(COMMAND_PLAN_SCHEMA_INVALID)
        if schema_errors:
            _reject(COMMAND_PLAN_SCHEMA_INVALID)
        if _canonical_json_bytes(embedded) != self.canonical_bytes:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        if (
            type(self.token_count) is not int
            or self.token_count < 0
            or self.token_count > _DECODER_LIMITS.tokens
            or type(self.parse_error_count) is not int
            or self.parse_error_count < 0
            or self.parse_error_count > _DECODER_LIMITS.parse_errors
        ):
            _reject(COMMAND_DECODER_LIMIT_EXCEEDED)
        if (
            self.token_count != len(embedded["tokens"])
            or self.parse_error_count != len(embedded["parse_errors"])
        ):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)


@dataclass(frozen=True, repr=False)
class _WindowsNativeVector:
    contract: Literal["complete-suite-windows-native-vector-v1"]
    utf16_units: int
    utf16le_sha256: str
    command_line: str = field(repr=False)


@dataclass(frozen=True)
class _PlainFileObservation:
    normalized_path: str
    volume_serial: int
    file_index: int
    size: int
    link_count: int
    sha256: str


def _reject(code: str) -> NoReturn:
    raise RuntimeError(code)


def _is_absolute_shell_path(path: object) -> bool:
    if type(path) is not str or not path:
        return False
    for character in path:
        if (
            character == "\x00"
            or character == "\r"
            or character == "\n"
            or character == '"'
        ):
            return False
    try:
        path.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return PureWindowsPath(path).is_absolute()


def _payload_utf8(payload: object) -> bytes:
    if type(payload) is not str:
        _reject(COMMAND_WRAPPER_INVALID)
    payload_utf8_bytes = 0
    for character in payload:
        scalar = ord(character)
        if scalar == 0x00 or scalar == 0x0D or 0xD800 <= scalar <= 0xDFFF:
            _reject(COMMAND_WRAPPER_INVALID)
        if scalar <= 0x7F:
            payload_utf8_bytes += 1
        elif scalar <= 0x7FF:
            payload_utf8_bytes += 2
        elif scalar <= 0xFFFF:
            payload_utf8_bytes += 3
        else:
            payload_utf8_bytes += 4
    if payload_utf8_bytes > _PAYLOAD_LIMIT_BYTES:
        _reject(COMMAND_PAYLOAD_LIMIT_EXCEEDED)
    try:
        payload_bytes = payload.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _reject(COMMAND_WRAPPER_INVALID)
    if len(payload_bytes) != payload_utf8_bytes:
        _reject(COMMAND_WRAPPER_INVALID)
    return payload_bytes


def _render_single_quoted(payload: bytes) -> bytes:
    rendered = bytearray((_APOSTROPHE,))
    for value in payload:
        rendered.append(value)
        if value == _APOSTROPHE:
            rendered.append(value)
    rendered.append(_APOSTROPHE)
    return bytes(rendered)


def _render_double_quoted(payload: bytes) -> bytes:
    rendered = bytearray((_DOUBLE_QUOTE,))
    cursor = 0
    while cursor < len(payload):
        value = payload[cursor]
        if value == _BACKSLASH:
            run_start = cursor
            while cursor < len(payload) and payload[cursor] == _BACKSLASH:
                cursor += 1
            run_length = cursor - run_start
            if cursor == len(payload):
                rendered.extend((_BACKSLASH,) * (run_length * 2))
                break
            if payload[cursor] == _DOUBLE_QUOTE:
                rendered.extend((_BACKSLASH,) * (run_length * 2 + 1))
                rendered.append(_DOUBLE_QUOTE)
                cursor += 1
                continue
            rendered.extend((_BACKSLASH,) * run_length)
            continue
        if value == _DOUBLE_QUOTE:
            rendered.append(_BACKSLASH)
        rendered.append(value)
        cursor += 1
    rendered.append(_DOUBLE_QUOTE)
    return bytes(rendered)


def render_powershell_argv(
    payload: str,
    *,
    shell_path: str,
    quote_style: Literal["single", "double"],
) -> bytes:
    if not _is_absolute_shell_path(shell_path):
        _reject(COMMAND_WRAPPER_INVALID)
    if type(quote_style) is not str:
        _reject(COMMAND_WRAPPER_INVALID)
    if quote_style != "single" and quote_style != "double":
        _reject(COMMAND_WRAPPER_INVALID)

    payload_bytes = _payload_utf8(payload)
    try:
        shell_path_bytes = shell_path.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _reject(COMMAND_WRAPPER_INVALID)

    if quote_style == "single":
        payload_field = _render_single_quoted(payload_bytes)
    else:
        payload_field = _render_double_quoted(payload_bytes)
    return (
        b'"'
        + shell_path_bytes
        + b'"'
        + _WRAPPER_ARGUMENTS
        + payload_field
    )


def _reject_forbidden_rendered_bytes(rendered: bytes) -> None:
    for value in rendered:
        if value in (0x00, 0x0D):
            _reject(COMMAND_WRAPPER_INVALID)


def _is_utf8_continuation(value: int) -> bool:
    return 0x80 <= value <= 0xBF


def _reject_invalid_utf8(rendered: bytes) -> None:
    cursor = 0
    while cursor < len(rendered):
        first = rendered[cursor]
        if first <= 0x7F:
            cursor += 1
            continue
        if 0xC2 <= first <= 0xDF:
            if (
                cursor + 1 >= len(rendered)
                or not _is_utf8_continuation(rendered[cursor + 1])
            ):
                _reject(COMMAND_WRAPPER_INVALID)
            cursor += 2
            continue
        if 0xE0 <= first <= 0xEF:
            if cursor + 2 >= len(rendered):
                _reject(COMMAND_WRAPPER_INVALID)
            second = rendered[cursor + 1]
            third = rendered[cursor + 2]
            if first == 0xE0:
                second_is_valid = 0xA0 <= second <= 0xBF
            elif first == 0xED:
                second_is_valid = 0x80 <= second <= 0x9F
            else:
                second_is_valid = _is_utf8_continuation(second)
            if not second_is_valid or not _is_utf8_continuation(third):
                _reject(COMMAND_WRAPPER_INVALID)
            cursor += 3
            continue
        if 0xF0 <= first <= 0xF4:
            if cursor + 3 >= len(rendered):
                _reject(COMMAND_WRAPPER_INVALID)
            second = rendered[cursor + 1]
            third = rendered[cursor + 2]
            fourth = rendered[cursor + 3]
            if first == 0xF0:
                second_is_valid = 0x90 <= second <= 0xBF
            elif first == 0xF4:
                second_is_valid = 0x80 <= second <= 0x8F
            else:
                second_is_valid = _is_utf8_continuation(second)
            if (
                not second_is_valid
                or not _is_utf8_continuation(third)
                or not _is_utf8_continuation(fourth)
            ):
                _reject(COMMAND_WRAPPER_INVALID)
            cursor += 4
            continue
        _reject(COMMAND_WRAPPER_INVALID)


def _closing_shell_quote(rendered: bytes) -> int:
    if not rendered or rendered[0] != _DOUBLE_QUOTE:
        _reject(COMMAND_WRAPPER_INVALID)
    cursor = 1
    while cursor < len(rendered):
        if rendered[cursor] == _DOUBLE_QUOTE:
            return cursor
        cursor += 1
    _reject(COMMAND_WRAPPER_INVALID)


def _count_single_quoted(field: memoryview) -> int:
    payload_bytes = 0
    cursor = 1
    while cursor < len(field):
        value = field[cursor]
        if value != _APOSTROPHE:
            payload_bytes += 1
            cursor += 1
            continue
        if cursor + 1 < len(field) and field[cursor + 1] == _APOSTROPHE:
            payload_bytes += 1
            cursor += 2
            continue
        if cursor != len(field) - 1:
            _reject(COMMAND_WRAPPER_INVALID)
        return payload_bytes
    _reject(COMMAND_WRAPPER_INVALID)


def _count_double_quoted(field: memoryview) -> int:
    payload_bytes = 0
    cursor = 1
    while cursor < len(field):
        value = field[cursor]
        if value == _BACKSLASH:
            run_start = cursor
            while cursor < len(field) and field[cursor] == _BACKSLASH:
                cursor += 1
            run_length = cursor - run_start
            if cursor < len(field) and field[cursor] == _DOUBLE_QUOTE:
                payload_bytes += run_length // 2
                if run_length % 2:
                    payload_bytes += 1
                    cursor += 1
                    continue
                if cursor != len(field) - 1:
                    _reject(COMMAND_WRAPPER_INVALID)
                return payload_bytes
            payload_bytes += run_length
            continue
        if value == _DOUBLE_QUOTE:
            if cursor != len(field) - 1:
                _reject(COMMAND_WRAPPER_INVALID)
            return payload_bytes
        payload_bytes += 1
        cursor += 1
    _reject(COMMAND_WRAPPER_INVALID)


def _decode_single_quoted(field: memoryview) -> bytes:
    payload = bytearray()
    cursor = 1
    while cursor < len(field):
        value = field[cursor]
        if value != _APOSTROPHE:
            payload.append(value)
            cursor += 1
            continue
        if cursor + 1 < len(field) and field[cursor + 1] == _APOSTROPHE:
            payload.append(_APOSTROPHE)
            cursor += 2
            continue
        if cursor != len(field) - 1:
            _reject(COMMAND_WRAPPER_INVALID)
        return bytes(payload)
    _reject(COMMAND_WRAPPER_INVALID)


def _decode_double_quoted(field: memoryview) -> bytes:
    payload = bytearray()
    cursor = 1
    while cursor < len(field):
        value = field[cursor]
        if value == _BACKSLASH:
            run_start = cursor
            while cursor < len(field) and field[cursor] == _BACKSLASH:
                cursor += 1
            run_length = cursor - run_start
            if cursor < len(field) and field[cursor] == _DOUBLE_QUOTE:
                payload.extend((_BACKSLASH,) * (run_length // 2))
                if run_length % 2:
                    payload.append(_DOUBLE_QUOTE)
                    cursor += 1
                    continue
                if cursor != len(field) - 1:
                    _reject(COMMAND_WRAPPER_INVALID)
                return bytes(payload)
            payload.extend((_BACKSLASH,) * run_length)
            continue
        if value == _DOUBLE_QUOTE:
            if cursor != len(field) - 1:
                _reject(COMMAND_WRAPPER_INVALID)
            return bytes(payload)
        payload.append(value)
        cursor += 1
    _reject(COMMAND_WRAPPER_INVALID)


def extract_powershell_payload(
    rendered: bytes,
    *,
    shell: ShellIdentity,
) -> ExtractedPowerShellPayload:
    if type(rendered) is not bytes or type(shell) is not ShellIdentity:
        _reject(COMMAND_WRAPPER_INVALID)
    if not _is_absolute_shell_path(shell.path):
        _reject(COMMAND_WRAPPER_INVALID)
    _reject_forbidden_rendered_bytes(rendered)
    _reject_invalid_utf8(rendered)

    closing_quote = _closing_shell_quote(rendered)
    rendered_shell_path = rendered[1:closing_quote]
    try:
        decoded_shell_path = rendered_shell_path.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _reject(COMMAND_WRAPPER_INVALID)
    if not _is_absolute_shell_path(decoded_shell_path):
        _reject(COMMAND_WRAPPER_INVALID)

    arguments_start = closing_quote + 1
    arguments_end = arguments_start + len(_WRAPPER_ARGUMENTS)
    if rendered[arguments_start:arguments_end] != _WRAPPER_ARGUMENTS:
        _reject(COMMAND_WRAPPER_INVALID)
    payload_field = memoryview(rendered)[arguments_end:]
    if len(payload_field) < 2:
        _reject(COMMAND_WRAPPER_INVALID)

    if payload_field[0] == _APOSTROPHE:
        quote_style: Literal["single", "double"] = "single"
        decoded_payload_bytes = _count_single_quoted(payload_field)
    elif payload_field[0] == _DOUBLE_QUOTE:
        quote_style = "double"
        decoded_payload_bytes = _count_double_quoted(payload_field)
    else:
        _reject(COMMAND_WRAPPER_INVALID)
    if decoded_payload_bytes > _PAYLOAD_LIMIT_BYTES:
        _reject(COMMAND_PAYLOAD_LIMIT_EXCEEDED)

    if quote_style == "single":
        payload_bytes = _decode_single_quoted(payload_field)
    else:
        payload_bytes = _decode_double_quoted(payload_field)
    if len(payload_bytes) != decoded_payload_bytes:
        _reject(COMMAND_WRAPPER_INVALID)

    try:
        payload = payload_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _reject(COMMAND_WRAPPER_INVALID)

    rerendered = render_powershell_argv(
        payload,
        shell_path=decoded_shell_path,
        quote_style=quote_style,
    )
    if rerendered != rendered:
        _reject(COMMAND_WRAPPER_INVALID)
    if decoded_shell_path != shell.path:
        _reject(COMMAND_WRAPPER_IDENTITY_MISMATCH)

    return ExtractedPowerShellPayload(
        rendered_utf8_bytes=len(rendered),
        rendered_sha256=sha256(rendered).hexdigest(),
        payload_field_utf8_bytes=len(payload_field),
        payload_field_sha256=sha256(payload_field).hexdigest(),
        payload_utf8_bytes=len(payload_bytes),
        payload_sha256=sha256(payload_bytes).hexdigest(),
        payload=payload,
    )


def _is_sha256(value: object) -> bool:
    return type(value) is str and _LOWER_SHA256.fullmatch(value) is not None


def _check_decoder_count(value: int, *, limit: int) -> int:
    if (
        type(value) is not int
        or type(limit) is not int
        or value < 0
        or limit < 0
        or value > limit
    ):
        _reject(COMMAND_DECODER_LIMIT_EXCEEDED)
    return value


def _enforce_decoder_document_limit(value: bytes) -> bytes:
    if type(value) is not bytes:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    if len(value) > _DECODER_LIMITS.plan_bytes:
        _reject(COMMAND_DECODER_LIMIT_EXCEEDED)
    return value


def _utf16_to_utf8_boundary_table(
    payload: bytes,
) -> tuple[int | None, ...]:
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    boundaries: list[int | None] = [None] * (len(payload) + 1)
    boundaries[0] = 0
    utf16_offset = 0
    utf8_offset = 0
    for character in text:
        scalar = ord(character)
        if 0xD800 <= scalar <= 0xDFFF:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        utf16_offset += 2 if scalar > 0xFFFF else 1
        if scalar <= 0x7F:
            utf8_offset += 1
        elif scalar <= 0x7FF:
            utf8_offset += 2
        elif scalar <= 0xFFFF:
            utf8_offset += 3
        else:
            utf8_offset += 4
        boundaries[utf16_offset] = utf8_offset
    if utf8_offset != len(payload):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    return tuple(boundaries[: utf16_offset + 1])


def _validate_emitted_span(
    entry: dict[str, Any],
    boundaries: tuple[int | None, ...],
) -> None:
    start_utf16 = entry["start_utf16"]
    end_utf16 = entry["end_utf16"]
    start_utf8 = entry["start_utf8"]
    end_utf8 = entry["end_utf8"]
    if (
        type(start_utf16) is not int
        or type(end_utf16) is not int
        or type(start_utf8) is not int
        or type(end_utf8) is not int
        or start_utf16 < 0
        or end_utf16 < start_utf16
        or end_utf16 >= len(boundaries)
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    expected_start = boundaries[start_utf16]
    expected_end = boundaries[end_utf16]
    if (
        expected_start is None
        or expected_end is None
        or start_utf8 != expected_start
        or end_utf8 != expected_end
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)


def _validate_decoder_spans(
    document: dict[str, Any],
    payload: bytes,
) -> tuple[int | None, ...]:
    boundaries = _utf16_to_utf8_boundary_table(payload)
    for collection_name in ("parse_errors", "tokens", "nodes"):
        for entry in document[collection_name]:
            _validate_emitted_span(entry, boundaries)
    return boundaries


def _single_quoted_token_value(token_bytes: bytes) -> str:
    try:
        source = token_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    if len(source) < 2 or source[0] != "'" or source[-1] != "'":
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    value: list[str] = []
    cursor = 1
    while cursor < len(source) - 1:
        character = source[cursor]
        if character != "'":
            value.append(character)
            cursor += 1
            continue
        if cursor + 1 >= len(source) - 1 or source[cursor + 1] != "'":
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        value.append("'")
        cursor += 2
    return "".join(value)


def _validate_token_literal(
    token: dict[str, Any],
    token_bytes: bytes,
) -> None:
    kind = token["kind"]
    literal = token["literal"]
    if kind not in _SAFE_TOKEN_LITERAL_KINDS:
        if literal is not None:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        return
    if type(literal) is not dict or set(literal) != {
        "kind",
        "value",
        "utf8_bytes",
        "sha256",
    }:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    if kind == "StringLiteral":
        expected_literal_kind = "single_quoted"
        expected_value = _single_quoted_token_value(token_bytes)
    else:
        expected_literal_kind = "bare"
        try:
            expected_value = token_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
    value = literal["value"]
    if type(value) is not str:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    try:
        value_bytes = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    if (
        literal["kind"] != expected_literal_kind
        or value != expected_value
        or type(literal["utf8_bytes"]) is not int
        or literal["utf8_bytes"] != len(value_bytes)
        or not _is_sha256(literal["sha256"])
        or literal["sha256"] != sha256(value_bytes).hexdigest()
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)


def _validate_decoder_tokens(
    tokens: list[dict[str, Any]],
    payload: bytes,
    boundaries: tuple[int | None, ...],
) -> None:
    previous_end = 0
    for expected_index, token in enumerate(tokens):
        if type(token) is not dict:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        kind = token["kind"]
        flags = token["flags"]
        if (
            type(token["index"]) is not int
            or token["index"] != expected_index
            or type(kind) is not str
            or kind not in _TOKEN_KINDS
            or type(flags) is not list
            or any(type(flag) is not str for flag in flags)
            or flags != sorted(set(flags))
            or any(flag not in _TOKEN_FLAGS for flag in flags)
        ):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        start_utf8 = token["start_utf8"]
        end_utf8 = token["end_utf8"]
        if start_utf8 < previous_end or end_utf8 < start_utf8:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        token_bytes = payload[start_utf8:end_utf8]
        if (
            not _is_sha256(token["text_sha256"])
            or token["text_sha256"] != sha256(token_bytes).hexdigest()
        ):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        _validate_token_literal(token, token_bytes)
        previous_end = end_utf8
    end_of_input_count = sum(
        token["kind"] == "EndOfInput" for token in tokens
    )
    payload_end_utf16 = len(boundaries) - 1
    if (
        end_of_input_count != 1
        or not tokens
        or tokens[-1]["kind"] != "EndOfInput"
        or tokens[-1]["start_utf16"] != payload_end_utf16
        or tokens[-1]["end_utf16"] != payload_end_utf16
        or tokens[-1]["start_utf8"] != len(payload)
        or tokens[-1]["end_utf8"] != len(payload)
        or tokens[-1]["literal"] is not None
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)


def _validate_ast_literal_record(
    literal: object,
    *,
    expected: tuple[str, str] | None,
) -> None:
    if expected is None:
        if literal is not None:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        return
    if type(literal) is not dict or set(literal) != {
        "kind",
        "value",
        "utf8_bytes",
        "sha256",
    }:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    expected_kind, expected_value = expected
    try:
        value_bytes = expected_value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    if (
        type(literal["kind"]) is not str
        or literal["kind"] != expected_kind
        or type(literal["value"]) is not str
        or literal["value"] != expected_value
        or type(literal["utf8_bytes"]) is not int
        or literal["utf8_bytes"] != len(value_bytes)
        or not _is_sha256(literal["sha256"])
        or literal["sha256"] != sha256(value_bytes).hexdigest()
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)


def _simple_double_quoted_ast_value(source: bytes) -> str | None:
    try:
        text = source.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    if len(text) < 2 or text[0] != '"' or text[-1] != '"':
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    escapes = {
        "0": "\0",
        "a": "\a",
        "b": "\b",
        "e": "\x1b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
        '"': '"',
        "`": "`",
        "$": "$",
    }
    value: list[str] = []
    cursor = 1
    while cursor < len(text) - 1:
        character = text[cursor]
        if character == "$" or character in "\r\n":
            return None
        if character == '"':
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        if character != "`":
            value.append(character)
            cursor += 1
            continue
        cursor += 1
        if cursor >= len(text) - 1:
            return None
        escaped = text[cursor]
        replacement = escapes.get(escaped)
        if replacement is None:
            return None
        value.append(replacement)
        cursor += 1
    return "".join(value)


def _expected_string_ast_literal(source: bytes) -> tuple[str, str] | None:
    if source.startswith((b"@'", b'@"')):
        return None
    if source.startswith(b"'"):
        return "single_quoted", _single_quoted_token_value(source)
    if source.startswith(b'"'):
        value = _simple_double_quoted_ast_value(source)
        if value is None:
            return None
        return "double_quoted", value
    try:
        value = source.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    if (
        not value
        or value[0] in "@#"
        or any(
            character.isspace()
            or ord(character) < 0x20
            or character in "`$'\";,|&(){}[]<>"
            for character in value
        )
    ):
        return None
    return "bare", value


def _validate_decoder_ast(
    document: dict[str, Any],
    *,
    payload: bytes,
    boundaries: tuple[int | None, ...],
    tokens: list[dict[str, Any]],
) -> None:
    nodes = document["nodes"]
    metrics = document["metrics"]
    if type(nodes) is not list or not nodes:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    if (
        type(metrics) is not dict
        or set(metrics) != _AST_METRIC_KEYS
        or any(type(value) is not int for value in metrics.values())
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)

    node_count = len(nodes)
    _check_decoder_count(node_count, limit=_DECODER_LIMITS.ast_nodes)
    parents: list[int | None] = []
    children_by_node: list[list[int]] = []
    ast_types: list[str] = []
    edge_count = 0
    statements = 0
    operations = 0
    pipeline_stages = 0

    token_start_map: dict[int, dict[str, Any] | None] = {}
    for token in tokens:
        token_start = token["start_utf8"]
        if token_start in token_start_map:
            token_start_map[token_start] = None
        else:
            token_start_map[token_start] = token

    for expected_index, node in enumerate(nodes):
        if type(node) is not dict or set(node) != _AST_NODE_KEYS:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        ast_type = node["ast_type"]
        role = node["role"]
        parent_index = node["parent_index"]
        child_indices = node["child_indices"]
        if (
            type(node["index"]) is not int
            or node["index"] != expected_index
            or type(ast_type) is not str
            or ast_type not in _AST_ROLE_BY_TYPE
            or type(role) is not str
            or role != _AST_ROLE_BY_TYPE[ast_type]
            or type(child_indices) is not list
        ):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        if expected_index == 0:
            if parent_index is not None:
                _reject(COMMAND_PLAN_CANONICAL_INVALID)
        elif (
            type(parent_index) is not int
            or parent_index < 0
            or parent_index >= expected_index
        ):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)

        previous_child = expected_index
        for child_index in child_indices:
            if (
                type(child_index) is not int
                or child_index <= previous_child
                or child_index >= node_count
            ):
                _reject(COMMAND_PLAN_CANONICAL_INVALID)
            previous_child = child_index
        edge_count += len(child_indices)
        if edge_count > node_count - 1:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)

        invocation_operator = node["invocation_operator"]
        if ast_type != "CommandAst":
            if invocation_operator is not None:
                _reject(COMMAND_PLAN_CANONICAL_INVALID)
        else:
            if (
                type(invocation_operator) is not str
                or invocation_operator not in {"none", "call", "dot"}
            ):
                _reject(COMMAND_PLAN_CANONICAL_INVALID)
            leading_token = token_start_map.get(node["start_utf8"])
            if (
                leading_token is None
                or leading_token["start_utf16"] != node["start_utf16"]
                or leading_token["end_utf8"] <= leading_token["start_utf8"]
                or leading_token["end_utf16"] > node["end_utf16"]
                or leading_token["end_utf8"] > node["end_utf8"]
                or leading_token["kind"] == "EndOfInput"
            ):
                _reject(COMMAND_PLAN_CANONICAL_INVALID)
            leading_width = (
                leading_token["end_utf8"] - leading_token["start_utf8"]
            )
            leading_byte = payload[leading_token["start_utf8"]]
            leading_kind = leading_token["kind"]
            starts_with_ampersand = leading_byte == ord("&")
            is_exact_ampersand = leading_width == 1 and starts_with_ampersand
            is_exact_dot = leading_width == 1 and leading_byte == ord(".")
            if leading_kind == "Ampersand" or starts_with_ampersand:
                if leading_kind != "Ampersand" or not is_exact_ampersand:
                    _reject(COMMAND_PLAN_CANONICAL_INVALID)
                expected_operator = "call"
            elif leading_kind == "Dot" or is_exact_dot:
                if leading_kind != "Dot" or not is_exact_dot:
                    _reject(COMMAND_PLAN_CANONICAL_INVALID)
                expected_operator = "dot"
            else:
                expected_operator = "none"
            if invocation_operator != expected_operator:
                _reject(COMMAND_PLAN_CANONICAL_INVALID)

        parents.append(parent_index)
        children_by_node.append(child_indices)
        ast_types.append(ast_type)
        statements += ast_type in _CONCRETE_STATEMENT_AST_TYPES
        operations += ast_type in _OPERATION_AST_TYPES
        pipeline_stages += ast_type in _PIPELINE_STAGE_AST_TYPES

    root = nodes[0]
    if (
        root["ast_type"] != "ScriptBlockAst"
        or root["role"] != "script_block"
        or root["start_utf16"] != 0
        or root["end_utf16"] != len(boundaries) - 1
        or root["start_utf8"] != 0
        or root["end_utf8"] != len(payload)
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)

    owners: list[int | None] = [None] * node_count
    for parent, child_indices in enumerate(children_by_node):
        parent_node = nodes[parent]
        previous_end_utf16: int | None = None
        previous_end_utf8: int | None = None
        for child_index in child_indices:
            child_node = nodes[child_index]
            if owners[child_index] is not None:
                _reject(COMMAND_PLAN_CANONICAL_INVALID)
            owners[child_index] = parent
            if parents[child_index] != parent:
                _reject(COMMAND_PLAN_CANONICAL_INVALID)
            if (
                child_node["start_utf16"] < parent_node["start_utf16"]
                or child_node["end_utf16"] > parent_node["end_utf16"]
                or child_node["start_utf8"] < parent_node["start_utf8"]
                or child_node["end_utf8"] > parent_node["end_utf8"]
            ):
                _reject(COMMAND_PLAN_CANONICAL_INVALID)
            if (
                previous_end_utf16 is not None
                and (
                    child_node["start_utf16"] < previous_end_utf16
                    or child_node["start_utf8"] < previous_end_utf8
                )
            ):
                _reject(COMMAND_PLAN_CANONICAL_INVALID)
            previous_end_utf16 = child_node["end_utf16"]
            previous_end_utf8 = child_node["end_utf8"]

    if (
        edge_count != node_count - 1
        or owners[0] is not None
        or any(owner is None for owner in owners[1:])
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)

    stack: list[tuple[int, int]] = [(0, 1)]
    visited = bytearray(node_count)
    next_preorder_index = 0
    ast_depth = 0
    while stack:
        node_index, depth = stack.pop()
        if visited[node_index] or node_index != next_preorder_index:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        visited[node_index] = 1
        next_preorder_index += 1
        ast_depth = max(ast_depth, depth)
        for child_index in reversed(children_by_node[node_index]):
            stack.append((child_index, depth + 1))
    if next_preorder_index != node_count:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)

    _check_decoder_count(ast_depth, limit=_DECODER_LIMITS.ast_depth)
    _check_decoder_count(statements, limit=_DECODER_LIMITS.statements)
    _check_decoder_count(operations, limit=_DECODER_LIMITS.operations)
    _check_decoder_count(
        pipeline_stages,
        limit=_DECODER_LIMITS.pipeline_stages,
    )
    expected_metrics = {
        "ast_nodes": node_count,
        "ast_depth": ast_depth,
        "statements": statements,
        "operations": operations,
        "pipeline_stages": pipeline_stages,
    }
    if metrics != expected_metrics:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)

    for node, ast_type in zip(nodes, ast_types, strict=True):
        if ast_type == "StringConstantExpressionAst":
            source = payload[node["start_utf8"] : node["end_utf8"]]
            expected_literal = _expected_string_ast_literal(source)
        else:
            expected_literal = None
        _validate_ast_literal_record(
            node["literal"],
            expected=expected_literal,
        )


def _validate_native_string(value: object) -> str:
    if type(value) is not str:
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    for character in value:
        scalar = ord(character)
        if scalar == 0 or 0xD800 <= scalar <= 0xDFFF:
            _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    return value


def _quote_windows_native_argument(value: str) -> str:
    text = _validate_native_string(value)
    if text and not any(character in '" \t' for character in text):
        return text
    rendered = ['"']
    backslashes = 0
    for character in text:
        if character == "\\":
            backslashes += 1
            continue
        if character == '"':
            rendered.append("\\" * (2 * backslashes + 1))
            rendered.append('"')
            backslashes = 0
            continue
        if backslashes:
            rendered.append("\\" * backslashes)
            backslashes = 0
        rendered.append(character)
    if backslashes:
        rendered.append("\\" * (2 * backslashes))
    rendered.append('"')
    return "".join(rendered)


def _windows_native_vector(
    executable: str,
    arguments: tuple[str, ...],
) -> _WindowsNativeVector:
    executable_text = _validate_native_string(executable)
    if not executable_text or not PureWindowsPath(executable_text).is_absolute():
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    if type(arguments) is not tuple:
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    serialized = [_quote_windows_native_argument(executable_text)]
    for argument in arguments:
        serialized.append(_quote_windows_native_argument(argument))
    command_line = " ".join(serialized)
    try:
        utf16_units = len(command_line.encode("utf-16-le", errors="strict")) // 2 + 1
    except UnicodeEncodeError:
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    if utf16_units > 30000:
        _reject(COMMAND_DECODER_LIMIT_EXCEEDED)
    serialized_bytes = (command_line + "\x00").encode("utf-16-le", errors="strict")
    return _WindowsNativeVector(
        contract="complete-suite-windows-native-vector-v1",
        utf16_units=utf16_units,
        utf16le_sha256=sha256(serialized_bytes).hexdigest(),
        command_line=command_line,
    )


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = (
        ("file_attributes", wintypes.DWORD),
        ("creation_time", wintypes.FILETIME),
        ("last_access_time", wintypes.FILETIME),
        ("last_write_time", wintypes.FILETIME),
        ("volume_serial_number", wintypes.DWORD),
        ("file_size_high", wintypes.DWORD),
        ("file_size_low", wintypes.DWORD),
        ("number_of_links", wintypes.DWORD),
        ("file_index_high", wintypes.DWORD),
        ("file_index_low", wintypes.DWORD),
    )


def _observe_plain_file(path: Path, expected_sha256: str) -> _PlainFileObservation:
    if type(path) is not type(Path()) or not _is_sha256(expected_sha256):
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    path_text = str(path)
    if not PureWindowsPath(path_text).is_absolute():
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    )
    get_information.restype = wintypes.BOOL
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    get_final_path.restype = wintypes.DWORD
    generic_read = 0x80000000
    file_read_attributes = 0x00000080
    file_share_read = 0x00000001
    file_share_write = 0x00000002
    file_share_delete = 0x00000004
    open_existing = 3
    file_attribute_directory = 0x00000010
    file_attribute_reparse_point = 0x00000400
    file_flag_open_reparse_point = 0x00200000
    file_flag_backup_semantics = 0x02000000
    file_flag_sequential_scan = 0x08000000
    ancestor = Path(path.anchor)
    for part in path.parts[1:-1]:
        ancestor /= part
        ancestor_handle = create_file(
            str(ancestor),
            file_read_attributes,
            file_share_read | file_share_write | file_share_delete,
            None,
            open_existing,
            file_flag_open_reparse_point | file_flag_backup_semantics,
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if ancestor_handle in (None, invalid_handle):
            _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
        try:
            ancestor_information = _ByHandleFileInformation()
            if not get_information(
                ancestor_handle,
                ctypes.byref(ancestor_information),
            ):
                _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
            if (
                not ancestor_information.file_attributes
                & file_attribute_directory
                or ancestor_information.file_attributes
                & file_attribute_reparse_point
            ):
                _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
        finally:
            kernel32.CloseHandle(ancestor_handle)
    handle = create_file(
        path_text,
        generic_read,
        file_share_read,
        None,
        open_existing,
        file_flag_open_reparse_point | file_flag_sequential_scan,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle in (None, invalid_handle):
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    fd = -1
    try:
        information = _ByHandleFileInformation()
        if not get_information(handle, ctypes.byref(information)):
            _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
        if (
            information.file_attributes & file_attribute_directory
            or information.file_attributes & file_attribute_reparse_point
            or information.number_of_links != 1
        ):
            _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
        final_path_size = get_final_path(handle, None, 0, 0)
        if final_path_size <= 0 or final_path_size > 32767:
            _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
        final_path_buffer = ctypes.create_unicode_buffer(final_path_size + 1)
        final_path_length = get_final_path(
            handle,
            final_path_buffer,
            len(final_path_buffer),
            0,
        )
        if final_path_length <= 0 or final_path_length >= len(final_path_buffer):
            _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
        normalized_path = final_path_buffer.value
        if normalized_path.startswith("\\\\?\\UNC\\"):
            normalized_path = "\\\\" + normalized_path[8:]
        elif normalized_path.startswith("\\\\?\\"):
            normalized_path = normalized_path[4:]
        if PureWindowsPath(normalized_path) != PureWindowsPath(path_text):
            _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
        size = (information.file_size_high << 32) | information.file_size_low
        if size < 0 or size > 256 * 1024 * 1024:
            _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        handle = None
        digest = sha256()
        observed_size = 0
        with os.fdopen(fd, "rb", closefd=True) as source:
            fd = -1
            while True:
                chunk = source.read(_PIPE_CHUNK_BYTES)
                if not chunk:
                    break
                observed_size += len(chunk)
                if observed_size > size:
                    _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
                digest.update(chunk)
        observed_sha256 = digest.hexdigest()
        if observed_size != size or observed_sha256 != expected_sha256:
            _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
        return _PlainFileObservation(
            normalized_path=str(PureWindowsPath(normalized_path)),
            volume_serial=information.volume_serial_number,
            file_index=(information.file_index_high << 32)
            | information.file_index_low,
            size=size,
            link_count=information.number_of_links,
            sha256=observed_sha256,
        )
    except RuntimeError:
        raise
    except (OSError, ValueError):
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    finally:
        if fd >= 0:
            os.close(fd)
        if handle not in (None, invalid_handle):
            kernel32.CloseHandle(handle)


def _make_decoder_temp_root() -> Path:
    try:
        root = Path(
            tempfile.mkdtemp(
                prefix="kokoroarc-command-decoder-",
                dir=r"D:\tmp",
            )
        )
    except OSError:
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    try:
        if root.parent != Path(r"D:\tmp") or not root.is_dir():
            _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    except OSError:
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    return root


def _remove_decoder_temp_root(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)


def _closed_decoder_environment(temp_root: Path) -> dict[str, str]:
    required = ("SYSTEMROOT", "WINDIR", "COMSPEC")
    values: dict[str, str] = {}
    for name in required:
        value = os.environ.get(name)
        if type(value) is not str or not value:
            _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
        _validate_native_string(value)
        values[name] = value
    values.update(
        {
            "PATHEXT": ".COM;.EXE;.BAT;.CMD",
            "TEMP": str(temp_root),
            "TMP": str(temp_root),
            "POWERSHELL_TELEMETRY_OPTOUT": "1",
            "POWERSHELL_UPDATECHECK": "Off",
        }
    )
    return values


_POPEN = subprocess.Popen


def _decoder_is_reaped(process: Any) -> bool:
    try:
        return process.poll() is not None
    except (OSError, ProcessLookupError, ValueError):
        return False


def _request_decoder_stop(process: Any) -> None:
    if _decoder_is_reaped(process):
        return
    try:
        process.kill()
    except (OSError, ProcessLookupError, ValueError):
        pass


def _terminate_decoder(process: Any) -> bool:
    for _attempt in range(3):
        if _decoder_is_reaped(process):
            return True
        _request_decoder_stop(process)
        try:
            process.wait(timeout=1.0)
        except (OSError, ProcessLookupError, subprocess.TimeoutExpired, ValueError):
            continue
        if _decoder_is_reaped(process):
            return True
    return _decoder_is_reaped(process)


def _read_pipe_bounded(
    stream: Any,
    *,
    limit: int,
    process: Any,
    output: list[bytes],
    failures: list[str],
) -> None:
    retained = bytearray()
    try:
        while True:
            chunk = stream.read(_PIPE_CHUNK_BYTES)
            if type(chunk) is not bytes:
                failures.append(COMMAND_DECODER_PARSE_INVALID)
                _request_decoder_stop(process)
                return
            if not chunk:
                output.append(bytes(retained))
                return
            if len(retained) + len(chunk) > limit:
                failures.append(COMMAND_DECODER_LIMIT_EXCEEDED)
                _request_decoder_stop(process)
                return
            retained.extend(chunk)
    except (OSError, ValueError):
        failures.append(COMMAND_DECODER_PARSE_INVALID)
        _request_decoder_stop(process)


def _write_decoder_stdin(
    process: Any,
    payload: bytes,
    failures: list[str],
) -> None:
    try:
        for offset in range(0, len(payload), _PIPE_CHUNK_BYTES):
            chunk = payload[offset : offset + _PIPE_CHUNK_BYTES]
            chunk_offset = 0
            while chunk_offset < len(chunk):
                remaining = chunk[chunk_offset:]
                written = process.stdin.write(remaining)
                if (
                    type(written) is not int
                    or written <= 0
                    or written > len(remaining)
                ):
                    failures.append(COMMAND_DECODER_PARSE_INVALID)
                    _request_decoder_stop(process)
                    return
                chunk_offset += written
        process.stdin.flush()
    except (BrokenPipeError, OSError, ValueError):
        failures.append(COMMAND_DECODER_PARSE_INVALID)
        _request_decoder_stop(process)
    finally:
        try:
            process.stdin.close()
        except (OSError, ValueError):
            failures.append(COMMAND_DECODER_PARSE_INVALID)


def _close_decoder_streams(process: Any) -> None:
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(process, stream_name, None)
        if stream is not None:
            try:
                stream.close()
            except (OSError, ValueError):
                pass


def _communicate_decoder_body(
    process: Any,
    payload: bytes,
) -> tuple[bytes, bytes, int]:
    stdout_values: list[bytes] = []
    stderr_values: list[bytes] = []
    failures: list[str] = []
    stdout_thread = threading.Thread(
        target=_read_pipe_bounded,
        kwargs={
            "stream": process.stdout,
            "limit": _DECODER_LIMITS.plan_bytes,
            "process": process,
            "output": stdout_values,
            "failures": failures,
        },
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_read_pipe_bounded,
        kwargs={
            "stream": process.stderr,
            "limit": _STDERR_LIMIT_BYTES,
            "process": process,
            "output": stderr_values,
            "failures": failures,
        },
        daemon=True,
    )
    stdin_thread = threading.Thread(
        target=_write_decoder_stdin,
        args=(process, payload, failures),
        daemon=True,
    )
    threads = (stdin_thread, stdout_thread, stderr_thread)
    deadline = time.monotonic() + _DECODER_TIMEOUT_SECONDS
    for thread in threads:
        thread.start()
    exit_code = -1
    timed_out = False
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired("decoder", _DECODER_TIMEOUT_SECONDS)
        exit_code = process.wait(timeout=remaining)
    except subprocess.TimeoutExpired:
        timed_out = True
        failures.append(COMMAND_DECODER_PARSE_INVALID)
    except (OSError, ValueError):
        failures.append(COMMAND_DECODER_PARSE_INVALID)

    reaped = _decoder_is_reaped(process)
    if timed_out or failures or not reaped:
        reaped = _terminate_decoder(process)

    join_deadline = max(deadline, time.monotonic() + 1.0)
    for thread in threads:
        thread.join(max(0.0, join_deadline - time.monotonic()))
    if any(thread.is_alive() for thread in threads):
        reaped = _terminate_decoder(process)
        _close_decoder_streams(process)
        final_join_deadline = time.monotonic() + 1.0
        for thread in threads:
            thread.join(max(0.0, final_join_deadline - time.monotonic()))
    if any(thread.is_alive() for thread in threads) or not reaped:
        failures.append(COMMAND_DECODER_PARSE_INVALID)
    if failures:
        if COMMAND_DECODER_LIMIT_EXCEEDED in failures:
            _reject(COMMAND_DECODER_LIMIT_EXCEEDED)
        _reject(COMMAND_DECODER_PARSE_INVALID)
    if len(stdout_values) != 1 or len(stderr_values) != 1:
        _reject(COMMAND_DECODER_PARSE_INVALID)
    return stdout_values[0], stderr_values[0], exit_code


def _communicate_decoder(
    process: Any,
    payload: bytes,
) -> tuple[bytes, bytes, int]:
    try:
        return _communicate_decoder_body(process, payload)
    finally:
        _close_decoder_streams(process)


def _run_decoder(
    payload: bytes,
    *,
    shell: ShellIdentity,
    decoder_path: Path,
    decoder_sha256: str,
) -> tuple[bytes, _WindowsNativeVector]:
    if type(payload) is not bytes:
        _reject(COMMAND_DECODER_PARSE_INVALID)
    if len(payload) > _DECODER_LIMITS.payload_bytes:
        _reject(COMMAND_PAYLOAD_LIMIT_EXCEEDED)
    if type(shell) is not ShellIdentity:
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    if (
        not _is_absolute_shell_path(shell.path)
        or not _is_sha256(shell.sha256)
        or type(shell.edition) is not str
        or shell.edition != "Core"
        or any(
            type(value) is not str or not value
            for value in (
                shell.file_version,
                shell.product_version,
                shell.parser_version,
            )
        )
    ):
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    if type(decoder_path) is not type(Path()) or not _is_sha256(decoder_sha256):
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    if not decoder_path.is_absolute() or any(
        part in ("", ".", "..") for part in decoder_path.parts[1:]
    ):
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    decoder_absolute = decoder_path
    module_path = Path(__file__)
    expected_decoder = module_path.with_name(
        "complete_suite_command_plan_decoder.ps1"
    )
    if not module_path.is_absolute() or decoder_absolute != expected_decoder:
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    arguments = (
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(decoder_absolute),
    )
    native_vector = _windows_native_vector(shell.path, arguments)
    shell_before = _observe_plain_file(Path(shell.path), shell.sha256)
    decoder_before = _observe_plain_file(decoder_absolute, decoder_sha256)
    temp_root = _make_decoder_temp_root()
    process: Any | None = None
    outcome_error: RuntimeError | None = None
    stdout = b""
    stderr = b""
    exit_code = -1
    try:
        environment = _closed_decoder_environment(temp_root)
        try:
            process = _POPEN(
                [shell.path, *arguments],
                shell=False,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                env=environment,
                close_fds=True,
                bufsize=0,
            )
            stdout, stderr, exit_code = _communicate_decoder(process, payload)
        except RuntimeError as exc:
            outcome_error = exc
        except (OSError, ValueError):
            outcome_error = RuntimeError(COMMAND_DECODER_PARSE_INVALID)
        if process is not None and not _decoder_is_reaped(process):
            if not _terminate_decoder(process):
                outcome_error = RuntimeError(COMMAND_DECODER_PARSE_INVALID)
    finally:
        shell_after: _PlainFileObservation | None = None
        decoder_after: _PlainFileObservation | None = None
        postcheck_error: RuntimeError | None = None
        try:
            shell_after = _observe_plain_file(Path(shell.path), shell.sha256)
        except RuntimeError as exc:
            postcheck_error = exc
        except (OSError, ValueError):
            postcheck_error = RuntimeError(COMMAND_DECODER_IDENTITY_MISMATCH)
        try:
            decoder_after = _observe_plain_file(
                decoder_absolute,
                decoder_sha256,
            )
        except RuntimeError as exc:
            if postcheck_error is None:
                postcheck_error = exc
        except (OSError, ValueError):
            if postcheck_error is None:
                postcheck_error = RuntimeError(
                    COMMAND_DECODER_IDENTITY_MISMATCH
                )
        cleanup_error: RuntimeError | None = None
        try:
            _remove_decoder_temp_root(temp_root)
        except RuntimeError as exc:
            cleanup_error = exc
        if postcheck_error is not None:
            _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
        if shell_after != shell_before or decoder_after != decoder_before:
            _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
        if cleanup_error is not None:
            raise cleanup_error
    if outcome_error is not None:
        raise outcome_error
    if exit_code != 0 or stderr != b"":
        stable_child_errors = {
            COMMAND_DECODER_LIMIT_EXCEEDED.encode("ascii"):
                COMMAND_DECODER_LIMIT_EXCEEDED,
            COMMAND_PAYLOAD_LIMIT_EXCEEDED.encode("ascii"):
                COMMAND_PAYLOAD_LIMIT_EXCEEDED,
        }
        if exit_code != 0 and stdout == b"" and stderr in stable_child_errors:
            _reject(stable_child_errors[stderr])
        _reject(COMMAND_DECODER_PARSE_INVALID)
    return stdout, native_vector


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _decode_single_json_object(value: bytes) -> dict[str, Any]:
    if type(value) is not bytes or not value:
        _reject(COMMAND_DECODER_PARSE_INVALID)
    try:
        text = value.decode("utf-8", errors="strict")
        decoder = json.JSONDecoder(object_pairs_hook=_reject_duplicate_keys)
        document, end = decoder.raw_decode(text)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        _reject(COMMAND_DECODER_PARSE_INVALID)
    if end != len(text) or type(document) is not dict:
        _reject(COMMAND_DECODER_PARSE_INVALID)
    return document


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (UnicodeEncodeError, TypeError, ValueError, RecursionError):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)


def _load_decoder_schema() -> dict[str, Any]:
    schema_path = Path(__file__).with_name("complete-suite-command-plan.schema.json")
    try:
        schema_bytes = schema_path.read_bytes()
    except OSError:
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    if len(schema_bytes) > 1024 * 1024:
        _reject(COMMAND_DECODER_LIMIT_EXCEEDED)
    try:
        schema = json.loads(
            schema_bytes.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    if type(schema) is not dict:
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    try:
        Draft202012Validator.check_schema(schema)
    except Exception:
        _reject(COMMAND_PLAN_SCHEMA_INVALID)
    return schema


def _validate_decoder_parent_document(
    document: dict[str, Any],
    *,
    payload: bytes,
    shell: ShellIdentity,
    decoder_sha256: str,
) -> tuple[int, int]:
    if document["payload"] != {
        "utf8_bytes": len(payload),
        "sha256": sha256(payload).hexdigest(),
    }:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    if document["powershell"] != {
        "path": shell.path,
        "sha256": shell.sha256,
        "file_version": shell.file_version,
        "product_version": shell.product_version,
        "edition": shell.edition,
        "parser_version": shell.parser_version,
    }:
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    if document["decoder"] != {
        "path": _DECODER_RELATIVE_PATH,
        "sha256": decoder_sha256,
    }:
        _reject(COMMAND_DECODER_IDENTITY_MISMATCH)
    parse_errors = document["parse_errors"]
    tokens = document["tokens"]
    nodes = document["nodes"]
    if (
        type(parse_errors) is not list
        or type(tokens) is not list
        or type(nodes) is not list
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    _check_decoder_count(len(parse_errors), limit=_DECODER_LIMITS.parse_errors)
    _check_decoder_count(len(tokens), limit=_DECODER_LIMITS.tokens)
    _check_decoder_count(len(nodes), limit=_DECODER_LIMITS.ast_nodes)
    boundaries = _validate_decoder_spans(document, payload)
    _validate_decoder_tokens(tokens, payload, boundaries)
    _validate_decoder_ast(
        document,
        payload=payload,
        boundaries=boundaries,
        tokens=tokens,
    )
    return len(tokens), len(parse_errors)


def decode_powershell_payload(
    payload: bytes,
    *,
    shell: ShellIdentity,
    decoder_path: Path,
    decoder_sha256: str,
) -> DecodedPowerShellPayload:
    stdout, _launch_observation = _run_decoder(
        payload,
        shell=shell,
        decoder_path=decoder_path,
        decoder_sha256=decoder_sha256,
    )
    document = _decode_single_json_object(stdout)
    schema = _load_decoder_schema()
    try:
        errors = tuple(Draft202012Validator(schema).iter_errors(document))
    except Exception:
        _reject(COMMAND_PLAN_SCHEMA_INVALID)
    if errors:
        _reject(COMMAND_PLAN_SCHEMA_INVALID)
    canonical_bytes = _canonical_json_bytes(document)
    _enforce_decoder_document_limit(canonical_bytes)
    token_count, parse_error_count = _validate_decoder_parent_document(
        document,
        payload=payload,
        shell=shell,
        decoder_sha256=decoder_sha256,
    )
    return DecodedPowerShellPayload(
        schema_version=_DECODER_SCHEMA_VERSION,
        canonical_bytes=canonical_bytes,
        canonical_sha256=sha256(canonical_bytes).hexdigest(),
        token_count=token_count,
        parse_error_count=parse_error_count,
    )
