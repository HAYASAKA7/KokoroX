from __future__ import annotations

from collections.abc import Mapping

from researching_characters_sanitization import (
    CREDENTIAL_REPLACEMENT,
    ENVIRONMENT_SECRET_REPLACEMENT,
    USER_PROFILE_REPLACEMENT,
    contains_sensitive_material,
    sanitize_sensitive_bytes,
)


_REPLACEMENTS: Mapping[str, str] = {
    "credential": CREDENTIAL_REPLACEMENT,
    "environment_secret": ENVIRONMENT_SECRET_REPLACEMENT,
    "user_profile": USER_PROFILE_REPLACEMENT,
}


def sanitize_artifact(value: bytes) -> tuple[bytes, dict[str, object]]:
    if not isinstance(value, bytes):
        raise TypeError("artifact payload must be bytes")
    try:
        retained, count = sanitize_sensitive_bytes(value)
    except UnicodeDecodeError as exc:
        raise ValueError("artifact is not valid UTF-8 text") from exc
    classes = sorted(
        name
        for name, replacement in _REPLACEMENTS.items()
        if retained.count(replacement.encode("utf-8"))
        > value.count(replacement.encode("utf-8"))
    )
    if count and not classes:
        classes = ["sensitive_material"]
    if contains_sensitive_material(retained):
        raise ValueError("sanitized artifact still contains sensitive material")
    second, second_count = sanitize_sensitive_bytes(retained)
    if second != retained or second_count != 0:
        raise ValueError("sanitizer is not idempotent")
    return retained, {
        "redaction_count": count,
        "redaction_classes": classes,
    }


def require_clean_artifact(value: bytes) -> None:
    retained, summary = sanitize_artifact(value)
    if retained != value or summary["redaction_count"] != 0:
        raise ValueError("immutable artifact requires redaction")
