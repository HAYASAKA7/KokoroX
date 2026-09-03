from __future__ import annotations

from hashlib import sha256
import importlib
import io
import json
from pathlib import Path

import pytest


def _server_module():
    return importlib.import_module("complete_suite_client_preflight_server")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _owned_server(module: object, case_root: Path) -> object:
    server = module.LoopbackPreflightServer(
        scenario="shell",
        case_root=str(case_root),
    )
    server._port = 43123
    return server


def _headers(port: int, body: bytes) -> tuple[tuple[str, str], ...]:
    return (
        ("Host", f"127.0.0.1:{port}"),
        ("User-Agent", "kokoroarc-campaign6-client-preflight-v1"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
    )


def _request(module: object, server: object, body: dict[str, object]) -> object:
    encoded = _canonical(body)
    return module._ParsedRequest(
        method="POST",
        route="/v1/responses",
        http_version="HTTP/1.1",
        headers=_headers(server.port, encoded),
        head=b"",
        body=encoded,
    )


def _supported_optional_fields() -> dict[str, object]:
    return {
        "client_metadata": {"campaign": "six", "probe": "loopback"},
        "codex_output_schema": {
            "additionalProperties": False,
            "properties": {"result": {"type": "string"}},
            "required": ["result"],
            "type": "object",
        },
        "include": ["reasoning.encrypted_content"],
        "instructions": "Use only the advertised bounded tools.",
        "prompt_cache_key": "campaign6-loopback",
        "reasoning": {"effort": "low", "summary": "auto"},
        "service_tier": "default",
        "stream_options": {"include_obfuscation": False},
    }


@pytest.mark.parametrize("ordinal", (1, 2))
def test_request_contract_accepts_typed_supported_optional_fields(
    tmp_path: Path,
    ordinal: int,
) -> None:
    module = _server_module()
    case_root = tmp_path / "case"
    case_root.mkdir()
    server = _owned_server(module, case_root)
    body = server._first_body() if ordinal == 1 else server._second_body()
    body.update(_supported_optional_fields())

    server._validate_request(_request(module, server, body), ordinal)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("instructions", True),
        ("reasoning", []),
        ("reasoning", {"effort": 1}),
        ("reasoning", {"unknown": "low"}),
        ("stream_options", {"include_obfuscation": 0}),
        ("stream_options", {"unknown": False}),
        ("include", ["unknown.include"]),
        ("include", [{}]),
        ("service_tier", 1),
        ("service_tier", "unknown-tier"),
        ("prompt_cache_key", None),
        ("client_metadata", {"campaign": 6}),
        ("codex_output_schema", []),
    ),
)
def test_request_contract_rejects_wrong_optional_field_types(
    tmp_path: Path,
    field_name: str,
    invalid_value: object,
) -> None:
    module = _server_module()
    case_root = tmp_path / "case"
    case_root.mkdir()
    server = _owned_server(module, case_root)
    body = server._first_body()
    body[field_name] = invalid_value

    with pytest.raises(module._ContractViolation):
        server._validate_request(_request(module, server, body), 1)


@pytest.mark.parametrize("mutation", ("unknown", "first_previous", "second_missing"))
def test_request_contract_rejects_unknown_or_phase_misused_fields(
    tmp_path: Path,
    mutation: str,
) -> None:
    module = _server_module()
    case_root = tmp_path / "case"
    case_root.mkdir()
    server = _owned_server(module, case_root)
    if mutation == "second_missing":
        ordinal = 2
        body = server._second_body()
        del body["previous_response_id"]
    else:
        ordinal = 1
        body = server._first_body()
        key = "unknown_field" if mutation == "unknown" else "previous_response_id"
        body[key] = "resp_c6_not_allowed_in_first_phase"

    with pytest.raises(module._ContractViolation):
        server._validate_request(_request(module, server, body), ordinal)


