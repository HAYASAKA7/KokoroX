from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import PureWindowsPath
from typing import Literal, NoReturn


COMMAND_WRAPPER_INVALID = "COMMAND_WRAPPER_INVALID"
COMMAND_WRAPPER_IDENTITY_MISMATCH = "COMMAND_WRAPPER_IDENTITY_MISMATCH"
COMMAND_PAYLOAD_LIMIT_EXCEEDED = "COMMAND_PAYLOAD_LIMIT_EXCEEDED"

_PAYLOAD_LIMIT_BYTES = 256 * 1024
_WRAPPER_ARGUMENTS = b" -NoLogo -NoProfile -NonInteractive -Command "
_APOSTROPHE = 0x27
_DOUBLE_QUOTE = 0x22
_BACKSLASH = 0x5C


@dataclass(frozen=True)
class ShellIdentity:
    path: str
    sha256: str
    file_version: str
    product_version: str
    edition: str
    parser_version: str


@dataclass(frozen=True)
class ExtractedPowerShellPayload:
    rendered_utf8_bytes: int
    rendered_sha256: str
    payload_field_utf8_bytes: int
    payload_field_sha256: str
    payload_utf8_bytes: int
    payload_sha256: str
    payload: str


def _reject(code: str) -> NoReturn:
    raise RuntimeError(code)


def _is_absolute_shell_path(path: object) -> bool:
    if type(path) is not str or not path:
        return False
    for character in path:
        if (
            character == "\x00"
            or character == "\r"
            or character == "\n"
            or character == '"'
        ):
            return False
    try:
        path.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return PureWindowsPath(path).is_absolute()


def _payload_utf8(payload: object) -> bytes:
    if type(payload) is not str:
        _reject(COMMAND_WRAPPER_INVALID)
    payload_utf8_bytes = 0
    for character in payload:
        scalar = ord(character)
        if scalar == 0x00 or scalar == 0x0D or 0xD800 <= scalar <= 0xDFFF:
            _reject(COMMAND_WRAPPER_INVALID)
        if scalar <= 0x7F:
            payload_utf8_bytes += 1
        elif scalar <= 0x7FF:
            payload_utf8_bytes += 2
        elif scalar <= 0xFFFF:
            payload_utf8_bytes += 3
        else:
            payload_utf8_bytes += 4
    if payload_utf8_bytes > _PAYLOAD_LIMIT_BYTES:
        _reject(COMMAND_PAYLOAD_LIMIT_EXCEEDED)
    try:
        payload_bytes = payload.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _reject(COMMAND_WRAPPER_INVALID)
    if len(payload_bytes) != payload_utf8_bytes:
        _reject(COMMAND_WRAPPER_INVALID)
    return payload_bytes


def _render_single_quoted(payload: bytes) -> bytes:
    rendered = bytearray((_APOSTROPHE,))
    for value in payload:
        rendered.append(value)
        if value == _APOSTROPHE:
            rendered.append(value)
    rendered.append(_APOSTROPHE)
    return bytes(rendered)


def _render_double_quoted(payload: bytes) -> bytes:
    rendered = bytearray((_DOUBLE_QUOTE,))
    cursor = 0
    while cursor < len(payload):
        value = payload[cursor]
        if value == _BACKSLASH:
            run_start = cursor
            while cursor < len(payload) and payload[cursor] == _BACKSLASH:
                cursor += 1
            run_length = cursor - run_start
            if cursor == len(payload):
                rendered.extend((_BACKSLASH,) * (run_length * 2))
                break
            if payload[cursor] == _DOUBLE_QUOTE:
                rendered.extend((_BACKSLASH,) * (run_length * 2 + 1))
                rendered.append(_DOUBLE_QUOTE)
                cursor += 1
                continue
            rendered.extend((_BACKSLASH,) * run_length)
            continue
        if value == _DOUBLE_QUOTE:
            rendered.append(_BACKSLASH)
        rendered.append(value)
        cursor += 1
    rendered.append(_DOUBLE_QUOTE)
    return bytes(rendered)


def render_powershell_argv(
    payload: str,
    *,
    shell_path: str,
    quote_style: Literal["single", "double"],
) -> bytes:
    if not _is_absolute_shell_path(shell_path):
        _reject(COMMAND_WRAPPER_INVALID)
    if type(quote_style) is not str:
        _reject(COMMAND_WRAPPER_INVALID)
    if quote_style != "single" and quote_style != "double":
        _reject(COMMAND_WRAPPER_INVALID)

    payload_bytes = _payload_utf8(payload)
    try:
        shell_path_bytes = shell_path.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _reject(COMMAND_WRAPPER_INVALID)

    if quote_style == "single":
        payload_field = _render_single_quoted(payload_bytes)
    else:
        payload_field = _render_double_quoted(payload_bytes)
    return (
        b'"'
        + shell_path_bytes
        + b'"'
        + _WRAPPER_ARGUMENTS
        + payload_field
    )


