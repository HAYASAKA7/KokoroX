from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

import kokoroarc.cli as cli
from kokoroarc.cli import build_parser
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry
from kokoroarc.standalone_cli import handle_standalone

from karc_test_support import (
    archive_documents,
    build_private_archive,
    make_legacy_090_archive,
)


SCHEMAS = SchemaRegistry(Path("schemas/v1"))


def _private_export_arguments(
    root: Path,
    release: dict[str, Any],
) -> tuple[list[str], dict[str, Path], bytes]:
    archive = build_private_archive(release)
    documents = archive_documents(archive)
    promotion_dir = root / "published-promotion"
    promotion_dir.mkdir()
    paths = {
        "compiled": root / "compiled.json",
        "promotion": promotion_dir / "promotion.json",
        "hard": root / "hard.json",
        "soft": root / "soft.json",
        "review": promotion_dir / "review-attestation.json",
        "output": root / "rin.karc",
    }
    members = {
        "compiled": "pack/compiled.json",
        "promotion": "release/promotion-record.json",
        "hard": "release/hard-validation-report.json",
        "soft": "release/soft-evaluation-report.json",
        "review": "release/review-attestation.json",
    }
    for name, member in members.items():
        paths[name].write_bytes(canonical_bytes(documents[member]))
    arguments = [
        "pack",
        "export",
        "--compiled",
        str(paths["compiled"]),
        "--promotion",
        str(paths["promotion"]),
        "--hard-report",
        str(paths["hard"]),
        "--soft-report",
        str(paths["soft"]),
        "--out",
        str(paths["output"]),
        "--json",
    ]
    return arguments, paths, archive


def _error(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    captured = capsys.readouterr()
    assert captured.err == ""
    body = json.loads(captured.out)
    assert body["ok"] is False
    return body["error"]


def test_export_rejects_duplicate_json_without_writing(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments, paths, _archive = _private_export_arguments(
        tmp_path,
        rin_verified_release,
    )
    paths["hard"].write_bytes(b'{"duplicate":1,"duplicate":2}')
    monkeypatch.delenv("KOKOROARC_DATA_DIR", raising=False)

    assert cli.main(arguments) == 2

    assert _error(capsys)["code"] == "INPUT_INVALID_JSON"
    assert not paths["output"].exists()


def test_export_rejects_hardlinked_input_without_writing(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments, paths, _archive = _private_export_arguments(
        tmp_path,
        rin_verified_release,
    )
    alias = tmp_path / "compiled-alias.json"
    try:
        os.link(paths["compiled"], alias)
    except OSError:
        pytest.skip("hard links are unavailable")
    arguments[arguments.index(str(paths["compiled"]))] = str(alias)
    monkeypatch.delenv("KOKOROARC_DATA_DIR", raising=False)

    assert cli.main(arguments) == 2

    assert _error(capsys)["code"] == "INPUT_PATH_UNSAFE"
    assert not paths["output"].exists()


def test_export_never_overwrites_existing_output(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments, paths, _archive = _private_export_arguments(
        tmp_path,
        rin_verified_release,
    )
    sentinel = b"caller-owned-output"
    paths["output"].write_bytes(sentinel)
    monkeypatch.delenv("KOKOROARC_DATA_DIR", raising=False)

    assert cli.main(arguments) == 2

    assert _error(capsys)["code"] == "KARC_EXPORT_OUTPUT_EXISTS"
    assert paths["output"].read_bytes() == sentinel


def test_export_rejects_input_changed_during_schema_callback(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    arguments, paths, _archive = _private_export_arguments(
        tmp_path,
        rin_verified_release,
    )

    class MutatingSchemas:
        def __init__(self) -> None:
            self.called = False

        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if not self.called:
                self.called = True
                paths["hard"].write_bytes(b"{}")

    with pytest.raises(KokoroError) as caught:
        handle_standalone(
            build_parser().parse_args(arguments),
            None,
            MutatingSchemas(),  # type: ignore[arg-type]
        )

    assert caught.value.code == "INPUT_PATH_UNSAFE"
    assert not paths["output"].exists()


def test_export_preserves_output_that_appears_during_schema_callback(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    arguments, paths, _archive = _private_export_arguments(
        tmp_path,
        rin_verified_release,
    )
    sentinel = b"concurrent-caller-output"

    class MutatingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if not paths["output"].exists():
                paths["output"].write_bytes(sentinel)

    with pytest.raises(KokoroError) as caught:
        handle_standalone(
            build_parser().parse_args(arguments),
            None,
            MutatingSchemas(),  # type: ignore[arg-type]
        )

    assert caught.value.code == "KARC_EXPORT_OUTPUT_EXISTS"
    assert paths["output"].read_bytes() == sentinel


def test_compatibility_rejects_archive_changed_during_schema_callback(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "rin.karc"
    archive_path.write_bytes(build_private_archive(rin_verified_release))

    class MutatingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            archive_path.write_bytes(b"changed")

    with pytest.raises(KokoroError) as caught:
        handle_standalone(
            build_parser().parse_args(
                ["pack", "compatibility", str(archive_path), "--json"]
            ),
            None,
            MutatingSchemas(),  # type: ignore[arg-type]
        )

    assert caught.value.code == "INPUT_PATH_UNSAFE"


def test_migration_never_overwrites_existing_output(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "legacy.karc"
    source.write_bytes(
        make_legacy_090_archive(build_private_archive(rin_verified_release))
    )
    output = tmp_path / "current.karc"
    sentinel = b"caller-owned-output"
    output.write_bytes(sentinel)
    monkeypatch.delenv("KOKOROARC_DATA_DIR", raising=False)

    assert (
        cli.main(
            [
                "pack",
                "migrate",
                str(source),
                "--to-format",
                "1.0.0",
                "--out",
                str(output),
                "--json",
            ]
        )
        == 2
    )

    assert _error(capsys)["code"] == "MIGRATION_OUTPUT_EXISTS"
    assert output.read_bytes() == sentinel


def test_migration_rejects_archive_changed_during_schema_callback(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy.karc"
    source.write_bytes(
        make_legacy_090_archive(build_private_archive(rin_verified_release))
    )
    output = tmp_path / "current.karc"

    class MutatingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            source.write_bytes(b"changed")

    with pytest.raises(KokoroError) as caught:
        handle_standalone(
            build_parser().parse_args(
                [
                    "pack",
                    "migrate",
                    str(source),
                    "--to-format",
                    "1.0.0",
                    "--out",
                    str(output),
                    "--dry-run",
                    "--json",
                ]
            ),
            None,
            MutatingSchemas(),  # type: ignore[arg-type]
        )

    assert caught.value.code == "INPUT_PATH_UNSAFE"
    assert not output.exists()


def test_migration_preserves_output_that_appears_during_schema_callback(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy.karc"
    source.write_bytes(
        make_legacy_090_archive(build_private_archive(rin_verified_release))
    )
    output = tmp_path / "current.karc"
    sentinel = b"concurrent-caller-output"

    class MutatingSchemas:
        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if not output.exists():
                output.write_bytes(sentinel)

    with pytest.raises(KokoroError) as caught:
        handle_standalone(
            build_parser().parse_args(
                [
                    "pack",
                    "migrate",
                    str(source),
                    "--to-format",
                    "1.0.0",
                    "--out",
                    str(output),
                    "--dry-run",
                    "--json",
                ]
            ),
            None,
            MutatingSchemas(),  # type: ignore[arg-type]
        )

    assert caught.value.code == "MIGRATION_OUTPUT_EXISTS"
    assert output.read_bytes() == sentinel
