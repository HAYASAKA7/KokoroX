from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.schemas import SchemaRegistry


SCHEMAS = SchemaRegistry(Path("schemas/v1"))
FIXTURE_ROOT = Path("tests/fixtures/standalone-contracts")
SCHEMA_BY_FIXTURE_KEY = {
    "karc_manifest": "karc-manifest",
    "compatibility_report": "pack-compatibility-report",
    "migration_plan": "pack-migration-plan",
    "installed_registry": "installed-pack-registry",
    "default_config": "character-default-config",
    "persistence_consent": "persistence-consent",
    "memory_reference": "memory-reference",
}
STANDALONE_SCHEMA_NAMES = tuple(SCHEMA_BY_FIXTURE_KEY.values())


def _bundle(name: str) -> dict[str, dict[str, Any]]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _assert_invalid(schema_name: str, document: dict[str, Any]) -> None:
    with pytest.raises(KokoroError) as caught:
        SCHEMAS.validate(schema_name, document)
    assert caught.value.code == "SCHEMA_VALIDATION_FAILED"


def _check_result(passed: bool) -> dict[str, Any]:
    return {
        "passed": passed,
        "findings": [] if passed else [
            {
                "code": "PACK_COMPATIBILITY_FAILED",
                "message": "Compatibility check failed.",
                "path": ["archive"],
            }
        ],
    }


def test_standalone_schemas_are_registered_as_draft_2020_12() -> None:
    for name in STANDALONE_SCHEMA_NAMES:
        schema = SCHEMAS.load(name)
        assert schema["$schema"].endswith("2020-12/schema")
        assert schema["$id"].endswith(f"/{name}.schema.json")


def test_standalone_schemas_share_core_identity_definitions() -> None:
    definition_names = (
        "artifact_id",
        "created_by",
        "slug_id",
        "semantic_version",
        "sha256",
    )
    definitions = [SCHEMAS.load(name)["$defs"] for name in STANDALONE_SCHEMA_NAMES]

    for definition_name in definition_names:
        expected = definitions[0][definition_name]
        assert all(
            schema_definitions[definition_name] == expected
            for schema_definitions in definitions[1:]
        )


@pytest.mark.parametrize(
    "fixture_name", ["private-global.json", "public-workspace.json"]
)
def test_standalone_contract_fixtures_are_valid(fixture_name: str) -> None:
    artifacts = _bundle(fixture_name)
    assert set(artifacts) == set(SCHEMA_BY_FIXTURE_KEY)

    for fixture_key, schema_name in SCHEMA_BY_FIXTURE_KEY.items():
        SCHEMAS.validate(schema_name, artifacts[fixture_key])


@pytest.mark.parametrize(
    "fixture_name", ["private-global.json", "public-workspace.json"]
)
@pytest.mark.parametrize("fixture_key,schema_name", SCHEMA_BY_FIXTURE_KEY.items())
def test_standalone_schemas_reject_unknown_root_fields(
    fixture_name: str, fixture_key: str, schema_name: str
) -> None:
    invalid = deepcopy(_bundle(fixture_name)[fixture_key])
    invalid["unknown"] = True

    _assert_invalid(schema_name, invalid)


@pytest.mark.parametrize("fixture_key,schema_name", SCHEMA_BY_FIXTURE_KEY.items())
@pytest.mark.parametrize(
    "field", ["schema_version", "artifact_id", "created_by"]
)
def test_every_standalone_artifact_requires_metadata(
    fixture_key: str, schema_name: str, field: str
) -> None:
    invalid = deepcopy(_bundle("private-global.json")[fixture_key])
    del invalid[field]

    _assert_invalid(schema_name, invalid)


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../pack/compiled.json",
        "/pack/compiled.json",
        "pack\\compiled.json",
        "pack//compiled.json",
        "pack/../compiled.json",
        "pack/compiled.json:payload",
        "CON",
    ],
)
def test_manifest_rejects_unsafe_or_unlisted_member_paths(
    unsafe_path: str,
) -> None:
    invalid = deepcopy(_bundle("private-global.json")["karc_manifest"])
    invalid["members"][0]["path"] = unsafe_path

    _assert_invalid("karc-manifest", invalid)


