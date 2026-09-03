from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import socket
import socketserver
import threading
from typing import Literal
from uuid import uuid4


MAX_REQUEST_BYTES = 1_048_576
MAX_HEADER_BYTES = 16_384
MAX_HEADER_LINE_BYTES = 4_096
LOOPBACK_HOST = "127.0.0.1"
LOOPBACK_ROUTE = "/v1/responses"
LOOPBACK_MODEL = "gpt-5.6-terra"
LOOPBACK_USER_AGENT = "kokoroarc-campaign6-client-preflight-v1"
NATIVE_TOOL_SCHEMA_PROVENANCE = (
    "unverified-fail-closed-static-request-tool-schema-v1"
)
FILE_ADD_BYTES = b"campaign6-add\n"
FILE_UPDATE_BYTES = b"campaign6-update\n"

_REQUEST_REQUIRED_HEADER_NAMES = frozenset(
    {"host", "user-agent", "content-type", "content-length"}
)
_REQUEST_OPTIONAL_HEADER_NAMES = frozenset(
    {
        "accept",
        "accept-encoding",
        "connection",
        "openai-beta",
        "traceparent",
        "tracestate",
        "x-client-request-id",
        "x-codex-installation-id",
        "x-codex-routing-hint",
        "x-codex-turn-metadata",
        "x-codex-turn-state",
        "x-oai-attestation",
        "x-openai-subagent",
        "x-responsesapi-include-timing-metrics",
    }
)
_REQUEST_ALLOWED_HEADER_NAMES = (
    _REQUEST_REQUIRED_HEADER_NAMES | _REQUEST_OPTIONAL_HEADER_NAMES
)
_NORMALIZABLE_DYNAMIC_REQUEST_HEADERS = {
    "traceparent": b"<traceparent>",
    "tracestate": b"<tracestate>",
    "x-client-request-id": b"<x-client-request-id>",
}
_HEADER_NAME = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+\Z")
_MAX_REQUEST_HEADERS = 32
_REQUEST_BODY_COMMON = {
    "model": LOOPBACK_MODEL,
    "parallel_tool_calls": False,
    "store": False,
    "stream": True,
    "tool_choice": "auto",
}
_ADVERTISED_TOOLS = [
    {
        "description": "Execute exactly one inert PowerShell payload.",
        "name": "shell",
        "parameters": {
            "additionalProperties": False,
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
            "type": "object",
        },
        "strict": True,
        "type": "function",
    },
    {
        "description": "Apply exactly one campaign-owned file patch.",
        "name": "apply_patch",
        "parameters": {
            "additionalProperties": False,
            "properties": {"patch": {"type": "string"}},
            "required": ["patch"],
            "type": "object",
        },
        "strict": True,
        "type": "function",
    },
]


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


_ADVERTISED_TOOLS_BYTES = _canonical(_ADVERTISED_TOOLS)

_REQUEST_OPTIONAL_FIELD_NAMES = frozenset(
    {
        "client_metadata",
        "codex_output_schema",
        "include",
        "instructions",
        "prompt_cache_key",
        "reasoning",
        "service_tier",
        "stream_options",
    }
)
_REQUEST_REASONING_FIELD_NAMES = frozenset({"effort", "summary"})
_REQUEST_STREAM_OPTION_FIELD_NAMES = frozenset({"include_obfuscation"})
_REQUEST_INCLUDE_VALUES = frozenset({"reasoning.encrypted_content"})
_REQUEST_SERVICE_TIERS = frozenset({"auto", "default", "flex", "priority"})


def advertised_tools() -> list[dict[str, object]]:
    return json.loads(_ADVERTISED_TOOLS_BYTES)


_ADVERTISED_TOOLS_MANIFEST = {
    "capabilities": {
        "parallel_tool_calls": False,
        "tool_choice": "auto",
    },
    "model": LOOPBACK_MODEL,
    "tools": advertised_tools(),
    "version": "complete-suite-advertised-tools-v1",
}
ADVERTISED_TOOLS_SHA256 = sha256(
    _canonical(_ADVERTISED_TOOLS_MANIFEST)
).hexdigest()


@dataclass(frozen=True)
class LoopbackScenarioContract:
    name: Literal["shell", "file_add", "file_update"]
    prompt_role: Literal["harness-owned"]
    tool_name: Literal["shell", "apply_patch"]
    arguments: str
    tool_output: str
    final_text: Literal["campaign6-loopback-complete"]
    file_bytes: bytes | None


_SCENARIOS = {
    "shell": LoopbackScenarioContract(
        name="shell",
        prompt_role="harness-owned",
        tool_name="shell",
        arguments=_canonical(
            {"command": r"Test-Path -LiteralPath '.\case.json'"}
        ).decode("utf-8"),
        tool_output=(
            "Chunk ID: campaign6-loopback\n"
            "Process exited with code 0\n"
            "Final output:\n"
            "True\n"
        ),
        final_text="campaign6-loopback-complete",
        file_bytes=None,
    ),
    "file_add": LoopbackScenarioContract(
        name="file_add",
        prompt_role="harness-owned",
        tool_name="apply_patch",
        arguments=_canonical(
            {
                "patch": (
                    "*** Begin Patch\n"
                    "*** Add File: preflight-file-change.txt\n"
                    "+campaign6-add\n"
                    "*** End Patch"
                )
            }
        ).decode("utf-8"),
        tool_output="Done!",
        final_text="campaign6-loopback-complete",
        file_bytes=FILE_ADD_BYTES,
    ),
    "file_update": LoopbackScenarioContract(
        name="file_update",
        prompt_role="harness-owned",
        tool_name="apply_patch",
        arguments=_canonical(
            {
                "patch": (
                    "*** Begin Patch\n"
                    "*** Update File: preflight-file-change.txt\n"
                    "@@\n"
                    "-campaign6-add\n"
                    "+campaign6-update\n"
                    "*** End Patch"
                )
            }
        ).decode("utf-8"),
        tool_output="Done!",
        final_text="campaign6-loopback-complete",
        file_bytes=FILE_UPDATE_BYTES,
    ),
}


