from __future__ import annotations

from collections.abc import Sequence
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
import weakref

from jsonschema import Draft202012Validator


COMMAND_WRAPPER_INVALID = "COMMAND_WRAPPER_INVALID"
COMMAND_WRAPPER_IDENTITY_MISMATCH = "COMMAND_WRAPPER_IDENTITY_MISMATCH"
COMMAND_PAYLOAD_LIMIT_EXCEEDED = "COMMAND_PAYLOAD_LIMIT_EXCEEDED"
COMMAND_DECODER_IDENTITY_MISMATCH = "COMMAND_DECODER_IDENTITY_MISMATCH"
COMMAND_DECODER_PARSE_INVALID = "COMMAND_DECODER_PARSE_INVALID"
COMMAND_DECODER_LIMIT_EXCEEDED = "COMMAND_DECODER_LIMIT_EXCEEDED"
COMMAND_PLAN_SCHEMA_INVALID = "COMMAND_PLAN_SCHEMA_INVALID"
COMMAND_PLAN_CANONICAL_INVALID = "COMMAND_PLAN_CANONICAL_INVALID"
COMMAND_PLAN_RAW_RETAINED_MISMATCH = "COMMAND_PLAN_RAW_RETAINED_MISMATCH"

_PAYLOAD_LIMIT_BYTES = 256 * 1024
_DECODER_SCHEMA_VERSION = "complete-suite-command-plan-decoder-v1"
_BOUND_COMMAND_PLAN_VERSION = "complete-suite-bound-command-plan-v1"
_PATH_NAMESPACE_MANIFEST_VERSION = (
    "complete-suite-path-namespace-manifest-v1"
)
_PATH_NAMESPACE_LIMIT = 32
_PATH_NAMESPACE_ROOT_UTF8_LIMIT = 4096
_PATH_NAMESPACE_LABEL = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_DIRECTORY_FILE_TYPE = 1
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
class PathNamespaceRequest:
    raw_root: str
    retained_root: str
    label: str

    def __post_init__(self) -> None:
        if (
            type(self.raw_root) is not str
            or type(self.retained_root) is not str
            or type(self.label) is not str
            or not self.raw_root
            or not self.retained_root
            or not self.label
        ):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)


@dataclass(frozen=True)
class FilesystemObjectIdentity:
    device: int
    inode: int
    file_type: int
    reparse_tag: int
    link_count: int

    def __post_init__(self) -> None:
        values = (
            self.device,
            self.inode,
            self.file_type,
            self.reparse_tag,
            self.link_count,
        )
        if (
            any(type(value) is not int or value < 0 for value in values)
            or self.file_type == 0
            or self.link_count == 0
        ):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)


@dataclass(frozen=True)
class BoundPathNamespace:
    raw_root: str
    retained_root: str
    label: str
    raw_identity: FilesystemObjectIdentity
    retained_identity: FilesystemObjectIdentity
    raw_ancestor_identities: tuple[FilesystemObjectIdentity, ...]
    retained_ancestor_identities: tuple[FilesystemObjectIdentity, ...]
    raw_case_sensitive: bool
    retained_case_sensitive: bool
    canonical_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.raw_root) is not str
            or type(self.retained_root) is not str
            or type(self.label) is not str
            or not self.raw_root
            or not self.retained_root
            or not self.label
            or type(self.raw_identity) is not FilesystemObjectIdentity
            or type(self.retained_identity) is not FilesystemObjectIdentity
            or type(self.raw_ancestor_identities) is not tuple
            or type(self.retained_ancestor_identities) is not tuple
            or any(
                type(identity) is not FilesystemObjectIdentity
                for identity in self.raw_ancestor_identities
            )
            or any(
                type(identity) is not FilesystemObjectIdentity
                for identity in self.retained_ancestor_identities
            )
            or type(self.raw_case_sensitive) is not bool
            or type(self.retained_case_sensitive) is not bool
            or not _is_sha256(self.canonical_sha256)
        ):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)