def test_manifest_rejects_duplicate_members() -> None:
    invalid = deepcopy(_bundle("private-global.json")["karc_manifest"])
    invalid["members"].append(deepcopy(invalid["members"][0]))

    _assert_invalid("karc-manifest", invalid)


def test_manifest_rejects_out_of_order_members() -> None:
    invalid = deepcopy(_bundle("private-global.json")["karc_manifest"])
    invalid["members"][0], invalid["members"][1] = (
        invalid["members"][1],
        invalid["members"][0],
    )

    _assert_invalid("karc-manifest", invalid)


def test_private_manifest_rejects_publication_member_or_reference() -> None:
    fixture = _bundle("private-global.json")["karc_manifest"]
    public_fixture = _bundle("public-workspace.json")["karc_manifest"]
    with_member = deepcopy(fixture)
    with_member["members"].insert(3, deepcopy(public_fixture["members"][3]))
    with_reference = deepcopy(fixture)
    with_reference["publication_readiness_report"] = deepcopy(
        public_fixture["publication_readiness_report"]
    )

    _assert_invalid("karc-manifest", with_member)
    _assert_invalid("karc-manifest", with_reference)


def test_public_manifest_requires_publication_member_and_reference() -> None:
    fixture = _bundle("public-workspace.json")["karc_manifest"]
    without_member = deepcopy(fixture)
    del without_member["members"][3]
    without_reference = deepcopy(fixture)
    without_reference["publication_readiness_report"] = None

    _assert_invalid("karc-manifest", without_member)
    _assert_invalid("karc-manifest", without_reference)


@pytest.mark.parametrize(
    "minimum,maximum",
    [
        ("1", "2.0.0"),
        ("v1.0.0", "2.0.0"),
        ("1.0.0", "*"),
        ("1.0.0", "2.0"),
        ("01.0.0", "2.0.0"),
    ],
)
def test_manifest_rejects_invalid_runtime_version_ranges(
    minimum: str, maximum: str
) -> None:
    invalid = deepcopy(_bundle("private-global.json")["karc_manifest"])
    runtime = invalid["compatibility"]["runtime"]
    runtime["minimum_inclusive"] = minimum
    runtime["maximum_exclusive"] = maximum

    _assert_invalid("karc-manifest", invalid)


def test_manifest_rejects_incomplete_schema_version_range() -> None:
    invalid = deepcopy(_bundle("private-global.json")["karc_manifest"])
    del invalid["compatibility"]["schemas"]["compiled_pack"][
        "maximum_exclusive"
    ]

    _assert_invalid("karc-manifest", invalid)


def test_compatible_report_requires_all_checks_and_installation_to_pass() -> None:
    fixture = _bundle("private-global.json")["compatibility_report"]
    failed_check = deepcopy(fixture)
    failed_check["checks"]["member_integrity"] = _check_result(False)
    denied_install = deepcopy(fixture)
    denied_install["installation_allowed"] = False
    missing_identity = deepcopy(fixture)
    missing_identity["compiled_hash"] = None

    _assert_invalid("pack-compatibility-report", failed_check)
    _assert_invalid("pack-compatibility-report", denied_install)
    _assert_invalid("pack-compatibility-report", missing_identity)


def test_incompatible_report_requires_a_failed_check() -> None:
    invalid = deepcopy(_bundle("private-global.json")["compatibility_report"])
    invalid["compatible"] = False
    invalid["installation_allowed"] = False

    _assert_invalid("pack-compatibility-report", invalid)


