"""Resolve ordered language-policy layers with protected-channel enforcement."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from kokoroarc.policy.compiler import (
    CHANNELS,
    MANDATORY_PROTECTED_CHANNELS,
    _invalid_policy,
    _merge_policy,
    _validate_layer,
    normalize_policy,
)


def _validated_protected_channels(value: Any) -> frozenset[str]:
    if (
        isinstance(value, (str, bytes, bytearray, Mapping))
        or not isinstance(value, (list, tuple, set, frozenset))
    ):
        raise _invalid_policy()
    if any(not isinstance(channel, str) or channel not in CHANNELS for channel in value):
        raise _invalid_policy()
    return MANDATORY_PROTECTED_CHANNELS | frozenset(value)


def resolve_policy(
    layers: Sequence[Mapping[str, Any]],
    protected_channels: set[str] | frozenset[str] | list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Merge low-to-high precedence layers and force protected channels to preserve.

    A conflicting protected-channel value in any layer is rejected, even when a
    higher-precedence layer would otherwise replace it.
    """
    if (
        isinstance(layers, (str, bytes, bytearray, Mapping))
        or not isinstance(layers, Sequence)
    ):
        raise _invalid_policy()

    protected = _validated_protected_channels(protected_channels)
    merged: dict[str, Any] = {
        "channels": {},
        "mixing": {},
        "subtitles": {},
    }
    for layer in layers:
        validated = _validate_layer(layer, protected)
        _merge_policy(merged, validated)

    resolved = normalize_policy(merged)
    for channel in protected:
        resolved["channels"][channel] = "preserve"
    return deepcopy(resolved)
