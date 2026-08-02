import subprocess
import sys
import json
import os


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
    assert body["error"]["code"] == "DATA_DIR_REQUIRED"
