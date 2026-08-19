from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

from kokoroarc.errors import KokoroError
from kokoroarc.schemas import SchemaRegistry


StandaloneRoute = tuple[str, str]

_PACK_ROUTES = frozenset(
    {
        "compatibility",
        "export",
        "install",
        "list",
        "migrate",
        "remove",
    }
)
_STATE_ROUTES = frozenset({"export", "reset"})
_TOP_LEVEL_ROUTES = frozenset({"consent", "memory", "suite"})
_DATA_ROOT_ROUTES = frozenset(
    {
        ("pack", "install"),
        ("pack", "list"),
        ("pack", "remove"),
        ("consent", "grant"),
        ("consent", "show"),
        ("consent", "revoke"),
        ("state", "export"),
        ("state", "reset"),
        ("memory", "add"),
        ("memory", "list"),
        ("memory", "remove"),
    }
)


def _add_json(
    parser: argparse.ArgumentParser,
    leaf_json: Callable[[argparse.ArgumentParser], None],
) -> None:
    leaf_json(parser)


def _add_scope(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--scope",
        choices=("global", "workspace"),
        default="global",
    )
    parser.add_argument("--workspace")


def _add_character(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--character", required=True)
    parser.add_argument("--namespace", default="original")


def add_standalone_parsers(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    pack_commands: argparse._SubParsersAction[argparse.ArgumentParser],
    state_commands: argparse._SubParsersAction[argparse.ArgumentParser],
    leaf_json: Callable[[argparse.ArgumentParser], None],
) -> None:
    pack_export = pack_commands.add_parser("export")
    pack_export.add_argument("--compiled", required=True)
    pack_export.add_argument("--promotion", required=True)
    pack_export.add_argument("--hard-report", required=True)
    pack_export.add_argument("--soft-report", required=True)
    pack_export.add_argument("--publication-report")
    pack_export.add_argument("--out", required=True)
    _add_json(pack_export, leaf_json)

    compatibility = pack_commands.add_parser("compatibility")
    compatibility.add_argument("archive")
    _add_json(compatibility, leaf_json)

    migrate = pack_commands.add_parser("migrate")
    migrate.add_argument("archive")
    migrate.add_argument("--to-format", required=True)
    migrate.add_argument("--out", required=True)
    migrate.add_argument("--dry-run", action="store_true")
    _add_json(migrate, leaf_json)

    install = pack_commands.add_parser("install")
    install.add_argument("archive")
    _add_scope(install)
    install.add_argument("--dry-run", action="store_true")
    _add_json(install, leaf_json)

    pack_list = pack_commands.add_parser("list")
    _add_scope(pack_list)
    _add_json(pack_list, leaf_json)

    remove = pack_commands.add_parser("remove")
    remove.add_argument("character_id")
    remove.add_argument("--version", required=True)
    remove.add_argument("--namespace", default="original")
    _add_scope(remove)
    remove.add_argument("--dry-run", action="store_true")
    _add_json(remove, leaf_json)

    consent = commands.add_parser("consent")
    consent_commands = consent.add_subparsers(
        dest="consent_command",
        required=True,
    )
    grant = consent_commands.add_parser("grant")
    _add_character(grant)
    grant.add_argument("--version")
    grant.add_argument(
        "--scope",
        choices=("global", "workspace"),
        required=True,
    )
    grant.add_argument("--workspace")
    grant.add_argument("--permissions", required=True)
    _add_json(grant, leaf_json)
    for name in ("show", "revoke"):
        command = consent_commands.add_parser(name)
        _add_character(command)
        _add_scope(command)
        _add_json(command, leaf_json)

    state_export = state_commands.add_parser("export")
    _add_character(state_export)
    _add_scope(state_export)
    state_export.add_argument("--out", required=True)
    _add_json(state_export, leaf_json)
    state_reset = state_commands.add_parser("reset")
    _add_character(state_reset)
    _add_scope(state_reset)
    state_reset.add_argument(
        "--part",
        choices=("mood", "relationship", "memory", "all"),
        required=True,
    )
    state_reset.add_argument("--dry-run", action="store_true")
    _add_json(state_reset, leaf_json)

    memory = commands.add_parser("memory")
    memory_commands = memory.add_subparsers(
        dest="memory_command",
        required=True,
    )
    memory_add = memory_commands.add_parser("add")
    _add_character(memory_add)
    _add_scope(memory_add)
    memory_add.add_argument("--host-id", required=True)
    memory_add.add_argument("--summary-file", required=True)
    _add_json(memory_add, leaf_json)
    memory_list = memory_commands.add_parser("list")
    _add_character(memory_list)
    _add_scope(memory_list)
    _add_json(memory_list, leaf_json)
    memory_remove = memory_commands.add_parser("remove")
    _add_character(memory_remove)
    _add_scope(memory_remove)
    memory_remove.add_argument("--host-id", required=True)
    memory_remove.add_argument("--dry-run", action="store_true")
    _add_json(memory_remove, leaf_json)

    suite = commands.add_parser("suite")
    suite_commands = suite.add_subparsers(
        dest="suite_command",
        required=True,
    )
    suite_install = suite_commands.add_parser("install")
    suite_install.add_argument(
        "--scope",
        choices=("user", "repo"),
        default="user",
    )
    suite_install.add_argument("--repo")
    suite_install.add_argument("--skills-root")
    suite_install.add_argument("--dry-run", action="store_true")
    _add_json(suite_install, leaf_json)


def standalone_route(args: argparse.Namespace) -> StandaloneRoute | None:
    command = getattr(args, "command", None)
    if command == "pack":
        subcommand = getattr(args, "pack_command", None)
        if subcommand in _PACK_ROUTES:
            return (command, subcommand)
        return None
    if command == "state":
        subcommand = getattr(args, "state_command", None)
        if subcommand in _STATE_ROUTES:
            return (command, subcommand)
        return None
    if command in _TOP_LEVEL_ROUTES:
        subcommand = getattr(args, f"{command}_command", None)
        if isinstance(subcommand, str):
            return (command, subcommand)
    return None


def standalone_requires_data_root(args: argparse.Namespace) -> bool:
    route = standalone_route(args)
    return route in _DATA_ROOT_ROUTES


def handle_standalone(
    args: argparse.Namespace,
    data_root: Path | None,
    schemas: SchemaRegistry,
) -> dict[str, Any]:
    del args, data_root, schemas
    raise KokoroError("COMMAND_FAILED", "Command could not be completed.")


__all__ = [
    "StandaloneRoute",
    "add_standalone_parsers",
    "handle_standalone",
    "standalone_requires_data_root",
    "standalone_route",
]