def scenario_contract(
    scenario: str,
) -> LoopbackScenarioContract:
    if type(scenario) is not str or scenario not in _SCENARIOS:
        raise RuntimeError("LOOPBACK_SERVER_CONTRACT_MISMATCH")
    return _SCENARIOS[scenario]


def _valid_case_root(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and "\x00" not in value
        and "\r" not in value
        and "\n" not in value
        and os.path.isabs(value)
        and os.path.normpath(value) == value
    )


def _first_request_body(
    contract: LoopbackScenarioContract,
    case_root: str,
) -> dict[str, object]:
    return {
        "input": [
            {
                "content": [
                    {
                        "text": f"{contract.name}\ncase-root={case_root}",
                        "type": "input_text",
                    }
                ],
                "role": "user",
            }
        ],
        **_REQUEST_BODY_COMMON,
        "tools": advertised_tools(),
    }


def _second_request_body(
    contract: LoopbackScenarioContract,
    *,
    response_id: str,
    call_id: str,
) -> dict[str, object]:
    return {
        "input": [
            {
                "call_id": call_id,
                "output": contract.tool_output,
                "type": "function_call_output",
            }
        ],
        **_REQUEST_BODY_COMMON,
        "previous_response_id": response_id,
        "tools": advertised_tools(),
    }


def _sse_frame(event: str, payload: object) -> bytes:
    if (
        type(event) is not str
        or type(payload) is not dict
        or payload.get("type") != event
    ):
        raise RuntimeError("LOOPBACK_SERVER_CONTRACT_MISMATCH")
    return b"data: " + _canonical(payload) + b"\n\n"


def _completed_response_record(
    response_id: str,
) -> dict[str, object]:
    return {
        "id": response_id,
        "incomplete_details": None,
        "status": "completed",
        "usage": {
            "input_tokens": 0,
            "input_tokens_details": {
                "cache_write_tokens": 0,
                "cached_tokens": 0,
            },
            "output_tokens": 0,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 0,
        },
    }


def _tool_call_sse(
    contract: LoopbackScenarioContract,
    *,
    response_id: str,
    call_id: str,
    item_id: str,
) -> bytes:
    completed_item = {
        "arguments": contract.arguments,
        "call_id": call_id,
        "id": item_id,
        "name": contract.tool_name,
        "status": "completed",
        "type": "function_call",
    }
    return b"".join(
        (
            _sse_frame(
                "response.output_item.done",
                {
                    "item": completed_item,
                    "type": "response.output_item.done",
                },
            ),
            _sse_frame(
                "response.completed",
                {
                    "response": _completed_response_record(response_id),
                    "type": "response.completed",
                },
            ),
        )
    )


def _final_text_sse(
    contract: LoopbackScenarioContract,
    *,
    response_id: str,
) -> bytes:
    item = {
        "content": [
            {
                "annotations": [],
                "text": contract.final_text,
                "type": "output_text",
            }
        ],
        "id": "msg_campaign6_loopback_final",
        "phase": "final_answer",
        "role": "assistant",
        "status": "completed",
        "type": "message",
    }
    return b"".join(
        (
            _sse_frame(
                "response.output_item.done",
                {
                    "item": item,
                    "type": "response.output_item.done",
                },
            ),
            _sse_frame(
                "response.completed",
                {
                    "response": _completed_response_record(response_id),
                    "type": "response.completed",
                },
            ),
        )
    )


def loopback_contract_manifest() -> dict[str, object]:
    response_templates: list[dict[str, object]] = []
    for name in ("shell", "file_add", "file_update"):
        contract = scenario_contract(name)
        first = _tool_call_sse(
            contract,
            response_id="<response-id-1>",
            call_id="<response-call-id>",
            item_id="<tool-item-id>",
        )
        second = _final_text_sse(
            contract,
            response_id="<response-id-2>",
        )
        response_templates.append(
            {
                "arguments_sha256": sha256(
                    contract.arguments.encode("utf-8")
                ).hexdigest(),
                "file_bytes_sha256": (
                    None
                    if contract.file_bytes is None
                    else sha256(contract.file_bytes).hexdigest()
                ),
                "first_request_sha256": sha256(
                    _canonical(_first_request_body(contract, "<case-root>"))
                ).hexdigest(),
                "first_sse_sha256": sha256(first).hexdigest(),
                "name": name,
                "prompt_template": f"{name}\ncase-root=<case-root>",
                "second_request_sha256": sha256(
                    _canonical(
                        _second_request_body(
                            contract,
                            response_id="<response-id-1>",
                            call_id="<response-call-id>",
                        )
                    )
                ).hexdigest(),
                "second_sse_sha256": sha256(second).hexdigest(),
                "tool_name": contract.tool_name,
                "tool_output_sha256": sha256(
                    contract.tool_output.encode("utf-8")
                ).hexdigest(),
            }
        )
    return {
        "advertised_tools_sha256": ADVERTISED_TOOLS_SHA256,
        "bind_host": LOOPBACK_HOST,
        "capabilities": {
            "parallel_tool_calls": False,
            "tool_choice": "auto",
        },
        "max_request_bytes": MAX_REQUEST_BYTES,
        "method": "POST",
        "model": LOOPBACK_MODEL,
        "native_tool_schema_provenance": NATIVE_TOOL_SCHEMA_PROVENANCE,
        "normalizable_fields": [
            "owned_ephemeral_port",
            "responses_call_ids",
            "case_root",
            "derived_request_content_length",
            "request_header.traceparent",
            "request_header.tracestate",
            "request_header.x-client-request-id",
        ],
        "port_assignment": "os-assigned",
        "request_header_contract": {
            "allow_duplicate_names": False,
            "comparison": "case-insensitive-name-unordered",
            "content_length": "canonical-decimal-body-bytes",
            "content_type": "application/json",
            "host": "127.0.0.1:<owned-ephemeral-port>",
            "optional_names": sorted(_REQUEST_OPTIONAL_HEADER_NAMES),
            "required_names": sorted(_REQUEST_REQUIRED_HEADER_NAMES),
            "user_agent": LOOPBACK_USER_AGENT,
        },
        "request_optional_fields": sorted(_REQUEST_OPTIONAL_FIELD_NAMES),
        "request_ordinals": ["tool_call", "final_text"],
        "route": LOOPBACK_ROUTE,
        "scenarios": response_templates,
        "shell_repeat_additional_normalizable_fields": ["shell_tool_item_id"],
        "tools": advertised_tools(),
        "version": "complete-suite-loopback-contract-v1",
    }


