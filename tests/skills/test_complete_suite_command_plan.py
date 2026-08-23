from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest


SKILLS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILLS_ROOT))

import run_complete_suite_campaign as runner  # noqa: E402


LEGACY_PROVENANCE = "legacy-shell-words-v1"
COMMAND_PLAN_PROVENANCE = "powershell-command-plan-v1"
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
