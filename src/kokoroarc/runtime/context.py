"""Build the bounded character and relationship view used at runtime."""

from __future__ import annotations

from copy import deepcopy
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
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _semantic_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 128
        and _SEMANTIC_ID.fullmatch(value) is not None
    )


def _number_in_range(value: Any, minimum: float, maximum: float) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    return minimum <= value <= maximum


def _string_array(value: Any) -> bool:
    return (
        isinstance(value, list)
        and 1 <= len(value) <= 32
        and all(_bounded_string(item, 256) for item in value)
        and len(set(value)) == len(value)
    )


def _identity_valid(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    keys = set(value)
    if not _IDENTITY_REQUIRED.issubset(keys) or not keys.issubset(_IDENTITY_ALLOWED):
        return False
    if not _bounded_string(value["display_name"], 256):
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
        isinstance(value, dict)
        and 1 <= len(value) <= 256
        and all(_semantic_id(key) for key in value)
        and all(_number_in_range(item, 0, 1) for item in value.values())
    )


def _relationship_stage_map_valid(value: Any) -> bool:
    if not isinstance(value, dict) or not set(value).issubset(_STAGES):
        return False
    return all(
        item is None or _bounded_string(item, 128, allow_empty=True)
        for item in value.values()
    )


def _locale_config_valid(value: Any) -> bool:
    if not isinstance(value, dict) or not set(value).issubset(_LOCALE_CONFIG_KEYS):
        return False
    for key in ("register", "sentence_length", "technical_terms"):
        if key in value and not _bounded_string(value[key], 256):
            return False
    for key in ("addressing", "politeness"):
        if key in value and not _relationship_stage_map_valid(value[key]):
            return False
    return True


def _scenario_valid(value: Any) -> bool:
    if not isinstance(value, dict) or not set(value).issubset(_SCENARIO_KEYS):
        return False
    for key in (
        "first_action",
        "hypothesis_style",
        "correction_style",
        "reassurance",
    ):
        if key in value and not _bounded_string(value[key], 256):
            return False
    return "intensity_cap" not in value or value["intensity_cap"] in _INTENSITIES


def _expression_lines_valid(value: Any) -> bool:
    return (
        isinstance(value, list)
        and 1 <= len(value) <= 32
        and all(_bounded_string(line, 500) for line in value)
    )


def _expression_selection(expressions: Any, locale: str) -> dict[str, Any]:
    if not isinstance(expressions, dict) or not 1 <= len(expressions) <= 256:
        raise _invalid()
    selected: dict[str, Any] = {}
    for intent, locale_set in expressions.items():
        if not _semantic_id(intent):
            raise _invalid()
        if (
            not isinstance(locale_set, dict)
            or not 1 <= len(locale_set) <= len(_SUPPORTED_LOCALES)
            or not set(locale_set).issubset(_SUPPORTED_LOCALES)
        ):
            raise _invalid()
        if locale in locale_set:
            lines = locale_set[locale]
            if not _expression_lines_valid(lines):
                raise _invalid()
            selected[intent] = {locale: lines}
    return selected


def _growth_dimensions(growth: Any) -> Any:
    if not isinstance(growth, dict):
        raise _invalid()
    dimensions = growth.get("dimensions")
    if (
        not isinstance(dimensions, list)
        or not 1 <= len(dimensions) <= 4
        or any(item not in _DIMENSIONS for item in dimensions)
        or len(set(dimensions)) != len(dimensions)
    ):
        raise _invalid()
    return dimensions


def _state_summary(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise _invalid()
    revision = state.get("revision")
    stage = state.get("stage")
    dimensions = state.get("dimensions")
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 0
        or stage not in _STAGES
        or not isinstance(dimensions, dict)
        or not 1 <= len(dimensions) <= len(_DIMENSIONS)
        or not set(dimensions).issubset(_DIMENSIONS)
        or any(not _number_in_range(value, 0, 100) for value in dimensions.values())
    ):
        raise _invalid()
    return {"revision": revision, "stage": stage, "dimensions": dimensions}


def _validate_selection(locale: Any, scenario: Any) -> tuple[str, str]:
    if (
        not isinstance(locale, str)
        or _LOCALE_ID.fullmatch(locale) is None
        or not _bounded_string(locale, 5)
    ):
        raise _invalid()
    if not _semantic_id(scenario):
        raise _invalid()
    return locale, scenario


def _build_runtime_context(
    compiled: Any,
    state: Any,
    locale: Any,
    scenario: Any,
) -> dict[str, Any]:
    selected_locale, selected_scenario = _validate_selection(locale, scenario)
    if not isinstance(compiled, dict) or not isinstance(state, dict):
        raise _invalid()

    locales = compiled.get("locales")
    scenarios = compiled.get("scenarios")
    if (
        not isinstance(locales, dict)
        or len(locales) > len(_SUPPORTED_LOCALES)
        or not set(locales).issubset(_SUPPORTED_LOCALES)
        or not isinstance(scenarios, dict)
        or not 1 <= len(scenarios) <= 128
        or any(not _semantic_id(key) for key in scenarios)
    ):
        raise _invalid()
    if selected_locale not in _SUPPORTED_LOCALES or selected_locale not in locales:
        raise _unsupported_locale()
    if selected_scenario not in scenarios:
        raise _unknown_scenario()

    character_id = compiled.get("character_id")
    character_version = compiled.get("character_version")
    if (
        not isinstance(character_id, str)
        or not 1 <= len(character_id) <= 64
        or _SLUG_ID.fullmatch(character_id) is None
        or not isinstance(character_version, str)
        or not 1 <= len(character_version) <= 64
        or _SEMVER.fullmatch(character_version) is None
    ):
        raise _invalid()

    identity = compiled.get("identity")
    effective_profile = compiled.get("effective_profile")
    locale_config = locales[selected_locale]
    scenario_config = scenarios[selected_scenario]
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
    if find_json_incompatibility(selected_data) is not None:
        raise _invalid()
    if (
        not _identity_valid(identity)
        or not _profile_valid(effective_profile)
        or not _locale_config_valid(locale_config)
        or not _scenario_valid(scenario_config)
    ):
        raise _invalid()
    return deepcopy(selected_data)


def build_runtime_context(
    compiled: Any,
    state: Any,
    locale: Any,
    scenario: Any,
) -> dict[str, Any]:
    """Return a deterministic, detached runtime view for one locale and scenario."""
    try:
        return _build_runtime_context(compiled, state, locale, scenario)
    except KokoroError:
        raise
    except Exception:
        raise _invalid() from None