LOOPBACK_CONTRACT_SHA256 = sha256(
    _canonical(loopback_contract_manifest())
).hexdigest()


def server_module_sha256() -> str:
    return sha256(Path(__file__).read_bytes()).hexdigest()


class _ContractViolation(Exception):
    def __init__(self, *, status: int = 400) -> None:
        super().__init__("LOOPBACK_SERVER_CONTRACT_MISMATCH")
        self.status = status


def _reject_constant(_value: str) -> object:
    raise _ContractViolation()


def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _ContractViolation()
        result[key] = value
    return result


def _parse_json_object(content: bytes) -> dict[str, object]:
    try:
        text = content.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_closed_object,
            parse_constant=_reject_constant,
        )
    except _ContractViolation:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise _ContractViolation() from exc
    if type(value) is not dict:
        raise _ContractViolation()
    return value


def _json_values_match(actual: object, expected: object) -> bool:
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        actual_dict = actual
        expected_dict = expected
        if actual_dict.keys() != expected_dict.keys():
            return False
        return all(
            _json_values_match(actual_dict[key], expected_dict[key])
            for key in expected_dict
        )
    if type(expected) is list:
        actual_list = actual
        expected_list = expected
        return len(actual_list) == len(expected_list) and all(
            _json_values_match(actual_item, expected_item)
            for actual_item, expected_item in zip(actual_list, expected_list)
        )
    return bool(actual == expected)


def _bounded_request_text(value: object, *, allow_empty: bool = False) -> bool:
    return (
        type(value) is str
        and (allow_empty or bool(value))
        and "\x00" not in value
        and len(value.encode("utf-8")) <= MAX_REQUEST_BYTES
    )


def _bounded_json_value(value: object, *, depth: int = 0) -> bool:
    if depth > 64:
        return False
    if value is None or type(value) is bool:
        return True
    if type(value) is int:
        return True
    if type(value) is float:
        return value == value and value not in {float("inf"), float("-inf")}
    if type(value) is str:
        return _bounded_request_text(value, allow_empty=True)
    if type(value) is list:
        return all(_bounded_json_value(item, depth=depth + 1) for item in value)
    if type(value) is dict:
        return all(
            _bounded_request_text(key)
            and _bounded_json_value(item, depth=depth + 1)
            for key, item in value.items()
        )
    return False


def _valid_optional_request_field(name: str, value: object) -> bool:
    if name in {"instructions", "prompt_cache_key"}:
        return _bounded_request_text(value)
    if name == "reasoning":
        return (
            type(value) is dict
            and bool(value)
            and value.keys() <= _REQUEST_REASONING_FIELD_NAMES
            and _bounded_request_text(value.get("effort"))
            and (
                "summary" not in value
                or _bounded_request_text(value["summary"])
            )
        )
    if name == "stream_options":
        return (
            type(value) is dict
            and value.keys() <= _REQUEST_STREAM_OPTION_FIELD_NAMES
            and all(type(item) is bool for item in value.values())
        )
    if name == "include":
        return (
            type(value) is list
            and all(
                type(item) is str and item in _REQUEST_INCLUDE_VALUES
                for item in value
            )
            and len(value) == len(set(value))
        )
    if name == "service_tier":
        return type(value) is str and value in _REQUEST_SERVICE_TIERS
    if name == "client_metadata":
        return type(value) is dict and all(
            _bounded_request_text(key) and _bounded_request_text(item, allow_empty=True)
            for key, item in value.items()
        )
    if name == "codex_output_schema":
        return type(value) is dict and _bounded_json_value(value)
    return False


def _request_body_matches_phase(
    actual: dict[str, object],
    expected: dict[str, object],
) -> bool:
    if not expected.keys() <= actual.keys():
        return False
    if not actual.keys() <= expected.keys() | _REQUEST_OPTIONAL_FIELD_NAMES:
        return False
    if not all(
        _json_values_match(actual[name], expected[name]) for name in expected
    ):
        return False
    return all(
        _valid_optional_request_field(name, actual[name])
        for name in actual.keys() - expected.keys()
    )


@dataclass(frozen=True)
class _ParsedRequest:
    method: str
    route: str
    http_version: str
    headers: tuple[tuple[str, str], ...]
    head: bytes
    body: bytes


