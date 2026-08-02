"""Deterministic effective-profile resolution."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from kokoroarc.errors import KokoroError


INTENSITY_ORDER = (
    "neutral",
    "subtle",
    "balanced",
    "immersive",
    "performance",
)


def _validate_intensity(value: Any, source: str) -> str:
    if not isinstance(value, str):
        reason = "expected_string"
    elif value not in INTENSITY_ORDER:
        reason = "unsupported_id"
    else:
        return value

    raise KokoroError(
        "INVALID_PROFILE_VALUE",
        "Profile field has an invalid value.",
        details={
            "field": "persona_intensity",
            "source": source,
            "reason": reason,
        },
    )


def resolve_profile(
    base: dict[str, Any],
    user: dict[str, Any],
    host_caps: dict[str, Any],
    immutable: set[str],
) -> dict[str, Any]:
    """Resolve base, user, and host layers without overriding immutable fields."""
    resolved = {key: deepcopy(value) for key, value in base.items()}
    for key, value in user.items():
        if key not in immutable:
            resolved[key] = deepcopy(value)

    requested: str | None = None
    if "persona_intensity" in resolved:
        source = (
            "user"
            if "persona_intensity" in user
            and "persona_intensity" not in immutable
            else "base"
        )
        requested = _validate_intensity(resolved["persona_intensity"], source)

    cap: str | None = None
    if (
        "persona_intensity" in host_caps
        and "persona_intensity" not in immutable
    ):
        cap = _validate_intensity(host_caps["persona_intensity"], "host_caps")

    for key, value in host_caps.items():
        if key != "persona_intensity" and key not in immutable:
            resolved[key] = deepcopy(value)

    if cap is not None and "persona_intensity" not in immutable:
        effective_request = requested or "balanced"
        resolved["persona_intensity"] = INTENSITY_ORDER[
            min(INTENSITY_ORDER.index(effective_request), INTENSITY_ORDER.index(cap))
        ]

    return resolved
