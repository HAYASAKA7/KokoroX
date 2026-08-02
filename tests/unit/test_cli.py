import subprocess
import sys
import json
import os

import pytest


def test_module_version_command() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "kokoroarc.cli", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == "kokoro 0.0.0.dev0"


def test_json_error_when_data_directory_is_missing() -> None:
    env = os.environ.copy()
    env.pop("KOKOROARC_DATA_DIR", None)
    completed = subprocess.run(
        [sys.executable, "-m", "kokoroarc.cli", "session", "show", "--json"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    body = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert body == {
        "ok": False,
        "error": {
            "code": "DATA_DIR_REQUIRED",
            "message": "Set KOKOROARC_DATA_DIR before running a stateful command.",
            "retryable": False,
            "details": {},
        },
    }
    assert completed.stderr == ""


def test_json_session_show_succeeds_with_configured_data_directory(tmp_path) -> None:
    env = os.environ.copy()
    env["KOKOROARC_DATA_DIR"] = str(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-m", "kokoroarc.cli", "session", "show", "--json"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {"ok": True, "session": None}
    assert completed.stderr == ""


@pytest.mark.parametrize("arguments", [[], ["session"]])
def test_incomplete_commands_return_usage_errors(arguments: list[str]) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "kokoroarc.cli", *arguments],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "usage: kokoro" in completed.stderr