def _parse_request_head(
    content: bytes,
) -> tuple[str, str, str, tuple[tuple[str, str], ...], int]:
    if (
        type(content) is not bytes
        or len(content) > MAX_HEADER_BYTES
        or not content.endswith(b"\r\n\r\n")
    ):
        raise _ContractViolation()
    lines = content[:-4].split(b"\r\n")
    if not lines or any(not line for line in lines):
        raise _ContractViolation()
    request_line = lines[0]
    if len(request_line) + 2 > MAX_HEADER_LINE_BYTES:
        raise _ContractViolation()
    try:
        decoded_line = request_line.decode("ascii", errors="strict")
        method, route, http_version = decoded_line.split(" ")
    except (UnicodeDecodeError, ValueError) as exc:
        raise _ContractViolation() from exc
    headers: list[tuple[str, str]] = []
    names: set[str] = set()
    for line in lines[1:]:
        if (
            len(line) + 2 > MAX_HEADER_LINE_BYTES
            or line[:1] in (b" ", b"\t")
            or b":" not in line
            or len(headers) >= _MAX_REQUEST_HEADERS
        ):
            raise _ContractViolation()
        name_bytes, value_bytes = line.split(b":", 1)
        value_bytes = value_bytes.strip(b" \t")
        try:
            name = name_bytes.decode("ascii", errors="strict")
            value = value_bytes.decode("ascii", errors="strict")
        except UnicodeDecodeError as exc:
            raise _ContractViolation() from exc
        folded_name = name.casefold()
        if (
            not name
            or not value
            or "\x00" in value
            or _HEADER_NAME.fullmatch(name) is None
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or folded_name in names
        ):
            raise _ContractViolation()
        names.add(folded_name)
        headers.append((name, value))
    normalized_headers = {name.casefold(): value for name, value in headers}
    content_length_value = normalized_headers.get("content-length")
    if type(content_length_value) is not str:
        raise _ContractViolation()
    if (
        not content_length_value.isascii()
        or not content_length_value.isdecimal()
        or str(int(content_length_value)) != content_length_value
    ):
        raise _ContractViolation()
    content_length = int(content_length_value)
    if content_length > MAX_REQUEST_BYTES:
        raise _ContractViolation(status=413)
    return method, route, http_version, tuple(headers), content_length


def _parse_retained_request(head: bytes, body: bytes) -> _ParsedRequest:
    if type(head) is not bytes or type(body) is not bytes:
        raise _ContractViolation()
    method, route, http_version, headers, content_length = _parse_request_head(head)
    if len(body) != content_length:
        raise _ContractViolation()
    return _ParsedRequest(
        method=method,
        route=route,
        http_version=http_version,
        headers=headers,
        head=head,
        body=body,
    )


def _validate_request_headers(
    headers: tuple[tuple[str, str], ...],
    content_length: int,
    *,
    port: int,
) -> None:
    normalized = {name.casefold(): value for name, value in headers}
    names = frozenset(normalized)
    if (
        type(port) is not int
        or not 1 <= port <= 65_535
        or not _REQUEST_REQUIRED_HEADER_NAMES.issubset(names)
        or not names.issubset(_REQUEST_ALLOWED_HEADER_NAMES)
        or normalized["host"] != f"{LOOPBACK_HOST}:{port}"
        or normalized["user-agent"] != LOOPBACK_USER_AGENT
        or normalized["content-type"].casefold() != "application/json"
        or normalized["content-length"] != str(content_length)
        or (
            "accept" in normalized
            and normalized["accept"].casefold() != "text/event-stream"
        )
        or (
            "connection" in normalized
            and normalized["connection"].casefold() not in {"close", "keep-alive"}
        )
        or any(len(value.encode("ascii")) > 1_024 for value in normalized.values())
    ):
        raise _ContractViolation()


def _validate_loopback_request(
    request: _ParsedRequest,
    *,
    ordinal: int,
    contract: LoopbackScenarioContract,
    case_root: str,
    response_id: str,
    call_id: str,
    port: int,
) -> None:
    if ordinal not in (1, 2) or request.method != "POST":
        raise _ContractViolation(status=405 if request.method != "POST" else 400)
    if request.route != LOOPBACK_ROUTE or request.http_version != "HTTP/1.1":
        raise _ContractViolation()
    _validate_request_headers(request.headers, len(request.body), port=port)
    body = _parse_json_object(request.body)
    expected = (
        _first_request_body(contract, case_root)
        if ordinal == 1
        else _second_request_body(
            contract,
            response_id=response_id,
            call_id=call_id,
        )
    )
    if not _request_body_matches_phase(body, expected):
        raise _ContractViolation()


@dataclass(frozen=True)
class LoopbackExchange:
    ordinal: int
    request_head: bytes
    request_body: bytes
    response_head: bytes
    response_body: bytes
    request_sha256: str
    response_sha256: str

    def __post_init__(self) -> None:
        if self.ordinal not in (1, 2):
            raise RuntimeError("LOOPBACK_SERVER_CONTRACT_MISMATCH")
        if self.request_sha256 != sha256(
            self.request_head + self.request_body
        ).hexdigest():
            raise RuntimeError("LOOPBACK_SERVER_CONTRACT_MISMATCH")
        if self.response_sha256 != sha256(
            self.response_head + self.response_body
        ).hexdigest():
            raise RuntimeError("LOOPBACK_SERVER_CONTRACT_MISMATCH")


def _framed_field(name: str, value: bytes) -> bytes:
    return (
        name.encode("ascii")
        + b":"
        + str(len(value)).encode("ascii")
        + b"\n"
        + value
        + b"\n"
    )


