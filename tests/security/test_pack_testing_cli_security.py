from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import pytest

from kokoroarc import cli as cli_module
from kokoroarc.config import Settings
from kokoroarc.errors import KokoroError
from kokoroarc.packs import compiler as pack_compiler
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RIN_PACK = REPOSITORY_ROOT / "characters" / "original" / "rin-aster"
SCHEMA_ROOT = REPOSITORY_ROOT / "schemas" / "v1"


def _write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")
    return path


def _run_cli(
    data_dir: Path,
    *arguments: str,
) -> tuple[dict[str, Any], subprocess.CompletedProcess[str]]:
    env = os.environ.copy()
    env["KOKOROX_DATA_DIR"] = str(data_dir)
    env["PYTHONPATH"] = str(REPOSITORY_ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-m", "kokoroarc.cli", *arguments, "--json"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=REPOSITORY_ROOT,
        timeout=60,
    )
    assert completed.stderr == ""
    assert len(completed.stdout.splitlines()) == 1
    return json.loads(completed.stdout), completed


@pytest.mark.parametrize(
    "out",
    ["../escape.json", "ABSOLUTE_OUTSIDE", "NUL.json", "trailing.json "],
)
def test_report_output_must_remain_beneath_configured_root(
    tmp_path: Path,
    rin_verified_release: dict[str, Any],
    out: str,
) -> None:
    data_dir = tmp_path / "data"
    soft_input = _write_json(
        tmp_path / "soft-input.json",
        rin_verified_release["evidence"]["soft_evaluation_input"],
    )
    outside = tmp_path / "outside.json"
    selected = str(outside.resolve()) if out == "ABSOLUTE_OUTSIDE" else out

    body, completed = _run_cli(
        data_dir,
        "pack",
        "soft-eval",
        str(soft_input),
        "--out",
        selected,
    )

    assert completed.returncode == 2
    assert body["error"]["code"] == "REPORT_OUTPUT_PATH_UNSAFE"
    assert body["error"]["details"] == {}
    assert not outside.exists()


def test_report_output_cannot_alias_an_input(
    tmp_path: Path,
    rin_verified_release: dict[str, Any],
) -> None:
    data_dir = tmp_path / "data"
    shared = _write_json(
        data_dir / "reports" / "shared.json",
        rin_verified_release["evidence"]["soft_evaluation_input"],
    )
    before = shared.read_bytes()

    body, completed = _run_cli(
        data_dir,
        "pack",
        "soft-eval",
        str(shared),
        "--out",
        "shared.json",
    )

    assert completed.returncode == 2
    assert body["error"]["code"] == "REPORT_OUTPUT_PATH_UNSAFE"
    assert shared.read_bytes() == before


def test_report_output_cannot_be_created_inside_the_source_pack(
    tmp_path: Path,
    rin_verified_release: dict[str, Any],
) -> None:
    data_dir = tmp_path / "data"
    source = data_dir / "reports" / "source"
    shutil.copytree(RIN_PACK, source)
    request = _write_json(
        tmp_path / "request.json",
        rin_verified_release["evidence"]["request"],
    )

    body, completed = _run_cli(
        data_dir,
        "pack",
        "test",
        str(source),
        "--request",
        str(request),
        "--out",
        "source/generated-report.json",
    )

    assert completed.returncode == 2
    assert body["error"]["code"] == "REPORT_OUTPUT_PATH_UNSAFE"
    assert not (source / "generated-report.json").exists()


def test_report_output_cannot_alias_trusted_research_bundle_tree(
    tmp_path: Path,
    rin_verified_release: dict[str, Any],
) -> None:
    data_dir = tmp_path / "data"
    bundle = data_dir / "reports" / "trusted-bundle"
    bundle.mkdir(parents=True)
    marker = bundle / "bundle.json"
    marker.write_bytes(b'{"private":"unchanged"}\n')
    request = _write_json(
        tmp_path / "request.json",
        rin_verified_release["evidence"]["request"],
    )

    body, completed = _run_cli(
        data_dir,
        "pack",
        "test",
        str(RIN_PACK),
        "--request",
        str(request),
        "--research-bundle",
        str(bundle),
        "--out",
        "trusted-bundle/bundle.json",
    )

    assert completed.returncode == 2
    assert body["error"]["code"] == "REPORT_OUTPUT_PATH_UNSAFE"
    assert marker.read_bytes() == b'{"private":"unchanged"}\n'


def test_external_json_hardlink_is_rejected_without_reading_alias(
    tmp_path: Path,
) -> None:
    original = _write_json(tmp_path / "original.json", {"value": "private"})
    alias = tmp_path / "alias.json"
    try:
        os.link(original, alias)
    except OSError:
        pytest.skip("The current account cannot create hardlinks")

    with pytest.raises(KokoroError) as caught:
        cli_module._read_json(alias)

    assert caught.value.code == "INPUT_PATH_UNSAFE"
    assert original.read_bytes() == canonical_bytes({"value": "private"}) + b"\n"


