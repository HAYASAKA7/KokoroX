"""Validation and normalization for structured character build requests."""

from __future__ import annotations

import json
from typing import Any, cast

from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry


_SUPPORTED_MODES = frozenset({"original", "dossier", "researched", "hybrid"})


def normalize_build_request(
    value: dict[str, Any], schemas: SchemaRegistry
) -> dict[str, Any]:
    """Return a validated canonical copy of a character build request."""
    normalized_value = json.loads(canonical_bytes(value))
    if isinstance(normalized_value, dict):
        normalized_value.setdefault("requested_visibility", "private")

    schemas.validate("character-build-request", normalized_value)
    normalized = cast(dict[str, Any], normalized_value)
    if normalized["mode"] not in _SUPPORTED_MODES:
        raise KokoroError(
            "AUTHORING_MODE_UNSUPPORTED",
            "Construction mode is not available in this milestone.",
        )
    return normalized
