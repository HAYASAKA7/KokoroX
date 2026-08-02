from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from kokoroarc.errors import KokoroError
from kokoroarc.schemas import SchemaRegistry


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