def test_external_json_mutation_during_stable_read_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_json(tmp_path / "input.json", {"value": "first"})
    replacement = canonical_bytes({"value": "other"}) + b"\n"
    assert len(replacement) == path.stat().st_size
    real_fstat = os.fstat
    calls = 0

    def mutate_after_open(descriptor: int) -> os.stat_result:
        nonlocal calls
        result = real_fstat(descriptor)
        calls += 1
        if calls == 1:
            path.write_bytes(replacement)
        return result

    monkeypatch.setattr(os, "fstat", mutate_after_open)
    with pytest.raises(KokoroError) as caught:
        cli_module._read_json(path)

    assert caught.value.code == "INPUT_PATH_UNSAFE"


def test_report_output_rejects_symlink_target_or_skips(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    reports = data_dir / "reports"
    reports.mkdir(parents=True)
    target = reports / "real.json"
    target.write_bytes(b"{}\n")
    alias = reports / "alias.json"
    try:
        alias.symlink_to(target.name)
    except OSError:
        pytest.skip("The current account cannot create file symlinks")

    with pytest.raises(KokoroError) as caught:
        cli_module._prepare_report_output(
            Settings(data_dir=data_dir.resolve(), schema_dir=SCHEMA_ROOT),
            "alias.json",
        )

    assert caught.value.code == "REPORT_OUTPUT_PATH_UNSAFE"
    assert target.read_bytes() == b"{}\n"


def test_report_output_rejects_junction_marked_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    marked = data_dir / "reports" / "nested"
    marked.mkdir(parents=True)
    real_is_junction = getattr(Path, "is_junction", lambda _path: False)

    def is_junction(path: Path) -> bool:
        return path == marked or bool(real_is_junction(path))

    monkeypatch.setattr(Path, "is_junction", is_junction, raising=False)
    with pytest.raises(KokoroError) as caught:
        cli_module._prepare_report_output(
            Settings(data_dir=data_dir.resolve(), schema_dir=SCHEMA_ROOT),
            "nested/report.json",
        )

    assert caught.value.code == "REPORT_OUTPUT_PATH_UNSAFE"


def test_parent_replacement_before_cutover_is_rejected_without_output(
    tmp_path: Path,
    rin_verified_release: dict[str, Any],
) -> None:
    data_dir = tmp_path / "data"
    settings = Settings(data_dir=data_dir.resolve(), schema_dir=SCHEMA_ROOT)
    output = cli_module._prepare_report_output(settings, "nested/report.json")
    original_parent = output.target.parent
    moved = original_parent.with_name("nested-moved")
    original_parent.rename(moved)
    original_parent.mkdir()

    with pytest.raises(KokoroError) as caught:
        cli_module._publish_report_output(
            output,
            rin_verified_release["evidence"]["soft_evaluation_report"],
            SchemaRegistry(SCHEMA_ROOT),
            "pack-soft-evaluation-report",
        )

    assert caught.value.code == "REPORT_OUTPUT_PATH_UNSAFE"
    assert not (moved / "report.json").exists()
    assert not (original_parent / "report.json").exists()


def test_atomic_write_failure_preserves_existing_output_and_removes_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rin_verified_release: dict[str, Any],
) -> None:
    data_dir = tmp_path / "data"
    target = data_dir / "reports" / "soft.json"
    target.parent.mkdir(parents=True)
    original = b'{"existing":true}\n'
    target.write_bytes(original)
    output = cli_module._prepare_report_output(
        Settings(data_dir=data_dir.resolve(), schema_dir=SCHEMA_ROOT),
        "soft.json",
    )

    def deny_replace(_staging: Path, _target: Path) -> None:
        raise PermissionError("injected replace failure")

    monkeypatch.setattr(pack_compiler, "_replace_atomically", deny_replace)
    with pytest.raises(KokoroError) as caught:
        cli_module._publish_report_output(
            output,
            rin_verified_release["evidence"]["soft_evaluation_report"],
            SchemaRegistry(SCHEMA_ROOT),
            "pack-soft-evaluation-report",
        )

    assert caught.value.code == "REPORT_OUTPUT_WRITE_FAILED"
    assert target.read_bytes() == original
    assert list(target.parent.glob(".*.tmp")) == []


def test_soft_eval_revalidates_report_before_atomic_handoff(
    tmp_path: Path,
    rin_verified_release: dict[str, Any],
) -> None:
    input_path = _write_json(
        tmp_path / "soft-input.json",
        rin_verified_release["evidence"]["soft_evaluation_input"],
    )
    delegate = SchemaRegistry(SCHEMA_ROOT)

    class CountingSchemas:
        def __init__(self) -> None:
            self.report_validations = 0

        def validate(self, name: str, value: Any) -> None:
            if name == "pack-soft-evaluation-report":
                self.report_validations += 1
            delegate.validate(name, value)

    schemas = CountingSchemas()
    result = cli_module._handle_pack_soft_eval(
        argparse.Namespace(input=str(input_path), out="soft.json"),
        Settings(data_dir=(tmp_path / "data").resolve(), schema_dir=SCHEMA_ROOT),
        schemas,  # type: ignore[arg-type]
    )

    assert result["passed"] is True
    assert schemas.report_validations == 3
