from __future__ import annotations

import ast
import io
from pathlib import Path

import pytest

from kokorox.bounded_read import read_at_most


class _RecordingStream(io.BytesIO):
    def __init__(self, payload: bytes, *, trickle: int | None = None) -> None:
        super().__init__(payload)
        self.requests: list[int] = []
        self._trickle = trickle

    def read(self, size: int | None = -1) -> bytes:  # type: ignore[override]
        assert size is not None
        self.requests.append(size)
        if self._trickle is not None and size > self._trickle:
            size = self._trickle
        return super().read(size)


@pytest.mark.parametrize(
    ("payload", "limit", "expected"),
    [
        (b"", 10, b""),
        (b"abc", 10, b"abc"),
        (b"abcdef", 4, b"abcd"),
        (b"abcdef", 0, b""),
        (b"x" * (3 * 1024 * 1024 + 5), 3 * 1024 * 1024 + 1, b"x" * (3 * 1024 * 1024 + 1)),
    ],
    ids=["empty", "short", "truncated", "zero", "several-chunks"],
)
def test_reads_until_the_limit_or_the_end(payload: bytes, limit: int, expected: bytes) -> None:
    assert read_at_most(io.BytesIO(payload), limit) == expected


def test_never_asks_the_stream_for_the_whole_bound() -> None:
    """A 64 MiB bound reserved 64 MiB per read, whatever the file held."""

    stream = _RecordingStream(b"small file")

    assert read_at_most(stream, 64 * 1024 * 1024 + 1) == b"small file"
    assert max(stream.requests) <= 1024 * 1024


def test_keeps_reading_through_short_reads() -> None:
    stream = _RecordingStream(b"0123456789", trickle=3)

    assert read_at_most(stream, 8) == b"01234567"


@pytest.mark.parametrize("limit", [-1, True, 1.5])
def test_rejects_a_limit_that_is_not_a_count(limit: object) -> None:
    with pytest.raises(ValueError):
        read_at_most(io.BytesIO(b"abc"), limit)  # type: ignore[arg-type]


def test_no_source_reads_a_whole_large_bound_in_one_call() -> None:
    """Keep the reservation from coming back through a new call site.

    A `read(<bound> + 1)` is allowed only where the bound is small, sized by
    data already in hand, or the stream is a zip member reader, which does not
    reserve its argument.
    """

    allowed = {
        ("src/kokorox/distribution/archive.py", "limits.max_member_bytes + 1"),
        ("src/kokorox/distribution/defaults.py", "_MAX_CONFIG_BYTES + 1"),
        ("src/kokorox/distribution/installer.py", "len(expected) + 1"),
        ("src/kokorox/distribution/migrations.py", "len(payload) + 1"),
        ("src/kokorox/state/store.py", "SESSION_MANIFEST_MAX_BYTES + 1"),
        ("src/kokorox/state/store.py", "SESSION_BINDING_MAX_BYTES + 1"),
    }
    found = set()
    for path in sorted(Path("src/kokorox").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "read"
                and node.args
                and isinstance(node.args[0], ast.BinOp)
                and isinstance(node.args[0].op, ast.Add)
                and isinstance(node.args[0].right, ast.Constant)
                and node.args[0].right.value == 1
            ):
                found.add((path.as_posix(), ast.unparse(node.args[0])))
    assert found <= allowed, sorted(found - allowed)