@dataclass(frozen=True)
class BoundCommandPlan:
    version: str
    raw_rendered_utf8_bytes: int
    raw_rendered_sha256: str
    retained_rendered_utf8_bytes: int
    retained_rendered_sha256: str
    raw_payload_field_utf8_bytes: int
    raw_payload_field_sha256: str
    raw_payload_utf8_bytes: int
    raw_payload_sha256: str
    retained_payload_field_utf8_bytes: int
    retained_payload_field_sha256: str
    retained_payload_utf8_bytes: int
    retained_payload_sha256: str
    namespaces: tuple[BoundPathNamespace, ...]
    namespace_manifest_sha256: str
    normalized_plan_sha256: str
    normalized_plan_bytes: bytes

    def __post_init__(self) -> None:
        byte_counts = (
            self.raw_rendered_utf8_bytes,
            self.retained_rendered_utf8_bytes,
            self.raw_payload_field_utf8_bytes,
            self.raw_payload_utf8_bytes,
            self.retained_payload_field_utf8_bytes,
            self.retained_payload_utf8_bytes,
        )
        digests = (
            self.raw_rendered_sha256,
            self.retained_rendered_sha256,
            self.raw_payload_field_sha256,
            self.raw_payload_sha256,
            self.retained_payload_field_sha256,
            self.retained_payload_sha256,
            self.namespace_manifest_sha256,
            self.normalized_plan_sha256,
        )
        if (
            type(self.version) is not str
            or self.version != _BOUND_COMMAND_PLAN_VERSION
            or any(type(value) is not int or value < 0 for value in byte_counts)
            or any(not _is_sha256(value) for value in digests)
            or type(self.namespaces) is not tuple
            or any(type(value) is not BoundPathNamespace for value in self.namespaces)
            or type(self.normalized_plan_bytes) is not bytes
            or sha256(self.normalized_plan_bytes).hexdigest()
            != self.normalized_plan_sha256
        ):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        _enforce_decoder_document_limit(self.normalized_plan_bytes)
        try:
            document = _decode_single_json_object(self.normalized_plan_bytes)
        except RuntimeError:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        if (
            _canonical_json_bytes(document) != self.normalized_plan_bytes
            or set(document) != {
                "bindings",
                "command",
                "decoder",
                "namespace_manifest_sha256",
                "namespaces",
                "shell",
                "version",
            }
            or document["version"] != self.version
            or document["namespace_manifest_sha256"]
            != self.namespace_manifest_sha256
        ):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        _authenticate_bound_namespaces(self.namespaces)
        expected_manifest = _namespace_manifest(self.namespaces)
        if (
            document["namespaces"] != expected_manifest["namespaces"]
            or sha256(_canonical_json_bytes(expected_manifest)).hexdigest()
            != self.namespace_manifest_sha256
        ):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        expected_bindings = {
            "raw": {
                "rendered": {
                    "utf8_bytes": self.raw_rendered_utf8_bytes,
                    "sha256": self.raw_rendered_sha256,
                },
                "payload_field": {
                    "utf8_bytes": self.raw_payload_field_utf8_bytes,
                    "sha256": self.raw_payload_field_sha256,
                },
                "payload": {
                    "utf8_bytes": self.raw_payload_utf8_bytes,
                    "sha256": self.raw_payload_sha256,
                },
            },
            "retained": {
                "rendered": {
                    "utf8_bytes": self.retained_rendered_utf8_bytes,
                    "sha256": self.retained_rendered_sha256,
                },
                "payload_field": {
                    "utf8_bytes": self.retained_payload_field_utf8_bytes,
                    "sha256": self.retained_payload_field_sha256,
                },
                "payload": {
                    "utf8_bytes": self.retained_payload_utf8_bytes,
                    "sha256": self.retained_payload_sha256,
                },
            },
        }
        if document["bindings"] != expected_bindings:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)


_BOUND_NAMESPACE_REGISTRY_LOCK = threading.Lock()
_BOUND_NAMESPACE_REGISTRY: dict[
    int,
    tuple[weakref.ReferenceType[BoundPathNamespace], str],
] = {}


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


class _FileAttributeTagInformation(ctypes.Structure):
    _fields_ = (
        ("file_attributes", wintypes.DWORD),
        ("reparse_tag", wintypes.DWORD),
    )


class _FileCaseSensitiveInformation(ctypes.Structure):
    _fields_ = (("flags", wintypes.DWORD),)


class _UnicodeString(ctypes.Structure):
    _fields_ = (
        ("length", wintypes.USHORT),
        ("maximum_length", wintypes.USHORT),
        ("buffer", wintypes.LPWSTR),
    )


class _ObjectAttributes(ctypes.Structure):
    _fields_ = (
        ("length", wintypes.ULONG),
        ("root_directory", wintypes.HANDLE),
        ("object_name", ctypes.POINTER(_UnicodeString)),
        ("attributes", wintypes.ULONG),
        ("security_descriptor", wintypes.LPVOID),
        ("security_quality_of_service", wintypes.LPVOID),
    )


