"""Fold text for matching across line wraps without joining words."""

from __future__ import annotations

import re


UNSPACED_SCRIPT = (
    "\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff"
    "\uf900-\ufaff\uff00-\uffef\U00020000-\U0002fa1f"
)
_SPACE_BESIDE_UNSPACED = re.compile(
    f" (?=[{UNSPACED_SCRIPT}])|(?<=[{UNSPACED_SCRIPT}]) "
)


def fold_spacing(value: str) -> str:
    """Collapse whitespace to single spaces, dropping a space only beside CJK script.

    Chinese and Japanese text has no spaces, so a space there came from a line
    wrap or a stray keystroke; between Latin words a space is the word
    boundary, and removing it would let "is notable" stand for "is not able".
    """

    return _SPACE_BESIDE_UNSPACED.sub("", " ".join(value.split()))