def _replace_json_string_field(
    content: bytes,
    *,
    field_name: str,
    source: str,
    target: str,
) -> bytes:
    source_literal = json.dumps(
        source,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    target_literal = json.dumps(
        target,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    pattern = re.compile(
        b'("'
        + re.escape(field_name.encode("ascii"))
        + rb'"[ \t\r\n]*:[ \t\r\n]*)'
        + re.escape(source_literal)
    )
    return pattern.sub(lambda match: match.group(1) + target_literal, content)


def _normalize_request_head(
    content: bytes,
    *,
    port: int,
    raw_content_length: int,
    normalized_content_length: int,
) -> bytes:
    lines = content.split(b"\r\n")
    normalized: list[bytes] = []
    for line in lines:
        if b":" not in line:
            normalized.append(line)
            continue
        name, raw_value = line.split(b":", 1)
        try:
            folded_name = name.decode("ascii", errors="strict").casefold()
        except UnicodeDecodeError:
            normalized.append(line)
            continue
        value = raw_value.strip(b" \t")
        replacement: bytes | None = None
        if folded_name == "host" and value == f"{LOOPBACK_HOST}:{port}".encode(
            "ascii"
        ):
            replacement = b"127.0.0.1:<owned-ephemeral-port>"
        elif (
            folded_name == "content-length"
            and value == str(raw_content_length).encode("ascii")
        ):
            replacement = str(normalized_content_length).encode("ascii")
        elif folded_name in _NORMALIZABLE_DYNAMIC_REQUEST_HEADERS:
            replacement = _NORMALIZABLE_DYNAMIC_REQUEST_HEADERS[folded_name]
        normalized.append(line if replacement is None else name + b": " + replacement)
    return b"\r\n".join(normalized)


@dataclass(frozen=True)
class LoopbackTranscript:
    version: Literal["complete-suite-loopback-transcript-v1"]
    host: Literal["127.0.0.1"]
    port: int
    scenario: Literal["shell", "file_add", "file_update"]
    case_root: str
    request_count: int
    response_ids: tuple[str, str]
    call_id: str
    tool_item_id: str
    exchanges: tuple[LoopbackExchange, LoopbackExchange]

    def _project(
        self,
        field_name: str,
        value: bytes,
        *,
        normalize: bool,
        normalize_shell_item: bool,
    ) -> bytes:
        if not normalize:
            return value
        if field_name == "port":
            return b"<owned-ephemeral-port>"
        if field_name == "case_root":
            return b"<case-root>"
        if field_name == "response_id_1":
            return b"<response-id-1>"
        if field_name == "response_id_2":
            return b"<response-id-2>"
        if field_name == "call_id":
            return b"<response-call-id>"
        if field_name == "tool_item_id":
            if normalize_shell_item:
                return b"<shell-tool-item-id>"
            return value
        if field_name.endswith("_request_body"):
            value = _replace_json_string_field(
                value,
                field_name="text",
                source=f"{self.scenario}\ncase-root={self.case_root}",
                target=f"{self.scenario}\ncase-root=<case-root>",
            )
            value = _replace_json_string_field(
                value,
                field_name="previous_response_id",
                source=self.response_ids[0],
                target="<response-id-1>",
            )
            value = _replace_json_string_field(
                value,
                field_name="call_id",
                source=self.call_id,
                target="<response-call-id>",
            )
        if field_name.endswith("_response_body"):
            for response_id, placeholder in zip(
                self.response_ids,
                ("<response-id-1>", "<response-id-2>"),
            ):
                value = _replace_json_string_field(
                    value,
                    field_name="id",
                    source=response_id,
                    target=placeholder,
                )
            value = _replace_json_string_field(
                value,
                field_name="call_id",
                source=self.call_id,
                target="<response-call-id>",
            )
            if normalize_shell_item:
                for item_field in ("id", "item_id"):
                    value = _replace_json_string_field(
                        value,
                        field_name=item_field,
                        source=self.tool_item_id,
                        target="<shell-tool-item-id>",
                    )
        return value

    def _bytes(
        self,
        *,
        normalize: bool,
        normalize_shell_item: bool,
    ) -> bytes:
        if normalize_shell_item and self.scenario != "shell":
            raise RuntimeError("LOOPBACK_SERVER_CONTRACT_MISMATCH")
        fields: list[tuple[str, bytes]] = [
            ("version", self.version.encode("ascii")),
            ("host", self.host.encode("ascii")),
            ("port", str(self.port).encode("ascii")),
            ("scenario", self.scenario.encode("ascii")),
            ("case_root", self.case_root.encode("utf-8")),
            ("request_count", str(self.request_count).encode("ascii")),
            ("response_id_1", self.response_ids[0].encode("ascii")),
            ("response_id_2", self.response_ids[1].encode("ascii")),
            ("call_id", self.call_id.encode("ascii")),
            ("tool_item_id", self.tool_item_id.encode("ascii")),
        ]
        for exchange in self.exchanges:
            prefix = f"exchange_{exchange.ordinal}"
            request_body = self._project(
                f"{prefix}_request_body",
                exchange.request_body,
                normalize=normalize,
                normalize_shell_item=normalize_shell_item,
            )
            request_head = self._project(
                f"{prefix}_request_head",
                exchange.request_head,
                normalize=normalize,
                normalize_shell_item=normalize_shell_item,
            )
            if normalize:
                request_head = _normalize_request_head(
                    request_head,
                    port=self.port,
                    raw_content_length=len(exchange.request_body),
                    normalized_content_length=len(request_body),
                )
            fields.extend(
                (
                    (f"{prefix}_request_head", request_head),
                    (f"{prefix}_request_body", request_body),
                    (
                        f"{prefix}_response_head",
                        self._project(
                            f"{prefix}_response_head",
                            exchange.response_head,
                            normalize=normalize,
                            normalize_shell_item=normalize_shell_item,
                        ),
                    ),
                    (
                        f"{prefix}_response_body",
                        self._project(
                            f"{prefix}_response_body",
                            exchange.response_body,
                            normalize=normalize,
                            normalize_shell_item=normalize_shell_item,
                        ),
                    ),
                )
            )
        return b"".join(
            _framed_field(
                name,
                self._project(
                    name,
                    value,
                    normalize=normalize,
                    normalize_shell_item=normalize_shell_item,
                ),
            )
            for name, value in fields
        )

    @property
    def raw_bytes(self) -> bytes:
        return self._bytes(normalize=False, normalize_shell_item=False)

    @property
    def normalized_bytes(self) -> bytes:
        return self._bytes(normalize=True, normalize_shell_item=False)

    @property
    def shell_repeat_normalized_bytes(self) -> bytes:
        return self._bytes(normalize=True, normalize_shell_item=True)

    @property
    def raw_sha256(self) -> str:
        return sha256(self.raw_bytes).hexdigest()

    @property
    def normalized_sha256(self) -> str:
        return sha256(self.normalized_bytes).hexdigest()


def _http_response(
    status: int,
    reason: str,
    content_type: str,
    body: bytes,
) -> tuple[bytes, bytes]:
    head = (
        f"HTTP/1.1 {status} {reason}\r\n"
        f"Content-Type: {content_type}\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n"
        f"Content-Length: {len(body)}\r\n"
        "\r\n"
    ).encode("ascii")
    return head, body


def _error_response(status: int) -> tuple[bytes, bytes]:
    reason = {
        400: "Bad Request",
        405: "Method Not Allowed",
        413: "Content Too Large",
    }.get(status, "Bad Request")
    return _http_response(
        status,
        reason,
        "application/json",
        _canonical({"error": "LOOPBACK_SERVER_CONTRACT_MISMATCH"}),
    )


def _build_loopback_response(
    contract: LoopbackScenarioContract,
    *,
    ordinal: int,
    response_ids: tuple[str, str],
    call_id: str,
    tool_item_id: str,
) -> tuple[bytes, bytes]:
    if ordinal == 1:
        body = _tool_call_sse(
            contract,
            response_id=response_ids[0],
            call_id=call_id,
            item_id=tool_item_id,
        )
    elif ordinal == 2:
        body = _final_text_sse(
            contract,
            response_id=response_ids[1],
        )
    else:
        raise _ContractViolation()
    return _http_response(
        200,
        "OK",
        "text/event-stream; charset=utf-8",
        body,
    )


def _loopback_exact_response_caps() -> tuple[int, int]:
    heads: list[int] = []
    bodies: list[int] = []
    response_ids = (
        "resp_c6_" + "0" * 32,
        "resp_c6_" + "1" * 32,
    )
    call_id = "call_c6_" + "0" * 32
    item_id = "item_c6_" + "0" * 32
    for contract in _SCENARIOS.values():
        for ordinal in (1, 2):
            head, body = _build_loopback_response(
                contract,
                ordinal=ordinal,
                response_ids=response_ids,
                call_id=call_id,
                tool_item_id=item_id,
            )
            heads.append(len(head))
            bodies.append(len(body))
    return max(heads), max(bodies)


(
    _LOOPBACK_RESPONSE_HEAD_MAX_BYTES,
    _LOOPBACK_RESPONSE_BODY_MAX_BYTES,
) = _loopback_exact_response_caps()

_LOOPBACK_TRANSCRIPT_FIELD_CAPS = (
    ("version", len(b"complete-suite-loopback-transcript-v1")),
    ("host", len(LOOPBACK_HOST.encode("ascii"))),
    ("port", 5),
    ("scenario", max(len(name.encode("ascii")) for name in _SCENARIOS)),
    ("case_root", MAX_REQUEST_BYTES),
    ("request_count", 1),
    ("response_id_1", len(b"resp_c6_") + 32),
    ("response_id_2", len(b"resp_c6_") + 32),
    ("call_id", len(b"call_c6_") + 32),
    ("tool_item_id", len(b"item_c6_") + 32),
    ("exchange_1_request_head", MAX_HEADER_BYTES),
    ("exchange_1_request_body", MAX_REQUEST_BYTES),
    ("exchange_1_response_head", _LOOPBACK_RESPONSE_HEAD_MAX_BYTES),
    ("exchange_1_response_body", _LOOPBACK_RESPONSE_BODY_MAX_BYTES),
    ("exchange_2_request_head", MAX_HEADER_BYTES),
    ("exchange_2_request_body", MAX_REQUEST_BYTES),
    ("exchange_2_response_head", _LOOPBACK_RESPONSE_HEAD_MAX_BYTES),
    ("exchange_2_response_body", _LOOPBACK_RESPONSE_BODY_MAX_BYTES),
)

LOOPBACK_TRANSCRIPT_MAX_BYTES = sum(
    len(name.encode("ascii"))
    + 1
    + len(str(field_cap).encode("ascii"))
    + 1
    + field_cap
    + 1
    for name, field_cap in _LOOPBACK_TRANSCRIPT_FIELD_CAPS
)

_RESPONSE_ID_BYTES = re.compile(rb"resp_c6_[0-9a-f]{32}\Z")
_CALL_ID_BYTES = re.compile(rb"call_c6_[0-9a-f]{32}\Z")
_ITEM_ID_BYTES = re.compile(rb"item_c6_[0-9a-f]{32}\Z")


def _decode_loopback_transcript_fields(content: bytes) -> dict[str, bytes]:
    if (
        type(content) is not bytes
        or not content
        or len(content) > LOOPBACK_TRANSCRIPT_MAX_BYTES
    ):
        raise _ContractViolation()
    values: dict[str, bytes] = {}
    offset = 0
    for name, field_cap in _LOOPBACK_TRANSCRIPT_FIELD_CAPS:
        prefix = name.encode("ascii") + b":"
        if not content.startswith(prefix, offset):
            raise _ContractViolation()
        offset += len(prefix)
        max_length_digits = len(str(field_cap))
        newline = content.find(b"\n", offset, offset + max_length_digits + 1)
        if newline < 0:
            raise _ContractViolation()
        length_text = content[offset:newline]
        if (
            not length_text
            or (len(length_text) > 1 and length_text.startswith(b"0"))
            or any(character < 48 or character > 57 for character in length_text)
        ):
            raise _ContractViolation()
        value_length = int(length_text)
        if value_length > field_cap:
            raise _ContractViolation()
        value_start = newline + 1
        value_end = value_start + value_length
        if value_end >= len(content) or content[value_end : value_end + 1] != b"\n":
            raise _ContractViolation()
        values[name] = content[value_start:value_end]
        offset = value_end + 1
    if offset != len(content):
        raise _ContractViolation()
    return values


def _decode_canonical_ascii_integer(value: bytes, *, maximum: int) -> int:
    if (
        not value
        or len(value) > len(str(maximum))
        or (len(value) > 1 and value.startswith(b"0"))
        or any(character < 48 or character > 57 for character in value)
    ):
        raise _ContractViolation()
    decoded = int(value)
    if not 1 <= decoded <= maximum:
        raise _ContractViolation()
    return decoded


def _decode_loopback_transcript(content: bytes) -> LoopbackTranscript:
    fields = _decode_loopback_transcript_fields(content)
    if fields["version"] != b"complete-suite-loopback-transcript-v1":
        raise _ContractViolation()
    if fields["host"] != LOOPBACK_HOST.encode("ascii"):
        raise _ContractViolation()
    port = _decode_canonical_ascii_integer(fields["port"], maximum=65_535)
    try:
        scenario = fields["scenario"].decode("ascii", errors="strict")
        case_root = fields["case_root"].decode("utf-8", errors="strict")
        response_ids = (
            fields["response_id_1"].decode("ascii", errors="strict"),
            fields["response_id_2"].decode("ascii", errors="strict"),
        )
        call_id = fields["call_id"].decode("ascii", errors="strict")
        tool_item_id = fields["tool_item_id"].decode("ascii", errors="strict")
    except UnicodeDecodeError as exc:
        raise _ContractViolation() from exc
    if (
        scenario not in _SCENARIOS
        or fields["request_count"] != b"2"
        or not _valid_case_root(case_root)
        or _RESPONSE_ID_BYTES.fullmatch(fields["response_id_1"]) is None
        or _RESPONSE_ID_BYTES.fullmatch(fields["response_id_2"]) is None
        or response_ids[0] == response_ids[1]
        or _CALL_ID_BYTES.fullmatch(fields["call_id"]) is None
        or _ITEM_ID_BYTES.fullmatch(fields["tool_item_id"]) is None
    ):
        raise _ContractViolation()
    contract = scenario_contract(scenario)
    exchanges: list[LoopbackExchange] = []
    for ordinal in (1, 2):
        prefix = f"exchange_{ordinal}"
        request_head = fields[f"{prefix}_request_head"]
        request_body = fields[f"{prefix}_request_body"]
        response_head = fields[f"{prefix}_response_head"]
        response_body = fields[f"{prefix}_response_body"]
        request = _parse_retained_request(request_head, request_body)
        _validate_loopback_request(
            request,
            ordinal=ordinal,
            contract=contract,
            case_root=case_root,
            response_id=response_ids[0],
            call_id=call_id,
            port=port,
        )
        expected_head, expected_body = _build_loopback_response(
            contract,
            ordinal=ordinal,
            response_ids=response_ids,
            call_id=call_id,
            tool_item_id=tool_item_id,
        )
        if response_head != expected_head or response_body != expected_body:
            raise _ContractViolation()
        exchanges.append(
            LoopbackExchange(
                ordinal=ordinal,
                request_head=request_head,
                request_body=request_body,
                response_head=response_head,
                response_body=response_body,
                request_sha256=sha256(request_head + request_body).hexdigest(),
                response_sha256=sha256(response_head + response_body).hexdigest(),
            )
        )
    transcript = LoopbackTranscript(
        version="complete-suite-loopback-transcript-v1",
        host=LOOPBACK_HOST,
        port=port,
        scenario=scenario,
        case_root=case_root,
        request_count=2,
        response_ids=response_ids,
        call_id=call_id,
        tool_item_id=tool_item_id,
        exchanges=(exchanges[0], exchanges[1]),
    )
    if transcript.raw_bytes != content:
        raise _ContractViolation()
    return transcript


def decode_loopback_transcript(content: bytes) -> LoopbackTranscript:
    try:
        return _decode_loopback_transcript(content)
    except _ContractViolation:
        raise RuntimeError("LOOPBACK_SERVER_CONTRACT_MISMATCH") from None


class _OwnedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    address_family = socket.AF_INET
    allow_reuse_address = False
    daemon_threads = True
    block_on_close = True

    owner: LoopbackPreflightServer


class _LoopbackRequestHandler(socketserver.StreamRequestHandler):
    timeout = 5.0

    def handle(self) -> None:
        owner = self.server.owner
        try:
            request = self._read_request()
            head, body = owner._dispatch(request)
        except _ContractViolation as exc:
            owner._record_failure()
            head, body = _error_response(exc.status)
        try:
            self.request.sendall(head + body)
        except OSError:
            owner._record_failure()

    def _readline(self, remaining: int) -> bytes:
        if remaining <= 0:
            raise _ContractViolation()
        line = self.rfile.readline(min(MAX_HEADER_LINE_BYTES + 1, remaining + 1))
        if not line or len(line) > MAX_HEADER_LINE_BYTES or not line.endswith(
            b"\r\n"
        ):
            raise _ContractViolation()
        return line

    def _read_request(self) -> _ParsedRequest:
        total = 0
        request_line = self._readline(MAX_HEADER_BYTES)
        total += len(request_line)
        raw_lines = [request_line]
        while True:
            line = self._readline(MAX_HEADER_BYTES - total)
            total += len(line)
            raw_lines.append(line)
            if line == b"\r\n":
                break
        head = b"".join(raw_lines)
        method, route, http_version, headers, content_length = _parse_request_head(
            head
        )
        body = self.rfile.read(content_length)
        if len(body) != content_length:
            raise _ContractViolation()
        return _ParsedRequest(
            method=method,
            route=route,
            http_version=http_version,
            headers=headers,
            head=head,
            body=body,
        )


class LoopbackPreflightServer:
    def __init__(self, *, scenario: str, case_root: str) -> None:
        contract = scenario_contract(scenario)
        if not _valid_case_root(case_root):
            raise RuntimeError("LOOPBACK_SERVER_CONTRACT_MISMATCH")
        self._scenario = contract
        self._case_root = case_root
        self._lock = threading.Lock()
        self._server: _OwnedTCPServer | None = None
        self._thread: threading.Thread | None = None
        self._port: int | None = None
        self._request_count = 0
        self._failures = 0
        self._exchanges: list[LoopbackExchange] = []
        self._response_ids = (
            "resp_c6_" + uuid4().hex,
            "resp_c6_" + uuid4().hex,
        )
        self._call_id = "call_c6_" + uuid4().hex
        self._tool_item_id = "item_c6_" + uuid4().hex

    @property
    def host(self) -> Literal["127.0.0.1"]:
        return LOOPBACK_HOST

    @property
    def port(self) -> int:
        if self._port is None:
            raise RuntimeError("LOOPBACK_SERVER_CONTRACT_MISMATCH")
        return self._port

    @property
    def responses_url(self) -> str:
        return f"http://{LOOPBACK_HOST}:{self.port}{LOOPBACK_ROUTE}"

    def start(self) -> LoopbackPreflightServer:
        if self._server is not None or self._thread is not None:
            raise RuntimeError("LOOPBACK_SERVER_CONTRACT_MISMATCH")
        server = _OwnedTCPServer(
            (LOOPBACK_HOST, 0),
            _LoopbackRequestHandler,
            bind_and_activate=False,
        )
        server.owner = self
        try:
            server.server_bind()
            server.server_activate()
            host, port = server.server_address
            if host != LOOPBACK_HOST or not (0 < port <= 65_535):
                raise RuntimeError("LOOPBACK_SERVER_CONTRACT_MISMATCH")
            thread = threading.Thread(
                target=server.serve_forever,
                kwargs={"poll_interval": 0.05},
                name="campaign6-owned-loopback-server",
                daemon=True,
            )
            self._server = server
            self._thread = thread
            self._port = port
            thread.start()
        except BaseException:
            server.server_close()
            raise
        return self

    def close(self) -> None:
        server = self._server
        thread = self._thread
        if server is None or thread is None:
            return
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)
        if thread.is_alive():
            raise RuntimeError("LOOPBACK_SERVER_CONTRACT_MISMATCH")
        self._server = None
        self._thread = None

    def __enter__(self) -> LoopbackPreflightServer:
        return self.start()

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def _record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            self._request_count += 1

    def _validate_headers(
        self,
        headers: tuple[tuple[str, str], ...],
        content_length: int,
    ) -> None:
        _validate_request_headers(headers, content_length, port=self.port)

    def _first_body(self) -> dict[str, object]:
        return _first_request_body(self._scenario, self._case_root)

    def _second_body(self) -> dict[str, object]:
        return _second_request_body(
            self._scenario,
            response_id=self._response_ids[0],
            call_id=self._call_id,
        )

    def _validate_request(self, request: _ParsedRequest, ordinal: int) -> None:
        _validate_loopback_request(
            request,
            ordinal=ordinal,
            contract=self._scenario,
            case_root=self._case_root,
            response_id=self._response_ids[0],
            call_id=self._call_id,
            port=self.port,
        )

    def _dispatch(self, request: _ParsedRequest) -> tuple[bytes, bytes]:
        with self._lock:
            if self._failures or self._request_count >= 2:
                raise _ContractViolation()
            ordinal = self._request_count + 1
            self._validate_request(request, ordinal)
            response_head, response_body = _build_loopback_response(
                self._scenario,
                ordinal=ordinal,
                response_ids=self._response_ids,
                call_id=self._call_id,
                tool_item_id=self._tool_item_id,
            )
            exchange = LoopbackExchange(
                ordinal=ordinal,
                request_head=request.head,
                request_body=request.body,
                response_head=response_head,
                response_body=response_body,
                request_sha256=sha256(
                    request.head + request.body
                ).hexdigest(),
                response_sha256=sha256(
                    response_head + response_body
                ).hexdigest(),
            )
            self._exchanges.append(exchange)
            self._request_count += 1
            return response_head, response_body

    def assert_complete(self) -> LoopbackTranscript:
        with self._lock:
            if (
                self._port is None
                or self._failures != 0
                or self._request_count != 2
                or len(self._exchanges) != 2
                or tuple(exchange.ordinal for exchange in self._exchanges)
                != (1, 2)
            ):
                raise RuntimeError("LOOPBACK_SERVER_CONTRACT_MISMATCH")
            return LoopbackTranscript(
                version="complete-suite-loopback-transcript-v1",
                host=LOOPBACK_HOST,
                port=self._port,
                scenario=self._scenario.name,
                case_root=self._case_root,
                request_count=self._request_count,
                response_ids=self._response_ids,
                call_id=self._call_id,
                tool_item_id=self._tool_item_id,
                exchanges=tuple(self._exchanges),
            )
