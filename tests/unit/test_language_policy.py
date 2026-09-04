from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from math import inf, nan
from typing import Any

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.policy.compiler import DEFAULT_POLICY, normalize_policy
from kokoroarc.policy.resolver import resolve_policy


EXPECTED_DEFAULT = {
    "mode": "single",
    "primary_language": "en-US",
    "channels": {
        "character_dialogue": "en-US",
        "technical_explanation": "en-US",
        "recommendations": "en-US",
        "warnings": "en-US",
        "technical_terms": "preserve",
        "commands": "preserve",
        "file_paths": "preserve",
        "exact_errors": "preserve",
        "code_identifiers": "preserve",
    },
    "mixing": {"max_switches": 4, "min_primary_ratio": 0.7},
    "subtitles": {"enabled": False, "language": None},
}


def assert_error(call: Any, code: str) -> KokoroError:
    with pytest.raises(KokoroError) as raised:
        call()
    assert raised.value.code == code
    assert raised.value.retryable is False
    return raised.value


def test_normalize_empty_policy_returns_complete_defaults() -> None:
    assert DEFAULT_POLICY == EXPECTED_DEFAULT
    assert normalize_policy({}) == EXPECTED_DEFAULT


def test_normalize_nested_overrides_preserve_sibling_defaults() -> None:
    normalized = normalize_policy(
        {
            "mode": "mixed",
            "primary_language": "ja-JP",
            "channels": {"character_dialogue": "zh-CN"},
            "mixing": {"max_switches": 2},
            "subtitles": {"enabled": True, "language": "en-US"},
        }
    )

    assert normalized == {
        **EXPECTED_DEFAULT,
        "mode": "mixed",
        "primary_language": "ja-JP",
        "channels": {
            **EXPECTED_DEFAULT["channels"],
            "character_dialogue": "zh-CN",
        },
        "mixing": {"max_switches": 2, "min_primary_ratio": 0.7},
        "subtitles": {"enabled": True, "language": "en-US"},
    }


def test_higher_turn_layer_wins_and_nested_layers_merge() -> None:
    resolved = resolve_policy(
        [
            {
                "primary_language": "zh-CN",
                "channels": {"warnings": "zh-CN"},
                "mixing": {"max_switches": 8},
            },
            {
                "primary_language": "ja-JP",
                "channels": {"technical_explanation": "ja-JP"},
                "mixing": {"min_primary_ratio": 0.8},
            },
        ],
        protected_channels=set(),
    )

    assert resolved["primary_language"] == "ja-JP"
    assert resolved["channels"]["warnings"] == "zh-CN"
    assert resolved["channels"]["technical_explanation"] == "ja-JP"
    assert resolved["mixing"] == {
        "max_switches": 8,
        "min_primary_ratio": 0.8,
    }


@pytest.mark.parametrize(
    "channel",
    ["commands", "file_paths", "exact_errors", "code_identifiers"],
)
def test_mandatory_protected_channel_override_is_rejected(channel: str) -> None:
    error = assert_error(
        lambda: resolve_policy(
            [{"channels": {channel: "en-US"}}], protected_channels=set()
        ),
        "PROTECTED_CHANNEL_OVERRIDE",
    )

    assert error.details == {"channel": channel}


def test_lower_layer_protected_conflict_is_rejected_even_if_overwritten() -> None:
    assert_error(
        lambda: resolve_policy(
            [
                {"channels": {"commands": "zh-CN"}},
                {"channels": {"commands": "preserve"}},
            ],
            protected_channels=set(),
        ),
        "PROTECTED_CHANNEL_OVERRIDE",
    )


def test_normalize_rejects_mandatory_protected_conflicts() -> None:
    assert_error(
        lambda: normalize_policy({"channels": {"commands": "ja-JP"}}),
        "PROTECTED_CHANNEL_OVERRIDE",
    )


def test_additional_protected_channels_are_forced_to_preserve() -> None:
    resolved = resolve_policy(
        [{"channels": {"recommendations": "preserve"}}],
        protected_channels={"recommendations", "technical_terms"},
    )

    assert resolved["channels"]["recommendations"] == "preserve"
    assert resolved["channels"]["technical_terms"] == "preserve"
    for channel in ("commands", "file_paths", "exact_errors", "code_identifiers"):
        assert resolved["channels"][channel] == "preserve"


def test_additional_protected_channel_conflict_is_rejected() -> None:
    assert_error(
        lambda: resolve_policy(
            [{"channels": {"warnings": "ja-JP"}}],
            protected_channels={"warnings"},
        ),
        "PROTECTED_CHANNEL_OVERRIDE",
    )


@pytest.mark.parametrize(
    "policy",
    [
        None,
        [],
        {"secret_top_level": True},
        {"channels": []},
        {"channels": {"secret_channel": "en-US"}},
        {"mixing": []},
        {"mixing": {"secret_option": 1}},
        {"subtitles": []},
        {"subtitles": {"secret_option": True}},
    ],
)
def test_invalid_mapping_shapes_and_unknown_keys_are_sanitized(policy: Any) -> None:
    error = assert_error(lambda: normalize_policy(policy), "INVALID_LANGUAGE_POLICY")

    assert "secret" not in str(error.envelope())


