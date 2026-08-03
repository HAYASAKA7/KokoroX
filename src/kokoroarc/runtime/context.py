"""Build the bounded character and relationship view used at runtime."""

from __future__ import annotations

import math
import re
from typing import Any

from kokoroarc.errors import KokoroError
from kokoroarc.json_compat import find_json_incompatibility


_SUPPORTED_LOCALES = frozenset({"zh-CN", "en-US", "ja-JP"})
_LOCALE_ID = re.compile(r"^[a-z]{2}-[A-Z]{2}\Z", re.ASCII)
_SEMANTIC_ID = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*\Z", re.ASCII)
_SLUG_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\Z", re.ASCII)
_SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z",
    re.ASCII,
)
_STAGES = frozenset({"unknown", "acquainted", "familiar", "trusted"})
_DIMENSIONS = frozenset({"familiarity", "trust", "collaboration", "tension"})
_INTENSITIES = frozenset(
    {"neutral", "subtle", "balanced", "immersive", "performance"}
)
_IDENTITY_REQUIRED = frozenset({"display_name"})
_IDENTITY_ALLOWED = _IDENTITY_REQUIRED | {
    "declared_age",
    "role",
    "worldview",
    "non_negotiables",
}
_LOCALE_CONFIG_KEYS = frozenset(
    {"register", "sentence_length", "technical_terms", "addressing", "politeness"}
)
_SCENARIO_KEYS = frozenset(
    {
        "first_action",
        "hypothesis_style",
        "correction_style",
        "reassurance",
        "intensity_cap",
    }
)
_MAX_JSON_DEPTH = 64


class _InvalidContext(Exception):
    """Private marker for sanitized invalid-context failures."""


class _UnsupportedLocale(Exception):
    """Private marker for an unavailable syntactically valid locale."""


class _UnknownScenario(Exception):
    """Private marker for an unavailable syntactically valid scenario."""


def _invalid() -> KokoroError:
    return KokoroError(
        "INVALID_RUNTIME_CONTEXT",
        "Runtime context input is invalid.",
    )


def _unsupported_locale() -> KokoroError:
    return KokoroError(
        "UNSUPPORTED_LOCALE",
        "The requested locale is not available.",
    )


def _unknown_scenario() -> KokoroError:
    return KokoroError(
        "UNKNOWN_SCENARIO",
        "The requested scenario is not available.",
    )


def _bounded_string(value: Any, maximum: int, *, allow_empty: bool = False) -> bool:
    minimum = 0 if allow_empty else 1
    if type(value) is not str or not minimum <= len(value) <= maximum:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _semantic_id(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) <= 128
        and _SEMANTIC_ID.fullmatch(value) is not None
    )


def _number_in_range(value: Any, minimum: float, maximum: float) -> bool:
    if type(value) not in (int, float):
        return False
    if type(value) is float and not math.isfinite(value):
        return False
    return minimum <= value <= maximum


def _keys_are_allowed(value: dict[Any, Any], allowed: frozenset[str]) -> bool:
    return all(type(key) is str and key in allowed for key in value)


def _string_array(value: Any) -> bool:
    return (
        type(value) is list
        and 1 <= len(value) <= 32
        and all(_bounded_string(item, 256) for item in value)
        and len(set(value)) == len(value)
    )


def _identity_valid(value: Any) -> bool:
    if type(value) is not dict or not _keys_are_allowed(value, _IDENTITY_ALLOWED):
        return False
    if not _IDENTITY_REQUIRED.issubset(value) or not _bounded_string(
        value["display_name"], 256
    ):
        return False
    for key in ("declared_age", "role"):
        if key in value and not _bounded_string(value[key], 256):
            return False
    for key in ("worldview", "non_negotiables"):
        if key in value and not _string_array(value[key]):
            return False
    return True


def _profile_valid(value: Any) -> bool:
    return (
        type(value) is dict
        and 1 <= len(value) <= 256
        and all(_semantic_id(key) for key in value)
        and all(_number_in_range(item, 0, 1) for item in value.values())
    )


