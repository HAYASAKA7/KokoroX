from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import pytest

from kokoroarc import cli as cli_module
from kokoroarc.errors import KokoroError


@pytest.fixture
def original_request() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": "original/rin-aster/build-request",
        "created_by": {"component": "kokoroarc", "version": "0.0.0.dev0"},
        "mode": "original",
        "namespace": "original",
        "character_id": "rin-aster",
        "display_name": "Rin Aster",
        "character_version": "1.0.0",
        "requested_locales": ["zh-CN", "en-US", "ja-JP"],
        "intended_use_cases": ["technical collaboration"],
        "user_constraints": ["Do not fabricate certainty."],
        "inputs": [
            {
                "type": "creative_brief",
                "content": "A restrained systems architect.",
            }
        ],
    }


def _write_request(path: Path, request: dict[str, Any]) -> Path:
    path.write_text(json.dumps(request), encoding="utf-8")
    return path


def _cli(
    arguments: list[str], *, data_dir: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
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
    )


def _assert_error(
    completed: subprocess.CompletedProcess[str], code: str, message: str
) -> dict[str, Any]:
    body = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert body == {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "retryable": False,
            "details": {},
        },
    }
    assert completed.stderr == ""
    return body


def test_character_request_validate_returns_normalized_request_without_data_dir(
    tmp_path: Path, original_request: dict[str, Any]
) -> None:
    request_path = _write_request(tmp_path / "request.json", original_request)
    completed = _cli(
        ["character", "request", "validate", "--input", str(request_path), "--json"]
    )
    expected = deepcopy(original_request)
    expected["requested_visibility"] = "private"
    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {"ok": True, "request": expected}
    assert completed.stderr == ""


def test_character_draft_validate_returns_report_without_data_dir(
    tmp_path: Path, original_request: dict[str, Any]
) -> None:
    request_path = _write_request(tmp_path / "request.json", original_request)
    completed = _cli(
        [
            "character",
            "draft",
            "validate",
            "--request",
            str(request_path),
            "--pack",
            "characters/original/rin-aster",
            "--json",
        ]
    )
    body = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert body["ok"] is True
    assert body["valid"] is True
    assert body["validation_report"]["valid"] is True
    assert body["validation_report"]["hard_failures"] == []
    assert completed.stderr == ""


def test_character_draft_compile_publishes_deterministic_private_inactive_bundle(
    tmp_path: Path, original_request: dict[str, Any]
) -> None:
    request_path = _write_request(tmp_path / "request.json", original_request)
    data_dir = tmp_path / "data"
    arguments = [
        "character",
        "draft",
        "compile",
        "--request",
        str(request_path),
        "--pack",
        "characters/original/rin-aster",
        "--json",
    ]
    first = _cli(arguments, data_dir=data_dir)
    second = _cli(arguments, data_dir=data_dir)
    first_body = json.loads(first.stdout)
    assert first.returncode == second.returncode == 0
    assert first_body == json.loads(second.stdout)
    assert first_body["ok"] is True
    assert first_body["build_status"] == "draft"
    assert first_body["visibility"] == "private"
    assert first_body["activation_allowed"] is False
    assert first_body["validation_report"]["valid"] is True
    assert set(first_body) >= {
        "path",
        "artifact_id",
        "request_hash",
        "source_pack_hash",
        "validation_report_hash",
    }
    bundle = Path(first_body["path"])
    assert bundle.is_relative_to((data_dir / "drafts").resolve())
    assert (bundle / "draft.json").is_file()
    assert not (data_dir / "compiled").exists()
    assert not (data_dir / "sessions").exists()
    assert not (data_dir / "state").exists()
    assert not (data_dir / "events").exists()
    assert first.stderr == second.stderr == ""


def test_character_request_validate_sanitizes_malformed_json(
    tmp_path: Path,
) -> None:
    secret = "PRIVATE-DOSSIER-CONTENT"
    request_path = tmp_path / "request.json"
    request_path.write_text('{"secret": "' + secret + '",}', encoding="utf-8")

    completed = _cli(
        ["character", "request", "validate", "--input", str(request_path), "--json"]
    )

    _assert_error(completed, "INPUT_INVALID_JSON", "Input file contains invalid JSON.")
    assert secret not in completed.stdout


def test_character_request_validate_sanitizes_schema_failure(
    tmp_path: Path, original_request: dict[str, Any]
) -> None:
    secret = "PRIVATE-SCHEMA-PAYLOAD"
    original_request["unexpected"] = secret
    request_path = _write_request(tmp_path / "request.json", original_request)

    completed = _cli(
        ["character", "request", "validate", "--input", str(request_path), "--json"]
    )

    _assert_error(
        completed,
        "SCHEMA_VALIDATION_FAILED",
        "Input did not match the required schema.",
    )
    assert secret not in completed.stdout


def test_character_request_validate_reports_unsupported_mode_without_payload(
    tmp_path: Path, original_request: dict[str, Any]
) -> None:
    secret = "PRIVATE-RESEARCH-PAYLOAD"
    original_request["mode"] = "researched"
    original_request["inputs"] = [{"type": "research_bundle", "content": secret}]
    request_path = _write_request(tmp_path / "request.json", original_request)

    completed = _cli(
        ["character", "request", "validate", "--input", str(request_path), "--json"]
    )

    _assert_error(
        completed,
        "AUTHORING_MODE_UNSUPPORTED",
        "Construction mode is not available in this milestone.",
    )
    assert secret not in completed.stdout


