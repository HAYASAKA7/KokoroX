from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
from typing import Any

import pytest

import kokoroarc.cli as cli
from kokoroarc.cli import build_parser
from kokoroarc.distribution.installer import install_karc_archive
from kokoroarc.distribution.registry import (
    empty_installed_registry,
    resolve_install_scope,
)
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.persistence.consent import grant_consent
from kokoroarc.persistence.memory import list_memory_references
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


def _filesystem_snapshot(root: Path) -> tuple[tuple[Any, ...], ...]:
    if not root.exists():
        return ()
    snapshot: list[tuple[Any, ...]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        path_stat = path.stat(follow_symlinks=False)
        if path.is_file():
            snapshot.append(
                (relative, "file", path_stat.st_mtime_ns, path.read_bytes())
            )
        else:
            snapshot.append((relative, "directory", path_stat.st_mtime_ns))
    return tuple(snapshot)


def _prepare_persistence(
    root: Path,
    release: dict[str, Any],
) -> Path:
    archive = root / "rin.karc"
    archive.write_bytes(build_private_archive(release))
    data_root = root / "data"
    install_karc_archive(archive, data_root, SCHEMAS)
    grant_consent(
        data_root,
        "rin-aster",
        ["relationship_state", "mood_state", "memory_references"],
        SCHEMAS,
        expected_revision=0,
    )
    return data_root


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


def test_compatibility_rejects_archive_aba_across_schema_callbacks(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "rin.karc"
    original = build_private_archive(rin_verified_release)
    archive_path.write_bytes(original)
    original_stat = archive_path.stat()

    class MutatingSchemas:
        def __init__(self) -> None:
            self.calls = 0

        def validate(self, name: str, instance: Any) -> None:
            self.calls += 1
            if self.calls == 2:
                archive_path.write_bytes(original)
                os.utime(
                    archive_path,
                    ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
                )
            SCHEMAS.validate(name, instance)
            if self.calls == 1:
                archive_path.write_bytes(b"changed")

    mutating = MutatingSchemas()
    with pytest.raises(KokoroError) as caught:
        handle_standalone(
            build_parser().parse_args(
                ["pack", "compatibility", str(archive_path), "--json"]
            ),
            None,
            mutating,  # type: ignore[arg-type]
        )

    assert caught.value.code == "INPUT_PATH_UNSAFE"
    assert mutating.calls >= 2
    assert archive_path.read_bytes() == original
    restored_stat = archive_path.stat()
    assert restored_stat.st_ino == original_stat.st_ino
    assert restored_stat.st_size == original_stat.st_size
    assert restored_stat.st_mtime_ns == original_stat.st_mtime_ns


def test_install_captures_relative_workspace_before_schema_callbacks(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = tmp_path / "entry"
    rebound = tmp_path / "rebound"
    original_workspace = entry / "workspace"
    rebound_workspace = rebound / "workspace"
    original_workspace.mkdir(parents=True)
    rebound_workspace.mkdir(parents=True)
    archive_path = tmp_path / "rin.karc"
    archive_path.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"

    rebound_scope = resolve_install_scope(rebound_workspace)
    rebound_registry = empty_installed_registry(rebound_scope)
    rebound_registry["revision"] = 7
    rebound_registry_path = data_root.joinpath(
        *rebound_scope.registry_relative_path.split("/")
    )
    rebound_registry_path.parent.mkdir(parents=True)
    rebound_registry_path.write_bytes(canonical_bytes(rebound_registry))
    original_scope = resolve_install_scope(original_workspace)
    monkeypatch.chdir(entry)

    class MutatingSchemas:
        def __init__(self) -> None:
            self.called = False

        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if not self.called:
                self.called = True
                os.chdir(rebound)

    result = handle_standalone(
        build_parser().parse_args(
            [
                "pack",
                "install",
                str(archive_path),
                "--scope",
                "workspace",
                "--workspace",
                "workspace",
                "--dry-run",
                "--json",
            ]
        ),
        data_root,
        MutatingSchemas(),  # type: ignore[arg-type]
    )

    assert result["plan"]["workspace_id"] == original_scope.workspace_id
    assert result["plan"]["registry_revision_before"] == 0


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


def test_state_export_never_overwrites_existing_output(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_root = _prepare_persistence(tmp_path, rin_verified_release)
    output = tmp_path / "state.json"
    sentinel = b"caller-owned-state"
    output.write_bytes(sentinel)
    monkeypatch.setenv("KOKOROARC_DATA_DIR", str(data_root))

    assert (
        cli.main(
            [
                "state",
                "export",
                "--character",
                "rin-aster",
                "--out",
                str(output),
                "--json",
            ]
        )
        == 2
    )

    error = _error(capsys)
    assert error["code"] == "PERSISTENCE_OUTPUT_EXISTS"
    assert output.read_bytes() == sentinel
    assert str(output) not in json.dumps(error)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"summary":"one","summary":"two","localized_summaries":{}}',
        canonical_bytes(
            {
                "summary": "API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz123456",
                "localized_summaries": {
                    "en-US": "API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz123456"
                },
            }
        ),
    ],
)
def test_memory_add_rejects_duplicate_or_secret_summary_without_echo(
    payload: bytes,
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_root = _prepare_persistence(tmp_path, rin_verified_release)
    summary = tmp_path / "summary.json"
    summary.write_bytes(payload)
    before = _filesystem_snapshot(data_root)
    monkeypatch.setenv("KOKOROARC_DATA_DIR", str(data_root))

    assert (
        cli.main(
            [
                "memory",
                "add",
                "--character",
                "rin-aster",
                "--host-id",
                "host-memory-secret-01",
                "--summary-file",
                str(summary),
                "--json",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    assert captured.err == ""
    body = json.loads(captured.out)
    assert body["error"]["code"] in {
        "INPUT_INVALID_JSON",
        "PERSISTENCE_MEMORY_CONTENT_REJECTED",
        "PERSISTENCE_MEMORY_UNSAFE_CONTENT",
    }
    assert "sk-proj-" not in captured.out
    assert str(summary) not in captured.out
    assert _filesystem_snapshot(data_root) == before
    assert list_memory_references(data_root, "rin-aster", SCHEMAS) == ()


def test_memory_add_rejects_summary_changed_during_schema_callback(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = _prepare_persistence(tmp_path, rin_verified_release)
    summary = tmp_path / "summary.json"
    summary.write_bytes(
        canonical_bytes(
            {
                "summary": "The user approved concise explanations.",
                "localized_summaries": {
                    "en-US": "The user approved concise explanations."
                },
            }
        )
    )

    class MutatingSchemas:
        def __init__(self) -> None:
            self.called = False

        def validate(self, name: str, instance: Any) -> None:
            SCHEMAS.validate(name, instance)
            if not self.called:
                self.called = True
                summary.write_bytes(b"{}")

    with pytest.raises(KokoroError) as caught:
        handle_standalone(
            build_parser().parse_args(
                [
                    "memory",
                    "add",
                    "--character",
                    "rin-aster",
                    "--host-id",
                    "host-memory-approved-01",
                    "--summary-file",
                    str(summary),
                    "--json",
                ]
            ),
            data_root,
            MutatingSchemas(),  # type: ignore[arg-type]
        )

    assert caught.value.code == "INPUT_PATH_UNSAFE"
    assert list_memory_references(data_root, "rin-aster", SCHEMAS) == ()


def test_skill_suite_cli_dry_run_does_not_touch_home_or_codex_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_home = tmp_path / "fake-home"
    config = fake_home / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_bytes(b"caller_owned = true\n")
    before = _filesystem_snapshot(fake_home)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.delenv("KOKOROARC_DATA_DIR", raising=False)

    assert cli.main(["suite", "install", "--dry-run", "--json"]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["skill_suite"]["dry_run"] is True
    assert _filesystem_snapshot(fake_home) == before
    assert config.read_bytes() == b"caller_owned = true\n"


def test_skill_suite_cli_conflict_preserves_existing_skill_and_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_home = tmp_path / "fake-home"
    config = fake_home / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_bytes(b"caller_owned = true\n")
    skills_root = fake_home / ".agents" / "skills"
    skills_root.mkdir(parents=True)
    conflicting = skills_root / "using-kokoroarc"
    shutil.copytree(Path("skills") / "using-kokoroarc", conflicting)
    (conflicting / "SKILL.md").write_bytes(b"caller-owned-conflict\n")
    before = _filesystem_snapshot(fake_home)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.delenv("KOKOROARC_DATA_DIR", raising=False)

    assert cli.main(["suite", "install", "--json"]) == 2

    error = _error(capsys)
    assert error["code"] == "SKILL_SUITE_CONFLICT"
    assert _filesystem_snapshot(fake_home) == before
    assert config.read_bytes() == b"caller_owned = true\n"


def test_skill_suite_cli_invalid_scope_does_not_echo_supplied_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    supplied = str(tmp_path / "API_KEY=sk-proj-secret-path")
    monkeypatch.delenv("KOKOROARC_DATA_DIR", raising=False)

    assert (
        cli.main(
            [
                "suite",
                "install",
                "--scope",
                "user",
                "--repo",
                supplied,
                "--dry-run",
                "--json",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    assert captured.err == ""
    body = json.loads(captured.out)
    assert body["error"]["code"] == "SKILL_SUITE_PATH_INVALID"
    assert "sk-proj-secret-path" not in captured.out