def _relationship_stage_map_valid(value: Any) -> bool:
    if type(value) is not dict or not _keys_are_allowed(value, _STAGES):
        return False
    return all(
        item is None or _bounded_string(item, 128, allow_empty=True)
        for item in value.values()
    )


def _locale_config_valid(value: Any) -> bool:
    if type(value) is not dict or not _keys_are_allowed(value, _LOCALE_CONFIG_KEYS):
        return False
    for key in ("register", "sentence_length", "technical_terms"):
        if key in value and not _bounded_string(value[key], 256):
            return False
    for key in ("addressing", "politeness"):
        if key in value and not _relationship_stage_map_valid(value[key]):
            return False
    return True


def _scenario_valid(value: Any) -> bool:
    if type(value) is not dict or not _keys_are_allowed(value, _SCENARIO_KEYS):
        return False
    for key in (
        "first_action",
        "hypothesis_style",
        "correction_style",
        "reassurance",
    ):
        if key in value and not _bounded_string(value[key], 256):
            return False
    if "intensity_cap" in value:
        intensity = value["intensity_cap"]
        if type(intensity) is not str or intensity not in _INTENSITIES:
            return False
    return True


def _expression_lines_valid(value: Any) -> bool:
    return (
        type(value) is list
        and 1 <= len(value) <= 32
        and all(_bounded_string(line, 500) for line in value)
    )


def _expression_selection(expressions: Any, locale: str) -> dict[str, Any]:
    if type(expressions) is not dict or not 1 <= len(expressions) <= 256:
        raise _InvalidContext
    selected: dict[str, Any] = {}
    for intent, locale_set in expressions.items():
        if not _semantic_id(intent):
            raise _InvalidContext
        if (
            type(locale_set) is not dict
            or not 1 <= len(locale_set) <= len(_SUPPORTED_LOCALES)
            or not _keys_are_allowed(locale_set, _SUPPORTED_LOCALES)
        ):
            raise _InvalidContext
        if locale in locale_set:
            lines = locale_set[locale]
            if not _expression_lines_valid(lines):
                raise _InvalidContext
            selected[intent] = {locale: lines}
    return selected


def _growth_dimensions(growth: Any) -> list[str]:
    if type(growth) is not dict:
        raise _InvalidContext
    dimensions = growth.get("dimensions")
    if (
        type(dimensions) is not list
        or not 1 <= len(dimensions) <= 4
        or any(type(item) is not str or item not in _DIMENSIONS for item in dimensions)
        or len(set(dimensions)) != len(dimensions)
    ):
        raise _InvalidContext
    return dimensions


def _state_summary(state: Any) -> dict[str, Any]:
    if type(state) is not dict:
        raise _InvalidContext
    revision = state.get("revision")
    stage = state.get("stage")
    dimensions = state.get("dimensions")
    if (
        type(revision) is not int
        or revision < 0
        or type(stage) is not str
        or stage not in _STAGES
        or type(dimensions) is not dict
        or not 1 <= len(dimensions) <= len(_DIMENSIONS)
        or not _keys_are_allowed(dimensions, _DIMENSIONS)
        or any(not _number_in_range(value, 0, 100) for value in dimensions.values())
    ):
        raise _InvalidContext
    return {"revision": revision, "stage": stage, "dimensions": dimensions}


def _validate_selection(locale: Any, scenario: Any) -> tuple[str, str]:
    if (
        type(locale) is not str
        or _LOCALE_ID.fullmatch(locale) is None
        or not _bounded_string(locale, 5)
    ):
        raise _InvalidContext
    if not _semantic_id(scenario):
        raise _InvalidContext
    return locale, scenario


