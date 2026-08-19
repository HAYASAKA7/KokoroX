from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import pytest

import kokoroarc.cli as cli
from kokoroarc.cli import build_parser
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.standalone_cli import (
    standalone_requires_data_root,
    standalone_route,
)

from karc_test_support import (
    archive_documents,
    build_private_archive,
    build_public_archive,
    make_legacy_090_archive,
)


def _cli_json(
    arguments: list[str],
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, dict[str, Any]]:
    result = cli.main(arguments)
    captured = capsys.readouterr()
    assert captured.err == ""
    return result, json.loads(captured.out)


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


def _install_and_grant_cli(
    release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    permissions: str,
) -> tuple[Path, dict[str, Any]]:
    source = tmp_path / "rin.karc"
    source.write_bytes(build_private_archive(release))
    data_root = tmp_path / "data"
    monkeypatch.setenv("KOKOROARC_DATA_DIR", str(data_root))
    code, _installed = _cli_json(
        ["pack", "install", str(source), "--json"],
        capsys,
    )
    assert code == 0
    code, granted = _cli_json(
        [
            "consent",
            "grant",
            "--character",
            "rin-aster",
            "--scope",
            "global",
            "--permissions",
            permissions,
            "--json",
        ],
        capsys,
    )
    assert code == 0
    return data_root, granted["consent"]


@pytest.mark.parametrize(
    ("arguments", "route", "requires_data_root"),
    [
        (
            [
                "pack",
                "export",
                "--compiled",
                "compiled.json",
                "--promotion",
                "promotion.json",
                "--hard-report",
                "hard.json",
                "--soft-report",
                "soft.json",
                "--out",
                "rin.karc",
                "--json",
            ],
            ("pack", "export"),
            False,
        ),
        (
            ["pack", "compatibility", "rin.karc", "--json"],
            ("pack", "compatibility"),
            False,
        ),
        (
            [
                "pack",
                "migrate",
                "rin.karc",
                "--to-format",
                "1.0.0",
                "--out",
                "new.karc",
                "--dry-run",
                "--json",
            ],
            ("pack", "migrate"),
            False,
        ),
        (
            ["pack", "install", "rin.karc", "--dry-run", "--json"],
            ("pack", "install"),
            True,
        ),
        (
            [
                "pack",
                "list",
                "--scope",
                "workspace",
                "--workspace",
                "D:/workspace",
                "--json",
            ],
            ("pack", "list"),
            True,
        ),
        (
            [
                "pack",
                "remove",
                "rin-aster",
                "--version",
                "1.0.0",
                "--dry-run",
                "--json",
            ],
            ("pack", "remove"),
            True,
        ),
        (
            [
                "consent",
                "grant",
                "--character",
                "rin-aster",
                "--scope",
                "global",
                "--permissions",
                "relationship_state,memory_references",
                "--json",
            ],
            ("consent", "grant"),
            True,
        ),
        (
            ["consent", "show", "--character", "rin-aster", "--json"],
            ("consent", "show"),
            True,
        ),
        (
            ["consent", "revoke", "--character", "rin-aster", "--json"],
            ("consent", "revoke"),
            True,
        ),
        (
            [
                "state",
                "export",
                "--character",
                "rin-aster",
                "--out",
                "state.json",
                "--json",
            ],
            ("state", "export"),
            True,
        ),
        (
            [
                "state",
                "reset",
                "--character",
                "rin-aster",
                "--part",
                "all",
                "--dry-run",
                "--json",
            ],
            ("state", "reset"),
            True,
        ),
        (
            [
                "memory",
                "add",
                "--character",
                "rin-aster",
                "--host-id",
                "host-memory-1",
                "--summary-file",
                "summary.json",
                "--json",
            ],
            ("memory", "add"),
            True,
        ),
        (
            ["memory", "list", "--character", "rin-aster", "--json"],
            ("memory", "list"),
            True,
        ),
        (
            [
                "memory",
                "remove",
                "--character",
                "rin-aster",
                "--host-id",
                "host-memory-1",
                "--dry-run",
                "--json",
            ],
            ("memory", "remove"),
            True,
        ),
        (
            ["suite", "install", "--dry-run", "--json"],
            ("suite", "install"),
            False,
        ),
    ],
)
def test_parses_standalone_routes(
    arguments: list[str],
    route: tuple[str, str],
    requires_data_root: bool,
) -> None:
    parsed = build_parser().parse_args(arguments)

    assert standalone_route(parsed) == route
    assert standalone_requires_data_root(parsed) is requires_data_root


