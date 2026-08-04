"""Validation and normalization for character research requests."""

from __future__ import annotations

import json
from typing import Any, cast

from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry


_UNRESOLVED = frozenset({"unknown", "unspecified", "ambiguous", "mixed"})
_SCOPE_FIELDS = ("medium", "work", "adaptation", "continuity", "timeline_cutoff")


def normalize_research_request(
    value: dict[str, Any], schemas: SchemaRegistry
) -> dict[str, Any]:
    """Return a validated canonical copy of a character research request."""
    try:
        canonical_value = canonical_bytes(value)
    except KokoroError as error:
        if error.code != "INVALID_PACK_DATA":
            raise
        raise KokoroError(
            "INVALID_PACK_DATA",
            "Artifact cannot be represented as canonical JSON.",
            details={"path": []},
        ) from None

    normalized_value = json.loads(canonical_value)
    if isinstance(normalized_value, dict):
        normalized_value.setdefault("requested_visibility", "private")

    try:
        schemas.validate("research-request", normalized_value)
    except KokoroError as error:
        if error.code != "SCHEMA_VALIDATION_FAILED":
            raise
        raise KokoroError(
            "SCHEMA_VALIDATION_FAILED",
            "Research request does not satisfy the required schema.",
            details={
                "schema": "research-request",
                "path": error.details.get("path", []),
            },
        ) from None

    normalized = cast(dict[str, Any], normalized_value)
    for field in _SCOPE_FIELDS:
        if normalized[field].strip().casefold() in _UNRESOLVED:
            raise KokoroError(
                "RESEARCH_CONTINUITY_UNRESOLVED",
                "Research identity and continuity must be resolved before collection.",
                details={"field": field},
            )
    return normalized