@pytest.mark.parametrize("field", ["script", "command", "executable"])
def test_migration_plan_rejects_executable_root_fields(field: str) -> None:
    invalid = deepcopy(_bundle("private-global.json")["migration_plan"])
    invalid[field] = "python payload.py"

    _assert_invalid("pack-migration-plan", invalid)


def test_migration_plan_rejects_executable_change_fields() -> None:
    invalid = deepcopy(_bundle("private-global.json")["migration_plan"])
    invalid["changes"][0]["command"] = "run-migration"

    _assert_invalid("pack-migration-plan", invalid)


def test_migration_plan_never_accepts_archive_code() -> None:
    invalid = deepcopy(_bundle("private-global.json")["migration_plan"])
    invalid["archive_code_accepted"] = True

    _assert_invalid("pack-migration-plan", invalid)


def test_migration_plan_accepts_only_escaped_json_pointer_tildes() -> None:
    escaped = deepcopy(_bundle("private-global.json")["migration_plan"])
    escaped["changes"][0]["path"] = "/manifest/a~0b/~1"
    unescaped = deepcopy(escaped)
    unescaped["changes"][0]["path"] = "/manifest/a~2b"

    SCHEMAS.validate("pack-migration-plan", escaped)
    _assert_invalid("pack-migration-plan", unescaped)


def test_state_migration_flag_requires_a_bound_plan() -> None:
    private_plan = deepcopy(_bundle("private-global.json")["migration_plan"])
    private_plan["state_migration_required"] = True
    public_plan = deepcopy(_bundle("public-workspace.json")["migration_plan"])
    public_plan["state_migration_required"] = False

    _assert_invalid("pack-migration-plan", private_plan)
    _assert_invalid("pack-migration-plan", public_plan)


def test_registry_entries_are_keyed_by_logical_identity() -> None:
    entries = _bundle("private-global.json")["installed_registry"]["entries"]

    assert isinstance(entries, dict)
    assert list(entries) == ["original/rin-aster/1.0.0"]


def test_registry_rejects_duplicate_identity_array_representation() -> None:
    invalid = deepcopy(_bundle("private-global.json")["installed_registry"])
    key, entry = next(iter(invalid["entries"].items()))
    duplicate = deepcopy(entry)
    duplicate["archive_sha256"] = "a" * 64
    invalid["entries"] = [
        {"identity": key, **entry},
        {"identity": key, **duplicate},
    ]

    _assert_invalid("installed-pack-registry", invalid)


def test_registry_rejects_backslash_installed_paths() -> None:
    invalid = deepcopy(_bundle("private-global.json")["installed_registry"])
    entry = next(iter(invalid["entries"].values()))
    entry["relative_path"] = "global\\rin-aster\\1.0.0"

    _assert_invalid("installed-pack-registry", invalid)


@pytest.mark.parametrize(
    "identity",
    [
        "original/rin-aster",
        "original/rin-aster/1",
        "original/rin-aster/v1.0.0",
        "original/../rin-aster/1.0.0",
        "Original/rin-aster/1.0.0",
    ],
)
def test_registry_rejects_invalid_identity_keys(identity: str) -> None:
    invalid = deepcopy(_bundle("private-global.json")["installed_registry"])
    entry = next(iter(invalid["entries"].values()))
    invalid["entries"] = {identity: entry}

    _assert_invalid("installed-pack-registry", invalid)


@pytest.mark.parametrize(
    "fixture_name,fixture_key,schema_name",
    [
        ("private-global.json", "installed_registry", "installed-pack-registry"),
        ("private-global.json", "default_config", "character-default-config"),
        ("private-global.json", "persistence_consent", "persistence-consent"),
        ("private-global.json", "memory_reference", "memory-reference"),
    ],
)
def test_global_artifacts_reject_workspace_bindings(
    fixture_name: str, fixture_key: str, schema_name: str
) -> None:
    invalid = deepcopy(_bundle(fixture_name)[fixture_key])
    invalid["workspace_id"] = "a" * 64

    _assert_invalid(schema_name, invalid)