def test_pack_export_parser_accepts_publication_report() -> None:
    parsed = build_parser().parse_args(
        [
            "pack",
            "export",
            "--compiled",
            "compiled.json",
            "--promotion",
            "promotion.json",
            "--hard-report",
            "hard.json",
            "--soft-report",
            "soft.json",
            "--publication-report",
            "publication.json",
            "--out",
            "rin.karc",
            "--json",
        ]
    )

    assert parsed.publication_report == "publication.json"


def test_standalone_scope_defaults_are_global() -> None:
    parser = build_parser()

    for arguments in (
        ["pack", "install", "rin.karc", "--json"],
        ["pack", "list", "--json"],
        ["consent", "show", "--character", "rin-aster", "--json"],
        [
            "state",
            "export",
            "--character",
            "rin-aster",
            "--out",
            "state.json",
            "--json",
        ],
        ["memory", "list", "--character", "rin-aster", "--json"],
    ):
        parsed = parser.parse_args(arguments)
        assert parsed.scope == "global"
        assert parsed.workspace is None


def test_consent_grant_requires_explicit_scope() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "consent",
                "grant",
                "--character",
                "rin-aster",
                "--permissions",
                "relationship_state",
                "--json",
            ]
        )


def test_suite_scope_defaults_to_user() -> None:
    parsed = build_parser().parse_args(
        ["suite", "install", "--dry-run", "--json"]
    )

    assert parsed.scope == "user"
    assert parsed.repo is None
    assert parsed.skills_root is None


def test_existing_state_route_is_not_claimed_by_standalone_adapter() -> None:
    parsed = build_parser().parse_args(
        [
            "state",
            "preview",
            "--session",
            "session-1",
            "--event",
            "event.json",
            "--json",
        ]
    )

    assert standalone_route(parsed) is None


@pytest.mark.parametrize(
    "arguments",
    [
        ["pack", "compatibility", "--json"],
        ["pack", "migrate", "rin.karc", "--to-format", "1.0.0", "--json"],
        ["pack", "remove", "rin-aster", "--json"],
        ["state", "reset", "--character", "rin-aster", "--json"],
        ["memory", "add", "--character", "rin-aster", "--json"],
        ["suite", "install", "--scope", "machine", "--json"],
    ],
)
def test_standalone_parser_rejects_incomplete_or_unknown_arguments(
    arguments: list[str],
) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(arguments)


def test_route_helpers_reject_incomplete_namespace() -> None:
    incomplete = argparse.Namespace(command="suite")

    assert standalone_route(incomplete) is None
    assert standalone_requires_data_root(incomplete) is False


