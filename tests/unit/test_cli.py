import subprocess
import sys
import json
import os

import pytest

from kokoroarc.cli import build_parser


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
    assert body == {
        "ok": False,
        "error": {
            "code": "DATA_DIR_REQUIRED",
            "message": "Set KOKOROARC_DATA_DIR before running a stateful command.",
            "retryable": False,
            "details": {},
        },
    }
    assert completed.stderr == ""


def test_json_session_show_succeeds_with_configured_data_directory(tmp_path) -> None:
    env = os.environ.copy()
    env["KOKOROARC_DATA_DIR"] = str(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-m", "kokoroarc.cli", "session", "show", "--json"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {"ok": True, "session": None}
    assert completed.stderr == ""


@pytest.mark.parametrize("arguments", [[], ["session"]])
def test_incomplete_commands_return_sanitized_json_errors(
    arguments: list[str],
) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "kokoroarc.cli", *arguments],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout) == {
        "ok": False,
        "error": {
            "code": "ARGUMENT_INVALID",
            "message": "Command arguments are invalid.",
            "retryable": False,
            "details": {},
        },
    }
    assert len(completed.stdout.splitlines()) == 1
    assert completed.stderr == ""


@pytest.mark.parametrize(
    "arguments",
    [
        ["character", "PRIVATE-INVALID-SUBCOMMAND"],
        ["character", "request", "PRIVATE-REQUEST-SUBCOMMAND"],
        ["character", "draft", "PRIVATE-DRAFT-SUBCOMMAND"],
        [
            "character",
            "draft",
            "compile",
            "--request",
            "request.json",
            "--pack",
            "pack",
            "--output",
            r"D:\PRIVATE\dossier-output",
        ],
        [
            "character",
            "draft",
            "compile",
            "--request",
            "request.json",
            "--pack",
            "pack",
            "--publish",
            "PRIVATE-PUBLISH-PAYLOAD",
        ],
        [
            "character",
            "draft",
            "compile",
            "--request",
            "request.json",
            "--pack",
            "pack",
            "--activate",
            r"D:\PRIVATE\activate-path",
        ],
        [
            "character",
            "draft",
            "validate",
            "--request",
            "request.json",
            "--pack",
            "pack",
            r"D:\PRIVATE\extra-dossier-token",
        ],
    ],
)
def test_invalid_character_arguments_never_echo_private_values(
    arguments: list[str],
) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "kokoroarc.cli", *arguments],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout) == {
        "ok": False,
        "error": {
            "code": "ARGUMENT_INVALID",
            "message": "Command arguments are invalid.",
            "retryable": False,
            "details": {},
        },
    }
    assert len(completed.stdout.splitlines()) == 1
    assert "PRIVATE" not in completed.stdout
    assert "usage:" not in completed.stdout
    assert "unrecognized arguments" not in completed.stdout
    assert completed.stderr == ""


def test_nested_character_help_remains_a_successful_stdout_exit() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "kokoroarc.cli",
            "character",
            "draft",
            "compile",
            "--help",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stdout.startswith("usage: kokoro character draft compile")
    assert completed.stderr == ""


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (
            ["character", "request", "validate", "--input", "request.json", "--json"],
            {
                "command": "character",
                "character_command": "request",
                "request_command": "validate",
                "input": "request.json",
                "json": True,
            },
        ),
        (
            [
                "character",
                "draft",
                "validate",
                "--request",
                "request.json",
                "--pack",
                "pack",
                "--json",
            ],
            {
                "command": "character",
                "character_command": "draft",
                "draft_command": "validate",
                "request": "request.json",
                "pack": "pack",
                "research_bundle": None,
                "json": True,
            },
        ),
        (
            [
                "character",
                "draft",
                "compile",
                "--request",
                "request.json",
                "--pack",
                "pack",
                "--json",
            ],
            {
                "command": "character",
                "character_command": "draft",
                "draft_command": "compile",
                "request": "request.json",
                "pack": "pack",
                "research_bundle": None,
                "json": True,
            },
        ),
    ],
)
def test_character_authoring_parser_leaves(
    arguments: list[str], expected: dict[str, object]
) -> None:
    assert vars(build_parser().parse_args(arguments)) == expected


def test_character_draft_parser_accepts_trusted_research_bundle_path() -> None:
    parsed = build_parser().parse_args(
        [
            "character",
            "draft",
            "validate",
            "--request",
            "request.json",
            "--pack",
            "pack",
            "--research-bundle",
            "private-bundle",
            "--json",
        ]
    )

    assert parsed.research_bundle == "private-bundle"


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (
            ["research", "request", "validate", "--input", "request.json", "--json"],
            {
                "command": "research",
                "research_group": "request",
                "research_request_command": "validate",
                "input": "request.json",
                "json": True,
            },
        ),
        (
            [
                "research",
                "workspace",
                "validate",
                "--workspace",
                "workspace",
                "--json",
            ],
            {
                "command": "research",
                "research_group": "workspace",
                "research_workspace_command": "validate",
                "workspace": "workspace",
                "json": True,
            },
        ),
        (
            [
                "research",
                "bundle",
                "compile",
                "--workspace",
                "workspace",
                "--json",
            ],
            {
                "command": "research",
                "research_group": "bundle",
                "research_bundle_command": "compile",
                "workspace": "workspace",
                "json": True,
            },
        ),
        (
            [
                "research",
                "bundle",
                "validate",
                "--bundle",
                "bundle",
                "--json",
            ],
            {
                "command": "research",
                "research_group": "bundle",
                "research_bundle_command": "validate",
                "bundle": "bundle",
                "json": True,
            },
        ),
    ],
)
def test_research_parser_leaves(
    arguments: list[str], expected: dict[str, object]
) -> None:
    assert vars(build_parser().parse_args(arguments)) == expected