def test_request_contract_reports_unresolved_native_tool_schema_provenance() -> None:
    module = _server_module()

    assert module.NATIVE_TOOL_SCHEMA_PROVENANCE == (
        "unverified-fail-closed-static-request-tool-schema-v1"
    )
    assert module.loopback_contract_manifest()["native_tool_schema_provenance"] == (
        module.NATIVE_TOOL_SCHEMA_PROVENANCE
    )


def test_http_parser_accepts_bounded_optional_whitespace_after_colon() -> None:
    module = _server_module()
    raw = (
        b"POST /v1/responses HTTP/1.1\r\n"
        b"Host:127.0.0.1:43123\r\n"
        b"User-Agent:\tkokoroarc-campaign6-client-preflight-v1\t\r\n"
        b"Content-Type:  application/json \r\n"
        b"Content-Length:0\r\n"
        b"\r\n"
    )
    handler = object.__new__(module._LoopbackRequestHandler)
    handler.rfile = io.BytesIO(raw)

    parsed = handler._read_request()

    assert parsed.headers == (
        ("Host", "127.0.0.1:43123"),
        ("User-Agent", "kokoroarc-campaign6-client-preflight-v1"),
        ("Content-Type", "application/json"),
        ("Content-Length", "0"),
    )


@pytest.mark.parametrize(
    "forbidden_name",
    ("Authorization", "Cookie", "Proxy-Authorization", "Transfer-Encoding"),
)
def test_header_contract_rejects_security_sensitive_transport_headers(
    tmp_path: Path,
    forbidden_name: str,
) -> None:
    module = _server_module()
    case_root = tmp_path / "case"
    case_root.mkdir()
    server = _owned_server(module, case_root)
    headers = (*_headers(server.port, b""), (forbidden_name, "forbidden"))

    with pytest.raises(module._ContractViolation):
        server._validate_headers(headers, 0)


def _exchange(
    module: object,
    *,
    ordinal: int,
    request_head: bytes,
    request_body: bytes,
) -> object:
    response_head = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n"
    response_body = b"{}"
    return module.LoopbackExchange(
        ordinal=ordinal,
        request_head=request_head,
        request_body=request_body,
        response_head=response_head,
        response_body=response_body,
        request_sha256=sha256(request_head + request_body).hexdigest(),
        response_sha256=sha256(response_head + response_body).hexdigest(),
    )


def _transcript(
    module: object,
    *,
    root: str,
    port: int,
    dynamic_suffix: str,
    attestation: str,
) -> object:
    contract = module.scenario_contract("file_add")
    first_body = _canonical(module._first_request_body(contract, root))
    second_body = _canonical(
        module._second_request_body(
            contract,
            response_id="resp_c6_fixed_one",
            call_id="call_c6_fixed",
        )
    )

    def head(body: bytes) -> bytes:
        return (
            b"POST /v1/responses HTTP/1.1\r\n"
            + f"Host: 127.0.0.1:{port}\r\n".encode("ascii")
            + f"Content-Length: {len(body)}\r\n".encode("ascii")
            + f"X-Client-Request-Id: request-{dynamic_suffix}\r\n".encode("ascii")
            + f"traceparent: trace-{dynamic_suffix}\r\n".encode("ascii")
            + f"tracestate: state-{dynamic_suffix}\r\n".encode("ascii")
            + f"X-OAI-Attestation: {attestation}\r\n".encode("ascii")
            + b"\r\n"
        )

    return module.LoopbackTranscript(
        version="complete-suite-loopback-transcript-v1",
        host="127.0.0.1",
        port=port,
        scenario="file_add",
        case_root=root,
        request_count=2,
        response_ids=("resp_c6_fixed_one", "resp_c6_fixed_two"),
        call_id="call_c6_fixed",
        tool_item_id="item_c6_fixed",
        exchanges=(
            _exchange(
                module,
                ordinal=1,
                request_head=head(first_body),
                request_body=first_body,
            ),
            _exchange(
                module,
                ordinal=2,
                request_head=head(second_body),
                request_body=second_body,
            ),
        ),
    )


