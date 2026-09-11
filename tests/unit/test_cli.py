import subprocess
import sys
import json
import os

import pytest

from kokorox.cli import build_parser
from kokorox import __version__


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (
            [
                "config",
                "default",
                "set",
                "--character",
                "rin-aster",
                "--json",
            ],
            {
                "command": "config",
                "config_command": "default",
                "default_command": "set",
                "character": "rin-aster",
                "namespace": "original",
                "version": None,
                "scope": "global",
                "workspace": None,
                "json": True,
            },
        ),
        (
            [
                "config",
                "default",
                "set",
                "--character",
                "rin-aster",
                "--namespace",
                "original",
                "--version",
                "1.0.0",
                "--scope",
                "workspace",
                "--workspace",
                "D:/workspace",
                "--json",
            ],
            {
                "command": "config",
                "config_command": "default",
                "default_command": "set",
                "character": "rin-aster",
                "namespace": "original",
                "version": "1.0.0",
                "scope": "workspace",
                "workspace": "D:/workspace",
                "json": True,
            },
        ),
        (
            ["config", "default", "show", "--json"],
            {
                "command": "config",
                "config_command": "default",
                "default_command": "show",
                "scope": "global",
                "workspace": None,
                "json": True,
            },
        ),
        (
            ["config", "default", "clear", "--json"],
            {
                "command": "config",
                "config_command": "default",
                "default_command": "clear",
                "scope": "global",
                "workspace": None,
                "json": True,
            },
        ),
    ],
)
def test_config_default_parser_leaves(
    arguments: list[str],
    expected: dict[str, object],
) -> None:
    assert vars(build_parser().parse_args(arguments)) == expected


@pytest.mark.parametrize(
    "arguments",
    [
        [
            "config",
            "default",
            "show",
            "--scope",
            "global",
            "--workspace",
            r"D:\PRIVATE\workspace",
            "--json",
        ],
        [
            "config",
            "default",
            "clear",
            "--scope",
            "workspace",
            "--json",
        ],
    ],
)
def test_invalid_config_default_scope_arguments_are_sanitized(
    arguments: list[str],
    tmp_path,
) -> None:
    data_root = tmp_path / "must-not-be-created"
    environment = os.environ.copy()
    environment["KOKOROX_DATA_DIR"] = str(data_root)
    completed = subprocess.run(
        [sys.executable, "-m", "kokorox.cli", *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
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
    assert "PRIVATE" not in completed.stdout
    assert completed.stderr == ""
    assert not data_root.exists()


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (
            ["session", "start", "--session", "s-global", "--json"],
            {
                "command": "session",
                "session_command": "start",
                "character": None,
                "session": "s-global",
                "workspace": None,
                "json": True,
            },
        ),
        (
            [
                "session",
                "start",
                "--session",
                "s-workspace",
                "--workspace",
                "D:/workspace",
                "--json",
            ],
            {
                "command": "session",
                "session_command": "start",
                "character": None,
                "session": "s-workspace",
                "workspace": "D:/workspace",
                "json": True,
            },
        ),
    ],
)
def test_session_start_parser_supports_default_resolution(
    arguments: list[str],
    expected: dict[str, object],
) -> None:
    assert vars(build_parser().parse_args(arguments)) == expected


def test_module_version_command() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "kokorox.cli", "--version"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == f"kokorox {__version__}"


