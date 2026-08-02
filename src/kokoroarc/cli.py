from __future__ import annotations

import argparse

from kokoroarc import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kokoro")
    parser.add_argument("--version", action="version", version=f"kokoro {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