def _reject_forbidden_rendered_bytes(rendered: bytes) -> None:
    for value in rendered:
        if value in (0x00, 0x0D):
            _reject(COMMAND_WRAPPER_INVALID)


def _is_utf8_continuation(value: int) -> bool:
    return 0x80 <= value <= 0xBF


def _reject_invalid_utf8(rendered: bytes) -> None:
    cursor = 0
    while cursor < len(rendered):
        first = rendered[cursor]
        if first <= 0x7F:
            cursor += 1
            continue
        if 0xC2 <= first <= 0xDF:
            if (
                cursor + 1 >= len(rendered)
                or not _is_utf8_continuation(rendered[cursor + 1])
            ):
                _reject(COMMAND_WRAPPER_INVALID)
            cursor += 2
            continue
        if 0xE0 <= first <= 0xEF:
            if cursor + 2 >= len(rendered):
                _reject(COMMAND_WRAPPER_INVALID)
            second = rendered[cursor + 1]
            third = rendered[cursor + 2]
            if first == 0xE0:
                second_is_valid = 0xA0 <= second <= 0xBF
            elif first == 0xED:
                second_is_valid = 0x80 <= second <= 0x9F
            else:
                second_is_valid = _is_utf8_continuation(second)
            if not second_is_valid or not _is_utf8_continuation(third):
                _reject(COMMAND_WRAPPER_INVALID)
            cursor += 3
            continue
        if 0xF0 <= first <= 0xF4:
            if cursor + 3 >= len(rendered):
                _reject(COMMAND_WRAPPER_INVALID)
            second = rendered[cursor + 1]
            third = rendered[cursor + 2]
            fourth = rendered[cursor + 3]
            if first == 0xF0:
                second_is_valid = 0x90 <= second <= 0xBF
            elif first == 0xF4:
                second_is_valid = 0x80 <= second <= 0x8F
            else:
                second_is_valid = _is_utf8_continuation(second)
            if (
                not second_is_valid
                or not _is_utf8_continuation(third)
                or not _is_utf8_continuation(fourth)
            ):
                _reject(COMMAND_WRAPPER_INVALID)
            cursor += 4
            continue
        _reject(COMMAND_WRAPPER_INVALID)


def _closing_shell_quote(rendered: bytes) -> int:
    if not rendered or rendered[0] != _DOUBLE_QUOTE:
        _reject(COMMAND_WRAPPER_INVALID)
    cursor = 1
    while cursor < len(rendered):
        if rendered[cursor] == _DOUBLE_QUOTE:
            return cursor
        cursor += 1
    _reject(COMMAND_WRAPPER_INVALID)


def _count_single_quoted(field: memoryview) -> int:
    payload_bytes = 0
    cursor = 1
    while cursor < len(field):
        value = field[cursor]
        if value != _APOSTROPHE:
            payload_bytes += 1
            cursor += 1
            continue
        if cursor + 1 < len(field) and field[cursor + 1] == _APOSTROPHE:
            payload_bytes += 1
            cursor += 2
            continue
        if cursor != len(field) - 1:
            _reject(COMMAND_WRAPPER_INVALID)
        return payload_bytes
    _reject(COMMAND_WRAPPER_INVALID)


def _count_double_quoted(field: memoryview) -> int:
    payload_bytes = 0
    cursor = 1
    while cursor < len(field):
        value = field[cursor]
        if value == _BACKSLASH:
            run_start = cursor
            while cursor < len(field) and field[cursor] == _BACKSLASH:
                cursor += 1
            run_length = cursor - run_start
            if cursor < len(field) and field[cursor] == _DOUBLE_QUOTE:
                payload_bytes += run_length // 2
                if run_length % 2:
                    payload_bytes += 1
                    cursor += 1
                    continue
                if cursor != len(field) - 1:
                    _reject(COMMAND_WRAPPER_INVALID)
                return payload_bytes
            payload_bytes += run_length
            continue
        if value == _DOUBLE_QUOTE:
            if cursor != len(field) - 1:
                _reject(COMMAND_WRAPPER_INVALID)
            return payload_bytes
        payload_bytes += 1
        cursor += 1
    _reject(COMMAND_WRAPPER_INVALID)