def test_transcript_normalizes_derived_length_and_allowlisted_dynamic_headers() -> None:
    module = _server_module()
    short = _transcript(
        module,
        root=r"D:\c6\short",
        port=43123,
        dynamic_suffix="one",
        attestation="security-binding",
    )
    long = _transcript(
        module,
        root=r"D:\campaign-six\a-much-longer-case-root",
        port=54321,
        dynamic_suffix="two",
        attestation="security-binding",
    )

    assert short.normalized_bytes == long.normalized_bytes
    normalized_body = _canonical(
        module._first_request_body(
            module.scenario_contract("file_add"),
            "<case-root>",
        )
    )
    assert f"Content-Length: {len(normalized_body)}\r\n".encode("ascii") in (
        short.normalized_bytes
    )
    for token in (
        b"<x-client-request-id>",
        b"<traceparent>",
        b"<tracestate>",
    ):
        assert token in short.normalized_bytes
    assert b"request-one" not in short.normalized_bytes
    assert b"trace-one" not in short.normalized_bytes
    assert b"state-one" not in short.normalized_bytes
    assert b"security-binding" in short.normalized_bytes


def test_transcript_retains_nonallowlisted_security_header_values() -> None:
    module = _server_module()
    first = _transcript(
        module,
        root=r"D:\c6\case",
        port=43123,
        dynamic_suffix="one",
        attestation="attestation-one",
    )
    second = _transcript(
        module,
        root=r"D:\c6\case",
        port=43123,
        dynamic_suffix="two",
        attestation="attestation-two",
    )

    assert first.normalized_bytes != second.normalized_bytes
    assert b"attestation-one" in first.normalized_bytes
    assert b"attestation-two" in second.normalized_bytes


