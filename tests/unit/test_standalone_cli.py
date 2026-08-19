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
