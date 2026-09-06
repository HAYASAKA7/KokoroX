"""Language-tag validation shared by every KokoroX layer.

KokoroX renders in the user's language. Locales are therefore an open set
validated by shape rather than a closed enumeration: a Character Pack declares
the locales it actually authors, and the runtime selects among them.

`DEFAULT_LOCALES` are the reference locales shipped with the repository's own
packs. They are defaults, not a requirement; a pack may author exactly one
locale or a dozen.
"""

from __future__ import annotations

import re
from typing import Final


#: Preserve the source text verbatim instead of rendering it in a language.
#: Used by protected channels (commands, file paths, exact errors, identifiers).
PRESERVE: Final = "preserve"

#: Reference locales for the repository's own packs. Not a required set.
DEFAULT_LOCALES: Final = ("zh-CN", "en-US", "ja-JP")

_MAX_TAG_LENGTH: Final = 35

# BCP-47 subset: language[-Script][-Region]
#   language : 2-3 letter ISO 639 code (lowercase)
#   Script   : 4-letter ISO 15924 code (titlecase), optional
#   Region   : 2-letter ISO 3166-1 (uppercase) or 3-digit UN M.49, optional
_LANGUAGE_TAG: Final = re.compile(
    r"^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|[0-9]{3}))?\Z",
    re.ASCII,
)


def is_language_tag(value: object) -> bool:
    """Return whether `value` is a well-formed language tag."""

    return (
        type(value) is str
        and len(value) <= _MAX_TAG_LENGTH
        and _LANGUAGE_TAG.fullmatch(value) is not None
    )


def is_channel_language(value: object) -> bool:
    """Return whether `value` is a language tag or the `preserve` sentinel."""

    return value == PRESERVE or is_language_tag(value)


def are_language_tags(values: object) -> bool:
    """Return whether `values` is a non-empty iterable of language tags."""

    if isinstance(values, (str, bytes)) or not hasattr(values, "__iter__"):
        return False
    items = tuple(values)
    return bool(items) and all(is_language_tag(item) for item in items)