def _decoder_request_head(
    body: bytes,
    *,
    port: int,
    extra_headers: tuple[tuple[str, str], ...] = (),
) -> bytes:
    headers = (
        ("Host", f"127.0.0.1:{port}"),
        ("User-Agent", "kokoroarc-campaign6-client-preflight-v1"),
        ("Accept", "text/event-stream"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
        ("Connection", "close"),
        *extra_headers,
    )
    return (
        b"POST /v1/responses HTTP/1.1\r\n"
        + b"".join(
            f"{name}: {value}\r\n".encode("ascii") for name, value in headers
        )
        + b"\r\n"
    )


def _decoder_transcript(
    module: object,
    *,
    scenario: str,
    case_root: str,
    first_optional: dict[str, object] | None = None,
    second_optional: dict[str, object] | None = None,
) -> object:
    port = 43123
    response_ids = (
        "resp_c6_" + "1" * 32,
        "resp_c6_" + "2" * 32,
    )
    call_id = "call_c6_" + "3" * 32
    tool_item_id = "item_c6_" + "4" * 32
    contract = module.scenario_contract(scenario)
    first_value = module._first_request_body(contract, case_root)
    second_value = module._second_request_body(
        contract,
        response_id=response_ids[0],
        call_id=call_id,
    )
    if first_optional:
        first_value.update(first_optional)
    if second_optional:
        second_value.update(second_optional)
    first_body = _canonical(first_value)
    second_body = _canonical(second_value)
    first_response_body = module._tool_call_sse(
        contract,
        response_id=response_ids[0],
        call_id=call_id,
        item_id=tool_item_id,
    )
    second_response_body = module._final_text_sse(
        contract,
        response_id=response_ids[1],
    )
    first_response_head, first_response_body = module._http_response(
        200,
        "OK",
        "text/event-stream; charset=utf-8",
        first_response_body,
    )
    second_response_head, second_response_body = module._http_response(
        200,
        "OK",
        "text/event-stream; charset=utf-8",
        second_response_body,
    )

    def exchange(
        ordinal: int,
        request_body: bytes,
        response_head: bytes,
        response_body: bytes,
    ) -> object:
        request_head = _decoder_request_head(request_body, port=port)
        return module.LoopbackExchange(
            ordinal=ordinal,
            request_head=request_head,
            request_body=request_body,
            response_head=response_head,
            response_body=response_body,
            request_sha256=sha256(request_head + request_body).hexdigest(),
            response_sha256=sha256(response_head + response_body).hexdigest(),
        )

    return module.LoopbackTranscript(
        version="complete-suite-loopback-transcript-v1",
        host="127.0.0.1",
        port=port,
        scenario=scenario,
        case_root=case_root,
        request_count=2,
        response_ids=response_ids,
        call_id=call_id,
        tool_item_id=tool_item_id,
        exchanges=(
            exchange(1, first_body, first_response_head, first_response_body),
            exchange(2, second_body, second_response_head, second_response_body),
        ),
    )


def _split_transcript_fields(content: bytes) -> list[tuple[str, bytes]]:
    fields: list[tuple[str, bytes]] = []
    offset = 0
    while offset < len(content):
        colon = content.index(b":", offset)
        newline = content.index(b"\n", colon + 1)
        name = content[offset:colon].decode("ascii")
        size = int(content[colon + 1 : newline])
        value_start = newline + 1
        value_end = value_start + size
        assert content[value_end : value_end + 1] == b"\n"
        fields.append((name, content[value_start:value_end]))
        offset = value_end + 1
    return fields


def _join_transcript_fields(fields: list[tuple[str, bytes]]) -> bytes:
    return b"".join(
        name.encode("ascii")
        + b":"
        + str(len(value)).encode("ascii")
        + b"\n"
        + value
        + b"\n"
        for name, value in fields
    )


def _replace_transcript_field(content: bytes, name: str, value: bytes) -> bytes:
    fields = _split_transcript_fields(content)
    matches = [index for index, item in enumerate(fields) if item[0] == name]
    assert len(matches) == 1
    fields[matches[0]] = (name, value)
    return _join_transcript_fields(fields)


def _replace_decoder_request_body(
    content: bytes,
    *,
    ordinal: int,
    value: dict[str, object],
) -> bytes:
    return _replace_decoder_request_body_bytes(
        content,
        ordinal=ordinal,
        body=_canonical(value),
    )


def _replace_decoder_request_body_bytes(
    content: bytes,
    *,
    ordinal: int,
    body: bytes,
) -> bytes:
    body_name = f"exchange_{ordinal}_request_body"
    head_name = f"exchange_{ordinal}_request_head"
    fields = dict(_split_transcript_fields(content))
    head_lines = fields[head_name].split(b"\r\n")
    head_lines = [
        (
            b"Content-Length: " + str(len(body)).encode("ascii")
            if line.lower().startswith(b"content-length:")
            else line
        )
        for line in head_lines
    ]
    content = _replace_transcript_field(
        content,
        head_name,
        b"\r\n".join(head_lines),
    )
    return _replace_transcript_field(content, body_name, body)


def _assert_decoder_rejects(module: object, content: object) -> None:
    with pytest.raises(
        RuntimeError,
        match=r"^LOOPBACK_SERVER_CONTRACT_MISMATCH$",
    ) as captured:
        module.decode_loopback_transcript(content)
    assert type(captured.value) is RuntimeError
    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__ is True


def test_decode_loopback_transcript_translates_only_contract_violations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _server_module()

    def contract_failure(_content: bytes) -> object:
        raise module._ContractViolation()

    monkeypatch.setattr(module, "_decode_loopback_transcript", contract_failure)

    _assert_decoder_rejects(module, b"synthetic-contract-failure")


@pytest.mark.parametrize(
    "failure_type",
    (
        AssertionError,
        TypeError,
        MemoryError,
        RuntimeError,
        KeyboardInterrupt,
        SystemExit,
    ),
)
def test_decode_loopback_transcript_propagates_noncontract_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure_type: type[BaseException],
) -> None:
    module = _server_module()
    failure = failure_type("synthetic-noncontract-failure")

    def noncontract_failure(_content: bytes) -> object:
        raise failure

    monkeypatch.setattr(module, "_decode_loopback_transcript", noncontract_failure)

    with pytest.raises(failure_type, match=r"^synthetic-noncontract-failure$") as captured:
        module.decode_loopback_transcript(b"synthetic-noncontract-failure")

    assert captured.value is failure


