from __future__ import annotations

import argparse
import json
import os

from kokoroarc import __version__
from kokoroarc.config import Settings
from kokoroarc.errors import KokoroError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kokoro")
    parser.add_argument("--version", action="version", version=f"kokoro {__version__}")
    commands = parser.add_subparsers(dest="command")
    session = commands.add_parser("session")
    session_commands = session.add_subparsers(dest="session_command")
    show = session_commands.add_parser("show")
    show.add_argument("--json", action="store_true", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "session" and args.session_command == "show":
        try:
            Settings.from_env(os.environ)
        except KokoroError as error:
            print(json.dumps(error.envelope(), ensure_ascii=False))
            return 2
        print(json.dumps({"ok": True, "session": None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
