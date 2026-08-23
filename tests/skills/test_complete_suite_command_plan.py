from __future__ import annotations

from dataclasses import FrozenInstanceError
from hashlib import sha256
import importlib
import json
from pathlib import Path
import sys
import tracemalloc

import pytest


SKILLS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILLS_ROOT))

import run_complete_suite_campaign as runner  # noqa: E402


LEGACY_PROVENANCE = "legacy-shell-words-v1"
COMMAND_PLAN_PROVENANCE = "powershell-command-plan-v1"
SHELL_PATH = r"C:\Program Files\PowerShell\7\pwsh.exe"
WRAPPER_ARGUMENTS = b" -NoLogo -NoProfile -NonInteractive -Command "
PAYLOAD_LIMIT_BYTES = 256 * 1024
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