@pytest.mark.parametrize("ordinal", (1, 2))
def test_build_loopback_response_preserves_exact_owned_bytes(
    tmp_path: Path,
    ordinal: int,
) -> None:
    module = _server_module()
    supplied = _decoder_transcript(
        module,
        scenario="shell",
        case_root=str(tmp_path / "case"),
    )

    actual = module._build_loopback_response(
        module.scenario_contract("shell"),
        ordinal=ordinal,
        response_ids=supplied.response_ids,
        call_id=supplied.call_id,
        tool_item_id=supplied.tool_item_id,
    )

    expected = supplied.exchanges[ordinal - 1]
    assert actual == (expected.response_head, expected.response_body)


def test_build_loopback_response_rejects_invalid_ordinal() -> None:
    module = _server_module()

    with pytest.raises(module._ContractViolation):
        module._build_loopback_response(
            module.scenario_contract("shell"),
            ordinal=3,
            response_ids=(
                "resp_c6_" + "1" * 32,
                "resp_c6_" + "2" * 32,
            ),
            call_id="call_c6_" + "3" * 32,
            tool_item_id="item_c6_" + "4" * 32,
        )


def test_live_dispatch_transcript_decodes_without_process_or_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _server_module()
    server = _owned_server(module, tmp_path / "case")

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("integration attempted a socket or server-start action")

    monkeypatch.setattr(module.LoopbackPreflightServer, "start", forbidden)
    monkeypatch.setattr(module.socket, "socket", forbidden)

    first_body = _canonical(server._first_body())
    first_request = module._parse_retained_request(
        _decoder_request_head(first_body, port=server.port),
        first_body,
    )
    server._dispatch(first_request)

    second_body = _canonical(server._second_body())
    second_request = module._parse_retained_request(
        _decoder_request_head(second_body, port=server.port),
        second_body,
    )
    server._dispatch(second_request)

    transcript = server.assert_complete()
    decoded = module.decode_loopback_transcript(transcript.raw_bytes)

    assert decoded == transcript
    assert decoded.raw_bytes == transcript.raw_bytes
    assert decoded.port == server.port
    assert decoded.scenario == "shell"
    assert tuple(exchange.ordinal for exchange in decoded.exchanges) == (1, 2)


def test_loopback_transcript_has_exact_versioned_field_order(tmp_path: Path) -> None:
    module = _server_module()
    transcript = _decoder_transcript(
        module,
        scenario="shell",
        case_root=str(tmp_path / "case"),
    )

    field_names = tuple(
        name for name, _value in _split_transcript_fields(transcript.raw_bytes)
    )
    assert field_names == (
        "version",
        "host",
        "port",
        "scenario",
        "case_root",
        "request_count",
        "response_id_1",
        "response_id_2",
        "call_id",
        "tool_item_id",
        "exchange_1_request_head",
        "exchange_1_request_body",
        "exchange_1_response_head",
        "exchange_1_response_body",
        "exchange_2_request_head",
        "exchange_2_request_body",
        "exchange_2_response_head",
        "exchange_2_response_body",
    )


