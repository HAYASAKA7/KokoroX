from copy import deepcopy
import json
from pathlib import Path

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.schemas import SchemaRegistry
from kokoroarc import __version__


SCHEMAS = SchemaRegistry(Path("schemas/v1"))
WINDOWS_RESERVED_DEVICE_BASENAMES = (
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
)


def _metadata(artifact_id: str) -> dict:
    return {
        "schema_version": "1.0",
        "artifact_id": artifact_id,
        "created_by": {"component": "kokoroarc", "version": __version__},
    }


def _research_bundle_input() -> dict[str, str]:
    return {
        "type": "research_bundle",
        "artifact_id": "research/aoi-kisaragi-fixture/research/0123456789abcdef",
        "sha256": "a" * 64,
    }


@pytest.fixture
def valid_request() -> dict:
    return {
        **_metadata("original/rin-aster/build-request"),
        "mode": "original",
        "namespace": "original",
        "character_id": "rin-aster",
        "display_name": "Rin Aster",
        "character_version": "1.0.0",
        "requested_locales": ["zh-CN", "en-US", "ja-JP"],
        "intended_use_cases": ["technical collaboration"],
        "user_constraints": ["Do not fabricate certainty."],
        "continuity": "Original setting",
        "timeline": "Present day",
        "spoiler_scope": "No restrictions",
        "inputs": [
            {
                "type": "creative_brief",
                "content": "A restrained systems architect.",
            }
        ],
        "requested_visibility": "private",
    }


@pytest.fixture
def valid_report() -> dict:
    return {
        **_metadata("original/rin-aster/build-validation"),
        "hard_failures": [],
        "advisory_findings": [
            {
                "code": "AUTHORING_SPARSE_EXAMPLES",
                "path": ["expressions"],
                "message": "More examples would improve coverage.",
            }
        ],
        "locale_coverage": {"zh-CN": True, "en-US": True, "ja-JP": True},
        "provenance_counts": {
            "evidence": 1,
            "derived_profile": 2,
            "user_override": 0,
        },
        "valid": True,
    }


@pytest.fixture
def valid_draft(valid_report: dict) -> dict:
    return {
        **_metadata("original/rin-aster/draft/0123456789abcdef"),
        "build_status": "draft",
        "visibility": "private",
        "activation_allowed": False,
        "mode": "original",
        "namespace": "original",
        "character_id": "rin-aster",
        "display_name": "Rin Aster",
        "character_version": "1.0.0",
        "request_hash": "a" * 64,
        "source_pack_hash": "b" * 64,
        "validation_report_hash": "c" * 64,
        "bundle_references": {
            "request": "request.json",
            "source_pack": "source-pack",
            "validation_report": "validation-report.json",
        },
        "locale_coverage": deepcopy(valid_report["locale_coverage"]),
        "provenance_counts": deepcopy(valid_report["provenance_counts"]),
        "unresolved_warnings": ["More examples would improve coverage."],
    }


def _assert_invalid(schema_name: str, document: dict) -> None:
    with pytest.raises(KokoroError) as caught:
        SCHEMAS.validate(schema_name, document)
    assert caught.value.code == "SCHEMA_VALIDATION_FAILED"


def test_authoring_schemas_are_registered() -> None:
    for name in (
        "character-build-request",
        "character-draft",
        "build-validation-report",
    ):
        assert SCHEMAS.load(name)["$schema"].endswith("2020-12/schema")


def test_authoring_schemas_accept_representative_artifacts(
    valid_request: dict,
    valid_draft: dict,
    valid_report: dict,
) -> None:
    SCHEMAS.validate("character-build-request", valid_request)
    SCHEMAS.validate("character-draft", valid_draft)
    SCHEMAS.validate("build-validation-report", valid_report)


@pytest.mark.parametrize("reserved", WINDOWS_RESERVED_DEVICE_BASENAMES)
@pytest.mark.parametrize(
    "schema_name,fixture_name,field",
    [
        ("character-build-request", "valid_request", "namespace"),
        ("character-build-request", "valid_request", "character_id"),
        ("character-draft", "valid_draft", "namespace"),
        ("character-draft", "valid_draft", "character_id"),
    ],
)
def test_authoring_path_identities_reject_windows_reserved_device_names(
    schema_name: str,
    fixture_name: str,
    field: str,
    reserved: str,
    request: pytest.FixtureRequest,
) -> None:
    invalid = deepcopy(request.getfixturevalue(fixture_name))
    invalid[field] = reserved

    _assert_invalid(schema_name, invalid)


@pytest.mark.parametrize("field", ["namespace", "character_id"])
@pytest.mark.parametrize("reserved", WINDOWS_RESERVED_DEVICE_BASENAMES)
def test_source_path_identities_reject_windows_reserved_device_names(
    field: str, reserved: str
) -> None:
    source = json.loads(
        Path("tests/fixtures/schema/valid-character-source.json").read_text(
            encoding="utf-8"
        )
    )
    source[field] = reserved

    _assert_invalid("character-source", source)


