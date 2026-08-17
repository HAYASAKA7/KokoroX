"""Deterministic, manifest-bound ``.karc`` archive construction and loading."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import io
import json
import re
import stat
import struct
from typing import Any, Protocol, cast
import zipfile

from kokoroarc import __version__
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes


_MANIFEST_PATH = "manifest.json"
_COMPILED_PATH = "pack/compiled.json"
_HARD_PATH = "release/hard-validation-report.json"
_PROMOTION_PATH = "release/promotion-record.json"
_PUBLICATION_PATH = "release/publication-readiness-report.json"
_REVIEW_PATH = "release/review-attestation.json"
_SOFT_PATH = "release/soft-evaluation-report.json"
_PRIVATE_PATHS = (
    _MANIFEST_PATH,
    _COMPILED_PATH,
    _HARD_PATH,
    _PROMOTION_PATH,
    _REVIEW_PATH,
    _SOFT_PATH,
)
_PUBLIC_PATHS = (
    _MANIFEST_PATH,
    _COMPILED_PATH,
    _HARD_PATH,
    _PROMOTION_PATH,
    _PUBLICATION_PATH,
    _REVIEW_PATH,
    _SOFT_PATH,
)
_ALLOWED_PATHS = frozenset(_PUBLIC_PATHS)
_MEMBER_ROLES = {
    _COMPILED_PATH: "compiled_pack",
    _HARD_PATH: "hard_validation_report",
    _PROMOTION_PATH: "promotion_record",
    _PUBLICATION_PATH: "publication_readiness_report",
    _REVIEW_PATH: "review_attestation",
    _SOFT_PATH: "soft_evaluation_report",
}
_MEMBER_SCHEMAS = {
    _COMPILED_PATH: "compiled-pack",
    _HARD_PATH: "pack-hard-validation-report",
    _PROMOTION_PATH: "pack-promotion-record",
    _PUBLICATION_PATH: "pack-publication-readiness-report",
    _REVIEW_PATH: "pack-review-attestation",
    _SOFT_PATH: "pack-soft-evaluation-report",
}
_FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_FIXED_DOS_DATE = 33
_FIXED_DOS_TIME = 0
_FIXED_MODE = stat.S_IFREG | 0o644
_LOCAL_HEADER = struct.Struct("<IHHHHHIIIHH")
_CENTRAL_HEADER = struct.Struct("<4s6H3I5H2I")
_EOCD = struct.Struct("<4s4H2LH")
_LOCAL_SIGNATURE = 0x04034B50
_CENTRAL_SIGNATURE = b"PK\x01\x02"
_EOCD_SIGNATURE = b"PK\x05\x06"
_FIXED_CREATE_VERSION = (3 << 8) | 20
_FIXED_EXTRACT_VERSION = 20
_SAFE_PATH = re.compile(r"[a-z0-9][a-z0-9._/-]{0,127}")
_WINDOWS_DEVICES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)
_SCHEMA_RANGE = {
    "minimum_inclusive": "1.0.0",
    "maximum_exclusive": "2.0.0",
}


class _SchemaValidator(Protocol):
    def validate(self, name: str, instance: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class KarcLimits:
    """Resource limits enforced before and while archive members are read."""

    max_archive_bytes: int = 64 * 1024 * 1024
    max_member_bytes: int = 16 * 1024 * 1024
    max_total_bytes: int = 64 * 1024 * 1024
    max_members: int = 7

    def __post_init__(self) -> None:
        if min(
            self.max_archive_bytes,
            self.max_member_bytes,
            self.max_total_bytes,
            self.max_members,
        ) <= 0:
            raise ValueError("KarcLimits values must be positive")


@dataclass(frozen=True, slots=True)
class LoadedKarcArchive:
    """Validated archive data detached from both input bytes and callbacks."""

    manifest: dict[str, Any]
    documents: dict[str, dict[str, Any]]
    archive_sha256: str


@dataclass(frozen=True, slots=True)
class _CapturedInput:
    name: str
    original: dict[str, Any]
    payload: bytes


class _AuditedSchemas:
    def __init__(
        self,
        delegate: _SchemaValidator,
        captured: tuple[_CapturedInput, ...],
    ) -> None:
        self._delegate = delegate
        self._captured = captured

    def validate(self, name: str, instance: Any) -> None:
        try:
            self._delegate.validate(name, instance)
        finally:
            _audit_inputs(self._captured)


def _error(code: str, message: str, **details: Any) -> KokoroError:
    return KokoroError(code, message, details=details)


def _digest(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _artifact_reference(document: dict[str, Any], payload: bytes) -> dict[str, str]:
    return {
        "artifact_id": cast(str, document["artifact_id"]),
        "sha256": _digest(payload),
    }


def _detached_object(payload: bytes, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise _error(code, "Artifact is not canonical JSON.") from error
    if not isinstance(value, dict):
        raise _error(code, "Artifact must be a JSON object.")
    return cast(dict[str, Any], value)


def _capture_input(name: str, value: Any) -> _CapturedInput:
    if not isinstance(value, dict):
        raise _error(
            "KARC_INPUT_INVALID",
            "Archive input must be a JSON object.",
            input=name,
        )
    try:
        payload = canonical_bytes(value)
    except KokoroError as error:
        raise _error(
            "KARC_INPUT_INVALID",
            "Archive input cannot be represented as canonical JSON.",
            input=name,
        ) from error
    return _CapturedInput(name, value, payload)


def _audit_inputs(captured: tuple[_CapturedInput, ...]) -> None:
    for item in captured:
        try:
            matches = canonical_bytes(item.original) == item.payload
        except KokoroError:
            matches = False
        if not matches:
            raise _error(
                "KARC_INPUT_MUTATION",
                "Archive input changed during export.",
                input=item.name,
            )


def _validate_schema(
    schemas: _SchemaValidator,
    name: str,
    document: dict[str, Any],
    *,
    invalid_code: str,
) -> None:
    payload = canonical_bytes(document)
    probe = _detached_object(payload, code=invalid_code)
    try:
        schemas.validate(name, probe)
    except KokoroError as error:
        if error.code == "KARC_INPUT_MUTATION":
            raise
        raise _error(
            invalid_code,
            "Release artifact failed schema validation.",
            schema=name,
        ) from error
    except Exception as error:
        raise _error(
            invalid_code,
            "Release artifact validation failed.",
            schema=name,
            reason=type(error).__name__,
        ) from error
    if canonical_bytes(probe) != payload:
        raise _error(
            invalid_code,
            "Schema validation mutated its detached input.",
            schema=name,
        )


def _binding(condition: bool, field: str) -> None:
    if not condition:
        raise _error(
            "KARC_BINDING_MISMATCH",
            "Release artifacts do not share an exact binding.",
            field=field,
        )


def _validate_release(
    documents: dict[str, dict[str, Any]],
    payloads: dict[str, bytes],
    schemas: _SchemaValidator,
) -> None:
    for path in sorted(documents):
        _validate_schema(
            schemas,
            _MEMBER_SCHEMAS[path],
            documents[path],
            invalid_code="KARC_RELEASE_INVALID",
        )

    compiled = documents[_COMPILED_PATH]
    hard = documents[_HARD_PATH]
    promotion = documents[_PROMOTION_PATH]
    review = documents[_REVIEW_PATH]
    soft = documents[_SOFT_PATH]
    publication = documents.get(_PUBLICATION_PATH)

    if (
        promotion.get("from_status") != "reviewed"
        or promotion.get("to_status") != "verified"
        or promotion.get("activation_allowed") is not True
    ):
        raise _error(
            "KARC_PROMOTION_NOT_VERIFIED",
            "Only an activation-eligible verified promotion may be exported.",
        )
    if hard.get("passed") is not True or soft.get("passed") is not True:
        raise _error(
            "KARC_RELEASE_INVALID",
            "Hard and soft release gates must pass before export.",
        )
    if review.get("decision") != "accept":
        raise _error(
            "KARC_RELEASE_INVALID",
            "The bound review must accept the release.",
        )

    visibility = promotion.get("visibility")
    if visibility == "private" and publication is not None:
        raise _error(
            "KARC_PUBLICATION_UNEXPECTED",
            "Private archives cannot contain a publication report.",
        )
    if visibility == "public_candidate" and publication is None:
        raise _error(
            "KARC_PUBLICATION_REQUIRED",
            "Public-candidate archives require a publication report.",
        )
    if visibility not in {"private", "public_candidate"}:
        raise _error("KARC_RELEASE_INVALID", "Promotion visibility is invalid.")

    identity_fields = ("character_id", "character_version")
    for field in identity_fields:
        expected = promotion.get(field)
        _binding(compiled.get(field) == expected, field)
        _binding(hard.get(field) == expected, field)
        _binding(review.get(field) == expected, field)
        _binding(soft.get(field) == expected, field)
    for field in ("namespace", "mode"):
        expected = promotion.get(field)
        _binding(hard.get(field) == expected, field)
        _binding(review.get(field) == expected, field)
        _binding(soft.get(field) == expected, field)
    _binding(hard.get("visibility") == visibility, "visibility")
    _binding(soft.get("visibility") == visibility, "visibility")

    source_artifact_id = promotion.get("source_artifact_id")
    source_hash = promotion.get("source_hash")
    for artifact in (hard, review, soft):
        _binding(
            artifact.get("source_artifact_id") == source_artifact_id,
            "source_artifact_id",
        )
        _binding(artifact.get("source_hash") == source_hash, "source_hash")

    compiled_hash = _digest(payloads[_COMPILED_PATH])
    compiled_artifact_id = compiled.get("artifact_id")
    _binding(compiled.get("source_hash") == source_hash, "compiled.source_hash")
    for artifact in (hard, promotion, soft):
        _binding(
            artifact.get("compiled_artifact_id") == compiled_artifact_id,
            "compiled_artifact_id",
        )
        _binding(artifact.get("compiled_hash") == compiled_hash, "compiled_hash")

    hard_reference = _artifact_reference(hard, payloads[_HARD_PATH])
    review_reference = _artifact_reference(review, payloads[_REVIEW_PATH])
    soft_reference = _artifact_reference(soft, payloads[_SOFT_PATH])
    _binding(review.get("hard_report") == hard_reference, "review.hard_report")
    _binding(promotion.get("hard_report") == hard_reference, "promotion.hard_report")
    _binding(
        promotion.get("review_attestation") == review_reference,
        "promotion.review_attestation",
    )
    _binding(
        promotion.get("soft_evaluation_report") == soft_reference,
        "promotion.soft_evaluation_report",
    )
    _binding(promotion.get("previous_promotion") is not None, "previous_promotion")

    if publication is not None:
        if (
            publication.get("requested_visibility") != "public_candidate"
            or publication.get("ready_for_private_export") is not True
            or publication.get("ready_for_publication") is not True
        ):
            raise _error(
                "KARC_PUBLICATION_NOT_READY",
                "Publication report does not authorize public release.",
            )
        for field in ("namespace", "character_id", "character_version", "mode"):
            _binding(publication.get(field) == promotion.get(field), field)
        for field in (
            "source_artifact_id",
            "source_hash",
            "compiled_artifact_id",
            "compiled_hash",
        ):
            _binding(publication.get(field) == promotion.get(field), field)
        _binding(
            publication.get("promotion")
            == _artifact_reference(promotion, payloads[_PROMOTION_PATH]),
            "publication.promotion",
        )


def _manifest(
    documents: dict[str, dict[str, Any]],
    payloads: dict[str, bytes],
) -> dict[str, Any]:
    compiled = documents[_COMPILED_PATH]
    hard = documents[_HARD_PATH]
    promotion = documents[_PROMOTION_PATH]
    review = documents[_REVIEW_PATH]
    soft = documents[_SOFT_PATH]
    publication = documents.get(_PUBLICATION_PATH)
    schema_ranges = {
        "compiled_pack": dict(_SCHEMA_RANGE),
        "hard_validation_report": dict(_SCHEMA_RANGE),
        "soft_evaluation_report": dict(_SCHEMA_RANGE),
        "review_attestation": dict(_SCHEMA_RANGE),
        "promotion_record": dict(_SCHEMA_RANGE),
        "publication_readiness_report": (
            dict(_SCHEMA_RANGE) if publication is not None else None
        ),
    }
    members = [
        {
            "path": path,
            "role": _MEMBER_ROLES[path],
            "size": len(payloads[path]),
            "sha256": _digest(payloads[path]),
        }
        for path in sorted(documents)
    ]
    publication_reference = (
        _artifact_reference(publication, payloads[_PUBLICATION_PATH])
        if publication is not None
        else None
    )
    return {
        "schema_version": "1.0",
        "artifact_id": (
            f"{promotion['namespace']}/{promotion['character_id']}"
            "/distribution/karc-manifest"
        ),
        "created_by": {"component": "kokoroarc", "version": __version__},
        "archive_id": (
            f"{promotion['namespace']}.{promotion['character_id']}."
            f"{promotion['compiled_hash'][:16]}"
        ),
        "format_version": "1.0.0",
        "namespace": promotion["namespace"],
        "character_id": promotion["character_id"],
        "character_version": promotion["character_version"],
        "source_artifact_id": promotion["source_artifact_id"],
        "source_hash": promotion["source_hash"],
        "compiled_artifact_id": compiled["artifact_id"],
        "compiled_hash": promotion["compiled_hash"],
        "hard_validation_report": _artifact_reference(hard, payloads[_HARD_PATH]),
        "soft_evaluation_report": _artifact_reference(soft, payloads[_SOFT_PATH]),
        "review_attestation": _artifact_reference(review, payloads[_REVIEW_PATH]),
        "promotion_record": _artifact_reference(
            promotion, payloads[_PROMOTION_PATH]
        ),
        "publication_readiness_report": publication_reference,
        "promotion_status": "verified",
        "visibility": promotion["visibility"],
        "activation_allowed": True,
        "trust": "unsigned_local",
        "compatibility": {
            "runtime": {
                "minimum_inclusive": "0.0.0",
                "maximum_exclusive": "1.0.0",
            },
            "schemas": schema_ranges,
        },
        "members": members,
    }


def _zip_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, _FIXED_TIMESTAMP)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.create_version = 20
    info.extract_version = _FIXED_EXTRACT_VERSION
    info.reserved = 0
    info.volume = 0
    info.external_attr = _FIXED_MODE << 16
    info.internal_attr = 0
    info.flag_bits = 0
    info.extra = b""
    info.comment = b""
    return info


def _write_archive(payloads: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_STORED,
        allowZip64=False,
        strict_timestamps=True,
    ) as package:
        package.comment = b""
        for path in sorted(payloads):
            package.writestr(_zip_info(path), payloads[path])
    return output.getvalue()


def build_karc_archive(
    *,
    compiled_pack: dict[str, Any],
    hard_validation_report: dict[str, Any],
    soft_evaluation_report: dict[str, Any],
    review_attestation: dict[str, Any],
    promotion_record: dict[str, Any],
    schemas: _SchemaValidator,
    publication_readiness_report: dict[str, Any] | None = None,
) -> bytes:
    """Build a deterministic archive from an exact verified release set."""

    raw_inputs = (
        ("compiled_pack", compiled_pack),
        ("hard_validation_report", hard_validation_report),
        ("soft_evaluation_report", soft_evaluation_report),
        ("review_attestation", review_attestation),
        ("promotion_record", promotion_record),
        *(
            (("publication_readiness_report", publication_readiness_report),)
            if publication_readiness_report is not None
            else ()
        ),
    )
    captured = tuple(_capture_input(name, value) for name, value in raw_inputs)
    _audit_inputs(captured)
    audited_schemas = _AuditedSchemas(schemas, captured)
    by_name = {item.name: item for item in captured}
    documents = {
        _COMPILED_PATH: _detached_object(
            by_name["compiled_pack"].payload, code="KARC_INPUT_INVALID"
        ),
        _HARD_PATH: _detached_object(
            by_name["hard_validation_report"].payload,
            code="KARC_INPUT_INVALID",
        ),
        _PROMOTION_PATH: _detached_object(
            by_name["promotion_record"].payload, code="KARC_INPUT_INVALID"
        ),
        _REVIEW_PATH: _detached_object(
            by_name["review_attestation"].payload, code="KARC_INPUT_INVALID"
        ),
        _SOFT_PATH: _detached_object(
            by_name["soft_evaluation_report"].payload,
            code="KARC_INPUT_INVALID",
        ),
    }
    if publication_readiness_report is not None:
        documents[_PUBLICATION_PATH] = _detached_object(
            by_name["publication_readiness_report"].payload,
            code="KARC_INPUT_INVALID",
        )
    payloads = {path: canonical_bytes(value) for path, value in documents.items()}

    try:
        _validate_release(documents, payloads, audited_schemas)
        manifest = _manifest(documents, payloads)
        _validate_schema(
            audited_schemas,
            "karc-manifest",
            manifest,
            invalid_code="KARC_RELEASE_INVALID",
        )
        archive_payloads = {_MANIFEST_PATH: canonical_bytes(manifest), **payloads}
        archive = _write_archive(archive_payloads)
        load_karc_archive(archive, audited_schemas)
        return archive
    finally:
        _audit_inputs(captured)


def _safe_name(name: str) -> bool:
    if not name.isascii() or _SAFE_PATH.fullmatch(name) is None:
        return False
    if name.startswith("/") or "\\" in name or ":" in name or "//" in name:
        return False
    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return False
    return not any(part.split(".", 1)[0].lower() in _WINDOWS_DEVICES for part in parts)


def _duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError("non-finite JSON number")


def _parse_member(payload: bytes) -> dict[str, Any]:
    try:
        text = payload.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_duplicate_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise _error(
            "KARC_ARCHIVE_INVALID",
            "Archive member is not strict canonical JSON.",
        ) from error
    if not isinstance(value, dict):
        raise _error(
            "KARC_ARCHIVE_INVALID",
            "Archive JSON members must contain objects.",
        )
    try:
        is_canonical = canonical_bytes(value) == payload
    except KokoroError as error:
        raise _error(
            "KARC_ARCHIVE_INVALID",
            "Archive member is not canonical JSON.",
        ) from error
    if not is_canonical:
        raise _error(
            "KARC_ARCHIVE_INVALID",
            "Archive member is not canonical JSON.",
        )
    return cast(dict[str, Any], value)


def _read_eocd(payload: bytes) -> tuple[int, int]:
    signature = payload[-_EOCD.size : -_EOCD.size + 4]
    if len(payload) < _EOCD.size or signature != _EOCD_SIGNATURE:
        raise _error("KARC_ARCHIVE_INVALID", "Archive framing is invalid.")
    (
        signature,
        disk_number,
        directory_disk,
        disk_entries,
        total_entries,
        directory_size,
        directory_offset,
        comment_size,
    ) = _EOCD.unpack(payload[-_EOCD.size :])
    if (
        signature != _EOCD_SIGNATURE
        or disk_number != 0
        or directory_disk != 0
        or disk_entries != total_entries
        or comment_size != 0
        or directory_offset + directory_size != len(payload) - _EOCD.size
    ):
        raise _error("KARC_ARCHIVE_INVALID", "Archive directory is invalid.")
    return total_entries, directory_offset


def _check_local_entry(
    payload: bytes,
    info: zipfile.ZipInfo,
    expected_offset: int,
) -> int:
    if info.header_offset != expected_offset:
        raise _error("KARC_ARCHIVE_INVALID", "Archive entries are not contiguous.")
    header_end = expected_offset + _LOCAL_HEADER.size
    if header_end > len(payload):
        raise _error("KARC_ARCHIVE_INVALID", "Archive local header is truncated.")
    (
        signature,
        extract_version,
        flags,
        compression,
        modified_time,
        modified_date,
        crc,
        compressed_size,
        file_size,
        name_size,
        extra_size,
    ) = _LOCAL_HEADER.unpack(payload[expected_offset:header_end])
    data_offset = header_end + name_size + extra_size
    data_end = data_offset + compressed_size
    try:
        name_bytes = info.filename.encode("ascii")
    except UnicodeEncodeError as error:
        raise _error("KARC_ARCHIVE_INVALID", "Archive path must be ASCII.") from error
    if (
        signature != _LOCAL_SIGNATURE
        or extract_version != _FIXED_EXTRACT_VERSION
        or flags != 0
        or compression != zipfile.ZIP_STORED
        or modified_time != _FIXED_DOS_TIME
        or modified_date != _FIXED_DOS_DATE
        or crc != info.CRC
        or compressed_size != info.compress_size
        or file_size != info.file_size
        or extra_size != 0
        or payload[header_end : header_end + name_size] != name_bytes
        or data_end > len(payload)
    ):
        raise _error("KARC_ARCHIVE_INVALID", "Archive local entry is invalid.")
    return data_end


def _check_central_directory(
    payload: bytes,
    total_entries: int,
    directory_offset: int,
    limits: KarcLimits,
) -> tuple[str, ...]:
    cursor = directory_offset
    directory_end = len(payload) - _EOCD.size
    declared_total = 0
    names: list[str] = []
    for _ in range(total_entries):
        header_end = cursor + _CENTRAL_HEADER.size
        if header_end > directory_end:
            raise _error(
                "KARC_ARCHIVE_INVALID",
                "Archive central directory is truncated.",
            )
        (
            signature,
            create_version,
            extract_version,
            flags,
            compression,
            modified_time,
            modified_date,
            _crc,
            compressed_size,
            file_size,
            name_size,
            extra_size,
            comment_size,
            disk_number,
            internal_attr,
            external_attr,
            _local_offset,
        ) = _CENTRAL_HEADER.unpack(payload[cursor:header_end])
        record_end = header_end + name_size + extra_size + comment_size
        if record_end > directory_end:
            raise _error(
                "KARC_ARCHIVE_INVALID",
                "Archive central directory record is truncated.",
            )
        try:
            name = payload[header_end : header_end + name_size].decode("ascii")
        except UnicodeDecodeError as error:
            raise _error(
                "KARC_ARCHIVE_INVALID",
                "Archive path must be ASCII.",
            ) from error
        if (
            signature != _CENTRAL_SIGNATURE
            or create_version != _FIXED_CREATE_VERSION
            or extract_version != _FIXED_EXTRACT_VERSION
            or flags != 0
            or compression != zipfile.ZIP_STORED
            or modified_time != _FIXED_DOS_TIME
            or modified_date != _FIXED_DOS_DATE
            or extra_size != 0
            or comment_size != 0
            or disk_number != 0
            or internal_attr != 0
            or external_attr != _FIXED_MODE << 16
            or compressed_size != file_size
        ):
            raise _error(
                "KARC_ARCHIVE_INVALID",
                "Archive central directory metadata is not canonical.",
            )
        if file_size > limits.max_member_bytes:
            raise _error(
                "KARC_ARCHIVE_LIMIT_EXCEEDED",
                "Archive member exceeds the byte limit.",
                limit="max_member_bytes",
            )
        declared_total += file_size
        if declared_total > limits.max_total_bytes:
            raise _error(
                "KARC_ARCHIVE_LIMIT_EXCEEDED",
                "Archive exceeds the expanded-byte limit.",
                limit="max_total_bytes",
            )
        names.append(name)
        cursor = record_end
    if cursor != directory_end:
        raise _error(
            "KARC_ARCHIVE_INVALID",
            "Archive central directory contains unlisted data.",
        )
    if names != sorted(names):
        raise _error(
            "KARC_ARCHIVE_INVALID",
            "Archive members are not lexicographically ordered.",
        )
    if len(names) != len(set(names)) or len(names) != len(
        {name.lower() for name in names}
    ):
        raise _error(
            "KARC_ARCHIVE_INVALID",
            "Archive contains duplicate or colliding member names.",
        )
    if any(
        not _safe_name(name) or name not in _ALLOWED_PATHS for name in names
    ):
        raise _error(
            "KARC_ARCHIVE_INVALID",
            "Archive contains an unsafe or forbidden member name.",
        )
    return tuple(names)


def _read_members(
    payload: bytes,
    limits: KarcLimits,
) -> tuple[dict[str, bytes], list[zipfile.ZipInfo]]:
    if len(payload) > limits.max_archive_bytes:
        raise _error(
            "KARC_ARCHIVE_LIMIT_EXCEEDED",
            "Archive exceeds the byte limit.",
            limit="max_archive_bytes",
        )
    if not payload.startswith(b"PK\x03\x04"):
        raise _error("KARC_ARCHIVE_INVALID", "Archive framing is invalid.")
    total_entries, directory_offset = _read_eocd(payload)
    if total_entries > limits.max_members:
        raise _error(
            "KARC_ARCHIVE_LIMIT_EXCEEDED",
            "Archive exceeds the member-count limit.",
            limit="max_members",
        )
    central_names = _check_central_directory(
        payload,
        total_entries,
        directory_offset,
        limits,
    )
    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as package:
            infos = package.infolist()
            if len(infos) != total_entries:
                raise _error(
                    "KARC_ARCHIVE_INVALID",
                    "Archive member count is inconsistent.",
                )
            names = [info.filename for info in infos]
            if tuple(names) != central_names:
                raise _error(
                    "KARC_ARCHIVE_INVALID",
                    "Archive member names are inconsistent.",
                )
            if names != sorted(names):
                raise _error(
                    "KARC_ARCHIVE_INVALID",
                    "Archive members are not lexicographically ordered.",
                )
            if len(names) != len(set(names)) or len(names) != len(
                {name.lower() for name in names}
            ):
                raise _error(
                    "KARC_ARCHIVE_INVALID",
                    "Archive contains duplicate or colliding member names.",
                )
            if any(
                not _safe_name(name) or name not in _ALLOWED_PATHS
                for name in names
            ):
                raise _error(
                    "KARC_ARCHIVE_INVALID",
                    "Archive contains an unsafe or forbidden member name.",
                )

            declared_total = 0
            cursor = 0
            for info in infos:
                if (
                    info.date_time != _FIXED_TIMESTAMP
                    or info.compress_type != zipfile.ZIP_STORED
                    or info.flag_bits != 0
                    or info.extra != b""
                    or info.comment != b""
                    or info.create_system != 3
                    or info.create_version != 20
                    or info.extract_version != _FIXED_EXTRACT_VERSION
                    or info.reserved != 0
                    or info.volume != 0
                    or info.internal_attr != 0
                    or info.external_attr != _FIXED_MODE << 16
                    or info.is_dir()
                ):
                    raise _error(
                        "KARC_ARCHIVE_INVALID",
                        "Archive member metadata is not canonical.",
                    )
                if (
                    info.file_size > limits.max_member_bytes
                    or info.compress_size > limits.max_member_bytes
                ):
                    raise _error(
                        "KARC_ARCHIVE_LIMIT_EXCEEDED",
                        "Archive member exceeds the byte limit.",
                        limit="max_member_bytes",
                    )
                if info.compress_size != info.file_size:
                    raise _error(
                        "KARC_ARCHIVE_INVALID",
                        "Archive members must use stored encoding.",
                    )
                declared_total += info.file_size
                if declared_total > limits.max_total_bytes:
                    raise _error(
                        "KARC_ARCHIVE_LIMIT_EXCEEDED",
                        "Archive exceeds the expanded-byte limit.",
                        limit="max_total_bytes",
                    )
                cursor = _check_local_entry(payload, info, cursor)
            if cursor != directory_offset:
                raise _error(
                    "KARC_ARCHIVE_INVALID",
                    "Archive contains data outside its members.",
                )

            members: dict[str, bytes] = {}
            actual_total = 0
            for info in infos:
                with package.open(info, "r") as reader:
                    member = reader.read(limits.max_member_bytes + 1)
                    if reader.read(1):
                        member += b"x"
                if (
                    len(member) != info.file_size
                    or len(member) > limits.max_member_bytes
                ):
                    raise _error(
                        "KARC_ARCHIVE_LIMIT_EXCEEDED",
                        "Archive member exceeds its declared or configured size.",
                        limit="max_member_bytes",
                    )
                actual_total += len(member)
                if actual_total > limits.max_total_bytes:
                    raise _error(
                        "KARC_ARCHIVE_LIMIT_EXCEEDED",
                        "Archive exceeds the expanded-byte limit.",
                        limit="max_total_bytes",
                    )
                members[info.filename] = member
            return members, infos
    except KokoroError:
        raise
    except (
        OSError,
        RuntimeError,
        ValueError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ) as error:
        raise _error(
            "KARC_ARCHIVE_INVALID", "Archive cannot be read safely."
        ) from error


def _validate_manifest(
    manifest: dict[str, Any],
    documents: dict[str, dict[str, Any]],
    member_payloads: dict[str, bytes],
) -> None:
    visibility = manifest.get("visibility")
    expected_paths = (
        _PUBLIC_PATHS if visibility == "public_candidate" else _PRIVATE_PATHS
    )
    if tuple(member_payloads) != expected_paths:
        raise _error(
            "KARC_ARCHIVE_INVALID",
            "Archive inventory does not match its visibility.",
        )
    expected_members = [
        {
            "path": path,
            "role": _MEMBER_ROLES[path],
            "size": len(member_payloads[path]),
            "sha256": _digest(member_payloads[path]),
        }
        for path in expected_paths[1:]
    ]
    if manifest.get("members") != expected_members:
        raise _error(
            "KARC_ARCHIVE_INVALID",
            "Manifest member inventory does not match archive bytes.",
        )
    compiled = documents[_COMPILED_PATH]
    promotion = documents[_PROMOTION_PATH]
    expected = {
        "namespace": promotion["namespace"],
        "character_id": promotion["character_id"],
        "character_version": promotion["character_version"],
        "source_artifact_id": promotion["source_artifact_id"],
        "source_hash": promotion["source_hash"],
        "compiled_artifact_id": compiled["artifact_id"],
        "compiled_hash": promotion["compiled_hash"],
        "promotion_status": "verified",
        "visibility": promotion["visibility"],
        "activation_allowed": True,
        "trust": "unsigned_local",
        "hard_validation_report": _artifact_reference(
            documents[_HARD_PATH], member_payloads[_HARD_PATH]
        ),
        "soft_evaluation_report": _artifact_reference(
            documents[_SOFT_PATH], member_payloads[_SOFT_PATH]
        ),
        "review_attestation": _artifact_reference(
            documents[_REVIEW_PATH], member_payloads[_REVIEW_PATH]
        ),
        "promotion_record": _artifact_reference(
            promotion, member_payloads[_PROMOTION_PATH]
        ),
        "publication_readiness_report": (
            _artifact_reference(
                documents[_PUBLICATION_PATH], member_payloads[_PUBLICATION_PATH]
            )
            if _PUBLICATION_PATH in documents
            else None
        ),
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            raise _error(
                "KARC_ARCHIVE_INVALID",
                "Manifest release binding is invalid.",
                field=field,
            )


def load_karc_archive(
    payload: bytes,
    schemas: _SchemaValidator,
    *,
    limits: KarcLimits = KarcLimits(),
) -> LoadedKarcArchive:
    """Strictly validate and load a closed ``.karc`` archive from bytes."""

    if not isinstance(payload, bytes):
        raise _error("KARC_ARCHIVE_INVALID", "Archive payload must be bytes.")
    member_payloads, _infos = _read_members(payload, limits)
    if _MANIFEST_PATH not in member_payloads:
        raise _error("KARC_ARCHIVE_INVALID", "Archive manifest is missing.")
    parsed = {path: _parse_member(value) for path, value in member_payloads.items()}
    manifest = parsed[_MANIFEST_PATH]
    documents = {
        path: value
        for path, value in parsed.items()
        if path != _MANIFEST_PATH
    }
    try:
        _validate_schema(
            schemas,
            "karc-manifest",
            manifest,
            invalid_code="KARC_ARCHIVE_INVALID",
        )
        _validate_manifest(manifest, documents, member_payloads)
        _validate_release(documents, member_payloads, schemas)
    except KokoroError as error:
        if error.code in {
            "KARC_ARCHIVE_INVALID",
            "KARC_ARCHIVE_LIMIT_EXCEEDED",
            "KARC_INPUT_MUTATION",
        }:
            raise
        raise _error(
            "KARC_ARCHIVE_INVALID",
            "Archive release bindings are invalid.",
            reason=error.code,
        ) from error
    detached_manifest = _parse_member(member_payloads[_MANIFEST_PATH])
    detached_documents = {
        path: _parse_member(member_payloads[path])
        for path in sorted(documents)
    }
    return LoadedKarcArchive(
        manifest=detached_manifest,
        documents={_MANIFEST_PATH: detached_manifest, **detached_documents},
        archive_sha256=_digest(payload),
    )