def test_json_error_when_data_directory_is_missing() -> None:
    env = os.environ.copy()
    env.pop("KOKOROX_DATA_DIR", None)
    completed = subprocess.run(
        [sys.executable, "-m", "kokorox.cli", "session", "show", "--json"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    body = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert body == {
        "ok": False,
        "error": {
            "code": "DATA_DIR_REQUIRED",
            "message": "Set KOKOROX_DATA_DIR before running a stateful command.",
            "retryable": False,
            "details": {},
        },
    }
    assert completed.stderr == ""


def test_json_session_show_succeeds_with_configured_data_directory(tmp_path) -> None:
    env = os.environ.copy()
    env["KOKOROX_DATA_DIR"] = str(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-m", "kokorox.cli", "session", "show", "--json"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
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
        [sys.executable, "-m", "kokorox.cli", *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
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
        [sys.executable, "-m", "kokorox.cli", *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
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
            "kokorox.cli",
            "character",
            "draft",
            "compile",
            "--help",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0
    assert completed.stdout.startswith("usage: kokorox character draft compile")
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
                "profile": "default-release",
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


def test_runtime_plan_parser_accepts_an_optional_context_path() -> None:
    parser = build_parser()

    without = parser.parse_args(
        ["runtime", "plan", "--semantic", "s.json", "--policy", "p.json", "--json"]
    )
    with_context = parser.parse_args(
        [
            "runtime",
            "plan",
            "--semantic",
            "s.json",
            "--policy",
            "p.json",
            "--context",
            "c.json",
            "--json",
        ]
    )

    assert without.context is None
    assert with_context.context == "c.json"


def test_runtime_context_body_accepts_the_envelope_the_cli_prints() -> None:
    """`runtime context > file` writes the envelope, so `--context` reads it."""

    from kokorox.cli import _runtime_context_body

    inner = {"character_id": "rin-aster", "expressions": {}}

    assert _runtime_context_body({"ok": True, "context": inner}) == inner
    assert _runtime_context_body(inner) == inner


def test_runtime_context_body_refuses_an_error_envelope() -> None:
    """Planning from a failed context would silence the character silently."""

    from kokorox.cli import _runtime_context_body
    from kokorox.errors import KokoroError

    with pytest.raises(KokoroError) as raised:
        _runtime_context_body(
            {"ok": False, "error": {"code": "SESSION_NOT_ACTIVE"}}
        )
    assert raised.value.code == "INVALID_RUNTIME_CONTEXT_INPUT"


@pytest.mark.parametrize("value", [None, [], "context", 7, True])
def test_runtime_context_body_refuses_a_non_object(value: object) -> None:
    """A malformed file is a caller error, not a reason to go quiet."""

    from kokorox.cli import _runtime_context_body
    from kokorox.errors import KokoroError

    with pytest.raises(KokoroError) as raised:
        _runtime_context_body(value)
    assert raised.value.code == "INVALID_RUNTIME_CONTEXT_INPUT"


def test_every_raised_error_code_has_a_public_message() -> None:
    """A family got public messages only once a report named it, so most never did.

    133 codes -- session, runtime, policy, promotion, persistence -- reached
    callers as "Command could not be completed". This keeps the table whole:
    every literal code raised in `src/kokorox` must carry its own message.
    """

    import ast
    import re
    from pathlib import Path

    from kokorox.cli import _PUBLIC_MESSAGES

    code_shape = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")
    missing: set[str] = set()
    for path in Path("src/kokorox").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else ""
            )
            if name != "KokoroError" and not name.endswith("_error"):
                continue
            first = node.args[0]
            if (
                isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and code_shape.match(first.value)
                and first.value not in _PUBLIC_MESSAGES
            ):
                missing.add(first.value)

    assert sorted(missing) == []


@pytest.mark.parametrize(
    ("code", "details", "kept"),
    [
        (
            "PLAN_CONCLUSION_LANGUAGE_MISMATCH",
            {"expected": "zh-CN", "actual": "ja-JP"},
            {"expected": "zh-CN", "actual": "ja-JP"},
        ),
        (
            "PLAN_CONCLUSION_LANGUAGE_MISMATCH",
            {"expected": "zh-CN", "actual": "<script>"},
            {},
        ),
        (
            "AUTHORING_VALIDATION_FAILED",
            {"failures": ["AUTHORING_IDENTITY_MISMATCH"]},
            {"failures": ["AUTHORING_IDENTITY_MISMATCH"]},
        ),
        ("AUTHORING_VALIDATION_FAILED", {"failures": ["not a code"]}, {}),
        (
            "MIGRATION_UNAVAILABLE",
            {"supported": ["0.9.0 -> 1.0.0"]},
            {"supported": ["0.9.0 -> 1.0.0"]},
        ),
        ("MIGRATION_UNAVAILABLE", {"supported": ["../../etc/passwd"]}, {}),
        (
            "PERSISTENCE_INSTALLATION_STALE",
            {"reason": "resolution"},
            {"reason": "resolution"},
        ),
        ("PERSISTENCE_INSTALLATION_STALE", {"reason": "C:\\secret"}, {}),
    ],
)
def test_actionable_details_survive_sanitization_and_nothing_else_does(
    code: str, details: dict[str, object], kept: dict[str, object]
) -> None:
    from kokorox.cli import _public_error_envelope
    from kokorox.errors import KokoroError

    envelope = _public_error_envelope(
        KokoroError(code, "internal detail", details=details)
    )["error"]

    assert envelope["details"] == kept