def test_source_evidence_claim_ids_do_not_use_path_identity_restrictions() -> None:
    source = json.loads(
        Path("tests/fixtures/schema/valid-character-source.json").read_text(
            encoding="utf-8"
        )
    )
    source["evidence"]["claims"] = [{"claim_id": "con"}]

    SCHEMAS.validate("character-source", source)


@pytest.mark.parametrize(
    "schema_name,fixture_name",
    [
        ("character-build-request", "valid_request"),
        ("character-draft", "valid_draft"),
        ("build-validation-report", "valid_report"),
    ],
)
def test_authoring_schemas_reject_unknown_fields(
    schema_name: str,
    fixture_name: str,
    request: pytest.FixtureRequest,
) -> None:
    invalid = deepcopy(request.getfixturevalue(fixture_name))
    invalid["unknown"] = True
    _assert_invalid(schema_name, invalid)


@pytest.mark.parametrize("mode", ["original", "dossier", "researched", "hybrid"])
def test_build_request_accepts_each_construction_mode(
    mode: str, valid_request: dict
) -> None:
    request = deepcopy(valid_request)
    request["mode"] = mode
    if mode == "dossier":
        request["inputs"] = [{"type": "user_dossier", "content": "User dossier."}]
    elif mode == "researched":
        request["inputs"] = [_research_bundle_input()]
    elif mode == "hybrid":
        request["inputs"] = [
            _research_bundle_input(),
            {"type": "user_override", "content": "Prefer a quieter delivery."}
        ]
    SCHEMAS.validate("character-build-request", request)


@pytest.mark.parametrize("mode", ["researched", "hybrid"])
def test_researched_modes_require_typed_bundle_binding(
    mode: str, valid_request: dict
) -> None:
    request = deepcopy(valid_request)
    request["mode"] = mode
    request["inputs"] = [_research_bundle_input()]
    if mode == "hybrid":
        request["inputs"].append(
            {"type": "user_dossier", "content": "Private user assertion."}
        )

    SCHEMAS.validate("character-build-request", request)

    for field, value in (
        ("path", "D:/untrusted/bundle"),
        ("content", "untrusted embedded bundle"),
    ):
        invalid = deepcopy(request)
        invalid["inputs"][0][field] = value
        _assert_invalid("character-build-request", invalid)


@pytest.mark.parametrize("mode", ["researched", "hybrid"])
def test_researched_modes_require_research_bundle_input(
    mode: str, valid_request: dict
) -> None:
    invalid = deepcopy(valid_request)
    invalid["mode"] = mode
    invalid["inputs"] = [
        {"type": "user_override", "content": "No bundle binding."}
    ]

    _assert_invalid("character-build-request", invalid)


def test_hybrid_requires_separate_user_input(valid_request: dict) -> None:
    invalid = deepcopy(valid_request)
    invalid["mode"] = "hybrid"
    invalid["inputs"] = [_research_bundle_input()]

    _assert_invalid("character-build-request", invalid)

    for input_type in ("user_dossier", "user_override"):
        valid = deepcopy(invalid)
        valid["inputs"].append(
            {"type": input_type, "content": "Separate user provenance."}
        )
        SCHEMAS.validate("character-build-request", valid)


@pytest.mark.parametrize("field", ["artifact_id", "sha256"])
def test_research_bundle_binding_requires_exact_identity_fields(
    field: str, valid_request: dict
) -> None:
    invalid = deepcopy(valid_request)
    invalid["mode"] = "researched"
    binding = _research_bundle_input()
    binding.pop(field)
    invalid["inputs"] = [binding]

    _assert_invalid("character-build-request", invalid)


def test_research_bundle_hash_requires_lowercase_sha256(valid_request: dict) -> None:
    invalid = deepcopy(valid_request)
    invalid["mode"] = "researched"
    binding = _research_bundle_input()
    binding["sha256"] = "A" * 64
    invalid["inputs"] = [binding]

    _assert_invalid("character-build-request", invalid)


@pytest.mark.parametrize("field", ["continuity", "timeline", "spoiler_scope"])
@pytest.mark.parametrize("mode", ["researched", "hybrid"])
def test_researched_modes_require_explicit_scope(
    field: str, mode: str, valid_request: dict
) -> None:
    invalid = deepcopy(valid_request)
    invalid["mode"] = mode
    invalid["inputs"] = [_research_bundle_input()]
    if mode == "hybrid":
        invalid["inputs"].append(
            {"type": "user_override", "content": "Separate user provenance."}
        )
    invalid.pop(field)

    _assert_invalid("character-build-request", invalid)


def test_researched_modes_require_exactly_one_bundle_binding(
    valid_request: dict,
) -> None:
    invalid = deepcopy(valid_request)
    invalid["mode"] = "researched"
    invalid["inputs"] = [_research_bundle_input(), _research_bundle_input()]

    _assert_invalid("character-build-request", invalid)