def test_main_dispatches_read_only_route_without_data_root(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, Any] = {}

    def fake_handler(
        args: argparse.Namespace,
        data_root: Path | None,
        schemas: object,
    ) -> dict[str, Any]:
        observed.update(
            {
                "route": standalone_route(args),
                "data_root": data_root,
                "schemas": schemas,
            }
        )
        return {"ok": True, "compatibility": {"compatible": True}}

    monkeypatch.delenv("KOKOROARC_DATA_DIR", raising=False)
    monkeypatch.setattr(cli, "handle_standalone", fake_handler)

    assert cli.main(["pack", "compatibility", "rin.karc", "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "ok": True,
        "compatibility": {"compatible": True},
    }
    assert captured.err == ""
    assert observed["route"] == ("pack", "compatibility")
    assert observed["data_root"] is None
    assert observed["schemas"] is not None


def test_main_dispatches_stateful_route_with_data_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, Any] = {}

    def fake_handler(
        args: argparse.Namespace,
        data_root: Path | None,
        schemas: object,
    ) -> dict[str, Any]:
        observed.update(
            {
                "route": standalone_route(args),
                "data_root": data_root,
                "schemas": schemas,
            }
        )
        return {"ok": True, "installed": []}

    monkeypatch.setenv("KOKOROARC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "handle_standalone", fake_handler)

    assert cli.main(["pack", "list", "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"ok": True, "installed": []}
    assert captured.err == ""
    assert observed["route"] == ("pack", "list")
    assert observed["data_root"] == tmp_path
    assert observed["schemas"] is not None


def test_pack_compatibility_inspects_archive_without_persistent_state(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = build_private_archive(rin_verified_release)
    archive_path = tmp_path / "rin.karc"
    archive_path.write_bytes(archive)
    before = tuple(sorted(path.name for path in tmp_path.iterdir()))
    monkeypatch.delenv("KOKOROARC_DATA_DIR", raising=False)

    assert (
        cli.main(["pack", "compatibility", str(archive_path), "--json"])
        == 0
    )

    captured = capsys.readouterr()
    body = json.loads(captured.out)
    assert captured.err == ""
    assert body["ok"] is True
    assert body["compatibility"]["compatible"] is True
    assert body["compatibility"]["installation_allowed"] is True
    assert archive_path.read_bytes() == archive
    assert tuple(sorted(path.name for path in tmp_path.iterdir())) == before


def test_pack_export_writes_exact_private_archive_once(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = build_private_archive(rin_verified_release)
    documents = archive_documents(expected)
    promotion_dir = tmp_path / "published-promotion"
    promotion_dir.mkdir()
    inputs = {
        "compiled": tmp_path / "compiled.json",
        "promotion": promotion_dir / "promotion.json",
        "hard": tmp_path / "hard.json",
        "soft": tmp_path / "soft.json",
        "review": promotion_dir / "review-attestation.json",
    }
    by_name = {
        "compiled": "pack/compiled.json",
        "promotion": "release/promotion-record.json",
        "hard": "release/hard-validation-report.json",
        "soft": "release/soft-evaluation-report.json",
        "review": "release/review-attestation.json",
    }
    for name, path in inputs.items():
        path.write_bytes(canonical_bytes(documents[by_name[name]]))
    output = tmp_path / "rin.karc"
    monkeypatch.delenv("KOKOROARC_DATA_DIR", raising=False)

    assert (
        cli.main(
            [
                "pack",
                "export",
                "--compiled",
                str(inputs["compiled"]),
                "--promotion",
                str(inputs["promotion"]),
                "--hard-report",
                str(inputs["hard"]),
                "--soft-report",
                str(inputs["soft"]),
                "--out",
                str(output),
                "--json",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "ok": True,
        "path": str(output.resolve()),
        "archive_sha256": sha256(expected).hexdigest(),
        "visibility": "private",
    }
    assert output.read_bytes() == expected


def test_pack_export_binds_publication_report_for_public_archive(
    rin_public_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = build_public_archive(rin_public_verified_release)
    documents = archive_documents(expected)
    promotion_dir = tmp_path / "published-promotion"
    promotion_dir.mkdir()
    inputs = {
        "compiled": tmp_path / "compiled.json",
        "promotion": promotion_dir / "promotion.json",
        "hard": tmp_path / "hard.json",
        "soft": tmp_path / "soft.json",
        "review": promotion_dir / "review-attestation.json",
        "publication": tmp_path / "publication.json",
    }
    by_name = {
        "compiled": "pack/compiled.json",
        "promotion": "release/promotion-record.json",
        "hard": "release/hard-validation-report.json",
        "soft": "release/soft-evaluation-report.json",
        "review": "release/review-attestation.json",
        "publication": "release/publication-readiness-report.json",
    }
    for name, path in inputs.items():
        path.write_bytes(canonical_bytes(documents[by_name[name]]))
    output = tmp_path / "rin-public.karc"
    monkeypatch.delenv("KOKOROARC_DATA_DIR", raising=False)

    assert (
        cli.main(
            [
                "pack",
                "export",
                "--compiled",
                str(inputs["compiled"]),
                "--promotion",
                str(inputs["promotion"]),
                "--hard-report",
                str(inputs["hard"]),
                "--soft-report",
                str(inputs["soft"]),
                "--publication-report",
                str(inputs["publication"]),
                "--out",
                str(output),
                "--json",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "ok": True,
        "path": str(output.resolve()),
        "archive_sha256": sha256(expected).hexdigest(),
        "visibility": "public_candidate",
    }
    assert output.read_bytes() == expected


def test_pack_migration_previews_then_writes_new_archive(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    current = build_private_archive(rin_verified_release)
    legacy = make_legacy_090_archive(current)
    source = tmp_path / "rin-legacy.karc"
    source.write_bytes(legacy)
    output = tmp_path / "rin-current.karc"
    monkeypatch.delenv("KOKOROARC_DATA_DIR", raising=False)
    arguments = [
        "pack",
        "migrate",
        str(source),
        "--to-format",
        "1.0.0",
        "--out",
        str(output),
        "--json",
    ]

    assert cli.main([*arguments[:-1], "--dry-run", "--json"]) == 0

    preview_capture = capsys.readouterr()
    preview = json.loads(preview_capture.out)
    assert preview_capture.err == ""
    assert preview["ok"] is True
    assert preview["dry_run"] is True
    assert preview["path"] == str(output.resolve())
    assert preview["plan"]["mode"] == "preview"
    assert preview["plan"]["input_archive_sha256"] == sha256(legacy).hexdigest()
    assert preview["plan"]["output_archive_sha256"] == sha256(current).hexdigest()
    assert not output.exists()

    assert cli.main(arguments) == 0

    applied_capture = capsys.readouterr()
    applied = json.loads(applied_capture.out)
    assert applied_capture.err == ""
    assert applied == {
        "ok": True,
        "dry_run": False,
        "path": str(output.resolve()),
        "archive_sha256": sha256(current).hexdigest(),
        "plan": {**preview["plan"], "mode": "applied"},
    }
    assert output.read_bytes() == current
    assert source.read_bytes() == legacy


def test_scoped_pack_cli_global_install_list_and_remove_workflow(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "rin.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    monkeypatch.setenv("KOKOROARC_DATA_DIR", str(data_root))
    install = ["pack", "install", str(source), "--json"]

    code, preview = _cli_json(
        ["pack", "install", str(source), "--dry-run", "--json"],
        capsys,
    )
    assert code == 0
    assert preview["ok"] is True
    assert preview["dry_run"] is True
    assert preview["plan"]["scope"] == "global"
    assert preview["plan"]["will_write"] is True
    assert preview["activates_character"] is False
    assert not data_root.exists()

    code, applied = _cli_json(install, capsys)
    assert code == 0
    assert applied["ok"] is True
    assert applied["dry_run"] is False
    assert applied["plan"]["scope"] == "global"
    assert applied["plan"]["idempotent"] is False
    assert applied["activates_character"] is False

    code, listed = _cli_json(["pack", "list", "--json"], capsys)
    assert code == 0
    assert listed["scope"] == "global"
    assert listed["workspace_id"] is None
    assert len(listed["installed"]) == 1
    assert listed["installed"][0]["registry_identity"] == (
        "original/rin-aster/1.0.0"
    )
    assert listed["activates_character"] is False

    code, repeated = _cli_json(install, capsys)
    assert code == 0
    assert repeated["plan"]["idempotent"] is True
    assert repeated["plan"]["will_write"] is False

    before = _filesystem_snapshot(data_root)
    code, removal_preview = _cli_json(
        [
            "pack",
            "remove",
            "rin-aster",
            "--version",
            "1.0.0",
            "--dry-run",
            "--json",
        ],
        capsys,
    )
    assert code == 0
    assert removal_preview["dry_run"] is True
    assert removal_preview["plan"]["will_write"] is False
    assert removal_preview["plan"]["archive_will_be_removed"] is True
    assert removal_preview["activates_character"] is False
    assert _filesystem_snapshot(data_root) == before

    code, removed = _cli_json(
        [
            "pack",
            "remove",
            "rin-aster",
            "--version",
            "1.0.0",
            "--json",
        ],
        capsys,
    )
    assert code == 0
    assert removed["dry_run"] is False
    assert removed["plan"]["operation"] == "remove"
    assert removed["activates_character"] is False

    code, empty = _cli_json(["pack", "list", "--json"], capsys)
    assert code == 0
    assert empty["installed"] == []


def test_scoped_pack_cli_workspace_dry_run_is_read_only(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "rin.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_root = tmp_path / "data"
    monkeypatch.setenv("KOKOROARC_DATA_DIR", str(data_root))
    before = _filesystem_snapshot(workspace)

    code, body = _cli_json(
        [
            "pack",
            "install",
            str(source),
            "--scope",
            "workspace",
            "--workspace",
            str(workspace),
            "--dry-run",
            "--json",
        ],
        capsys,
    )

    assert code == 0
    assert body["plan"]["scope"] == "workspace"
    assert len(body["plan"]["workspace_id"]) == 64
    assert body["activates_character"] is False
    assert not data_root.exists()
    assert _filesystem_snapshot(workspace) == before


def test_scoped_pack_cli_empty_list_does_not_create_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_root = tmp_path / "data"
    monkeypatch.setenv("KOKOROARC_DATA_DIR", str(data_root))

    code, body = _cli_json(["pack", "list", "--json"], capsys)

    assert code == 0
    assert body == {
        "ok": True,
        "scope": "global",
        "workspace_id": None,
        "installed": [],
        "activates_character": False,
    }
    assert not data_root.exists()


@pytest.mark.parametrize(
    "arguments",
    [
        ["pack", "list", "--scope", "workspace", "--json"],
        [
            "pack",
            "list",
            "--scope",
            "workspace",
            "--workspace",
            "",
            "--json",
        ],
        [
            "pack",
            "list",
            "--scope",
            "global",
            "--workspace",
            "D:/unexpected",
            "--json",
        ],
    ],
)
def test_scoped_pack_cli_rejects_mismatched_workspace_arguments(
    arguments: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("KOKOROARC_DATA_DIR", str(tmp_path / "data"))

    code, body = _cli_json(arguments, capsys)

    assert code == 2
    assert body["error"]["code"] == "ARGUMENT_INVALID"
    assert not (tmp_path / "data").exists()


def test_consent_cli_grant_show_replace_and_revoke_lifecycle(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "rin.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    monkeypatch.setenv("KOKOROARC_DATA_DIR", str(data_root))
    code, _installed = _cli_json(
        ["pack", "install", str(source), "--json"],
        capsys,
    )
    assert code == 0
    grant = [
        "consent",
        "grant",
        "--character",
        "rin-aster",
        "--scope",
        "global",
        "--permissions",
        "memory_references,relationship_state",
        "--json",
    ]

    code, first = _cli_json(grant, capsys)
    assert code == 0, first
    assert first["consent"]["status"] == "active"
    assert first["consent"]["grant_revision"] == 1
    assert first["consent"]["permissions"] == [
        "relationship_state",
        "memory_references",
    ]

    code, shown = _cli_json(
        ["consent", "show", "--character", "rin-aster", "--json"],
        capsys,
    )
    assert code == 0
    assert shown == {"ok": True, "consent": first["consent"]}

    code, repeated = _cli_json(grant, capsys)
    assert code == 0
    assert repeated == first

    code, replaced = _cli_json(
        [
            "consent",
            "grant",
            "--character",
            "rin-aster",
            "--scope",
            "global",
            "--permissions",
            "mood_state",
            "--json",
        ],
        capsys,
    )
    assert code == 0
    assert replaced["consent"]["grant_revision"] == 2
    assert replaced["consent"]["permissions"] == ["mood_state"]

    code, revoked = _cli_json(
        ["consent", "revoke", "--character", "rin-aster", "--json"],
        capsys,
    )
    assert code == 0
    assert revoked["consent"]["status"] == "revoked"
    assert revoked["consent"]["revoked_revision"] == 3

    code, final = _cli_json(
        ["consent", "show", "--character", "rin-aster", "--json"],
        capsys,
    )
    assert code == 0
    assert final == revoked


def test_consent_cli_rejects_invalid_permission_list_without_mutation(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "rin.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    data_root = tmp_path / "data"
    monkeypatch.setenv("KOKOROARC_DATA_DIR", str(data_root))
    code, _installed = _cli_json(
        ["pack", "install", str(source), "--json"],
        capsys,
    )
    assert code == 0
    before = _filesystem_snapshot(data_root)

    code, body = _cli_json(
        [
            "consent",
            "grant",
            "--character",
            "rin-aster",
            "--scope",
            "global",
            "--permissions",
            "relationship_state,,memory_references",
            "--json",
        ],
        capsys,
    )

    assert code == 2
    assert body["error"]["code"] == "ARGUMENT_INVALID"
    assert _filesystem_snapshot(data_root) == before


def test_consent_cli_workspace_scope_is_isolated_and_absent_show_is_read_only(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "rin.karc"
    source.write_bytes(build_private_archive(rin_verified_release))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_root = tmp_path / "data"
    monkeypatch.setenv("KOKOROARC_DATA_DIR", str(data_root))

    code, absent = _cli_json(
        ["consent", "show", "--character", "rin-aster", "--json"],
        capsys,
    )
    assert code == 0
    assert absent == {"ok": True, "consent": None}
    assert not data_root.exists()

    code, _installed = _cli_json(
        [
            "pack",
            "install",
            str(source),
            "--scope",
            "workspace",
            "--workspace",
            str(workspace),
            "--json",
        ],
        capsys,
    )
    assert code == 0
    code, granted = _cli_json(
        [
            "consent",
            "grant",
            "--character",
            "rin-aster",
            "--scope",
            "workspace",
            "--workspace",
            str(workspace),
            "--permissions",
            "relationship_state",
            "--json",
        ],
        capsys,
    )
    assert code == 0
    assert granted["consent"]["scope"] == "workspace"
    assert len(granted["consent"]["workspace_id"]) == 64

    code, global_show = _cli_json(
        ["consent", "show", "--character", "rin-aster", "--json"],
        capsys,
    )
    assert code == 0
    assert global_show == {"ok": True, "consent": None}


def test_state_cli_exports_canonical_json_and_resets_every_part(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_root, _consent = _install_and_grant_cli(
        rin_verified_release,
        tmp_path,
        monkeypatch,
        capsys,
        permissions="relationship_state,mood_state,memory_references",
    )
    output = tmp_path / "persistent-state.json"

    code, exported = _cli_json(
        [
            "state",
            "export",
            "--character",
            "rin-aster",
            "--out",
            str(output),
            "--json",
        ],
        capsys,
    )
    assert code == 0
    document = json.loads(output.read_bytes())
    assert output.read_bytes() == canonical_bytes(document)
    assert exported == {
        "ok": True,
        "export_sha256": document["export_sha256"],
    }

    for target in ("relationship", "mood", "memory", "all"):
        before = _filesystem_snapshot(data_root)
        code, preview = _cli_json(
            [
                "state",
                "reset",
                "--character",
                "rin-aster",
                "--part",
                target,
                "--dry-run",
                "--json",
            ],
            capsys,
        )
        assert code == 0
        assert preview["ok"] is True
        assert preview["dry_run"] is True
        assert preview["preview"]["target"] == target
        assert preview["preview"]["reset_id"].startswith("reset-")
        assert _filesystem_snapshot(data_root) == before

        code, applied = _cli_json(
            [
                "state",
                "reset",
                "--character",
                "rin-aster",
                "--part",
                target,
                "--json",
            ],
            capsys,
        )
        assert code == 0
        assert applied["ok"] is True
        assert applied["dry_run"] is False
        assert applied["preview"]["target"] == target
        assert applied["result"]["record_state"] == "committed"


def test_memory_cli_add_list_remove_and_revoked_generation_lifecycle(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_root, _consent = _install_and_grant_cli(
        rin_verified_release,
        tmp_path,
        monkeypatch,
        capsys,
        permissions="memory_references",
    )
    summary_file = tmp_path / "summary.json"
    summary = {
        "summary": "The user approved concise technical explanations.",
        "localized_summaries": {
            "zh-CN": "用户批准了简洁的技术说明。",
            "ja-JP": "簡潔な技術説明をユーザーが承認しました。",
            "en-US": "The user approved concise technical explanations.",
        },
    }
    summary_file.write_bytes(canonical_bytes(summary))
    add = [
        "memory",
        "add",
        "--character",
        "rin-aster",
        "--host-id",
        "host-memory-preference-01",
        "--summary-file",
        str(summary_file),
        "--json",
    ]

    code, added = _cli_json(add, capsys)
    assert code == 0
    reference = added["memory_reference"]
    assert reference["host_memory_id"] == "host-memory-preference-01"
    assert reference["localized_summaries"] == {
        locale: summary["localized_summaries"][locale]
        for locale in ("en-US", "ja-JP", "zh-CN")
    }
    code, repeated = _cli_json(add, capsys)
    assert code == 0
    assert repeated == added

    code, listed = _cli_json(
        ["memory", "list", "--character", "rin-aster", "--json"],
        capsys,
    )
    assert code == 0
    assert listed["memory_references"] == [
        {
            "reference": reference,
            "active_consent_generation": True,
        }
    ]

    before = _filesystem_snapshot(data_root)
    code, preview = _cli_json(
        [
            "memory",
            "remove",
            "--character",
            "rin-aster",
            "--host-id",
            "host-memory-preference-01",
            "--dry-run",
            "--json",
        ],
        capsys,
    )
    assert code == 0
    assert preview == {
        "ok": True,
        "dry_run": True,
        "plan": {
            "action": "remove_memory_reference",
            "host_memory_id": "host-memory-preference-01",
            "memory_reference_id": reference["memory_reference_id"],
            "will_remove": True,
        },
    }
    assert _filesystem_snapshot(data_root) == before

    code, revoked = _cli_json(
        ["consent", "revoke", "--character", "rin-aster", "--json"],
        capsys,
    )
    assert code == 0
    assert revoked["consent"]["status"] == "revoked"
    before_blocked_add = _filesystem_snapshot(data_root)
    code, blocked_add = _cli_json(
        [
            *add[: add.index("host-memory-preference-01")],
            "host-memory-preference-02",
            *add[add.index("host-memory-preference-01") + 1 :],
        ],
        capsys,
    )
    assert code == 2
    assert blocked_add["error"]["code"] == "PERSISTENCE_CONSENT_REVOKED"
    assert _filesystem_snapshot(data_root) == before_blocked_add
    code, stale = _cli_json(
        ["memory", "list", "--character", "rin-aster", "--json"],
        capsys,
    )
    assert code == 0
    assert stale["memory_references"][0]["active_consent_generation"] is False

    code, removed = _cli_json(
        [
            "memory",
            "remove",
            "--character",
            "rin-aster",
            "--host-id",
            "host-memory-preference-01",
            "--json",
        ],
        capsys,
    )
    assert code == 0
    assert removed == {
        "ok": True,
        "dry_run": False,
        "result": {
            "removed": True,
            "memory_reference_id": reference["memory_reference_id"],
        },
    }
    code, empty = _cli_json(
        ["memory", "list", "--character", "rin-aster", "--json"],
        capsys,
    )
    assert code == 0
    assert empty["memory_references"] == []