@pytest.mark.parametrize(
    "policy",
    [
        {"mode": "adaptive"},
        {"mode": 1},
        {"mode": []},
        {"primary_language": "preserve"},
        {"primary_language": "fr_FR"},
        {"primary_language": []},
        {"channels": {"warnings": "fr_FR"}},
        {"channels": {"warnings": None}},
        {"channels": {"warnings": []}},
        {"mixing": {"max_switches": True}},
        {"mixing": {"max_switches": -1}},
        {"mixing": {"max_switches": 1.5}},
        {"mixing": {"min_primary_ratio": True}},
        {"mixing": {"min_primary_ratio": -0.01}},
        {"mixing": {"min_primary_ratio": 1.01}},
        {"mixing": {"min_primary_ratio": inf}},
        {"mixing": {"min_primary_ratio": -inf}},
        {"mixing": {"min_primary_ratio": nan}},
        {"mixing": {"min_primary_ratio": Fraction(1, 2)}},
        {"subtitles": {"enabled": 1}},
        {"subtitles": {"language": "preserve"}},
        {"subtitles": {"language": "fr_FR"}},
        {"subtitles": {"language": []}},
        {"subtitles": {"enabled": True}},
        {"subtitles": {"enabled": True, "language": None}},
    ],
)
def test_invalid_policy_values_are_rejected(policy: dict[str, Any]) -> None:
    assert_error(lambda: normalize_policy(policy), "INVALID_LANGUAGE_POLICY")


@pytest.mark.parametrize("locale", ["zh-CN", "en-US", "ja-JP"])
def test_all_supported_locales_are_accepted(locale: str) -> None:
    normalized = normalize_policy(
        {
            "primary_language": locale,
            "channels": {
                "character_dialogue": locale,
                "technical_terms": "preserve",
            },
            "subtitles": {"enabled": True, "language": locale},
        }
    )

    assert normalized["primary_language"] == locale
    assert normalized["channels"]["character_dialogue"] == locale
    assert normalized["subtitles"]["language"] == locale


def test_disabled_subtitles_may_retain_a_valid_language() -> None:
    assert normalize_policy(
        {"subtitles": {"enabled": False, "language": "ja-JP"}}
    )["subtitles"] == {"enabled": False, "language": "ja-JP"}


@pytest.mark.parametrize(
    "layers",
    [None, {}, "not-layers", [None], [[]], [{"mode": "single"}, None]],
)
def test_resolve_rejects_invalid_layer_containers(layers: Any) -> None:
    assert_error(
        lambda: resolve_policy(layers, protected_channels=set()),
        "INVALID_LANGUAGE_POLICY",
    )


@pytest.mark.parametrize(
    "protected",
    [None, "commands", ["unknown"], [1], [[]], {"secret_channel"}],
)
def test_resolve_rejects_invalid_protected_channel_sets(protected: Any) -> None:
    error = assert_error(
        lambda: resolve_policy([], protected_channels=protected),
        "INVALID_LANGUAGE_POLICY",
    )

    assert "secret" not in str(error.envelope())


def test_normalization_and_resolution_do_not_mutate_or_alias_inputs() -> None:
    shared = {"enabled": False, "language": "zh-CN"}
    policy = {
        "channels": {"warnings": "ja-JP"},
        "subtitles": shared,
    }
    layer = {"mixing": {"max_switches": 1}}
    originals = deepcopy((policy, layer))

    normalized = normalize_policy(policy)
    first = resolve_policy([layer], protected_channels=set())
    second = resolve_policy([layer], protected_channels=set())
    normalized["channels"]["warnings"] = "en-US"
    normalized["subtitles"]["language"] = None
    first["mixing"]["max_switches"] = 99

    assert (policy, layer) == originals
    assert second["mixing"]["max_switches"] == 1
    assert first is not second
    assert first["channels"] is not second["channels"]
    assert first["mixing"] is not second["mixing"]
    assert first["subtitles"] is not second["subtitles"]


def test_callers_cannot_drift_global_defaults() -> None:
    normalized = normalize_policy({})
    normalized["channels"]["warnings"] = "ja-JP"
    normalized["mixing"]["max_switches"] = 999

    assert DEFAULT_POLICY == EXPECTED_DEFAULT
    assert normalize_policy({}) == EXPECTED_DEFAULT


def test_mutating_exported_default_does_not_change_normalization() -> None:
    original = deepcopy(DEFAULT_POLICY)
    try:
        DEFAULT_POLICY["channels"]["warnings"] = "ja-JP"
        DEFAULT_POLICY["mixing"]["max_switches"] = 999

        assert normalize_policy({}) == EXPECTED_DEFAULT
    finally:
        DEFAULT_POLICY.clear()
        DEFAULT_POLICY.update(original)
