"""Validation for JSON-compatible runtime artifacts."""

from __future__ import annotations

import math
from typing import Any


_MAX_JSON_NESTING_DEPTH = 64


def find_json_incompatibility(
    value: Any,
) -> tuple[list[str | int], str] | None:
    """Return a deterministic path and reason for a non-JSON value, if any."""
    # Every canonical write and comparison runs this, thousands of times per
    # operation, and nearly always on a valid document. Proving validity
    # needs no paths, sorting, or tuples; only a document the quick pass
    # cannot vouch for takes the exact walk that names what is wrong.
    if _plainly_json(value):
        return None
    return _first_incompatibility(value)


def _plainly_json(value: Any) -> bool:
    """Return True only for exact built-in JSON the full walk would accept.

    Conservative by design: subclasses, shared or cyclic containers, and
    anything at the depth limit answer False and fall through to the exact
    walk, which is the authority. It checks types with `type() is`, so no
    value-defined method ever runs.
    """

    seen: set[int] = set()
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        kind = type(current)
        if kind is str:
            if not current.isascii() and not _is_utf8_encodable(current):
                return False
            continue
        if current is None or kind is bool or kind is int:
            continue
        if kind is float:
            if not math.isfinite(current):
                return False
            continue
        if kind is not dict and kind is not list:
            return False
        if depth >= _MAX_JSON_NESTING_DEPTH or id(current) in seen:
            return False
        seen.add(id(current))
        if kind is dict:
            for key in current:
                if type(key) is not str or (
                    not key.isascii() and not _is_utf8_encodable(key)
                ):
                    return False
            children = current.values()
        else:
            children = current
        stack.extend((child, depth + 1) for child in children)
    return True


def _first_incompatibility(
    value: Any,
) -> tuple[list[str | int], str] | None:
    stack: list[tuple[bool, Any, tuple[str | int, ...], int]] = [
        (True, value, (), 0)
    ]
    active_container_ids: set[int] = set()
    seen_container_ids: set[int] = set()

    while stack:
        entering, current, path, depth = stack.pop()
        if not entering:
            active_container_ids.remove(id(current))
            continue

        if current is None or isinstance(current, (bool, int)):
            continue
        if isinstance(current, str):
            if not _is_utf8_encodable(current):
                return list(path), "JSON strings must be valid UTF-8."
            continue
        if isinstance(current, float):
            if not math.isfinite(current):
                return list(path), "Non-finite numbers are not valid JSON artifacts."
            continue
        if not isinstance(current, (dict, list)):
            return list(path), "Artifact contains a value that is not JSON-compatible."
        if depth >= _MAX_JSON_NESTING_DEPTH:
            return list(path), "JSON artifact nesting exceeds the maximum depth."

        container_id = id(current)
        if container_id in active_container_ids:
            return list(path), "Cyclic containers are not valid JSON artifacts."
        if container_id in seen_container_ids:
            return list(path), "Shared containers are not valid JSON artifacts."

        if isinstance(current, dict):
            if any(not isinstance(key, str) for key in current):
                return list(path), "JSON artifact object keys must be strings."
            if any(not _is_utf8_encodable(key) for key in current):
                return list(path), "JSON strings must be valid UTF-8."
            children = [
                (True, current[key], (*path, key), depth + 1)
                for key in reversed(sorted(current))
            ]
        else:
            children = [
                (True, current[index], (*path, index), depth + 1)
                for index in reversed(range(len(current)))
            ]

        seen_container_ids.add(container_id)
        active_container_ids.add(container_id)
        stack.append((False, current, path, depth))
        stack.extend(children)

    return None


def _is_utf8_encodable(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True