class _IoStatusBlock(ctypes.Structure):
    _fields_ = (
        ("status_or_pointer", wintypes.LPVOID),
        ("information", ctypes.c_size_t),
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


def _detached_json_value(value: object, *, depth: int = 0) -> object:
    if depth > 128:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is list:
        return [
            _detached_json_value(item, depth=depth + 1)
            for item in value
        ]
    if type(value) is dict:
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                _reject(COMMAND_PLAN_CANONICAL_INVALID)
            result[key] = _detached_json_value(item, depth=depth + 1)
        return result
    _reject(COMMAND_PLAN_CANONICAL_INVALID)


def _windows_ordinal_equal(
    left: object,
    right: object,
    *,
    ignore_case: bool,
) -> bool:
    if (
        type(left) is not str
        or type(right) is not str
        or type(ignore_case) is not bool
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    try:
        left_units = len(left.encode("utf-16-le", errors="strict")) // 2
        right_units = len(right.encode("utf-16-le", errors="strict")) // 2
    except UnicodeEncodeError:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    compare_string_ordinal = kernel32.CompareStringOrdinal
    compare_string_ordinal.argtypes = (
        wintypes.LPCWSTR,
        ctypes.c_int,
        wintypes.LPCWSTR,
        ctypes.c_int,
        wintypes.BOOL,
    )
    compare_string_ordinal.restype = ctypes.c_int
    result = compare_string_ordinal(
        left,
        left_units,
        right,
        right_units,
        ignore_case,
    )
    if result not in (1, 2, 3):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    return result == 2


def _windows_path_parts_equal(
    left: tuple[str, ...],
    right: tuple[str, ...],
    *,
    ignore_case: bool,
) -> bool:
    return len(left) == len(right) and all(
        _windows_ordinal_equal(
            left_part,
            right_part,
            ignore_case=ignore_case,
        )
        for left_part, right_part in zip(left, right, strict=True)
    )


def _normalized_path_literal(
    literal: object,
    *,
    namespaces: tuple[BoundPathNamespace, ...],
    side: Literal["raw", "retained"],
    allow_path: bool,
) -> tuple[object, dict[str, object] | None]:
    detached = _detached_json_value(literal)
    if detached is None:
        return None, None
    if type(detached) is not dict:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    if (
        detached.get("kind") not in ("single_quoted", "double_quoted")
        or type(detached.get("value")) is not str
    ):
        return detached, None
    value = detached["value"]
    candidate = PureWindowsPath(value.replace("/", "\\"))
    if not candidate.is_absolute():
        return detached, None
    if not allow_path or any(part in ("", ".", "..") for part in candidate.parts[1:]):
        _reject(COMMAND_PLAN_RAW_RETAINED_MISMATCH)
    matches: list[tuple[BoundPathNamespace, tuple[str, ...]]] = []
    candidate_parts = candidate.parts
    for namespace in namespaces:
        root = namespace.raw_root if side == "raw" else namespace.retained_root
        root_parts = PureWindowsPath(root).parts
        if len(candidate_parts) < len(root_parts):
            continue
        insensitive = (
            not namespace.raw_case_sensitive
            and not namespace.retained_case_sensitive
        )
        prefix_matches = _windows_path_parts_equal(
            tuple(candidate_parts[: len(root_parts)]),
            tuple(root_parts),
            ignore_case=insensitive,
        )
        if not prefix_matches:
            continue
        suffix = tuple(candidate_parts[len(root_parts) :])
        matches.append((namespace, suffix))
    if len(matches) != 1:
        _reject(COMMAND_PLAN_RAW_RETAINED_MISMATCH)
    namespace, suffix = matches[0]
    path_record: dict[str, object] = {
        "kind": "path",
        "namespace": namespace.label,
        "suffix": list(suffix),
    }
    return path_record, path_record


def _semantic_command_values_equivalent(
    left: object,
    right: object,
    *,
    namespaces: tuple[BoundPathNamespace, ...],
    depth: int = 0,
) -> bool:
    if depth > 128 or type(left) is not type(right):
        return False
    if type(left) is dict:
        if set(left) == {"kind", "namespace", "suffix"}:
            if (
                left.get("kind") != "path"
                or right.get("kind") != "path"
                or type(left.get("namespace")) is not str
                or left["namespace"] != right.get("namespace")
                or type(left.get("suffix")) is not list
                or type(right.get("suffix")) is not list
                or any(type(value) is not str for value in left["suffix"])
                or any(type(value) is not str for value in right["suffix"])
            ):
                return False
            matching_namespaces = tuple(
                namespace
                for namespace in namespaces
                if namespace.label == left["namespace"]
            )
            if len(matching_namespaces) != 1:
                return False
            namespace = matching_namespaces[0]
            return _windows_path_parts_equal(
                tuple(left["suffix"]),
                tuple(right["suffix"]),
                ignore_case=(
                    not namespace.raw_case_sensitive
                    and not namespace.retained_case_sensitive
                ),
            )
        if set(left) != set(right):
            return False
        return all(
            _semantic_command_values_equivalent(
                left[key],
                right[key],
                namespaces=namespaces,
                depth=depth + 1,
            )
            for key in left
        )
    if type(left) is list:
        return len(left) == len(right) and all(
            _semantic_command_values_equivalent(
                left_value,
                right_value,
                namespaces=namespaces,
                depth=depth + 1,
            )
            for left_value, right_value in zip(left, right, strict=True)
        )
    return left == right


def _semantic_command_view(
    document: dict[str, Any],
    *,
    payload: bytes,
    shell: ShellIdentity,
    decoder_sha256: str,
    namespaces: tuple[BoundPathNamespace, ...] = (),
    side: Literal["raw", "retained"] = "retained",
) -> dict[str, object]:
    _validate_decoder_parent_document(
        document,
        payload=payload,
        shell=shell,
        decoder_sha256=decoder_sha256,
    )
    if document["parse_errors"]:
        _reject(COMMAND_DECODER_PARSE_INVALID)
    token_entries: list[dict[str, object]] = []
    for token in document["tokens"]:
        try:
            token_text = payload[token["start_utf8"] : token["end_utf8"]].decode(
                "utf-8",
                errors="strict",
            )
        except (KeyError, TypeError, UnicodeDecodeError):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        token_literal, path_record = _normalized_path_literal(
            token["literal"],
            namespaces=namespaces,
            side=side,
            allow_path=token["kind"] == "StringLiteral",
        )
        token_entries.append(
            {
                "index": token["index"],
                "kind": token["kind"],
                "flags": _detached_json_value(token["flags"]),
                "text": token_text if path_record is None else path_record,
                "literal": token_literal,
            }
        )
    node_entries: list[dict[str, object]] = []
    for node in document["nodes"]:
        node_literal, _path_record = _normalized_path_literal(
            node["literal"],
            namespaces=namespaces,
            side=side,
            allow_path=node["ast_type"] == "StringConstantExpressionAst",
        )
        node_entries.append(
            {
                "index": node["index"],
                "ast_type": node["ast_type"],
                "role": node["role"],
                "parent_index": node["parent_index"],
                "child_indices": _detached_json_value(node["child_indices"]),
                "invocation_operator": node["invocation_operator"],
                "literal": node_literal,
            }
        )
    metrics = _detached_json_value(document["metrics"])
    if type(metrics) is not dict:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    return {
        "tokens": token_entries,
        "nodes": node_entries,
        "metrics": metrics,
    }


def _extracted_binding_record(
    extracted: ExtractedPowerShellPayload,
) -> dict[str, object]:
    if type(extracted) is not ExtractedPowerShellPayload:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    return {
        "rendered": {
            "utf8_bytes": extracted.rendered_utf8_bytes,
            "sha256": extracted.rendered_sha256,
        },
        "payload_field": {
            "utf8_bytes": extracted.payload_field_utf8_bytes,
            "sha256": extracted.payload_field_sha256,
        },
        "payload": {
            "utf8_bytes": extracted.payload_utf8_bytes,
            "sha256": extracted.payload_sha256,
        },
    }


def _normalize_namespace_root(value: object) -> str:
    if type(value) is not str or not value:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    if (
        len(encoded) > _PATH_NAMESPACE_ROOT_UTF8_LIMIT
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    normalized = PureWindowsPath(value.replace("/", "\\"))
    if (
        not normalized.is_absolute()
        or not normalized.anchor
        or len(normalized.parts) <= 1
        or any(part in ("", ".", "..") for part in normalized.parts[1:])
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    result = str(normalized)
    if result.startswith("\\\\?\\") or result.startswith("\\??\\"):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    return result


def _namespace_path_key(value: str) -> tuple[str, ...]:
    path = PureWindowsPath(value)
    return tuple(path.parts)


def _namespace_roots_overlap(left: str, right: str) -> bool:
    left_parts = _namespace_path_key(left)
    right_parts = _namespace_path_key(right)
    common = min(len(left_parts), len(right_parts))
    return _windows_path_parts_equal(
        left_parts[:common],
        right_parts[:common],
        ignore_case=True,
    )


def _identity_record(identity: FilesystemObjectIdentity) -> dict[str, int]:
    if type(identity) is not FilesystemObjectIdentity:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    return {
        "device": identity.device,
        "inode": identity.inode,
        "file_type": identity.file_type,
        "reparse_tag": identity.reparse_tag,
        "link_count": identity.link_count,
    }


def _namespace_full_record(
    *,
    raw_root: str,
    retained_root: str,
    label: str,
    raw_identity: FilesystemObjectIdentity,
    retained_identity: FilesystemObjectIdentity,
    raw_ancestor_identities: tuple[FilesystemObjectIdentity, ...],
    retained_ancestor_identities: tuple[FilesystemObjectIdentity, ...],
    raw_case_sensitive: bool,
    retained_case_sensitive: bool,
) -> dict[str, object]:
    return {
        "version": _PATH_NAMESPACE_MANIFEST_VERSION,
        "raw_root": raw_root,
        "retained_root": retained_root,
        "label": label,
        "raw_identity": _identity_record(raw_identity),
        "retained_identity": _identity_record(retained_identity),
        "raw_ancestor_identities": [
            _identity_record(value) for value in raw_ancestor_identities
        ],
        "retained_ancestor_identities": [
            _identity_record(value) for value in retained_ancestor_identities
        ],
        "raw_case_sensitive": raw_case_sensitive,
        "retained_case_sensitive": retained_case_sensitive,
    }


def _namespace_public_record(
    namespace: BoundPathNamespace,
) -> dict[str, object]:
    if type(namespace) is not BoundPathNamespace:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    return {
        "label": namespace.label,
        "raw_root_sha256": sha256(
            namespace.raw_root.encode("utf-8", errors="strict")
        ).hexdigest(),
        "retained_root": namespace.retained_root,
        "raw_identity": _identity_record(namespace.raw_identity),
        "retained_identity": _identity_record(namespace.retained_identity),
        "raw_ancestor_identities": [
            _identity_record(value)
            for value in namespace.raw_ancestor_identities
        ],
        "retained_ancestor_identities": [
            _identity_record(value)
            for value in namespace.retained_ancestor_identities
        ],
        "raw_case_sensitive": namespace.raw_case_sensitive,
        "retained_case_sensitive": namespace.retained_case_sensitive,
        "canonical_sha256": namespace.canonical_sha256,
    }


def _validated_namespace_observation(
    value: object,
    *,
    expected_root: str,
) -> tuple[
    str,
    FilesystemObjectIdentity,
    tuple[FilesystemObjectIdentity, ...],
    bool,
]:
    if type(value) is not tuple or len(value) != 4:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    observed_root, identity, ancestors, case_sensitive = value
    if (
        type(observed_root) is not str
        or _normalize_namespace_root(observed_root) != expected_root
        or type(identity) is not FilesystemObjectIdentity
        or type(ancestors) is not tuple
        or any(type(item) is not FilesystemObjectIdentity for item in ancestors)
        or not ancestors
        or type(case_sensitive) is not bool
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    return observed_root, identity, ancestors, case_sensitive


def _observe_namespace_root(
    path: str,
) -> tuple[
    str,
    FilesystemObjectIdentity,
    tuple[FilesystemObjectIdentity, ...],
    bool,
]:
    normalized_root = _normalize_namespace_root(path)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
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
    nt_create_file = ntdll.NtCreateFile
    nt_create_file.argtypes = (
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        ctypes.POINTER(_ObjectAttributes),
        ctypes.POINTER(_IoStatusBlock),
        wintypes.LPVOID,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.LPVOID,
        wintypes.ULONG,
    )
    nt_create_file.restype = ctypes.c_long
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    )
    get_information.restype = wintypes.BOOL
    get_information_ex = kernel32.GetFileInformationByHandleEx
    get_information_ex.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    get_information_ex.restype = wintypes.BOOL
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    get_final_path.restype = wintypes.DWORD
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    file_read_attributes = 0x00000080
    file_traverse = 0x00000020
    synchronize = 0x00100000
    file_share_read = 0x00000001
    file_share_write = 0x00000002
    file_share_delete = 0x00000004
    open_existing = 3
    file_attribute_directory = 0x00000010
    file_attribute_reparse_point = 0x00000400
    file_flag_open_reparse_point = 0x00200000
    file_flag_backup_semantics = 0x02000000
    file_directory_file = 0x00000001
    file_synchronous_io_nonalert = 0x00000020
    file_open_for_backup_intent = 0x00004000
    file_open_reparse_point = 0x00200000
    obj_dont_reparse = 0x00001000
    nt_file_open = 1
    file_attribute_tag_info = 9
    file_case_sensitive_info = 23
    file_cs_flag_case_sensitive_dir = 0x00000001
    invalid_handle = ctypes.c_void_p(-1).value

    def open_anchor(component: str) -> object:
        handle = create_file(
            component,
            file_read_attributes | file_traverse,
            file_share_read | file_share_write | file_share_delete,
            None,
            open_existing,
            file_flag_open_reparse_point | file_flag_backup_semantics,
            None,
        )
        if handle in (None, invalid_handle):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        return handle

    def open_relative(parent_handle: object, name: str) -> object:
        try:
            name_utf16le = name.encode("utf-16-le", errors="strict")
        except UnicodeEncodeError:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        if not name_utf16le or len(name_utf16le) > 65532:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        name_buffer = ctypes.create_unicode_buffer(name)
        unicode_name = _UnicodeString(
            length=len(name_utf16le),
            maximum_length=len(name_utf16le) + 2,
            buffer=ctypes.cast(name_buffer, wintypes.LPWSTR),
        )
        object_attributes = _ObjectAttributes(
            length=ctypes.sizeof(_ObjectAttributes),
            root_directory=parent_handle,
            object_name=ctypes.pointer(unicode_name),
            attributes=obj_dont_reparse,
            security_descriptor=None,
            security_quality_of_service=None,
        )
        io_status = _IoStatusBlock()
        handle = wintypes.HANDLE()
        status = nt_create_file(
            ctypes.byref(handle),
            file_read_attributes | file_traverse | synchronize,
            ctypes.byref(object_attributes),
            ctypes.byref(io_status),
            None,
            0,
            file_share_read | file_share_write | file_share_delete,
            nt_file_open,
            (
                file_directory_file
                | file_synchronous_io_nonalert
                | file_open_for_backup_intent
                | file_open_reparse_point
            ),
            None,
            0,
        )
        if status < 0 or handle.value in (None, invalid_handle):
            if handle.value not in (None, invalid_handle):
                close_handle(handle)
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        return handle

    def inspect_component(
        handle: object,
        component: str,
        *,
        query_case_sensitive: bool,
        require_exact_case: bool,
    ) -> tuple[FilesystemObjectIdentity, bool]:
        information = _ByHandleFileInformation()
        tag_information = _FileAttributeTagInformation()
        if not get_information(handle, ctypes.byref(information)):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        if not get_information_ex(
            handle,
            file_attribute_tag_info,
            ctypes.byref(tag_information),
            ctypes.sizeof(tag_information),
        ):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        if (
            not information.file_attributes & file_attribute_directory
            or information.file_attributes & file_attribute_reparse_point
            or not tag_information.file_attributes
            & file_attribute_directory
            or tag_information.file_attributes
            & file_attribute_reparse_point
            or tag_information.reparse_tag != 0
            or information.number_of_links <= 0
        ):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        final_size = get_final_path(handle, None, 0, 0)
        if final_size <= 0 or final_size > 32767:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        final_buffer = ctypes.create_unicode_buffer(final_size + 1)
        final_length = get_final_path(
            handle,
            final_buffer,
            len(final_buffer),
            0,
        )
        if final_length <= 0 or final_length >= len(final_buffer):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        observed_path = final_buffer.value
        if observed_path.startswith("\\\\?\\UNC\\"):
            observed_path = "\\\\" + observed_path[8:]
        elif observed_path.startswith("\\\\?\\"):
            observed_path = observed_path[4:]
        expected_path = str(PureWindowsPath(component))
        observed_path = str(PureWindowsPath(observed_path))
        case_sensitive = False
        if query_case_sensitive:
            case_information = _FileCaseSensitiveInformation()
            if not get_information_ex(
                handle,
                file_case_sensitive_info,
                ctypes.byref(case_information),
                ctypes.sizeof(case_information),
            ):
                _reject(COMMAND_PLAN_CANONICAL_INVALID)
            if case_information.flags & ~file_cs_flag_case_sensitive_dir:
                _reject(COMMAND_PLAN_CANONICAL_INVALID)
            case_sensitive = bool(
                case_information.flags & file_cs_flag_case_sensitive_dir
            )
        if not _windows_ordinal_equal(
            observed_path,
            expected_path,
            ignore_case=not require_exact_case,
        ):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        identity = FilesystemObjectIdentity(
            device=information.volume_serial_number,
            inode=(information.file_index_high << 32)
            | information.file_index_low,
            file_type=_DIRECTORY_FILE_TYPE,
            reparse_tag=tag_information.reparse_tag,
            link_count=information.number_of_links,
        )
        return identity, case_sensitive

    root_path = PureWindowsPath(normalized_root)
    handles: list[object] = []
    ancestor_identities: list[FilesystemObjectIdentity] = []
    root_identity: FilesystemObjectIdentity | None = None
    root_case_sensitive = False
    try:
        anchor_handle = open_anchor(root_path.anchor)
        handles.append(anchor_handle)
        anchor_identity, _anchor_case_sensitive = inspect_component(
            anchor_handle,
            root_path.anchor,
            query_case_sensitive=False,
            require_exact_case=False,
        )
        ancestor_identities.append(anchor_identity)
        current = PureWindowsPath(root_path.anchor)
        final_index = len(root_path.parts) - 2
        for index, part in enumerate(root_path.parts[1:]):
            handle = open_relative(handles[-1], part)
            handles.append(handle)
            current /= part
            is_root = index == final_index
            identity, case_sensitive = inspect_component(
                handle,
                str(current),
                query_case_sensitive=is_root,
                require_exact_case=True,
            )
            if is_root:
                root_identity = identity
                root_case_sensitive = case_sensitive
            else:
                ancestor_identities.append(identity)
        if root_identity is None:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        return (
            normalized_root,
            root_identity,
            tuple(ancestor_identities),
            root_case_sensitive,
        )
    except RuntimeError:
        raise
    except (OSError, OverflowError, TypeError, ValueError):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    finally:
        close_failed = False
        for handle in reversed(handles):
            if not close_handle(handle):
                close_failed = True
        if close_failed:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)


def _register_bound_namespace(namespace: BoundPathNamespace) -> None:
    key = id(namespace)

    def cleanup(reference: weakref.ReferenceType[BoundPathNamespace]) -> None:
        with _BOUND_NAMESPACE_REGISTRY_LOCK:
            registered = _BOUND_NAMESPACE_REGISTRY.get(key)
            if registered is not None and registered[0] is reference:
                del _BOUND_NAMESPACE_REGISTRY[key]

    reference = weakref.ref(namespace, cleanup)
    with _BOUND_NAMESPACE_REGISTRY_LOCK:
        if key in _BOUND_NAMESPACE_REGISTRY:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        _BOUND_NAMESPACE_REGISTRY[key] = (
            reference,
            namespace.canonical_sha256,
        )


def _authenticate_bound_namespaces(
    namespaces: tuple[BoundPathNamespace, ...],
) -> None:
    if (
        type(namespaces) is not tuple
        or len(namespaces) > _PATH_NAMESPACE_LIMIT
        or any(type(value) is not BoundPathNamespace for value in namespaces)
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    expected_order = tuple(
        sorted(
            namespaces,
            key=lambda value: (
                value.label,
                _namespace_path_key(value.raw_root),
                _namespace_path_key(value.retained_root),
            ),
        )
    )
    if namespaces != expected_order:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    with _BOUND_NAMESPACE_REGISTRY_LOCK:
        for namespace in namespaces:
            registered = _BOUND_NAMESPACE_REGISTRY.get(id(namespace))
            if (
                registered is None
                or registered[0]() is not namespace
                or registered[1] != namespace.canonical_sha256
            ):
                _reject(COMMAND_PLAN_CANONICAL_INVALID)
    for namespace in namespaces:
        full_record = _namespace_full_record(
            raw_root=namespace.raw_root,
            retained_root=namespace.retained_root,
            label=namespace.label,
            raw_identity=namespace.raw_identity,
            retained_identity=namespace.retained_identity,
            raw_ancestor_identities=namespace.raw_ancestor_identities,
            retained_ancestor_identities=namespace.retained_ancestor_identities,
            raw_case_sensitive=namespace.raw_case_sensitive,
            retained_case_sensitive=namespace.retained_case_sensitive,
        )
        if sha256(_canonical_json_bytes(full_record)).hexdigest() != (
            namespace.canonical_sha256
        ):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)


def _revalidate_retained_namespaces(
    namespaces: tuple[BoundPathNamespace, ...],
) -> None:
    for namespace in namespaces:
        observation = _validated_namespace_observation(
            _observe_namespace_root(namespace.retained_root),
            expected_root=namespace.retained_root,
        )
        if observation[1:] != (
            namespace.retained_identity,
            namespace.retained_ancestor_identities,
            namespace.retained_case_sensitive,
        ):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)


def _namespace_manifest(
    namespaces: tuple[BoundPathNamespace, ...],
) -> dict[str, object]:
    return {
        "version": _PATH_NAMESPACE_MANIFEST_VERSION,
        "namespaces": [
            _namespace_public_record(namespace) for namespace in namespaces
        ],
    }


def bind_path_namespaces(
    requests: Sequence[PathNamespaceRequest],
) -> tuple[BoundPathNamespace, ...]:
    if isinstance(requests, (str, bytes, bytearray)) or not isinstance(
        requests,
        Sequence,
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    snapshot_values: list[PathNamespaceRequest] = []
    try:
        for request in requests:
            if len(snapshot_values) >= _PATH_NAMESPACE_LIMIT:
                _reject(COMMAND_PLAN_CANONICAL_INVALID)
            if type(request) is not PathNamespaceRequest:
                _reject(COMMAND_PLAN_CANONICAL_INVALID)
            snapshot_values.append(request)
    except RuntimeError:
        raise
    except Exception:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    snapshot = tuple(snapshot_values)
    if not snapshot:
        return ()
    prepared: list[tuple[str, str, str]] = []
    for request in snapshot:
        if _PATH_NAMESPACE_LABEL.fullmatch(request.label) is None:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        prepared.append(
            (
                _normalize_namespace_root(request.raw_root),
                _normalize_namespace_root(request.retained_root),
                request.label,
            )
        )
    prepared.sort(
        key=lambda value: (
            value[2],
            _namespace_path_key(value[0]),
            _namespace_path_key(value[1]),
        )
    )
    labels = [value[2] for value in prepared]
    if len(labels) != len(set(labels)):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    all_roots = [root for value in prepared for root in value[:2]]
    for index, root in enumerate(all_roots):
        for other in all_roots[index + 1 :]:
            if _namespace_roots_overlap(root, other):
                _reject(COMMAND_PLAN_CANONICAL_INVALID)
    observations: list[
        tuple[
            tuple[str, FilesystemObjectIdentity, tuple[FilesystemObjectIdentity, ...], bool],
            tuple[str, FilesystemObjectIdentity, tuple[FilesystemObjectIdentity, ...], bool],
            str,
        ]
    ] = []
    for raw_root, retained_root, label in prepared:
        raw_observation = _validated_namespace_observation(
            _observe_namespace_root(raw_root),
            expected_root=raw_root,
        )
        retained_observation = _validated_namespace_observation(
            _observe_namespace_root(retained_root),
            expected_root=retained_root,
        )
        observations.append((raw_observation, retained_observation, label))
    for raw_observation, retained_observation, _label in observations:
        if _validated_namespace_observation(
            _observe_namespace_root(raw_observation[0]),
            expected_root=raw_observation[0],
        ) != raw_observation:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        if _validated_namespace_observation(
            _observe_namespace_root(retained_observation[0]),
            expected_root=retained_observation[0],
        ) != retained_observation:
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
    result: list[BoundPathNamespace] = []
    for raw_observation, retained_observation, label in observations:
        full_record = _namespace_full_record(
            raw_root=raw_observation[0],
            retained_root=retained_observation[0],
            label=label,
            raw_identity=raw_observation[1],
            retained_identity=retained_observation[1],
            raw_ancestor_identities=raw_observation[2],
            retained_ancestor_identities=retained_observation[2],
            raw_case_sensitive=raw_observation[3],
            retained_case_sensitive=retained_observation[3],
        )
        namespace = BoundPathNamespace(
            raw_root=raw_observation[0],
            retained_root=retained_observation[0],
            label=label,
            raw_identity=raw_observation[1],
            retained_identity=retained_observation[1],
            raw_ancestor_identities=raw_observation[2],
            retained_ancestor_identities=retained_observation[2],
            raw_case_sensitive=raw_observation[3],
            retained_case_sensitive=retained_observation[3],
            canonical_sha256=sha256(
                _canonical_json_bytes(full_record)
            ).hexdigest(),
        )
        result.append(namespace)
    frozen = tuple(result)
    for namespace in frozen:
        _register_bound_namespace(namespace)
    return frozen


def bind_raw_and_retained_plans(
    raw_rendered: bytes,
    retained_rendered: bytes,
    *,
    shell: ShellIdentity,
    decoder_path: Path,
    decoder_sha256: str,
    namespaces: tuple[BoundPathNamespace, ...],
) -> BoundCommandPlan:
    if (
        type(raw_rendered) is not bytes
        or type(retained_rendered) is not bytes
        or type(namespaces) is not tuple
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    _authenticate_bound_namespaces(namespaces)
    _revalidate_retained_namespaces(namespaces)
    raw_extracted = extract_powershell_payload(raw_rendered, shell=shell)
    retained_extracted = extract_powershell_payload(
        retained_rendered,
        shell=shell,
    )
    raw_payload = raw_extracted.payload.encode("utf-8", errors="strict")
    retained_payload = retained_extracted.payload.encode("utf-8", errors="strict")
    raw_decoded = decode_powershell_payload(
        raw_payload,
        shell=shell,
        decoder_path=decoder_path,
        decoder_sha256=decoder_sha256,
    )
    retained_decoded = decode_powershell_payload(
        retained_payload,
        shell=shell,
        decoder_path=decoder_path,
        decoder_sha256=decoder_sha256,
    )
    _revalidate_retained_namespaces(namespaces)
    if (
        type(raw_decoded) is not DecodedPowerShellPayload
        or type(retained_decoded) is not DecodedPowerShellPayload
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    raw_document = _decode_single_json_object(raw_decoded.canonical_bytes)
    retained_document = _decode_single_json_object(retained_decoded.canonical_bytes)
    raw_command = _semantic_command_view(
        raw_document,
        payload=raw_payload,
        shell=shell,
        decoder_sha256=decoder_sha256,
        namespaces=namespaces,
        side="raw",
    )
    retained_command = _semantic_command_view(
        retained_document,
        payload=retained_payload,
        shell=shell,
        decoder_sha256=decoder_sha256,
        namespaces=namespaces,
        side="retained",
    )
    if not _semantic_command_values_equivalent(
        raw_command,
        retained_command,
        namespaces=namespaces,
    ):
        _reject(COMMAND_PLAN_RAW_RETAINED_MISMATCH)
    manifest_document = _namespace_manifest(namespaces)
    manifest_bytes = _canonical_json_bytes(manifest_document)
    manifest_sha256 = sha256(manifest_bytes).hexdigest()
    normalized_document = {
        "version": _BOUND_COMMAND_PLAN_VERSION,
        "bindings": {
            "raw": _extracted_binding_record(raw_extracted),
            "retained": _extracted_binding_record(retained_extracted),
        },
        "shell": {
            "path": shell.path,
            "sha256": shell.sha256,
            "file_version": shell.file_version,
            "product_version": shell.product_version,
            "edition": shell.edition,
            "parser_version": shell.parser_version,
        },
        "decoder": {
            "path": _DECODER_RELATIVE_PATH,
            "sha256": decoder_sha256,
        },
        "namespaces": manifest_document["namespaces"],
        "namespace_manifest_sha256": manifest_sha256,
        "command": retained_command,
    }
    normalized_bytes = _canonical_json_bytes(normalized_document)
    return BoundCommandPlan(
        version=_BOUND_COMMAND_PLAN_VERSION,
        raw_rendered_utf8_bytes=raw_extracted.rendered_utf8_bytes,
        raw_rendered_sha256=raw_extracted.rendered_sha256,
        retained_rendered_utf8_bytes=retained_extracted.rendered_utf8_bytes,
        retained_rendered_sha256=retained_extracted.rendered_sha256,
        raw_payload_field_utf8_bytes=raw_extracted.payload_field_utf8_bytes,
        raw_payload_field_sha256=raw_extracted.payload_field_sha256,
        raw_payload_utf8_bytes=raw_extracted.payload_utf8_bytes,
        raw_payload_sha256=raw_extracted.payload_sha256,
        retained_payload_field_utf8_bytes=(
            retained_extracted.payload_field_utf8_bytes
        ),
        retained_payload_field_sha256=retained_extracted.payload_field_sha256,
        retained_payload_utf8_bytes=retained_extracted.payload_utf8_bytes,
        retained_payload_sha256=retained_extracted.payload_sha256,
        namespaces=namespaces,
        namespace_manifest_sha256=manifest_sha256,
        normalized_plan_sha256=sha256(normalized_bytes).hexdigest(),
        normalized_plan_bytes=normalized_bytes,
    )


def validate_retained_command_plan_bytes(
    plan_bytes: bytes,
    *,
    expected_sha256: str,
) -> dict[str, Any]:
    """Validate a detached retained normalized-plan record.

    This authenticates the closed canonical record and its internal digest
    topology.  It intentionally does not claim that recorded raw filesystem
    identities have been observed again; approved-raw replay must use the live
    binders for that stronger assertion.
    """

    if (
        type(plan_bytes) is not bytes
        or not plan_bytes
        or len(plan_bytes) > _DECODER_LIMITS.plan_bytes
        or type(expected_sha256) is not str
        or _LOWER_SHA256.fullmatch(expected_sha256) is None
        or sha256(plan_bytes).hexdigest() != expected_sha256
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    document = _decode_single_json_object(plan_bytes)
    if _canonical_json_bytes(document) != plan_bytes or set(document) != {
        "bindings",
        "command",
        "decoder",
        "namespace_manifest_sha256",
        "namespaces",
        "shell",
        "version",
    }:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    if document.get("version") != _BOUND_COMMAND_PLAN_VERSION:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)

    def digest_record(value: object) -> bool:
        return (
            type(value) is dict
            and set(value) == {"sha256", "utf8_bytes"}
            and type(value.get("utf8_bytes")) is int
            and value["utf8_bytes"] >= 0
            and type(value.get("sha256")) is str
            and _LOWER_SHA256.fullmatch(value["sha256"]) is not None
        )

    bindings = document.get("bindings")
    if type(bindings) is not dict or set(bindings) != {"raw", "retained"}:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    for domain in ("raw", "retained"):
        binding = bindings[domain]
        if (
            type(binding) is not dict
            or set(binding) != {"rendered", "payload_field", "payload"}
            or not all(digest_record(binding[name]) for name in binding)
        ):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)

    shell = document.get("shell")
    if (
        type(shell) is not dict
        or set(shell)
        != {
            "path",
            "sha256",
            "file_version",
            "product_version",
            "edition",
            "parser_version",
        }
        or any(
            type(shell.get(name)) is not str or not shell[name]
            for name in (
                "path",
                "file_version",
                "product_version",
                "edition",
                "parser_version",
            )
        )
        or type(shell.get("sha256")) is not str
        or _LOWER_SHA256.fullmatch(shell["sha256"]) is None
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)

    decoder = document.get("decoder")
    decoder_path = decoder.get("path") if type(decoder) is dict else None
    try:
        detached_decoder_path = PureWindowsPath(decoder_path)
    except (TypeError, ValueError):
        detached_decoder_path = PureWindowsPath(".")
    if (
        type(decoder) is not dict
        or set(decoder) != {"path", "sha256"}
        or type(decoder_path) is not str
        or not decoder_path
        or detached_decoder_path.is_absolute()
        or detached_decoder_path.anchor
        or not detached_decoder_path.parts
        or any(part in {"", ".", ".."} for part in detached_decoder_path.parts)
        or detached_decoder_path.suffix.casefold() != ".ps1"
        or type(decoder.get("sha256")) is not str
        or _LOWER_SHA256.fullmatch(decoder["sha256"]) is None
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)

    identity_fields = {
        "device",
        "inode",
        "file_type",
        "reparse_tag",
        "link_count",
    }

    def identity_record(value: object) -> bool:
        return (
            type(value) is dict
            and set(value) == identity_fields
            and all(type(item) is int and item >= 0 for item in value.values())
            and value["file_type"] != 0
            and value["link_count"] != 0
        )

    namespaces = document.get("namespaces")
    if (
        type(namespaces) is not list
        or len(namespaces) > _PATH_NAMESPACE_LIMIT
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    labels: list[str] = []
    for namespace in namespaces:
        if (
            type(namespace) is not dict
            or set(namespace)
            != {
                "label",
                "raw_root_sha256",
                "retained_root",
                "raw_identity",
                "retained_identity",
                "raw_ancestor_identities",
                "retained_ancestor_identities",
                "raw_case_sensitive",
                "retained_case_sensitive",
                "canonical_sha256",
            }
            or type(namespace.get("label")) is not str
            or _PATH_NAMESPACE_LABEL.fullmatch(namespace["label"]) is None
            or type(namespace.get("retained_root")) is not str
            or not namespace["retained_root"]
            or any(
                type(namespace.get(name)) is not str
                or _LOWER_SHA256.fullmatch(namespace[name]) is None
                for name in ("raw_root_sha256", "canonical_sha256")
            )
            or not identity_record(namespace.get("raw_identity"))
            or not identity_record(namespace.get("retained_identity"))
            or any(
                type(namespace.get(name)) is not list
                or len(namespace[name]) > 64
                or not all(identity_record(value) for value in namespace[name])
                for name in (
                    "raw_ancestor_identities",
                    "retained_ancestor_identities",
                )
            )
            or type(namespace.get("raw_case_sensitive")) is not bool
            or type(namespace.get("retained_case_sensitive")) is not bool
        ):
            _reject(COMMAND_PLAN_CANONICAL_INVALID)
        labels.append(namespace["label"])
    if len(labels) != len(set(labels)):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    manifest = {
        "version": _PATH_NAMESPACE_MANIFEST_VERSION,
        "namespaces": namespaces,
    }
    manifest_sha256 = document.get("namespace_manifest_sha256")
    if (
        type(manifest_sha256) is not str
        or _LOWER_SHA256.fullmatch(manifest_sha256) is None
        or sha256(_canonical_json_bytes(manifest)).hexdigest()
        != manifest_sha256
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)

    command = document.get("command")
    if (
        type(command) is not dict
        or set(command) != {"metrics", "nodes", "tokens"}
        or type(command.get("metrics")) is not dict
        or type(command.get("nodes")) is not list
        or type(command.get("tokens")) is not list
        or len(command["nodes"]) > _DECODER_LIMITS.ast_nodes
        or len(command["tokens"]) > _DECODER_LIMITS.tokens
    ):
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    try:
        import complete_suite_command_policy as command_policy

        command_policy._validate_normalized_command(document)
    except RuntimeError:
        _reject(COMMAND_PLAN_CANONICAL_INVALID)
    return _decode_single_json_object(bytes(plan_bytes))
