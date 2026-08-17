from __future__ import annotations

from dataclasses import replace
import io
from pathlib import Path
import stat
import struct
from typing import Any
import warnings
import zipfile

import pytest

from kokoroarc.distribution.archive import (
    KarcLimits,
    build_karc_archive,
    load_karc_archive,
)
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import compile_pack
from kokoroarc.packs.loader import load_source_pack
from kokoroarc.schemas import SchemaRegistry


SCHEMAS = SchemaRegistry(Path("schemas/v1"))
RIN_PACK = Path("characters/original/rin-aster")


def _valid_archive(release: dict[str, Any]) -> bytes:
    evidence = release["evidence"]
    compiled = compile_pack(load_source_pack(RIN_PACK, SCHEMAS), SCHEMAS)
    return build_karc_archive(
        compiled_pack=compiled,
        hard_validation_report=evidence["hard_report"],
        soft_evaluation_report=evidence["soft_evaluation_report"],
        review_attestation=evidence["review_attestation"],
        promotion_record=release["promotion"],
        schemas=SCHEMAS,
    )


def _entries(archive: bytes) -> list[tuple[zipfile.ZipInfo, bytes]]:
    with zipfile.ZipFile(io.BytesIO(archive), "r") as package:
        return [(info, package.read(info)) for info in package.infolist()]


def _info(
    name: str,
    *,
    compression: int = zipfile.ZIP_STORED,
    mode: int = stat.S_IFREG | 0o644,
    extra: bytes = b"",
    comment: bytes = b"",
) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.compress_type = compression
    info.create_system = 3
    info.external_attr = mode << 16
    info.extra = extra
    info.comment = comment
    return info


def _rewrite(
    entries: list[tuple[zipfile.ZipInfo, bytes]],
    *,
    archive_comment: bytes = b"",
) -> bytes:
    output = io.BytesIO()
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Duplicate name:")
        with zipfile.ZipFile(output, "w", allowZip64=False) as package:
            package.comment = archive_comment
            for info, payload in entries:
                package.writestr(info, payload)
    return output.getvalue()


def _assert_invalid(payload: bytes, *, limits: KarcLimits | None = None) -> None:
    with pytest.raises(KokoroError) as caught:
        load_karc_archive(payload, SCHEMAS, limits=limits or KarcLimits())
    assert caught.value.code in {
        "KARC_ARCHIVE_INVALID",
        "KARC_ARCHIVE_LIMIT_EXCEEDED",
    }


def test_loader_rejects_missing_and_extra_members(
    rin_verified_release: dict[str, Any],
) -> None:
    entries = _entries(_valid_archive(rin_verified_release))
    missing = _rewrite(entries[:-1])
    extra = _rewrite([*entries, (_info("source/identity.yaml"), b"private")])

    _assert_invalid(missing)
    _assert_invalid(extra)


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "../manifest.json",
        "/manifest.json",
        "pack\\compiled.json",
        "pack//compiled.json",
        "pack/../compiled.json",
        "pack/compiled.json:payload",
        "CON",
        "release/state.json",
        "release/memory.json",
        "release/research.json",
        "release/payload.exe",
    ],
)
def test_loader_rejects_unsafe_or_forbidden_names(
    rin_verified_release: dict[str, Any], unsafe_name: str
) -> None:
    entries = _entries(_valid_archive(rin_verified_release))
    entries[-1] = (_info(unsafe_name), entries[-1][1])

    _assert_invalid(_rewrite(entries))


def test_loader_rejects_duplicate_and_case_colliding_names(
    rin_verified_release: dict[str, Any],
) -> None:
    entries = _entries(_valid_archive(rin_verified_release))
    duplicate = _rewrite([*entries, (_info(entries[1][0].filename), entries[1][1])])
    collision = _rewrite(
        [*entries, (_info("PACK/compiled.json"), entries[1][1])]
    )

    _assert_invalid(duplicate)
    _assert_invalid(collision)


@pytest.mark.parametrize(
    "replacement",
    [
        _info("pack/compiled.json", mode=stat.S_IFLNK | 0o777),
        _info("pack/compiled.json", mode=stat.S_IFIFO | 0o644),
        _info("pack/compiled.json", extra=b"\x01\x00\x00\x00"),
        _info("pack/compiled.json", comment=b"member comment"),
        _info("pack/compiled.json", compression=zipfile.ZIP_DEFLATED),
    ],
)
def test_loader_rejects_links_devices_extras_comments_and_compression(
    rin_verified_release: dict[str, Any], replacement: zipfile.ZipInfo
) -> None:
    entries = _entries(_valid_archive(rin_verified_release))
    entries[1] = (replacement, entries[1][1])

    _assert_invalid(_rewrite(entries))


def test_loader_rejects_archive_comments_prefixes_and_suffixes(
    rin_verified_release: dict[str, Any],
) -> None:
    archive = _valid_archive(rin_verified_release)
    entries = _entries(archive)

    _assert_invalid(_rewrite(entries, archive_comment=b"comment"))
    _assert_invalid(b"prefix" + archive)
    _assert_invalid(archive + b"suffix")


def test_loader_rejects_encrypted_flags_before_reading_members(
    rin_verified_release: dict[str, Any],
) -> None:
    payload = bytearray(_valid_archive(rin_verified_release))
    local = payload.find(b"PK\x03\x04")
    central = payload.find(b"PK\x01\x02")
    local_flags = struct.unpack_from("<H", payload, local + 6)[0]
    central_flags = struct.unpack_from("<H", payload, central + 8)[0]
    struct.pack_into("<H", payload, local + 6, local_flags | 1)
    struct.pack_into("<H", payload, central + 8, central_flags | 1)

    _assert_invalid(bytes(payload))


def test_loader_rejects_noncanonical_zip_version_metadata(
    rin_verified_release: dict[str, Any],
) -> None:
    payload = bytearray(_valid_archive(rin_verified_release))
    local = payload.find(b"PK\x03\x04")
    central = payload.find(b"PK\x01\x02")
    struct.pack_into("<H", payload, local + 4, 10)
    struct.pack_into("<H", payload, central + 4, (3 << 8) | 10)
    struct.pack_into("<H", payload, central + 6, 10)

    _assert_invalid(bytes(payload))


def test_loader_enforces_archive_member_and_total_size_limits(
    rin_verified_release: dict[str, Any],
) -> None:
    archive = _valid_archive(rin_verified_release)
    infos = _entries(archive)
    largest = max(len(payload) for _, payload in infos)
    total = sum(len(payload) for _, payload in infos)

    _assert_invalid(archive, limits=KarcLimits(max_archive_bytes=len(archive) - 1))
    _assert_invalid(archive, limits=KarcLimits(max_member_bytes=largest - 1))
    _assert_invalid(archive, limits=KarcLimits(max_total_bytes=total - 1))
    _assert_invalid(archive, limits=replace(KarcLimits(), max_members=5))


def test_loader_rejects_noncanonical_or_manifest_mismatched_member_bytes(
    rin_verified_release: dict[str, Any],
) -> None:
    entries = _entries(_valid_archive(rin_verified_release))
    entries[1] = (entries[1][0], entries[1][1] + b"\n")

    _assert_invalid(_rewrite(entries))


def test_loader_rejects_duplicate_json_keys(
    rin_verified_release: dict[str, Any],
) -> None:
    entries = _entries(_valid_archive(rin_verified_release))
    duplicate_keys = b'{"schema_version":"1.0","schema_version":"1.0"}'
    entries[0] = (_info("manifest.json"), duplicate_keys)

    _assert_invalid(_rewrite(entries))
