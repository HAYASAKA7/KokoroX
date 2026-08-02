import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from kokoroarc.errors import KokoroError
from kokoroarc.schemas import SchemaRegistry


def load_fixture(name: str) -> dict:
    path = Path("tests/fixtures/schema") / name
    return json.loads(path.read_text(encoding="utf-8"))


def valid_compiled_pack() -> dict:
    return {
        "schema_version": "1.0",
        "artifact_id": "original/rin-aster/compiled",
        "created_by": {"component": "kokoroarc", "version": "0.0.0.dev0"},
        "character_id": "rin-aster",
        "character_version": "1.0.0",
        "source_hash": "a" * 64,
        "identity": {
            "display_name": "Rin Aster",
            "declared_age": "adult",
            "role": "systems architect",
            "non_negotiables": ["never fabricates certainty"],
        },
        "effective_profile": {"composure": 0.9},
        "provenance": {
            "composure": {"selected_layer": "derived_profile"},
        },
        "behavior": {"default_intensity": "balanced"},
        "growth": {
            "dimensions": ["familiarity", "trust", "collaboration", "tension"]
        },
        "expressions": {
            "restrained_diagnosis": {
                "zh-CN": ["原因已经明确。"],
                "en-US": ["The cause is clear."],
                "ja-JP": ["原因は明確です。"],
            }
        },
        "locales": {"zh-CN": {}, "en-US": {}, "ja-JP": {}},
        "scenarios": {"debugging": {"intensity_cap": "balanced"}},
    }


def test_character_source_schema_accepts_original_pack() -> None:
    SchemaRegistry(Path("schemas/v1")).validate(
        "character-source", load_fixture("valid-character-source.json")
    )


def test_character_source_schema_rejects_executable_hook() -> None:
    with pytest.raises(KokoroError) as raised:
        SchemaRegistry(Path("schemas/v1")).validate(
            "character-source", load_fixture("invalid-character-source.json")
        )

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"


def test_compiled_pack_schema_accepts_compiler_output() -> None:
    SchemaRegistry(Path("schemas/v1")).validate(
        "compiled-pack", valid_compiled_pack()
    )


def test_compiled_pack_schema_rejects_invalid_source_hash() -> None:
    document = valid_compiled_pack()
    document["source_hash"] = "A" * 64

    with pytest.raises(KokoroError) as raised:
        SchemaRegistry(Path("schemas/v1")).validate("compiled-pack", document)

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"


def test_registry_rejects_missing_artifact_metadata(tmp_path: Path) -> None:
    registry = SchemaRegistry(tmp_path)
    (tmp_path / "sample.schema.json").write_text(
        '{"$schema":"https://json-schema.org/draft/2020-12/schema",'
        '"type":"object","required":["schema_version"],'
        '"properties":{"schema_version":{"const":"1.0"}}}',
        encoding="utf-8",
    )
    with pytest.raises(KokoroError) as raised:
        registry.validate("sample", {})
    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"
    assert raised.value.details["path"] == []


def test_registry_rejects_malformed_schema_json(tmp_path: Path) -> None:
    registry = SchemaRegistry(tmp_path)
    (tmp_path / "broken.schema.json").write_text("{", encoding="utf-8")

    with pytest.raises(KokoroError) as raised:
        registry.load("broken")

    assert raised.value.code == "SCHEMA_INVALID"


def test_registry_rejects_invalid_utf8_schema(tmp_path: Path) -> None:
    (tmp_path / "bad-utf8.schema.json").write_bytes(b"\xff")

    with pytest.raises(KokoroError) as raised:
        SchemaRegistry(tmp_path).load("bad-utf8")

    assert raised.value.code == "SCHEMA_INVALID"
    assert raised.value.details["schema"] == "bad-utf8"
    assert all(
        isinstance(raised.value.details[field], str)
        for field in ("schema", "path", "reason")
    )


def test_registry_rejects_non_object_schema(tmp_path: Path) -> None:
    registry = SchemaRegistry(tmp_path)
    (tmp_path / "array.schema.json").write_text("[]", encoding="utf-8")

    with pytest.raises(KokoroError) as raised:
        registry.load("array")

    assert raised.value.code == "SCHEMA_INVALID"


def test_registry_rejects_invalid_draft_2020_12_schema(tmp_path: Path) -> None:
    registry = SchemaRegistry(tmp_path)
    (tmp_path / "invalid.schema.json").write_text(
        '{"$schema":"https://json-schema.org/draft/2020-12/schema","type":7}',
        encoding="utf-8",
    )

    with pytest.raises(KokoroError) as raised:
        registry.load("invalid")

    assert raised.value.code == "SCHEMA_INVALID"


def test_registry_rejects_non_2020_12_schema_declaration(tmp_path: Path) -> None:
    registry = SchemaRegistry(tmp_path)
    (tmp_path / "draft7.schema.json").write_text(
        '{"$schema":"http://json-schema.org/draft-07/schema#"}',
        encoding="utf-8",
    )

    with pytest.raises(KokoroError) as raised:
        registry.load("draft7")

    assert raised.value.code == "SCHEMA_INVALID"


def test_registry_rejects_traversal_schema_name(tmp_path: Path) -> None:
    registry = SchemaRegistry(tmp_path / "schemas")
    (tmp_path / "outside.schema.json").write_text(
        '{"$schema":"https://json-schema.org/draft/2020-12/schema"}',
        encoding="utf-8",
    )

    with pytest.raises(KokoroError) as raised:
        registry.load("../outside")

    assert raised.value.code == "SCHEMA_NAME_INVALID"


def test_common_schema_validates_metadata_and_locales() -> None:
    schema_root = Path(__file__).resolve().parents[2] / "schemas" / "v1"
    common = SchemaRegistry(schema_root).load("common")
    metadata = Draft202012Validator(common["$defs"]["metadata"])
    locale = Draft202012Validator(common["$defs"]["locale"])
    valid_metadata = {
        "schema_version": "1.0",
        "artifact_id": "persona/hero.v1",
        "created_by": {"component": "kokoroarc", "version": "1.0.0"},
    }

    assert metadata.is_valid(valid_metadata)
    assert all(locale.is_valid(value) for value in ("zh-CN", "en-US", "ja-JP", "preserve"))
    assert not metadata.is_valid({**valid_metadata, "extra": True})
    assert not metadata.is_valid({**valid_metadata, "artifact_id": "Invalid"})
    assert not locale.is_valid("zh_CN")
