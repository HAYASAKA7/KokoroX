"""Child-process output is decoded with a named encoding, never the locale's."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


_SPAWNERS = frozenset({"run", "check_output", "Popen", "call", "check_call"})


def _undecoded_text_calls(root: Path) -> list[str]:
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            )
            if name not in _SPAWNERS:
                continue
            keywords = {keyword.arg: keyword.value for keyword in node.keywords}
            text_mode = any(
                isinstance(keywords.get(flag), ast.Constant)
                and keywords[flag].value is True
                for flag in ("text", "universal_newlines")
            )
            if text_mode and "encoding" not in keywords:
                found.append(f"{path.as_posix()}:{node.lineno}")
    return found


@pytest.mark.parametrize("root", ["src", "tests"])
def test_text_mode_child_processes_name_their_encoding(root: str) -> None:
    """`text=True` alone decodes with the locale codepage.

    On a GBK or cp1252 Windows host a child's UTF-8 output then fails to
    decode in a reader thread, and a correct tree turns red intermittently --
    only when a child happens to print a non-ASCII byte. Name the encoding:
    `utf-8` for kokorox and node, which always write it, plus
    `errors="replace"` for tools such as pip and cmd that write the console
    codepage.
    """

    assert _undecoded_text_calls(Path(root)) == []