@pytest.mark.parametrize(
    "fixture_key,schema_name",
    [
        ("installed_registry", "installed-pack-registry"),
        ("default_config", "character-default-config"),
        ("persistence_consent", "persistence-consent"),
        ("memory_reference", "memory-reference"),
    ],
)
def test_workspace_artifacts_require_workspace_bindings(
    fixture_key: str, schema_name: str
) -> None:
    invalid = deepcopy(_bundle("public-workspace.json")[fixture_key])
    invalid["workspace_id"] = None

    _assert_invalid(schema_name, invalid)


@pytest.mark.parametrize(
    "field", ["installation_id", "archive_sha256", "compiled_sha256"]
)
def test_default_config_rejects_unbound_installations(field: str) -> None:
    invalid = deepcopy(_bundle("private-global.json")["default_config"])
    del invalid["binding"][field]

    _assert_invalid("character-default-config", invalid)


def test_default_config_permits_an_explicitly_empty_binding() -> None:
    valid = deepcopy(_bundle("private-global.json")["default_config"])
    valid["binding"] = None

    SCHEMAS.validate("character-default-config", valid)


@pytest.mark.parametrize(
    "permissions",
    [
        [],
        ["*"],
        ["all"],
        ["conversation_history"],
        ["relationship_state", "relationship_state"],
        [
            "relationship_state",
            "mood_state",
            "memory_references",
            "conversation_history",
        ],
    ],
)
def test_consent_rejects_empty_overbroad_or_duplicate_permissions(
    permissions: list[str],
) -> None:
    invalid = deepcopy(_bundle("private-global.json")["persistence_consent"])
    invalid["permissions"] = permissions

    _assert_invalid("persistence-consent", invalid)


def test_consent_revocation_state_is_closed() -> None:
    active_with_revocation = deepcopy(
        _bundle("private-global.json")["persistence_consent"]
    )
    active_with_revocation["revoked_revision"] = 2
    revoked_without_revision = deepcopy(active_with_revocation)
    revoked_without_revision["status"] = "revoked"
    revoked_without_revision["revoked_revision"] = None
    valid_revoked = deepcopy(active_with_revocation)
    valid_revoked["status"] = "revoked"

    _assert_invalid("persistence-consent", active_with_revocation)
    _assert_invalid("persistence-consent", revoked_without_revision)
    SCHEMAS.validate("persistence-consent", valid_revoked)


@pytest.mark.parametrize(
    "field,value",
    [
        ("content", "full conversation transcript"),
        ("messages", ["hello"]),
        ("conversation", {"turns": []}),
        ("tool_permissions", ["shell"]),
    ],
)
def test_memory_reference_rejects_embedded_memory_content(
    field: str, value: Any
) -> None:
    invalid = deepcopy(_bundle("private-global.json")["memory_reference"])
    invalid[field] = value

    _assert_invalid("memory-reference", invalid)


def test_memory_reference_requires_host_approval_and_no_fact_authority() -> None:
    unapproved = deepcopy(_bundle("private-global.json")["memory_reference"])
    unapproved["source_kind"] = "conversation_harvest"
    embedded = deepcopy(_bundle("private-global.json")["memory_reference"])
    embedded["embedded_content"] = True
    authoritative = deepcopy(_bundle("private-global.json")["memory_reference"])
    authoritative["canonical_fact_authority"] = True

    _assert_invalid("memory-reference", unapproved)
    _assert_invalid("memory-reference", embedded)
    _assert_invalid("memory-reference", authoritative)


def test_memory_reference_rejects_whitespace_only_summaries() -> None:
    invalid = deepcopy(_bundle("private-global.json")["memory_reference"])
    invalid["localized_summaries"]["en-US"] = " \t\r\n "

    _assert_invalid("memory-reference", invalid)
