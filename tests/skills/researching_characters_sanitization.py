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
_ENVIRONMENT_ASSIGNMENT_PREFIX = re.compile(
    r"(?P<prefix>[\"']?[A-Z0-9_-]*(?:API[_-]?KEY|ACCESS[_-]?KEY|"
    r"PRIVATE[_-]?KEY|CLIENT[_-]?SECRET|SECRET|TOKEN|PASSWORD|PASSWD|"
    r"CREDENTIALS?)"
    r"[\"']?\s*[:=]\s*)",
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


def _line_end(text: str, start: int) -> int:
    endings = [
        index
        for marker in ("\r", "\n")
        if (index := text.find(marker, start)) >= 0
    ]
    return min(endings, default=len(text))


def _is_value_boundary(text: str, index: int, end: int) -> bool:
    return index >= end or text[index] in " \t,;|&}]"


def _quoted_value_end(text: str, start: int) -> int:
    escaped_delimiter = (
        text[start : start + 2]
        if text[start : start + 1] == "\\"
        and text[start + 1 : start + 2] in {"\"", "'"}
        else ""
    )
    if escaped_delimiter:
        end = _line_end(text, start)
        closing = text.rfind(escaped_delimiter, start + 2, end)
        candidate = closing + 2
        return (
            candidate
            if closing >= start + 2 and _is_value_boundary(text, candidate, end)
            else end
        )

    quote = text[start]
    index = start + 1
    end = _line_end(text, start)
    while index < end:
        if text[index] == "\\" and index + 1 < end:
            index += 2
            continue
        if text[index] == quote:
            candidate = index + 1
            if _is_value_boundary(text, candidate, end):
                return candidate
        index += 1
    return end


def _structured_value_end(text: str, start: int) -> int:
    if start >= len(text):
        return start
    if text[start] in {"\"", "'"} or (
        text[start] == "\\" and text[start + 1 : start + 2] in {"\"", "'"}
    ):
        return _quoted_value_end(text, start)
    if text[start] not in "[{":
        index = start
        end = _line_end(text, start)
        while index < end and text[index] not in ",}]":
            index += 1
        return index

    pairs = {"[": "]", "{": "}"}
    stack = [pairs[text[start]]]
    quote: str | None = None
    index = start + 1
    while index < len(text):
        character = text[index]
        if quote is not None:
            if character == "\\" and index + 1 < len(text):
                index += 2
                continue
            if character == quote:
                quote = None
        elif character in {"\"", "'"}:
            quote = character
        elif character in pairs:
            stack.append(pairs[character])
        elif character in {"}", "]"}:
            if character != stack[-1]:
                return _line_end(text, start)
            stack.pop()
            if not stack:
                return index + 1
        index += 1
    return _line_end(text, start)


def _redacted_assignment_value(value: str) -> bool:
    candidate = value.strip()
    for delimiter in ('"', "'", '\\"', "\\'"):
        if candidate.startswith(delimiter) and candidate.endswith(delimiter):
            candidate = candidate[len(delimiter) : -len(delimiter)]
            break
    return candidate.casefold() == ENVIRONMENT_SECRET_REPLACEMENT.casefold()


def _format_assignment_replacement(value: str) -> str:
    for delimiter in ('\\"', "\\'", '"', "'"):
        if value.startswith(delimiter) and value.endswith(delimiter):
            return f"{delimiter}{ENVIRONMENT_SECRET_REPLACEMENT}{delimiter}"
    return ENVIRONMENT_SECRET_REPLACEMENT


def _replace_environment_assignments(text: str) -> tuple[str, int]:
    pieces: list[str] = []
    cursor = 0
    search_from = 0
    count = 0
    while match := _ENVIRONMENT_ASSIGNMENT_PREFIX.search(text, search_from):
        value_start = match.end()
        value_end = _structured_value_end(text, value_start)
        if value_end <= value_start:
            search_from = value_start
            continue
        raw_value = text[value_start:value_end]
        if _redacted_assignment_value(raw_value):
            search_from = value_end
            continue
        pieces.extend(
            (text[cursor:value_start], _format_assignment_replacement(raw_value))
        )
        cursor = value_end
        search_from = value_end
        count += 1
    pieces.append(text[cursor:])
    return "".join(pieces), count


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
    ):
        text, count = _subn_counted(pattern, replacement, text)
        total += count
    text, count = _replace_environment_assignments(text)
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
