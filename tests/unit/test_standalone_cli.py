from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

import kokoroarc.cli as cli
from kokoroarc.cli import build_parser
from kokoroarc.standalone_cli import (
    standalone_requires_data_root,
    standalone_route,
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