def _snapshot_json(
    value: Any,
    *,
    seen: set[int] | None = None,
    depth: int = 0,
) -> Any:
    """Copy exact JSON built-ins without invoking input-defined behavior."""
    if seen is None:
        seen = set()
    value_type = type(value)
    if value is None or value_type in (bool, int):
        return value
    if value_type is float:
        if not math.isfinite(value):
            raise _InvalidContext
        return value
    if value_type is str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise _InvalidContext from None
        return value
    if value_type not in (dict, list) or depth >= _MAX_JSON_DEPTH:
        raise _InvalidContext

    container_id = id(value)
    if container_id in seen:
        raise _InvalidContext
    seen.add(container_id)

    if value_type is list:
        return [
            _snapshot_json(item, seen=seen, depth=depth + 1) for item in value
        ]

    copied: dict[str, Any] = {}
    for key, item in value.items():
        if type(key) is not str:
            raise _InvalidContext
        try:
            key.encode("utf-8")
        except UnicodeEncodeError:
            raise _InvalidContext from None
        copied[key] = _snapshot_json(item, seen=seen, depth=depth + 1)
    return copied


def _build_runtime_context(
    compiled: Any,
    state: Any,
    locale: Any,
    scenario: Any,
) -> dict[str, Any]:
    selected_locale, selected_scenario = _validate_selection(locale, scenario)
    if type(compiled) is not dict or type(state) is not dict:
        raise _InvalidContext

    locales = compiled.get("locales")
    scenarios = compiled.get("scenarios")
    if (
        type(locales) is not dict
        or len(locales) > len(_SUPPORTED_LOCALES)
        or not _keys_are_allowed(locales, _SUPPORTED_LOCALES)
        or type(scenarios) is not dict
        or not 1 <= len(scenarios) <= 128
        or any(not _semantic_id(key) for key in scenarios)
    ):
        raise _InvalidContext
    if selected_locale not in _SUPPORTED_LOCALES or selected_locale not in locales:
        raise _UnsupportedLocale
    if selected_scenario not in scenarios:
        raise _UnknownScenario

    character_id = compiled.get("character_id")
    character_version = compiled.get("character_version")
    if (
        type(character_id) is not str
        or not 1 <= len(character_id) <= 64
        or _SLUG_ID.fullmatch(character_id) is None
        or type(character_version) is not str
        or not 1 <= len(character_version) <= 64
        or _SEMVER.fullmatch(character_version) is None
    ):
        raise _InvalidContext

    identity = compiled.get("identity")
    effective_profile = compiled.get("effective_profile")
    locale_config = locales[selected_locale]
    scenario_config = scenarios[selected_scenario]
    if (
        not _identity_valid(identity)
        or not _profile_valid(effective_profile)
        or not _locale_config_valid(locale_config)
        or not _scenario_valid(scenario_config)
    ):
        raise _InvalidContext

    expressions = _expression_selection(compiled.get("expressions"), selected_locale)
    growth_dimensions = _growth_dimensions(compiled.get("growth"))
    state_summary = _state_summary(state)
    selected_data = {
        "character_id": character_id,
        "character_version": character_version,
        "identity": identity,
        "effective_profile": effective_profile,
        "locales": {selected_locale: locale_config},
        "scenarios": {selected_scenario: scenario_config},
        "expressions": expressions,
        "growth": {"dimensions": growth_dimensions},
        "state": state_summary,
    }
    detached = _snapshot_json(selected_data)
    detached_dimensions = detached["state"]["dimensions"]
    projected_dimensions: dict[str, int | float] = {}
    for dimension in detached["growth"]["dimensions"]:
        if dimension not in detached_dimensions:
            raise _InvalidContext
        projected_dimensions[dimension] = detached_dimensions[dimension]
    detached["state"]["dimensions"] = projected_dimensions

    if find_json_incompatibility(detached) is not None:
        raise _InvalidContext
    return detached


def build_runtime_context(
    compiled: Any,
    state: Any,
    locale: Any,
    scenario: Any,
) -> dict[str, Any]:
    """Return a deterministic, detached runtime view for one locale and scenario."""
    try:
        return _build_runtime_context(compiled, state, locale, scenario)
    except _UnsupportedLocale:
        raise _unsupported_locale() from None
    except _UnknownScenario:
        raise _unknown_scenario() from None
    except _InvalidContext:
        raise _invalid() from None
    except Exception:
        raise _invalid() from None
