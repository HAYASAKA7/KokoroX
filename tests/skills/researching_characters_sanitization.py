from __future__ import annotations

import re
from collections.abc import Callable


USER_PROFILE_REPLACEMENT = "<redacted-user-profile>"
ENVIRONMENT_SECRET_REPLACEMENT = "<redacted-environment-secret>"
CREDENTIAL_REPLACEMENT = "<redacted-credential>"


_USER_PROFILE = re.compile(
    r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+(?:[\\/][^\s\"']*)?",
    re.IGNORECASE,
)
_ENVIRONMENT_ASSIGNMENT = re.compile(
    r"(?P<prefix>[\"']?[A-Z0-9_-]*(?:API[_-]?KEY|ACCESS[_-]?KEY|"
    r"PRIVATE[_-]?KEY|CLIENT[_-]?SECRET|SECRET|TOKEN|PASSWORD|PASSWD|"
    r"CREDENTIALS?)"
    r"[\"']?\s*[:=]\s*)(?P<value>[\"']?[^\s,}\]\r\n]+[\"']?)",
    re.IGNORECASE,
)
_AUTHORIZATION = re.compile(
    r"(?P<prefix>Authorization\s*[:=]\s*(?:Bearer|Basic|Token)\s+)"
    r"(?P<value>\S+)",
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
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
        r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        re.DOTALL,
    ),
)


def _replace_value(match: re.Match[str], replacement: str) -> str:
    value = match.group("value")
    if value.casefold().strip("\"'").startswith("<redacted-"):
        return match.group(0)
    quote = value[0] if value[:1] in {"\"", "'"} else ""
    if quote and value[-1:] != quote:
        quote = ""
    redacted = f"{quote}{replacement}{quote}" if quote else replacement
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