@pytest.mark.parametrize("scenario", ("shell", "file_add", "file_update"))
def test_decode_loopback_transcript_round_trips_owned_raw_bytes_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    module = _server_module()
    supplied = _decoder_transcript(
        module,
        scenario=scenario,
        case_root=str(tmp_path / f"case-{scenario}"),
    )

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("decoder attempted an online or server-start action")

    monkeypatch.setattr(module.LoopbackPreflightServer, "start", forbidden)
    monkeypatch.setattr(module.socket, "socket", forbidden)
    decoded = module.decode_loopback_transcript(supplied.raw_bytes)

    assert decoded == supplied
    assert decoded is not supplied
    assert decoded.exchanges is not supplied.exchanges
    assert all(
        actual is not expected
        for actual, expected in zip(decoded.exchanges, supplied.exchanges, strict=True)
    )
    assert decoded.raw_bytes == supplied.raw_bytes


@pytest.mark.parametrize(
    "mutation",
    (
        "noncanonical-length",
        "reordered",
        "missing",
        "duplicate",
        "unexpected",
        "off-by-one",
        "cr-framing",
        "premature-eof",
        "trailing",
    ),
)
def test_decode_loopback_transcript_rejects_malformed_framing(
    tmp_path: Path,
    mutation: str,
) -> None:
    module = _server_module()
    raw = _decoder_transcript(
        module,
        scenario="shell",
        case_root=str(tmp_path / "case"),
    ).raw_bytes
    fields = _split_transcript_fields(raw)
    if mutation == "noncanonical-length":
        malformed = raw.replace(b"version:37\n", b"version:037\n", 1)
    elif mutation == "reordered":
        malformed = _join_transcript_fields([fields[1], fields[0], *fields[2:]])
    elif mutation == "missing":
        malformed = _join_transcript_fields([*fields[:4], *fields[5:]])
    elif mutation == "duplicate":
        malformed = _join_transcript_fields([fields[0], fields[0], *fields[1:]])
    elif mutation == "unexpected":
        malformed = _join_transcript_fields(
            [("unexpected", fields[0][1]), *fields[1:]]
        )
    elif mutation == "off-by-one":
        malformed = raw.replace(b"version:37\n", b"version:38\n", 1)
    elif mutation == "cr-framing":
        malformed = raw.replace(b"version:37\n", b"version:37\r\n", 1)
    elif mutation == "premature-eof":
        malformed = raw[:-1]
    else:
        assert mutation == "trailing"
        malformed = raw + b"\x00"

    _assert_decoder_rejects(module, malformed)


@pytest.mark.parametrize(
    "invalid_length",
    (b"+37", b" 37", b"37 ", "３７".encode("utf-8"), b"12345678"),
)
def test_decode_loopback_transcript_rejects_noncanonical_length_text(
    tmp_path: Path,
    invalid_length: bytes,
) -> None:
    module = _server_module()
    raw = _decoder_transcript(
        module,
        scenario="shell",
        case_root=str(tmp_path / "case"),
    ).raw_bytes

    _assert_decoder_rejects(
        module,
        raw.replace(b"version:37\n", b"version:" + invalid_length + b"\n", 1),
    )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("version", b"complete-suite-loopback-transcript-v2"),
        ("host", b"localhost"),
        ("port", b"01"),
        ("port", b"+1"),
        ("port", b"65536"),
        ("scenario", b"unknown"),
        ("request_count", b"02"),
        ("request_count", b"3"),
        ("case_root", b""),
        ("case_root", b"relative\\case"),
        ("case_root", b"D:\\case\\..\\other"),
        ("case_root", b"D:\\case\x00bad"),
        ("case_root", b"D:\\case\nbad"),
        ("case_root", b"\xff"),
        ("response_id_1", b"resp_c6_" + b"A" * 32),
        ("response_id_2", b"resp_c6_" + b"2" * 31),
        ("call_id", b"call_c6_" + b"g" * 32),
        ("tool_item_id", b"item_c6_" + b"4" * 33),
    ),
)
def test_decode_loopback_transcript_rejects_invalid_scalars(
    tmp_path: Path,
    field_name: str,
    invalid_value: bytes,
) -> None:
    module = _server_module()
    raw = _decoder_transcript(
        module,
        scenario="shell",
        case_root=str(tmp_path / "case"),
    ).raw_bytes

    _assert_decoder_rejects(
        module,
        _replace_transcript_field(raw, field_name, invalid_value),
    )


