"""Language tags are an open, shape-validated set rather than a fixed list."""

from __future__ import annotations

import pytest

from kokoroarc.language_tags import (
    DEFAULT_LOCALES,
    PRESERVE,
    are_language_tags,
    is_channel_language,
    is_language_tag,
)


@pytest.mark.parametrize(
    "tag",
    [
        "en",
        "zh",
        "ja",
        "yue",
        "en-US",
        "zh-CN",
        "ja-JP",
        "fr-FR",
        "ko-KR",
        "de-DE",
        "pt-BR",
        "es-419",
        "zh-Hans",
        "zh-Hans-CN",
    ],
)
def test_well_formed_tags_are_accepted(tag: str) -> None:
    assert is_language_tag(tag)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "EN",
        "en_US",
        "en-us",
        "en-USA",
        "zh-hans",
        "english",
        "e",
        "abcd",
        "en-",
        "-US",
        "en US",
        "x" * 40,
        PRESERVE,
        None,
        123,
        ["en-US"],
    ],
)
def test_malformed_values_are_rejected(value: object) -> None:
    assert not is_language_tag(value)


def test_default_locales_are_well_formed_but_not_required() -> None:
    assert all(is_language_tag(tag) for tag in DEFAULT_LOCALES)
    assert set(DEFAULT_LOCALES) == {"zh-CN", "en-US", "ja-JP"}


def test_channel_language_allows_preserve_and_tags_only() -> None:
    assert is_channel_language(PRESERVE)
    assert is_channel_language("fr-FR")
    assert not is_channel_language("PRESERVE")
    assert not is_channel_language("nope!")


def test_are_language_tags_requires_a_non_empty_iterable_of_tags() -> None:
    assert are_language_tags(["en-US", "fr-FR"])
    assert are_language_tags(("ko-KR",))
    assert not are_language_tags([])
    assert not are_language_tags(["en-US", "bogus"])
    assert not are_language_tags("en-US")
    assert not are_language_tags(None)
