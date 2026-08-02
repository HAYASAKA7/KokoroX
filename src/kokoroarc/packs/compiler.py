"""Deterministic compilation of validated character source packs."""

from __future__ import annotations

from hashlib import sha256
import json
import math
from typing import Any, cast

from kokoroarc import __version__
from kokoroarc.errors import KokoroError
from kokoroarc.schemas import SchemaRegistry


_MAX_JSON_NESTING_DEPTH = 64


def canonical_bytes(value: Any) -> bytes:
    """Return a compact, deterministic UTF-8 JSON representation of *value*."""
    incompatibility = _find_json_incompatibility(value)
    if incompatibility is not None:
        path, message = incompatibility
        raise KokoroError(
            "INVALID_PACK_DATA",
            message,
            details={"path": path},
        )
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def compile_pack(source: dict[str, Any], schemas: SchemaRegistry) -> dict[str, Any]:
    """Compile a validated source pack into its runtime-only representation."""
    source_bytes = canonical_bytes(source)
    source_copy = cast(dict[str, Any], json.loads(source_bytes))
    traits = source_copy.get("derived_profile", {}).get("traits", {})
    overrides = source_copy.get("overrides", {}).get("values", {})
    effective_profile = {
        key: overrides[key] if key in overrides else traits[key]
        for key in sorted(set(traits) | set(overrides))
    }
    provenance = {
        key: {
            "selected_layer": (
                "user_override" if key in overrides else "derived_profile"
            )
        }
        for key in effective_profile
    }

    compiled = {
        "schema_version": "1.0",
        "artifact_id": (
            f"{source_copy['namespace']}/{source_copy['character_id']}/compiled"
        ),
        "created_by": {"component": "kokoroarc", "version": __version__},
        "character_id": source_copy["character_id"],
        "character_version": source_copy["character_version"],
        "source_hash": sha256(source_bytes).hexdigest(),
        "identity": source_copy["identity"],
        "effective_profile": effective_profile,
        "provenance": provenance,
        "behavior": source_copy["behavior"],
        "growth": source_copy["growth"],
        "expressions": source_copy["expressions"],
        "locales": source_copy["locales"],
        "scenarios": source_copy["scenarios"],
    }
    schemas.validate("compiled-pack", compiled)
    return compiled


def _find_json_incompatibility(
    value: Any,
) -> tuple[list[str | int], str] | None:
    stack: list[tuple[bool, Any, tuple[str | int, ...], int]] = [
        (True, value, (), 0)
    ]
    active_container_ids: set[int] = set()

    while stack:
        entering, current, path, depth = stack.pop()
        if not entering:
            active_container_ids.remove(id(current))
            continue

        if current is None or isinstance(current, (bool, int, str)):
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

        if isinstance(current, dict):
            if any(not isinstance(key, str) for key in current):
                return list(path), "JSON artifact object keys must be strings."
            children = [
                (True, current[key], (*path, key), depth + 1)
                for key in reversed(sorted(current))
            ]
        else:
            children = [
                (True, current[index], (*path, index), depth + 1)
                for index in reversed(range(len(current)))
            ]

        active_container_ids.add(container_id)
        stack.append((False, current, path, depth))
        stack.extend(children)

    return None