@pytest.mark.parametrize(
    "forbidden",
    [
        ["--output", "elsewhere"],
        ["--output-path", "elsewhere"],
        ["--publish"],
        ["--activate"],
    ],
)
def test_character_draft_compile_rejects_user_selected_destination_or_lifecycle_flags(
    forbidden: list[str],
) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "character",
                "draft",
                "compile",
                "--request",
                "request.json",
                "--pack",
                "pack",
                *forbidden,
            ]
        )


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (
            [
                "pack",
                "test",
                "pack",
                "--request",
                "request.json",
                "--research-bundle",
                "bundle",
                "--out",
                "hard.json",
                "--json",
            ],
            {
                "command": "pack",
                "pack_command": "test",
                "source_dir": "pack",
                "request": "request.json",
                "research_bundle": "bundle",
                "out": "hard.json",
                "json": True,
            },
        ),
        (
            [
                "pack",
                "soft-eval",
                "soft-input.json",
                "--out",
                "soft.json",
                "--json",
            ],
            {
                "command": "pack",
                "pack_command": "soft-eval",
                "input": "soft-input.json",
                "out": "soft.json",
                "json": True,
            },
        ),
        (
            [
                "pack",
                "promote",
                "pack",
                "--target",
                "verified",
                "--promotion-id",
                "rin-promotion-verified-02",
                "--request",
                "request.json",
                "--hard-report",
                "hard.json",
                "--review",
                "review.json",
                "--previous",
                "reviewed.json",
                "--soft-input",
                "soft-input.json",
                "--soft-report",
                "soft.json",
                "--research-bundle",
                "bundle",
                "--out",
                "promotions/rin-aster/rin-promotion-verified-02/promotion.json",
                "--json",
            ],
            {
                "command": "pack",
                "pack_command": "promote",
                "source_dir": "pack",
                "target": "verified",
                "promotion_id": "rin-promotion-verified-02",
                "request": "request.json",
                "hard_report": "hard.json",
                "review": "review.json",
                "previous": "reviewed.json",
                "soft_input": "soft-input.json",
                "soft_report": "soft.json",
                "research_bundle": "bundle",
                "out": (
                    "promotions/rin-aster/rin-promotion-verified-02/"
                    "promotion.json"
                ),
                "json": True,
            },
        ),
        (
            [
                "pack",
                "publication-check",
                "pack",
                "--promotion",
                "verified.json",
                "--request",
                "request.json",
                "--hard-report",
                "hard.json",
                "--review",
                "review.json",
                "--previous",
                "reviewed.json",
                "--soft-input",
                "soft-input.json",
                "--soft-report",
                "soft.json",
                "--research-bundle",
                "bundle",
                "--visibility",
                "public_candidate",
                "--compliance",
                "compliance.json",
                "--out",
                "publication.json",
                "--json",
            ],
            {
                "command": "pack",
                "pack_command": "publication-check",
                "source_dir": "pack",
                "promotion": "verified.json",
                "request": "request.json",
                "hard_report": "hard.json",
                "review": "review.json",
                "previous": "reviewed.json",
                "soft_input": "soft-input.json",
                "soft_report": "soft.json",
                "research_bundle": "bundle",
                "visibility": "public_candidate",
                "compliance": "compliance.json",
                "out": "publication.json",
                "json": True,
            },
        ),
    ],
)
def test_pack_testing_parser_leaves(
    arguments: list[str], expected: dict[str, object]
) -> None:
    assert vars(build_parser().parse_args(arguments)) == expected


@pytest.mark.parametrize(
    "arguments",
    [
        ["pack", "test", "pack", "--request", "request.json"],
        ["pack", "soft-eval", "input.json"],
        [
            "pack",
            "promote",
            "pack",
            "--target",
            "reviewed",
            "--promotion-id",
            "reviewed-01",
            "--request",
            "request.json",
            "--hard-report",
            "hard.json",
            "--review",
            "review.json",
        ],
        [
            "pack",
            "publication-check",
            "pack",
            "--promotion",
            "verified.json",
            "--request",
            "request.json",
            "--hard-report",
            "hard.json",
            "--review",
            "review.json",
            "--previous",
            "reviewed.json",
            "--soft-input",
            "input.json",
            "--soft-report",
            "soft.json",
            "--visibility",
            "private",
        ],
    ],
)
def test_pack_testing_commands_require_explicit_output(arguments: list[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(arguments)
