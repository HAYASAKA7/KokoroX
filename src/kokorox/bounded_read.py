"""Read a bounded prefix of a binary stream."""

from __future__ import annotations

from typing import BinaryIO


_CHUNK_BYTES = 1024 * 1024


def read_at_most(stream: BinaryIO, limit: int) -> bytes:
    """Return up to ``limit`` bytes, reading until end of stream or the limit.

    ``stream.read(limit)`` on a buffered file reserves ``limit`` bytes before
    it reads anything. Callers pass a bound one past their maximum so an
    oversized input shows itself, and with the 64 MiB archive bound that
    reservation cost about 17 ms and 64 MiB on every call, whatever the file
    held. Reading in chunks keeps both proportional to the data.
    """

    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("limit must be a non-negative integer")
    chunks: list[bytes] = []
    remaining = limit
    while remaining > 0:
        chunk = stream.read(min(remaining, _CHUNK_BYTES))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
