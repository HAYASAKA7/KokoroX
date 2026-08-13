from __future__ import annotations

import re
from collections.abc import Callable


USER_PROFILE_REPLACEMENT = "<redacted-user-profile>"
ENVIRONMENT_SECRET_REPLACEMENT = "<redacted-environment-secret>"
CREDENTIAL_REPLACEMENT = "<redacted-credential>"


_USER_PROFILE = re.compile(
    r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+",
    re.IGNORECASE,
)
_ENVIRONMENT_ASSIGNMENT = re.compile(
    r"(?P<prefix>[\"']?[A-Z0-9_-]*(?:API[_-]?KEY|ACCESS[_-]?KEY|"
    r"PRIVATE[_-]?KEY|CLIENT[_-]?SECRET|SECRET|TOKEN|PASSWORD|PASSWD|"
    r"CREDENTIALS?)"
    r"[\"']?\s*[:=]\s*)"
    r"(?P<value>(?P<environment_quote>\\?[\"']).*?"
    r"(?P=environment_quote)|[^\s,}\]\r\n]+)",
    re.IGNORECASE,
)
_AUTHORIZATION = re.compile(
    r"(?P<prefix>(?:\\?[\"'])?Authorization(?:\\?[\"'])?\s*[:=]\s*)"
    r"(?P<value>(?P<authorization_quote>\\?[\"'])"
    r"(?:Bearer|Basic|Token)\s+.*?(?P=authorization_quote)|"
    r"(?:Bearer|Basic|Token)\s+[^\s,}\]\r\n]+)",
    re.IGNORECASE,
)
_URL_CREDENTIALS = re.compile(
    r"(?P<prefix>\bhttps?://)(?P<value>[^/\s:@]+:[^/\s@]+)(?=@)",
    re.IGNORECASE,
)
_KNOWN_CREDENTIALS = (
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(
        r"-----BEGIN (?P<label>(?:(?:RSA|EC|OPENSSH|ENCRYPTED) )?PRIVATE KEY)"
        r"-----.*?-----END (?P=label)-----",
        re.DOTALL,
    ),
)


def _replace_value(match: re.Match[str], replacement: str) -> str:
    value = match.group("value")
    escaped_quote = (
        value[:2]
        if len(value) >= 4 and value[0] == "\\" and value[1] in {"\"", "'"}
        else ""
    )
    quote = value[0] if not escaped_quote and value[:1] in {"\"", "'"} else ""
    delimiter = escaped_quote or quote
    unquoted = (
        value[len(delimiter) : -len(delimiter)]
        if delimiter and value.endswith(delimiter)
        else value
    )
    if unquoted.casefold().startswith("<redacted-"):
        return match.group(0)
    redacted = f"{delimiter}{replacement}{delimiter}" if delimiter else replacement
    return f"{match.group('prefix')}{redacted}"


def _subn_counted(
    pattern: re.Pattern[str],
    replacement: str | Callable[[re.Match[str]], str],
    text: str,
) -> tuple[str, int]:
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        value = replacement(match) if callable(replacement) else replacement
        if value != match.group(0):
            count += 1
        return value

    return pattern.sub(replace, text), count


def sanitize_sensitive_text(value: str) -> tuple[str, int]:
    text = value
    total = 0
    for pattern, replacement in (
        (_USER_PROFILE, USER_PROFILE_REPLACEMENT),
        (
            _AUTHORIZATION,
            lambda match: _replace_value(match, CREDENTIAL_REPLACEMENT),
        ),
        (
            _URL_CREDENTIALS,
            lambda match: _replace_value(match, CREDENTIAL_REPLACEMENT),
        ),
        (
            _ENVIRONMENT_ASSIGNMENT,
            lambda match: _replace_value(match, ENVIRONMENT_SECRET_REPLACEMENT),
        ),
    ):
        text, count = _subn_counted(pattern, replacement, text)
        total += count
    for pattern in _KNOWN_CREDENTIALS:
        text, count = _subn_counted(pattern, CREDENTIAL_REPLACEMENT, text)
        total += count
    return text, total


def sanitize_sensitive_bytes(value: bytes) -> tuple[bytes, int]:
    text = value.decode("utf-8")
    retained, count = sanitize_sensitive_text(text)
    return retained.encode("utf-8"), count


def contains_sensitive_material(value: bytes | str) -> bool:
    text = value.decode("utf-8") if isinstance(value, bytes) else value
    _retained, count = sanitize_sensitive_text(text)
    return count > 0