def test_decode_loopback_transcript_rejects_equal_response_ids(
    tmp_path: Path,
) -> None:
    module = _server_module()
    raw = _decoder_transcript(
        module,
        scenario="shell",
        case_root=str(tmp_path / "case"),
    ).raw_bytes
    response_id = dict(_split_transcript_fields(raw))["response_id_1"]

    _assert_decoder_rejects(
        module,
        _replace_transcript_field(raw, "response_id_2", response_id),
    )


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    (
        ("response_id_1", b"resp_c6_" + b"5" * 32),
        ("call_id", b"call_c6_" + b"6" * 32),
        ("tool_item_id", b"item_c6_" + b"7" * 32),
    ),
)
def test_decode_loopback_transcript_rejects_valid_but_unbound_scalar_ids(
    tmp_path: Path,
    field_name: str,
    replacement: bytes,
) -> None:
    module = _server_module()
    raw = _decoder_transcript(
        module,
        scenario="shell",
        case_root=str(tmp_path / "case"),
    ).raw_bytes
    grammar = {
        "response_id_1": module._RESPONSE_ID_BYTES,
        "call_id": module._CALL_ID_BYTES,
        "tool_item_id": module._ITEM_ID_BYTES,
    }[field_name]
    assert grammar.fullmatch(replacement) is not None

    _assert_decoder_rejects(
        module,
        _replace_transcript_field(raw, field_name, replacement),
    )


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    (
        ("previous_response_id", "resp_c6_" + "8" * 32),
        ("call_id", "call_c6_" + "9" * 32),
    ),
)
def test_decode_loopback_transcript_rejects_valid_unbound_second_request_ids(
    tmp_path: Path,
    field_name: str,
    replacement: str,
) -> None:
    module = _server_module()
    raw = _decoder_transcript(
        module,
        scenario="shell",
        case_root=str(tmp_path / "case"),
    ).raw_bytes
    body = json.loads(
        dict(_split_transcript_fields(raw))["exchange_2_request_body"]
    )
    body[field_name] = replacement
    grammar = (
        module._RESPONSE_ID_BYTES
        if field_name == "previous_response_id"
        else module._CALL_ID_BYTES
    )
    assert grammar.fullmatch(replacement.encode("ascii")) is not None

    _assert_decoder_rejects(
        module,
        _replace_decoder_request_body(raw, ordinal=2, value=body),
    )


@pytest.mark.parametrize(
    "mutation",
    ("method", "header", "body", "malformed-optional", "security-header"),
)
def test_decode_loopback_transcript_rejects_mutated_request_semantics(
    tmp_path: Path,
    mutation: str,
) -> None:
    module = _server_module()
    supplied = _decoder_transcript(
        module,
        scenario="shell",
        case_root=str(tmp_path / "case"),
    )
    raw = supplied.raw_bytes
    fields = dict(_split_transcript_fields(raw))
    if mutation == "method":
        raw = _replace_transcript_field(
            raw,
            "exchange_1_request_head",
            fields["exchange_1_request_head"].replace(b"POST ", b"GET ", 1),
        )
    elif mutation == "header":
        raw = _replace_transcript_field(
            raw,
            "exchange_1_request_head",
            fields["exchange_1_request_head"].replace(
                b"Accept: text/event-stream\r\n",
                b"Accept: application/json\r\n",
            ),
        )
    elif mutation == "security-header":
        raw = _replace_transcript_field(
            raw,
            "exchange_1_request_head",
            fields["exchange_1_request_head"].replace(
                b"\r\n\r\n",
                b"\r\nAuthorization: Bearer forbidden\r\n\r\n",
            ),
        )
    else:
        body = json.loads(fields["exchange_1_request_body"])
        if mutation == "body":
            body["model"] = "wrong-model"
        else:
            body["reasoning"] = {"effort": 1}
        raw = _replace_decoder_request_body(raw, ordinal=1, value=body)

    _assert_decoder_rejects(module, raw)


