from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml
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
    valid = load_fixture("valid-character-source.json")
    invalid = load_fixture("invalid-character-source.json")
    without_hook = deepcopy(invalid)
    without_hook.pop("post_load_hook")

    assert without_hook == valid

    with pytest.raises(KokoroError) as raised:
        SchemaRegistry(Path("schemas/v1")).validate(
            "character-source", invalid
        )

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"
    assert raised.value.details["path"] == []


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


@pytest.mark.parametrize(
    "non_finite",
    [
        json.loads('{"value": NaN}')["value"],
        yaml.safe_load("value: .inf")["value"],
        yaml.safe_load("value: -.inf")["value"],
    ],
    ids=["nan", "positive-infinity", "negative-infinity"],
)
def test_character_source_schema_rejects_non_finite_trait(
    non_finite: float,
) -> None:
    document = load_fixture("valid-character-source.json")
    document["derived_profile"]["traits"]["composure"] = non_finite

    with pytest.raises(KokoroError) as raised:
        SchemaRegistry(Path("schemas/v1")).validate("character-source", document)

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"
    assert raised.value.details["path"] == [
        "derived_profile",
        "traits",
        "composure",
    ]


def test_character_source_schema_rejects_yaml_nan_growth_threshold() -> None:
    document = load_fixture("valid-character-source.json")
    document["growth"]["stages"] = {
        "unknown": {"enter_familiarity": yaml.safe_load("value: .nan")["value"]}
    }

    with pytest.raises(KokoroError) as raised:
        SchemaRegistry(Path("schemas/v1")).validate("character-source", document)

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"
    assert raised.value.details["path"] == [
        "growth",
        "stages",
        "unknown",
        "enter_familiarity",
    ]


def test_character_source_schema_accepts_finite_trait_boundary() -> None:
    document = load_fixture("valid-character-source.json")
    document["derived_profile"]["traits"]["composure"] = 1.0

    SchemaRegistry(Path("schemas/v1")).validate("character-source", document)


def test_character_source_schema_rejects_non_string_mapping_key() -> None:
    document = load_fixture("valid-character-source.json")
    document["overrides"]["values"] = yaml.safe_load("1: 0.5")

    with pytest.raises(KokoroError) as raised:
        SchemaRegistry(Path("schemas/v1")).validate("character-source", document)

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"
    assert raised.value.details["path"] == ["overrides", "values"]


def test_character_source_schema_rejects_recursive_list_alias() -> None:
    document = load_fixture("valid-character-source.json")
    document["identity"]["worldview"] = yaml.safe_load("&loop [*loop]")

    with pytest.raises(KokoroError) as raised:
        SchemaRegistry(Path("schemas/v1")).validate("character-source", document)

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"
    assert raised.value.details["path"] == ["identity", "worldview", 0]


def test_character_source_schema_rejects_recursive_mapping_alias() -> None:
    document = load_fixture("valid-character-source.json")
    document["overrides"]["values"] = yaml.safe_load("&loop {self: *loop}")

    with pytest.raises(KokoroError) as raised:
        SchemaRegistry(Path("schemas/v1")).validate("character-source", document)

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"
    assert raised.value.details["path"] == ["overrides", "values", "self"]


def test_character_source_schema_rejects_non_json_scalar() -> None:
    document = load_fixture("valid-character-source.json")
    document["identity"]["declared_age"] = yaml.safe_load("value: 2026-08-02")[
        "value"
    ]

    with pytest.raises(KokoroError) as raised:
        SchemaRegistry(Path("schemas/v1")).validate("character-source", document)

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"
    assert raised.value.details["path"] == ["identity", "declared_age"]


def test_character_source_schema_rejects_excessive_nesting() -> None:
    document = load_fixture("valid-character-source.json")
    nested: object = "too deep"
    for _ in range(64):
        nested = [nested]
    document["identity"]["worldview"] = nested

    with pytest.raises(KokoroError) as raised:
        SchemaRegistry(Path("schemas/v1")).validate("character-source", document)

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"
    assert raised.value.details["path"] == [
        "identity",
        "worldview",
        *([0] * 62),
    ]


def test_character_source_schema_allows_shared_acyclic_alias() -> None:
    document = load_fixture("valid-character-source.json")
    aliases = yaml.safe_load(
        "worldview: &values [evidence_before_confidence]\n"
        "non_negotiables: *values"
    )
    assert aliases["worldview"] is aliases["non_negotiables"]
    document["identity"]["worldview"] = aliases["worldview"]
    document["identity"]["non_negotiables"] = aliases["non_negotiables"]

    SchemaRegistry(Path("schemas/v1")).validate("character-source", document)


def test_character_source_schema_rejects_noncanonical_growth_stage() -> None:
    document = load_fixture("valid-character-source.json")
    document["growth"]["stages"] = {
        "best_friend": {"enter_familiarity": 80}
    }

    with pytest.raises(KokoroError) as raised:
        SchemaRegistry(Path("schemas/v1")).validate("character-source", document)

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"
    assert raised.value.details["path"] == ["growth", "stages"]


def test_compiled_pack_schema_rejects_noncanonical_growth_stage() -> None:
    document = valid_compiled_pack()
    document["growth"]["stages"] = {
        "best_friend": {"enter_familiarity": 80}
    }

    with pytest.raises(KokoroError) as raised:
        SchemaRegistry(Path("schemas/v1")).validate("compiled-pack", document)

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"
    assert raised.value.details["path"] == ["growth", "stages"]


def test_character_source_schema_rejects_overlong_expression_intent_id() -> None:
    document = load_fixture("valid-character-source.json")
    overlong_id = "a_" + "b" * 127
    expression = document["expressions"].pop("restrained_diagnosis")
    document["expressions"][overlong_id] = expression

    with pytest.raises(KokoroError) as raised:
        SchemaRegistry(Path("schemas/v1")).validate("character-source", document)

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"


@pytest.mark.parametrize("dynamic_map", ["traits", "scenarios"])
def test_character_source_schema_rejects_other_overlong_dynamic_ids(
    dynamic_map: str,
) -> None:
    document = load_fixture("valid-character-source.json")
    overlong_id = "a_" + "b" * 127
    if dynamic_map == "traits":
        document["derived_profile"]["traits"] = {overlong_id: 0.5}
    else:
        document["scenarios"] = {overlong_id: {"intensity_cap": "balanced"}}

    with pytest.raises(KokoroError) as raised:
        SchemaRegistry(Path("schemas/v1")).validate("character-source", document)

    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda document: document.update({"evidence": {}}),
        lambda document: document.update({"derived_profile": {}}),
        lambda document: document.update({"post_load_hook": "run this hook"}),
        lambda document: document["identity"].update({"unknown_field": True}),
        lambda document: document["effective_profile"].update({"composure": 1.1}),
        lambda document: document["effective_profile"].update({"Bad-Key": 0.5}),
        lambda document: document["provenance"]["composure"].update(
            {"selected_layer": "raw_source"}
        ),
        lambda document: document["provenance"]["composure"].update(
            {"extra": True}
        ),
        lambda document: document["growth"]["dimensions"].append("familiarity"),
    ],
    ids=[
        "raw-evidence",
        "raw-derived-profile",
        "unknown-root",
        "unknown-nested",
        "trait-above-one",
        "invalid-trait-id",
        "invalid-selected-layer",
        "extra-provenance-field",
        "duplicate-dimension",
    ],
)
def test_compiled_pack_schema_rejects_forbidden_or_invalid_data(mutation) -> None:
    document = deepcopy(valid_compiled_pack())
    mutation(document)

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
