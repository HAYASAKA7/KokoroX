from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


REPOSITORY_ROOT = Path.cwd().resolve()
RESEARCH_FIXTURES = REPOSITORY_ROOT / "tests" / "fixtures" / "research"


def _cli(
    arguments: list[str],
    *,
    data_dir: Path | None = None,
    python_path: Path | None = None,
    working_directory: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(python_path or REPOSITORY_ROOT / "src")
    if data_dir is None:
        env.pop("KOKOROARC_DATA_DIR", None)
    else:
        env["KOKOROARC_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, "-m", "kokoroarc.cli", *arguments],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=working_directory,
    )


def _assert_error(
    completed: subprocess.CompletedProcess[str],
    code: str,
    message: str,
) -> None:
    assert completed.returncode == 2
    assert json.loads(completed.stdout) == {
        "error": {
            "code": code,
            "details": {},
            "message": message,
            "retryable": False,
        },
        "ok": False,
    }
    assert completed.stderr == ""


def test_research_request_validate_is_stateless_and_deterministic() -> None:
    arguments = [
        "research",
        "request",
        "validate",
        "--input",
        str(RESEARCH_FIXTURES / "complete" / "request.json"),
        "--json",
    ]

    first = _cli(arguments)
    second = _cli(arguments)

    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    assert json.loads(first.stdout)["request"]["requested_visibility"] == "private"
    assert first.stderr == second.stderr == ""


def test_research_workspace_validate_is_stateless_and_deterministic() -> None:
    arguments = [
        "research",
        "workspace",
        "validate",
        "--workspace",
        str(RESEARCH_FIXTURES / "complete"),
        "--json",
    ]

    first = _cli(arguments)
    second = _cli(arguments)

    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    body = json.loads(first.stdout)
    assert body["ok"] is True
    assert body["valid"] is True
    assert body["validation_report"]["authoring_allowed"] is True
    assert body["workspace_hash"] == (
        "36c328d763dd4ca705f1619c8225cbc304ac09ccfe930c54375d2b9cf8c128a1"
    )
    assert first.stderr == second.stderr == ""


def test_research_bundle_compile_publishes_deterministic_private_bundle(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    arguments = [
        "research",
        "bundle",
        "compile",
        "--workspace",
        str(RESEARCH_FIXTURES / "complete"),
        "--json",
    ]

    first = _cli(arguments, data_dir=data_dir)
    second = _cli(arguments, data_dir=data_dir)

    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    body = json.loads(first.stdout)
    assert body["ok"] is True
    assert body["build_status"] == "research"
    assert body["visibility"] == "private"
    assert body["activation_allowed"] is False
    assert body["authoring_allowed"] is True
    assert body["coverage_summary"] == {
        "blocked": 0,
        "covered": 2,
        "missing": 0,
        "partial": 0,
    }
    assert body["blocking_reasons"] == []
    assert len(body["conflicts"]) == 1
    assert len(body["request_hash"]) == 64
    assert len(body["workspace_hash"]) == 64
    assert len(body["validation_report_hash"]) == 64
    assert len(body["bundle_hash"]) == 64
    published = Path(body["path"])
    assert published.is_relative_to((data_dir / "research").resolve())
    assert sorted(path.name for path in published.iterdir()) == [
        "bundle.json",
        "request.json",
        "validation-report.json",
        "workspace.json",
    ]
    for protected in (
        "drafts",
        "compiled",
        "installed",
        "public",
        "sessions",
        "state",
        "events",
        "workspaces",
        "config",
    ):
        assert not (data_dir / protected).exists()
    assert first.stderr == second.stderr == ""


def test_research_bundle_validate_is_stateless_and_deterministic(
    tmp_path: Path,
) -> None:
    compiled = _cli(
        [
            "research",
            "bundle",
            "compile",
            "--workspace",
            str(RESEARCH_FIXTURES / "complete"),
            "--json",
        ],
        data_dir=tmp_path / "data",
    )
    published = json.loads(compiled.stdout)["path"]
    arguments = [
        "research",
        "bundle",
        "validate",
        "--bundle",
        published,
        "--json",
    ]

    first = _cli(arguments)
    second = _cli(arguments)

    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    body = json.loads(first.stdout)
    assert body["ok"] is True
    assert body["valid"] is True
    assert body["build_status"] == "research"
    assert body["visibility"] == "private"
    assert body["activation_allowed"] is False
    assert body["coverage_summary"] == {
        "blocked": 0,
        "covered": 2,
        "missing": 0,
        "partial": 0,
    }
    assert "path" not in body
    assert first.stderr == second.stderr == ""


def test_research_bundle_compile_preserves_partial_blocked_lifecycle(
    tmp_path: Path,
) -> None:
    completed = _cli(
        [
            "research",
            "bundle",
            "compile",
            "--workspace",
            str(RESEARCH_FIXTURES / "partial"),
            "--json",
        ],
        data_dir=tmp_path / "data",
    )

    assert completed.returncode == 0
    body = json.loads(completed.stdout)
    assert body["build_status"] == "research"
    assert body["visibility"] == "private"
    assert body["activation_allowed"] is False
    assert body["authoring_allowed"] is False
    assert body["coverage_summary"] == {
        "blocked": 1,
        "covered": 0,
        "missing": 0,
        "partial": 1,
    }
    assert body["blocking_reasons"]
    assert body["limitations"] == [
        "The requested historical appendix is unavailable."
    ]
    assert completed.stderr == ""


def test_research_bundle_compile_alone_requires_data_dir() -> None:
    completed = _cli(
        [
            "research",
            "bundle",
            "compile",
            "--workspace",
            str(RESEARCH_FIXTURES / "complete"),
            "--json",
        ]
    )

    _assert_error(
        completed,
        "DATA_DIR_REQUIRED",
        "Set KOKOROARC_DATA_DIR before running a stateful command.",
    )


def test_research_request_validate_sanitizes_malformed_json(
    tmp_path: Path,
) -> None:
    secret = "PRIVATE-RESEARCH-CREDENTIAL"
    request_path = tmp_path / "private-request.json"
    request_path.write_text('{"secret": "' + secret + '",}', encoding="utf-8")

    completed = _cli(
        [
            "research",
            "request",
            "validate",
            "--input",
            str(request_path),
            "--json",
        ]
    )

    _assert_error(
        completed,
        "INPUT_INVALID_JSON",
        "Input file contains invalid JSON.",
    )
    assert secret not in completed.stdout
    assert str(request_path) not in completed.stdout


def test_research_workspace_validate_sanitizes_missing_workspace(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "PRIVATE-WORKSPACE-NAME"

    completed = _cli(
        [
            "research",
            "workspace",
            "validate",
            "--workspace",
            str(missing),
            "--json",
        ]
    )

    _assert_error(
        completed,
        "RESEARCH_WORKSPACE_NOT_FOUND",
        "Research workspace was not found.",
    )
    assert str(missing) not in completed.stdout


def test_research_bundle_validate_sanitizes_missing_bundle(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "PRIVATE-BUNDLE-NAME"

    completed = _cli(
        [
            "research",
            "bundle",
            "validate",
            "--bundle",
            str(missing),
            "--json",
        ]
    )

    _assert_error(
        completed,
        "RESEARCH_BUNDLE_INVALID",
        "Published Research Bundle validation failed.",
    )
    assert str(missing) not in completed.stdout


def test_research_request_validate_resolves_wheel_install_schema_layout(
    tmp_path: Path,
) -> None:
    installed = tmp_path / "installed"
    shutil.copytree(REPOSITORY_ROOT / "src" / "kokoroarc", installed / "kokoroarc")
    shutil.copytree(
        REPOSITORY_ROOT / "schemas" / "v1",
        installed / "share" / "kokoroarc" / "schemas" / "v1",
    )
    outside_repository = tmp_path / "working"
    outside_repository.mkdir()

    completed = _cli(
        [
            "research",
            "request",
            "validate",
            "--input",
            str(RESEARCH_FIXTURES / "complete" / "request.json"),
            "--json",
        ],
        python_path=installed,
        working_directory=outside_repository,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["request"]["requested_visibility"] == "private"
    assert completed.stderr == ""