def test_decode_loopback_transcript_accepts_typed_optional_request_fields(
    tmp_path: Path,
) -> None:
    module = _server_module()
    optional = _supported_optional_fields()
    supplied = _decoder_transcript(
        module,
        scenario="shell",
        case_root=str(tmp_path / "case"),
        first_optional=optional,
        second_optional=optional,
    )

    decoded = module.decode_loopback_transcript(supplied.raw_bytes)

    assert decoded.raw_bytes == supplied.raw_bytes


@pytest.mark.parametrize("mutation", ("duplicate-key", "nonfinite", "invalid-utf8"))
def test_decode_loopback_transcript_rejects_strict_json_violations(
    tmp_path: Path,
    mutation: str,
) -> None:
    module = _server_module()
    raw = _decoder_transcript(
        module,
        scenario="shell",
        case_root=str(tmp_path / "case"),
    ).raw_bytes
    body = dict(_split_transcript_fields(raw))["exchange_1_request_body"]
    if mutation == "duplicate-key":
        malformed = body[:-1] + b',"model":"gpt-5.6-terra"}'
    elif mutation == "nonfinite":
        malformed = body[:-1] + b',"service_tier":NaN}'
    else:
        assert mutation == "invalid-utf8"
        malformed = body[:-1] + b',"instructions":"\xff"}'
    raw = _replace_decoder_request_body_bytes(
        raw,
        ordinal=1,
        body=malformed,
    )

    _assert_decoder_rejects(module, raw)


@pytest.mark.parametrize("mutation", ("response-head", "response-body", "swapped"))
def test_decode_loopback_transcript_rejects_mutated_or_swapped_responses(
    tmp_path: Path,
    mutation: str,
) -> None:
    module = _server_module()
    raw = _decoder_transcript(
        module,
        scenario="shell",
        case_root=str(tmp_path / "case"),
    ).raw_bytes
    fields = _split_transcript_fields(raw)
    values = dict(fields)
    if mutation == "response-head":
        raw = _replace_transcript_field(
            raw,
            "exchange_1_response_head",
            values["exchange_1_response_head"].replace(
                b"Cache-Control: no-store",
                b"Cache-Control: max-age=1",
            ),
        )
    elif mutation == "response-body":
        raw = _replace_transcript_field(
            raw,
            "exchange_2_response_body",
            values["exchange_2_response_body"].replace(
                b"campaign6-loopback-complete",
                b"campaign6-loopback-mutated",
            ),
        )
    else:
        assert mutation == "swapped"
        swapped = []
        for name, value in fields:
            if name.startswith("exchange_1_"):
                value = values[name.replace("exchange_1_", "exchange_2_", 1)]
            elif name.startswith("exchange_2_"):
                value = values[name.replace("exchange_2_", "exchange_1_", 1)]
            swapped.append((name, value))
        raw = _join_transcript_fields(swapped)

    _assert_decoder_rejects(module, raw)


@pytest.mark.parametrize("content", (None, b"", bytearray(), memoryview(b""), ""))
def test_decode_loopback_transcript_rejects_nonbytes_and_empty(content: object) -> None:
    module = _server_module()

    _assert_decoder_rejects(module, content)


def test_decode_loopback_transcript_rejects_input_above_derived_cap() -> None:
    module = _server_module()

    _assert_decoder_rejects(
        module,
        b"x" * (module.LOOPBACK_TRANSCRIPT_MAX_BYTES + 1),
    )


def test_loopback_transcript_max_bytes_is_public_stable_cap() -> None:
    module = _server_module()

    cap = module.LOOPBACK_TRANSCRIPT_MAX_BYTES
    assert type(cap) is int
    assert isinstance(cap, bool) is False
    assert cap > 0
