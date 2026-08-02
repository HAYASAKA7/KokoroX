"""Deterministic compilation of validated character source packs."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any, cast

from kokoroarc import __version__
from kokoroarc.errors import KokoroError
from kokoroarc.json_compat import find_json_incompatibility
from kokoroarc.schemas import SchemaRegistry


def canonical_bytes(value: Any) -> bytes:
    """Return a compact, deterministic UTF-8 JSON representation of *value*."""
    incompatibility = find_json_incompatibility(value)
    if incompatibility is not None:
        path, message = incompatibility
        raise KokoroError(
            "INVALID_PACK_DATA",
            message,
            details={"path": path},
        )
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise KokoroError(
            "INVALID_PACK_DATA",
            "Artifact cannot be represented as canonical JSON.",
            details={"path": []},
        ) from error


def write_compiled_pack(value: dict[str, Any], target: Path) -> None:
    """Atomically publish a canonical compiled-pack document at *target*."""
    payload = canonical_bytes(value) + b"\n"
    target.parent.mkdir(parents=True, exist_ok=True)

    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    )
    staging = Path(handle.name)
    try:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(staging, target)
    except BaseException:
        try:
            if not handle.closed:
                handle.close()
        except BaseException:
            pass
        try:
            os.unlink(staging)
        except OSError:
            pass
        raise


def compile_pack(source: dict[str, Any], schemas: SchemaRegistry) -> dict[str, Any]:
    """Compile a validated source pack into its runtime-only representation."""
    source_bytes = canonical_bytes(source)
    source_copy = cast(dict[str, Any], json.loads(source_bytes))
    traits = source_copy.get("derived_profile", {}).get("traits", {})
    overrides = source_copy.get("overrides", {}).get("values", {})
    effective_profile = {
        key: overrides[key] if key in overrides else traits[key]
        for key in sorted(set(traits) | set(overrides))
    }
    provenance = {
        key: {
            "selected_layer": (
                "user_override" if key in overrides else "derived_profile"
            )
        }
        for key in effective_profile
    }

    compiled = {
        "schema_version": "1.0",
        "artifact_id": (
            f"{source_copy['namespace']}/{source_copy['character_id']}/compiled"
        ),
        "created_by": {"component": "kokoroarc", "version": __version__},
        "character_id": source_copy["character_id"],
        "character_version": source_copy["character_version"],
        "source_hash": sha256(source_bytes).hexdigest(),
        "identity": source_copy["identity"],
        "effective_profile": effective_profile,
        "provenance": provenance,
        "behavior": source_copy["behavior"],
        "growth": source_copy["growth"],
        "expressions": source_copy["expressions"],
        "locales": source_copy["locales"],
        "scenarios": source_copy["scenarios"],
    }
    schemas.validate("compiled-pack", compiled)
    return compiled
