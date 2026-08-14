from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.schemas import SchemaRegistry


SCHEMAS = SchemaRegistry(Path("schemas/v1"))
FIXTURE_ROOT = Path("tests/fixtures/pack-release")
SCHEMA_BY_FIXTURE_KEY = {
    "hard_report": "pack-hard-validation-report",
    "soft_input": "pack-soft-evaluation-input",
    "soft_report": "pack-soft-evaluation-report",
    "review_attestation": "pack-review-attestation",
    "promotion_record": "pack-promotion-record",
    "publication_report": "pack-publication-readiness-report",
}
RELEASE_SCHEMA_NAMES = tuple(SCHEMA_BY_FIXTURE_KEY.values())


def _bundle(name: str) -> dict[str, dict[str, Any]]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _nested(document: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = document
    for segment in path:
        value = value[segment]
    return value


def _set_nested(
    document: dict[str, Any], path: tuple[str, ...], value: Any
) -> None:
    target = _nested(document, path[:-1])
    target[path[-1]] = value


def _delete_nested(document: dict[str, Any], path: tuple[str, ...]) -> None:
    target = _nested(document, path[:-1])
    del target[path[-1]]


def _assert_invalid(schema_name: str, document: dict[str, Any]) -> None:
    with pytest.raises(KokoroError) as caught:
        SCHEMAS.validate(schema_name, document)
    assert caught.value.code == "SCHEMA_VALIDATION_FAILED"


def test_pack_release_schemas_are_registered_as_draft_2020_12() -> None:
    for name in RELEASE_SCHEMA_NAMES:
        schema = SCHEMAS.load(name)
        assert schema["$schema"].endswith("2020-12/schema")
        assert schema["$id"].endswith(f"/{name}.schema.json")


def test_pack_release_schemas_share_identity_version_and_hash_definitions() -> None:
    definition_names = (
        "artifact_id",
        "created_by",
        "slug_id",
        "semantic_version",
        "sha256",
    )
    definitions = [SCHEMAS.load(name)["$defs"] for name in RELEASE_SCHEMA_NAMES]

    for definition_name in definition_names:
        expected = definitions[0][definition_name]
        assert all(
            schema_definitions[definition_name] == expected
            for schema_definitions in definitions[1:]
        )


@pytest.mark.parametrize("fixture_name", ["original-minimal.json", "research-full.json"])
def test_pack_release_fixtures_are_valid(fixture_name: str) -> None:
    artifacts = _bundle(fixture_name)
    assert set(artifacts) == set(SCHEMA_BY_FIXTURE_KEY)

    for fixture_key, schema_name in SCHEMA_BY_FIXTURE_KEY.items():
        SCHEMAS.validate(schema_name, artifacts[fixture_key])


@pytest.mark.parametrize("fixture_name", ["original-minimal.json", "research-full.json"])
@pytest.mark.parametrize("fixture_key,schema_name", SCHEMA_BY_FIXTURE_KEY.items())
def test_pack_release_schemas_reject_unknown_root_fields(
    fixture_name: str, fixture_key: str, schema_name: str
) -> None:
    invalid = deepcopy(_bundle(fixture_name)[fixture_key])
    invalid["unknown"] = True

    _assert_invalid(schema_name, invalid)


@pytest.mark.parametrize(
    "fixture_key,schema_name,field",
    [
        ("hard_report", "pack-hard-validation-report", "checks"),
        ("soft_input", "pack-soft-evaluation-input", "samples"),
        ("soft_report", "pack-soft-evaluation-report", "threshold_profile"),
        ("review_attestation", "pack-review-attestation", "decision"),
        ("promotion_record", "pack-promotion-record", "from_status"),
        (
            "publication_report",
            "pack-publication-readiness-report",
            "ready_for_private_export",
        ),
    ],
)
def test_pack_release_schemas_reject_missing_required_fields(
    fixture_key: str, schema_name: str, field: str
) -> None:
    invalid = deepcopy(_bundle("original-minimal.json")[fixture_key])
    del invalid[field]

    _assert_invalid(schema_name, invalid)


@pytest.mark.parametrize("fixture_key,schema_name", SCHEMA_BY_FIXTURE_KEY.items())
@pytest.mark.parametrize(
    "field", ["namespace", "character_id", "character_version", "source_hash"]
)
def test_every_release_artifact_requires_exact_subject_identity_fields(
    fixture_key: str, schema_name: str, field: str
) -> None:
    invalid = deepcopy(_bundle("research-full.json")[fixture_key])
    del invalid[field]

    _assert_invalid(schema_name, invalid)


@pytest.mark.parametrize(
    "fixture_key,schema_name,path",
    [
        ("hard_report", "pack-hard-validation-report", ("source_hash",)),
        ("soft_input", "pack-soft-evaluation-input", ("compiled_hash",)),
        (
            "soft_report",
            "pack-soft-evaluation-report",
            ("evaluation_input", "sha256"),
        ),
        (
            "review_attestation",
            "pack-review-attestation",
            ("hard_report", "sha256"),
        ),
        ("promotion_record", "pack-promotion-record", ("compiled_hash",)),
        (
            "publication_report",
            "pack-publication-readiness-report",
            ("promotion", "sha256"),
        ),
    ],
)
def test_release_bindings_require_lowercase_sha256(
    fixture_key: str, schema_name: str, path: tuple[str, ...]
) -> None:
    invalid = deepcopy(_bundle("research-full.json")[fixture_key])
    _set_nested(invalid, path, "A" * 64)

    _assert_invalid(schema_name, invalid)


@pytest.mark.parametrize(
    "path",
    [
        ("evaluator", "version"),
        ("rubric_version",),
        ("fixture_version",),
    ],
)
@pytest.mark.parametrize(
    "fixture_key,schema_name",
    [
        ("soft_input", "pack-soft-evaluation-input"),
        ("soft_report", "pack-soft-evaluation-report"),
    ],
)
def test_soft_evaluation_contracts_require_all_version_bindings(
    fixture_key: str, schema_name: str, path: tuple[str, ...]
) -> None:
    invalid = deepcopy(_bundle("original-minimal.json")[fixture_key])
    _delete_nested(invalid, path)

    _assert_invalid(schema_name, invalid)


@pytest.mark.parametrize("field", ["score", "confidence"])
@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_soft_samples_reject_scores_outside_closed_unit_interval(
    field: str, value: float
) -> None:
    invalid = deepcopy(_bundle("original-minimal.json")["soft_input"])
    invalid["samples"]["semantic_equivalence"]["semantic-zh-01"][field] = value

    _assert_invalid("pack-soft-evaluation-input", invalid)


@pytest.mark.parametrize("field", ["score", "confidence", "lower_bound"])
@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_soft_results_reject_values_outside_closed_unit_interval(
    field: str, value: float
) -> None:
    invalid = deepcopy(_bundle("original-minimal.json")["soft_report"])
    invalid["results"]["semantic_equivalence"][field] = value

    _assert_invalid("pack-soft-evaluation-report", invalid)


def test_soft_input_requires_each_declared_dimension() -> None:
    invalid = deepcopy(_bundle("original-minimal.json")["soft_input"])
    invalid["samples"].pop("safety_policy_retention")

    _assert_invalid("pack-soft-evaluation-input", invalid)


def test_soft_report_requires_each_declared_dimension() -> None:
    invalid = deepcopy(_bundle("original-minimal.json")["soft_report"])
    invalid["results"].pop("safety_policy_retention")

    _assert_invalid("pack-soft-evaluation-report", invalid)


def test_soft_input_rejects_unknown_dimensions() -> None:
    invalid = deepcopy(_bundle("original-minimal.json")["soft_input"])
    invalid["samples"]["vibes"] = invalid["samples"].pop(
        "semantic_equivalence"
    )

    _assert_invalid("pack-soft-evaluation-input", invalid)


def test_soft_input_rejects_duplicate_finding_codes() -> None:
    invalid = deepcopy(_bundle("research-full.json")["soft_input"])
    invalid["samples"]["semantic_equivalence"]["semantic-zh-01"][
        "finding_codes"
    ] = [
        "EVALUATOR_ADVISORY",
        "EVALUATOR_ADVISORY",
    ]

    _assert_invalid("pack-soft-evaluation-input", invalid)


def test_hard_report_rejects_duplicate_findings() -> None:
    invalid = deepcopy(_bundle("research-full.json")["hard_report"])
    finding = invalid["checks"]["provenance"]["findings"][0]
    invalid["checks"]["provenance"]["findings"].append(deepcopy(finding))

    _assert_invalid("pack-hard-validation-report", invalid)


def test_passing_hard_report_requires_every_hard_gate_to_pass() -> None:
    invalid = deepcopy(_bundle("original-minimal.json")["hard_report"])
    invalid["checks"]["security"]["passed"] = False
    invalid["checks"]["security"]["findings"] = [
        {
            "severity": "error",
            "code": "PACK_SECURITY_FAILED",
            "path": ["source"],
            "message": "The source did not pass the security gate.",
        }
    ]

    _assert_invalid("pack-hard-validation-report", invalid)


def test_passing_soft_report_requires_every_dimension_to_pass() -> None:
    invalid = deepcopy(_bundle("original-minimal.json")["soft_report"])
    invalid["results"]["locale_naturalness"]["passed"] = False

    _assert_invalid("pack-soft-evaluation-report", invalid)


@pytest.mark.parametrize(
    "from_status,to_status",
    [
        ("draft", "verified"),
        ("reviewed", "draft"),
        ("verified", "reviewed"),
    ],
)
def test_promotion_rejects_skipped_or_reversed_transitions(
    from_status: str, to_status: str
) -> None:
    invalid = deepcopy(_bundle("research-full.json")["promotion_record"])
    invalid["from_status"] = from_status
    invalid["to_status"] = to_status

    _assert_invalid("pack-promotion-record", invalid)


def test_reviewed_promotion_rejects_activation_or_verified_inputs() -> None:
    invalid = deepcopy(_bundle("original-minimal.json")["promotion_record"])
    invalid["activation_allowed"] = True
    invalid["soft_evaluation_report"] = {
        "artifact_id": "original/rin-aster/release/soft-report",
        "sha256": "f" * 64,
    }

    _assert_invalid("pack-promotion-record", invalid)


def test_verified_promotion_requires_previous_and_soft_report_bindings() -> None:
    invalid = deepcopy(_bundle("research-full.json")["promotion_record"])
    invalid["previous_promotion"] = None
    invalid["soft_evaluation_report"] = None

    _assert_invalid("pack-promotion-record", invalid)


@pytest.mark.parametrize("mode", ["dossier", "researched", "hybrid"])
def test_non_original_promotions_cannot_be_public_by_default(mode: str) -> None:
    invalid = deepcopy(_bundle("research-full.json")["promotion_record"])
    invalid["mode"] = mode
    invalid["visibility"] = "public_candidate"

    _assert_invalid("pack-promotion-record", invalid)


def test_accepted_review_requires_every_review_dimension() -> None:
    invalid = deepcopy(_bundle("original-minimal.json")["review_attestation"])
    invalid["reviewed"]["privacy"] = False

    _assert_invalid("pack-review-attestation", invalid)


def test_accepted_review_cannot_retain_required_corrections() -> None:
    invalid = deepcopy(_bundle("research-full.json")["review_attestation"])
    invalid["corrections"]["tone-note"]["disposition"] = "required"

    _assert_invalid("pack-review-attestation", invalid)


def test_publication_ready_requires_approved_compliance_attestation() -> None:
    invalid = deepcopy(_bundle("research-full.json")["publication_report"])
    invalid["ready_for_publication"] = True
    invalid["blockers"] = []
    invalid["compliance_attestation"]["conclusion"] = "blocked"
    invalid["checks"]["compliance"]["passed"] = True
    invalid["checks"]["compliance"]["findings"] = []

    _assert_invalid("pack-publication-readiness-report", invalid)


def test_blocked_public_candidate_requires_a_blocker() -> None:
    invalid = deepcopy(_bundle("research-full.json")["publication_report"])
    invalid["blockers"] = []

    _assert_invalid("pack-publication-readiness-report", invalid)


def test_private_readiness_cannot_claim_publication_readiness() -> None:
    invalid = deepcopy(_bundle("original-minimal.json")["publication_report"])
    invalid["ready_for_publication"] = True

    _assert_invalid("pack-publication-readiness-report", invalid)


@pytest.mark.parametrize("fixture_key,schema_name", SCHEMA_BY_FIXTURE_KEY.items())
def test_release_artifact_ids_are_bounded_and_path_safe(
    fixture_key: str, schema_name: str
) -> None:
    invalid = deepcopy(_bundle("original-minimal.json")[fixture_key])
    invalid["artifact_id"] = "release/" + "a" * 193

    _assert_invalid(schema_name, invalid)


def test_nested_contracts_are_closed() -> None:
    cases = [
        (
            "hard_report",
            "pack-hard-validation-report",
            ("checks", "security"),
        ),
        (
            "soft_input",
            "pack-soft-evaluation-input",
            ("samples", "semantic_equivalence", "semantic-zh-01"),
        ),
        (
            "soft_report",
            "pack-soft-evaluation-report",
            ("threshold_profile",),
        ),
        (
            "review_attestation",
            "pack-review-attestation",
            ("reviewer",),
        ),
        (
            "promotion_record",
            "pack-promotion-record",
            ("hard_report",),
        ),
        (
            "publication_report",
            "pack-publication-readiness-report",
            ("promotion",),
        ),
    ]

    for fixture_key, schema_name, path in cases:
        invalid = deepcopy(_bundle("original-minimal.json")[fixture_key])
        _nested(invalid, path)["unknown"] = True
        _assert_invalid(schema_name, invalid)