def test_character_draft_validate_returns_invalid_identity_report(
    tmp_path: Path, original_request: dict[str, Any]
) -> None:
    original_request["character_id"] = "different-character"
    request_path = _write_request(tmp_path / "request.json", original_request)

    completed = _cli(
        [
            "character",
            "draft",
            "validate",
            "--request",
            str(request_path),
            "--pack",
            "characters/original/rin-aster",
            "--json",
        ]
    )

    body = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert body["valid"] is False
    assert body["validation_report"]["valid"] is False
    assert [item["code"] for item in body["validation_report"]["hard_failures"]] == [
        "AUTHORING_IDENTITY_MISMATCH"
    ]


def test_character_draft_compile_refuses_invalid_identity_report(
    tmp_path: Path, original_request: dict[str, Any]
) -> None:
    original_request["character_id"] = "different-character"
    request_path = _write_request(tmp_path / "request.json", original_request)

    completed = _cli(
        [
            "character",
            "draft",
            "compile",
            "--request",
            str(request_path),
            "--pack",
            "characters/original/rin-aster",
            "--json",
        ],
        data_dir=tmp_path / "data",
    )

    _assert_error(
        completed,
        "AUTHORING_VALIDATION_FAILED",
        "Character authoring validation failed.",
    )
    assert not (tmp_path / "data" / "drafts").exists()


def test_character_draft_compile_alone_requires_data_dir(
    tmp_path: Path, original_request: dict[str, Any]
) -> None:
    request_path = _write_request(tmp_path / "request.json", original_request)

    completed = _cli(
        [
            "character",
            "draft",
            "compile",
            "--request",
            str(request_path),
            "--pack",
            "characters/original/rin-aster",
            "--json",
        ]
    )

    _assert_error(
        completed,
        "DATA_DIR_REQUIRED",
        "Set KOKOROARC_DATA_DIR before running a stateful command.",
    )


def test_character_draft_validate_sanitizes_missing_pack(
    tmp_path: Path, original_request: dict[str, Any]
) -> None:
    request_path = _write_request(tmp_path / "request.json", original_request)

    completed = _cli(
        [
            "character",
            "draft",
            "validate",
            "--request",
            str(request_path),
            "--pack",
            str(tmp_path / "secret-pack-name"),
            "--json",
        ]
    )

    _assert_error(completed, "PACK_NOT_FOUND", "Character pack was not found.")
    assert "secret-pack-name" not in completed.stdout


def test_character_draft_validate_sanitizes_invalid_pack_data(
    tmp_path: Path, original_request: dict[str, Any]
) -> None:
    secret = "PRIVATE-INVALID-PACK-CONTENT"
    request_path = _write_request(tmp_path / "request.json", original_request)
    pack = tmp_path / "pack"
    shutil.copytree("characters/original/rin-aster", pack)
    (pack / "identity.yaml").write_text(
        "private: [" + secret,
        encoding="utf-8",
    )

    completed = _cli(
        [
            "character",
            "draft",
            "validate",
            "--request",
            str(request_path),
            "--pack",
            str(pack),
            "--json",
        ]
    )

    _assert_error(completed, "INVALID_PACK_DATA", "Character pack data is invalid.")
    assert secret not in completed.stdout


def test_character_draft_validate_sanitizes_traversal_pack_reference(
    tmp_path: Path, original_request: dict[str, Any]
) -> None:
    request_path = _write_request(tmp_path / "request.json", original_request)
    pack = tmp_path / "pack"
    shutil.copytree("characters/original/rin-aster", pack)
    manifest = pack / "character.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "identity.yaml", "../PRIVATE-DOSSIER.yaml"
        ),
        encoding="utf-8",
    )

    completed = _cli(
        [
            "character",
            "draft",
            "validate",
            "--request",
            str(request_path),
            "--pack",
            str(pack),
            "--json",
        ]
    )

    _assert_error(completed, "UNSAFE_PACK_PATH", "Character pack path is unsafe.")
    assert "PRIVATE-DOSSIER" not in completed.stdout


@pytest.mark.parametrize(
    ("error", "expected_message"),
    [
        (
            KokoroError(
                "AUTHORING_SOURCE_CHANGED",
                "PRIVATE stale path D:/users/name/source",
                details={"path": "D:/users/name/source", "reason": "inode"},
            ),
            "Character source pack changed during compilation.",
        ),
        (
            KokoroError(
                "DRAFT_PUBLISH_BUSY",
                "PRIVATE lock owner",
                details={"path": "D:/users/name/.lock"},
            ),
            "Character draft publication is already in progress.",
        ),
        (
            KokoroError(
                "DRAFT_PUBLISH_FAILED",
                "PRIVATE operating system detail",
                details={"reason": "AccessDenied", "path": "D:/users/name"},
            ),
            "Character draft publication failed.",
        ),
    ],
)
def test_character_draft_compile_sanitizes_stale_busy_and_storage_failures(
    tmp_path: Path,
    original_request: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: KokoroError,
    expected_message: str,
) -> None:
    request_path = _write_request(tmp_path / "request.json", original_request)
    monkeypatch.setenv("KOKOROARC_DATA_DIR", str(tmp_path / "data"))

    def fail_publish(*_args: object) -> Path:
        raise error

    monkeypatch.setattr(cli_module, "publish_draft_bundle", fail_publish)

    result = cli_module.main(
        [
            "character",
            "draft",
            "compile",
            "--request",
            str(request_path),
            "--pack",
            "characters/original/rin-aster",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert json.loads(captured.out) == {
        "ok": False,
        "error": {
            "code": error.code,
            "message": expected_message,
            "retryable": False,
            "details": {},
        },
    }
    assert "PRIVATE" not in captured.out
    assert "D:/users/name" not in captured.out
    assert captured.err == ""
