from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from kokoroarc import __version__
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes, compile_pack
from kokoroarc.packs.loader import load_source_pack
from kokoroarc.schemas import SchemaRegistry


SCHEMAS = SchemaRegistry(Path("schemas/v1"))
RIN_PACK = Path("characters/original/rin-aster")


def load_rin_source() -> dict[str, Any]:
    return load_source_pack(RIN_PACK, SCHEMAS)


def test_canonical_bytes_are_compact_utf8_and_independent_of_mapping_order() -> None:
    first = {"z": "原因已经明确。", "a": [2, 1]}
    second = {"a": [2, 1], "z": "原因已经明确。"}

    expected = b'{"a":[2,1],"z":"\xe5\x8e\x9f\xe5\x9b\xa0\xe5\xb7\xb2\xe7\xbb\x8f\xe6\x98\x8e\xe7\xa1\xae\xe3\x80\x82"}'

    assert canonical_bytes(first) == expected
    assert canonical_bytes(second) == expected
    assert list(first) == ["z", "a"]


def test_canonical_bytes_preserves_valid_multilingual_non_bmp_text_as_utf8() -> None:
    value = {"message": "日本語😀原因已经明确。"}

    encoded = canonical_bytes(value)

    assert "日本語😀原因已经明确。".encode("utf-8") in encoded
    assert b"\\u" not in encoded


def test_compile_rin_pack_is_deterministic_valid_and_excludes_authoring_only_data() -> None:
    source = load_rin_source()

    first = compile_pack(source, SCHEMAS)
    second = compile_pack(source, SCHEMAS)

    assert first == second
    assert len(first["source_hash"]) == 64
    assert all(character in "0123456789abcdef" for character in first["source_hash"])
    assert "evidence" not in first
    assert "derived_profile" not in first
    assert "overrides" not in first
    assert not {"files", "locale_files", "scenario_files"} & first.keys()
    SCHEMAS.validate("compiled-pack", first)


def test_compile_pack_hashes_the_exact_canonical_source_bytes() -> None:
    source = load_rin_source()

    compiled = compile_pack(source, SCHEMAS)

    assert compiled["source_hash"] == sha256(canonical_bytes(source)).hexdigest()


def test_compile_pack_applies_overrides_and_records_the_selected_layer() -> None:
    source = load_rin_source()
    source["overrides"] = {
        "values": {"warmth": 0.38, "focus": 0.61},
    }

    compiled = compile_pack(source, SCHEMAS)

    assert compiled["effective_profile"]["warmth"] == 0.38
    assert compiled["effective_profile"]["focus"] == 0.61
    assert compiled["provenance"]["warmth"] == {"selected_layer": "user_override"}
    assert compiled["provenance"]["focus"] == {"selected_layer": "user_override"}
    assert compiled["provenance"]["composure"] == {
        "selected_layer": "derived_profile"
    }
    assert list(compiled["effective_profile"]) == sorted(compiled["effective_profile"])
    assert list(compiled["provenance"]) == sorted(compiled["provenance"])


def test_compile_pack_builds_runtime_metadata() -> None:
    compiled = compile_pack(load_rin_source(), SCHEMAS)

    assert compiled["schema_version"] == "1.0"
    assert compiled["artifact_id"] == "original/rin-aster/compiled"
    assert compiled["created_by"] == {"component": "kokoroarc", "version": __version__}
    assert compiled["character_id"] == "rin-aster"
    assert compiled["character_version"] == "1.0.0"


def test_compile_pack_validates_exactly_once_and_propagates_schema_error() -> None:
    source = load_rin_source()
    expected = KokoroError("SCHEMA_VALIDATION_FAILED", "invalid compiled pack")
    calls: list[tuple[str, dict[str, Any]]] = []

    def validate(name: str, value: dict[str, Any]) -> None:
        calls.append((name, value))
        raise expected

    with pytest.raises(KokoroError) as raised:
        compile_pack(source, SimpleNamespace(validate=validate))  # type: ignore[arg-type]

    assert raised.value is expected
    assert len(calls) == 1
    assert calls[0][0] == "compiled-pack"
    assert calls[0][1]["artifact_id"] == "original/rin-aster/compiled"


def test_compile_pack_validates_the_exact_returned_object_once() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def validate(name: str, value: dict[str, Any]) -> None:
        calls.append((name, value))

    compiled = compile_pack(
        load_rin_source(), SimpleNamespace(validate=validate)  # type: ignore[arg-type]
    )

    assert calls == [("compiled-pack", compiled)]
    assert calls[0][1] is compiled


def test_compile_pack_does_not_mutate_or_alias_source_or_other_results() -> None:
    source = load_rin_source()
    original = deepcopy(source)

    first = compile_pack(source, SCHEMAS)
    second = compile_pack(source, SCHEMAS)
    first["identity"]["non_negotiables"].append("changed runtime")
    first["locales"]["zh-CN"]["register"] = "changed runtime"

    assert source == original
    assert second["identity"]["non_negotiables"] == original["identity"]["non_negotiables"]
    assert second["locales"]["zh-CN"] == original["locales"]["zh-CN"]


@pytest.mark.parametrize(
    "value",
    [
        {"number": float("nan")},
        {"number": float("inf")},
        {1: "not a JSON object key"},
        {"value": object()},
    ],
)
def test_canonical_bytes_rejects_non_json_values_deterministically(value: dict[Any, Any]) -> None:
    with pytest.raises(KokoroError) as raised:
        canonical_bytes(value)

    assert raised.value.code == "INVALID_PACK_DATA"


def test_canonical_bytes_rejects_cycles_without_recursing() -> None:
    cyclic: dict[str, Any] = {}
    cyclic["self"] = cyclic

    with pytest.raises(KokoroError) as raised:
        canonical_bytes(cyclic)

    assert raised.value.code == "INVALID_PACK_DATA"
    assert "Cyclic" in raised.value.message


@pytest.mark.parametrize(
    ("value", "expected_path"),
    [
        ({"value": "\ud800"}, ["value"]),
        ({"nested": {"value": "\udfff"}}, ["nested", "value"]),
        ({"\ud800": "value"}, []),
        ({"nested": {"\udfff": "value"}}, ["nested"]),
    ],
)
def test_canonical_bytes_rejects_unpaired_surrogates_without_leaking_unicode_errors(
    value: dict[str, Any], expected_path: list[str]
) -> None:
    with pytest.raises(KokoroError) as raised:
        canonical_bytes(value)

    assert raised.value.code == "INVALID_PACK_DATA"
    assert raised.value.message == "JSON strings must be valid UTF-8."
    assert raised.value.details == {"path": expected_path}
    assert "surrogates not allowed" not in raised.value.message