@pytest.mark.parametrize(
    "mode,required_input",
    [("original", "creative_brief"), ("dossier", "user_dossier")],
)
def test_build_request_requires_mode_specific_input(
    mode: str,
    required_input: str,
    valid_request: dict,
) -> None:
    invalid = deepcopy(valid_request)
    invalid["mode"] = mode
    invalid["inputs"] = [
        {"type": "user_override", "content": "Override without source input."}
    ]
    _assert_invalid("character-build-request", invalid)

    invalid["inputs"] = [{"type": required_input, "content": "Required input."}]
    SCHEMAS.validate("character-build-request", invalid)


def test_build_request_rejects_malformed_or_duplicate_locales(valid_request: dict) -> None:
    for locales in (
        [],
        ["zh-CN", "en-US", "en-US"],
        ["zh-CN", "fr_FR"],
    ):
        invalid = deepcopy(valid_request)
        invalid["requested_locales"] = locales
        _assert_invalid("character-build-request", invalid)


def test_original_request_may_omit_default_visibility(valid_request: dict) -> None:
    request = deepcopy(valid_request)
    request.pop("requested_visibility")

    SCHEMAS.validate("character-build-request", request)


@pytest.mark.parametrize("mode", ["dossier", "researched", "hybrid"])
def test_non_original_requests_must_be_private(
    mode: str, valid_request: dict
) -> None:
    invalid = deepcopy(valid_request)
    invalid["mode"] = mode
    invalid["requested_visibility"] = "public"
    if mode == "dossier":
        invalid["inputs"] = [{"type": "user_dossier", "content": "Private data."}]
    _assert_invalid("character-build-request", invalid)


@pytest.mark.parametrize(
    "field,value",
    [
        ("build_status", "validated"),
        ("visibility", "public"),
        ("activation_allowed", True),
    ],
)
def test_draft_lifecycle_is_fixed(
    field: str, value: object, valid_draft: dict
) -> None:
    invalid = deepcopy(valid_draft)
    invalid[field] = value
    _assert_invalid("character-draft", invalid)


@pytest.mark.parametrize(
    "field",
    ["request_hash", "source_pack_hash", "validation_report_hash"],
)
def test_draft_hashes_must_be_sha256(field: str, valid_draft: dict) -> None:
    invalid = deepcopy(valid_draft)
    invalid[field] = "not-a-sha256"
    _assert_invalid("character-draft", invalid)


def test_draft_accepts_maximum_generated_artifact_id(valid_draft: dict) -> None:
    namespace = "a" * 64
    character_id = "b" * 64
    valid_draft["namespace"] = namespace
    valid_draft["character_id"] = character_id
    valid_draft["artifact_id"] = (
        f"{namespace}/{character_id}/draft/0123456789abcdef"
    )

    assert len(valid_draft["artifact_id"]) == 152
    SCHEMAS.validate("character-draft", valid_draft)

    invalid = deepcopy(valid_draft)
    invalid["artifact_id"] += "a"
    _assert_invalid("character-draft", invalid)


@pytest.mark.parametrize(
    "path",
    ["../request.json", "/request.json", "nested/../../request.json", "C:\\request.json"],
)
def test_draft_references_must_be_safe_bundle_relative_paths(
    path: str, valid_draft: dict
) -> None:
    invalid = deepcopy(valid_draft)
    invalid["bundle_references"]["request"] = path
    _assert_invalid("character-draft", invalid)


@pytest.mark.parametrize(
    "valid,hard_failures",
    [
        (
            True,
            [
                {
                    "code": "AUTHORING_IDENTITY_MISMATCH",
                    "path": ["character_id"],
                    "message": "Character identity does not match.",
                }
            ],
        ),
        (False, []),
    ],
)
def test_report_valid_flag_must_agree_with_hard_findings(
    valid: bool,
    hard_failures: list[dict],
    valid_report: dict,
) -> None:
    invalid = deepcopy(valid_report)
    invalid["valid"] = valid
    invalid["hard_failures"] = hard_failures
    _assert_invalid("build-validation-report", invalid)


@pytest.mark.parametrize("locale", ["zh-CN", "en-US", "ja-JP"])
def test_valid_report_requires_complete_locale_coverage(
    locale: str, valid_report: dict
) -> None:
    invalid = deepcopy(valid_report)
    invalid["locale_coverage"][locale] = False

    _assert_invalid("build-validation-report", invalid)


def test_invalid_report_may_have_complete_locale_coverage(
    valid_report: dict,
) -> None:
    report = deepcopy(valid_report)
    report["valid"] = False
    report["hard_failures"] = [
        {
            "code": "AUTHORING_IDENTITY_MISMATCH",
            "path": ["character_id"],
            "message": "Character identity does not match.",
        }
    ]

    SCHEMAS.validate("build-validation-report", report)
