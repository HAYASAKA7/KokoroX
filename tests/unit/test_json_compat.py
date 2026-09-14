from __future__ import annotations

import pytest

from kokorox.json_compat import find_json_incompatibility


class _Text(str):
    pass


class _Number(int):
    pass


def _deep(levels: int) -> object:
    value: object = "leaf"
    for _ in range(levels):
        value = [value]
    return value


def _cases() -> list[object]:
    shared: list[object] = [1]
    cyclic: list[object] = []
    cyclic.append(cyclic)
    return [
        None,
        True,
        7,
        1.5,
        "plain",
        "caf\u00e9 \u732b",
        {"a": [1, 2, {"b": None}], "c": "d"},
        [shared, shared],
        cyclic,
        {"x": float("nan")},
        [float("inf")],
        {"bad": "\ud800"},
        {"\udfff": 1},
        {1: "non-string key"},
        {_Text("sub"): 1},
        [_Text("sub")],
        [_Number(3)],
        (1, 2),
        {"set": {1}},
        _deep(63),
        _deep(64),
        _deep(65),
        {"z": 1, "a": [{"m": float("nan")}, "\ud800"]},
        b"bytes",
    ]


@pytest.mark.parametrize("value", _cases(), ids=lambda value: type(value).__name__)
def test_the_quick_pass_never_changes_the_answer(value: object) -> None:
    """The fast path may only skip work; the exact walk stays the authority."""

    from kokorox.json_compat import _first_incompatibility, _plainly_json

    exact = _first_incompatibility(value)

    assert find_json_incompatibility(value) == exact
    if _plainly_json(value):
        assert exact is None


def test_the_quick_pass_runs_no_value_defined_code() -> None:
    from kokorox.json_compat import _plainly_json

    class Hostile(dict):
        def __iter__(self):  # pragma: no cover - must never run
            raise AssertionError("iterated a dict subclass")

        def values(self):  # pragma: no cover - must never run
            raise AssertionError("read a dict subclass")

    assert _plainly_json({"outer": Hostile(a=1)}) is False
