from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.packs.resolver import INTENSITY_ORDER, resolve_profile


def test_approved_profile_resolution_example() -> None:
    resolved = resolve_profile(
        base={
            "warmth": 0.3,
            "persona_intensity": "immersive",
            "display_name": "Rin",
        },
        user={"warmth": 0.6, "display_name": "Other"},
        host_caps={"persona_intensity": "balanced"},
        immutable={"display_name"},
    )

    assert resolved == {
        "warmth": 0.6,
        "persona_intensity": "balanced",
        "display_name": "Rin",
    }


def test_user_and_host_cannot_change_or_add_immutable_keys() -> None:
    resolved = resolve_profile(
        base={"display_name": "Rin", "warmth": 0.3},
        user={"display_name": "User", "missing_identity": "user"},
        host_caps={"display_name": "Host", "missing_identity": "host"},
        immutable={"display_name", "missing_identity"},
    )

    assert resolved == {"display_name": "Rin", "warmth": 0.3}


def test_allowed_user_and_host_keys_follow_precedence_and_may_be_new() -> None:
    resolved = resolve_profile(
        base={"shared": "base", "base_only": True},
        user={"shared": "user", "user_only": True},
        host_caps={"shared": "host", "host_only": True},
        immutable=set(),
    )

    assert resolved == {
        "shared": "host",
        "base_only": True,
        "user_only": True,
        "host_only": True,
    }


@pytest.mark.parametrize("requested", INTENSITY_ORDER)
@pytest.mark.parametrize("cap", INTENSITY_ORDER)
def test_persona_intensity_is_capped_by_canonical_order(
    requested: str, cap: str
) -> None:
    resolved = resolve_profile(
        base={"persona_intensity": requested},
        user={},
        host_caps={"persona_intensity": cap},
        immutable=set(),
    )

    expected = INTENSITY_ORDER[
        min(INTENSITY_ORDER.index(requested), INTENSITY_ORDER.index(cap))
    ]
    assert resolved["persona_intensity"] == expected


def test_user_intensity_is_the_request_and_absent_request_defaults_to_balanced() -> None:
    lower_user = resolve_profile(
        base={"persona_intensity": "performance"},
        user={"persona_intensity": "subtle"},
        host_caps={"persona_intensity": "immersive"},
        immutable=set(),
    )
    defaulted = resolve_profile(
        base={},
        user={},
        host_caps={"persona_intensity": "performance"},
        immutable=set(),
    )

    assert lower_user["persona_intensity"] == "subtle"
    assert defaulted["persona_intensity"] == "balanced"


def test_immutable_persona_intensity_remains_the_base_value() -> None:
    resolved = resolve_profile(
        base={"persona_intensity": "immersive"},
        user={"persona_intensity": "neutral"},
        host_caps={"persona_intensity": "subtle"},
        immutable={"persona_intensity"},
    )

    assert resolved == {"persona_intensity": "immersive"}


def test_immutable_intensity_ignores_invalid_user_and_host_values() -> None:
    present = resolve_profile(
        base={"persona_intensity": "immersive"},
        user={"persona_intensity": object()},
        host_caps={"persona_intensity": object()},
        immutable={"persona_intensity"},
    )
    absent = resolve_profile(
        base={},
        user={"persona_intensity": object()},
        host_caps={"persona_intensity": object()},
        immutable={"persona_intensity"},
    )

    assert present == {"persona_intensity": "immersive"}
    assert absent == {}


def test_invalid_immutable_base_intensity_is_rejected_because_it_is_retained() -> None:
    with pytest.raises(KokoroError) as raised:
        resolve_profile(
            base={"persona_intensity": object()},
            user={"persona_intensity": "neutral"},
            host_caps={"persona_intensity": "balanced"},
            immutable={"persona_intensity"},
        )

    assert raised.value.code == "INVALID_PROFILE_VALUE"
    assert raised.value.details == {
        "field": "persona_intensity",
        "source": "base",
        "reason": "expected_string",
    }


def test_valid_intensity_is_preserved_without_a_host_cap() -> None:
    assert resolve_profile(
        base={"persona_intensity": "immersive"},
        user={},
        host_caps={},
        immutable=set(),
    ) == {"persona_intensity": "immersive"}


@pytest.mark.parametrize(
    ("base", "user", "host_caps", "expected_source", "expected_reason"),
    [
        ({"persona_intensity": "secret-base"}, {}, {}, "base", "unsupported_id"),
        (
            {"persona_intensity": "balanced"},
            {"persona_intensity": "secret-user"},
            {},
            "user",
            "unsupported_id",
        ),
        (
            {"persona_intensity": "balanced"},
            {},
            {"persona_intensity": "secret-cap"},
            "host_caps",
            "unsupported_id",
        ),
        ({"persona_intensity": 1}, {}, {}, "base", "expected_string"),
        (
            {},
            {"persona_intensity": None},
            {},
            "user",
            "expected_string",
        ),
        (
            {},
            {},
            {"persona_intensity": ["balanced"]},
            "host_caps",
            "expected_string",
        ),
    ],
)
def test_invalid_intensity_raises_a_stable_sanitized_error(
    base: dict[str, Any],
    user: dict[str, Any],
    host_caps: dict[str, Any],
    expected_source: str,
    expected_reason: str,
) -> None:
    with pytest.raises(KokoroError) as raised:
        resolve_profile(base, user, host_caps, set())

    assert raised.value.code == "INVALID_PROFILE_VALUE"
    assert raised.value.details == {
        "field": "persona_intensity",
        "source": expected_source,
        "reason": expected_reason,
    }
    assert "secret" not in str(raised.value.envelope())


def test_empty_inputs_return_a_fresh_empty_mapping() -> None:
    base: dict[str, Any] = {}
    resolved = resolve_profile(base, {}, {}, set())

    assert resolved == {}
    assert resolved is not base


def test_resolution_is_deterministic_and_does_not_mutate_inputs() -> None:
    base = {"nested": {"value": 1}, "persona_intensity": "immersive"}
    user = {"warmth": 0.6}
    host_caps = {"persona_intensity": "balanced", "latency": "low"}
    immutable = {"display_name"}
    originals = deepcopy((base, user, host_caps, immutable))

    first = resolve_profile(base, user, host_caps, immutable)
    second = resolve_profile(base, user, host_caps, immutable)

    assert first == second
    assert first is not second
    assert (base, user, host_caps, immutable) == originals
