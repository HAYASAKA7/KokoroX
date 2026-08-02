import subprocess
import sys


def test_module_version_command() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "kokoroarc.cli", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == "kokoro 0.0.0.dev0"