def _decode_single_quoted(field: memoryview) -> bytes:
    payload = bytearray()
    cursor = 1
    while cursor < len(field):
        value = field[cursor]
        if value != _APOSTROPHE:
            payload.append(value)
            cursor += 1
            continue
        if cursor + 1 < len(field) and field[cursor + 1] == _APOSTROPHE:
            payload.append(_APOSTROPHE)
            cursor += 2
            continue
        if cursor != len(field) - 1:
            _reject(COMMAND_WRAPPER_INVALID)
        return bytes(payload)
    _reject(COMMAND_WRAPPER_INVALID)


def _decode_double_quoted(field: memoryview) -> bytes:
    payload = bytearray()
    cursor = 1
    while cursor < len(field):
        value = field[cursor]
        if value == _BACKSLASH:
            run_start = cursor
            while cursor < len(field) and field[cursor] == _BACKSLASH:
                cursor += 1
            run_length = cursor - run_start
            if cursor < len(field) and field[cursor] == _DOUBLE_QUOTE:
                payload.extend((_BACKSLASH,) * (run_length // 2))
                if run_length % 2:
                    payload.append(_DOUBLE_QUOTE)
                    cursor += 1
                    continue
                if cursor != len(field) - 1:
                    _reject(COMMAND_WRAPPER_INVALID)
                return bytes(payload)
            payload.extend((_BACKSLASH,) * run_length)
            continue
        if value == _DOUBLE_QUOTE:
            if cursor != len(field) - 1:
                _reject(COMMAND_WRAPPER_INVALID)
            return bytes(payload)
        payload.append(value)
        cursor += 1
    _reject(COMMAND_WRAPPER_INVALID)


def extract_powershell_payload(
    rendered: bytes,
    *,
    shell: ShellIdentity,
) -> ExtractedPowerShellPayload:
    if type(rendered) is not bytes or type(shell) is not ShellIdentity:
        _reject(COMMAND_WRAPPER_INVALID)
    if not _is_absolute_shell_path(shell.path):
        _reject(COMMAND_WRAPPER_INVALID)
    _reject_forbidden_rendered_bytes(rendered)
    _reject_invalid_utf8(rendered)

    closing_quote = _closing_shell_quote(rendered)
    rendered_shell_path = rendered[1:closing_quote]
    try:
        decoded_shell_path = rendered_shell_path.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _reject(COMMAND_WRAPPER_INVALID)
    if not _is_absolute_shell_path(decoded_shell_path):
        _reject(COMMAND_WRAPPER_INVALID)

    arguments_start = closing_quote + 1
    arguments_end = arguments_start + len(_WRAPPER_ARGUMENTS)
    if rendered[arguments_start:arguments_end] != _WRAPPER_ARGUMENTS:
        _reject(COMMAND_WRAPPER_INVALID)
    payload_field = memoryview(rendered)[arguments_end:]
    if len(payload_field) < 2:
        _reject(COMMAND_WRAPPER_INVALID)

    if payload_field[0] == _APOSTROPHE:
        quote_style: Literal["single", "double"] = "single"
        decoded_payload_bytes = _count_single_quoted(payload_field)
    elif payload_field[0] == _DOUBLE_QUOTE:
        quote_style = "double"
        decoded_payload_bytes = _count_double_quoted(payload_field)
    else:
        _reject(COMMAND_WRAPPER_INVALID)
    if decoded_payload_bytes > _PAYLOAD_LIMIT_BYTES:
        _reject(COMMAND_PAYLOAD_LIMIT_EXCEEDED)

    if quote_style == "single":
        payload_bytes = _decode_single_quoted(payload_field)
    else:
        payload_bytes = _decode_double_quoted(payload_field)
    if len(payload_bytes) != decoded_payload_bytes:
        _reject(COMMAND_WRAPPER_INVALID)

    try:
        payload = payload_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _reject(COMMAND_WRAPPER_INVALID)

    rerendered = render_powershell_argv(
        payload,
        shell_path=decoded_shell_path,
        quote_style=quote_style,
    )
    if rerendered != rendered:
        _reject(COMMAND_WRAPPER_INVALID)
    if decoded_shell_path != shell.path:
        _reject(COMMAND_WRAPPER_IDENTITY_MISMATCH)

    return ExtractedPowerShellPayload(
        rendered_utf8_bytes=len(rendered),
        rendered_sha256=sha256(rendered).hexdigest(),
        payload_field_utf8_bytes=len(payload_field),
        payload_field_sha256=sha256(payload_field).hexdigest(),
        payload_utf8_bytes=len(payload_bytes),
        payload_sha256=sha256(payload_bytes).hexdigest(),
        payload=payload,
    )
