from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest

from kokoroarc.authoring.requests import normalize_build_request
from kokoroarc.authoring.validation import validate_authoring_pack
from kokoroarc.errors import KokoroError
from kokoroarc.schemas import SchemaRegistry


@pytest.fixture
def registry() -> SchemaRegistry:
    return SchemaRegistry(Path("schemas/v1"))


@pytest.fixture
def original_request() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": "original/rin-aster/build-request",
        "created_by": {"component": "kokoroarc", "version": "0.0.0.dev0"},
        "mode": "original",
        "namespace": "original",
        "character_id": "rin-aster",
        "display_name": "Rin Aster",
        "character_version": "1.0.0",
        "requested_locales": ["zh-CN", "en-US", "ja-JP"],
        "intended_use_cases": ["technical collaboration"],
        "user_constraints": ["Do not fabricate certainty."],
        "inputs": [
            {
                "type": "creative_brief",
                "content": "A restrained systems architect.",
            }
        ],
    }


@pytest.fixture
def source() -> dict[str, Any]:
    return json.loads(
        Path("tests/fixtures/schema/valid-character-source.json").read_text(
            encoding="utf-8"
        )
    )


def _request_for_mode(
    original_request: dict[str, Any], mode: str
) -> dict[str, Any]:
    request = deepcopy(original_request)
    request["mode"] = mode
    if mode == "dossier":
        request["inputs"] = [
            {"type": "user_dossier", "content": "A private user dossier."}
        ]
    elif mode == "researched":
        request["inputs"] = [
            {"type": "research_bundle", "content": "A research bundle."}
        ]
    elif mode == "hybrid":
        request["inputs"].append(
            {"type": "user_override", "content": "Prefer quieter delivery."}
        )
    return request


def test_normalize_original_request_is_deterministic_and_non_mutating(
    registry: SchemaRegistry, original_request: dict[str, Any]
) -> None:
    before = deepcopy(original_request)

    first = normalize_build_request(original_request, registry)
    second = normalize_build_request(original_request, registry)

    assert first == second
    assert original_request == before
    assert first is not original_request
    assert first["inputs"] is not original_request["inputs"]


def test_normalize_request_materializes_default_private_visibility(
    registry: SchemaRegistry, original_request: dict[str, Any]
) -> None:
    normalized = normalize_build_request(original_request, registry)

    assert normalized["requested_visibility"] == "private"
    assert "requested_visibility" not in original_request


def test_normalize_accepts_explicit_private_original_request(
    registry: SchemaRegistry, original_request: dict[str, Any]
) -> None:
    original_request["requested_visibility"] = "private"

    assert normalize_build_request(original_request, registry) == original_request


def test_normalize_accepts_dossier_request(
    registry: SchemaRegistry, original_request: dict[str, Any]
) -> None:
    request = _request_for_mode(original_request, "dossier")

    normalized = normalize_build_request(request, registry)

    assert normalized["mode"] == "dossier"
    assert normalized["requested_visibility"] == "private"


@pytest.mark.parametrize("mode", ["researched", "hybrid"])
def test_normalize_rejects_modes_not_supported_in_this_milestone(
    mode: str,
    registry: SchemaRegistry,
    original_request: dict[str, Any],
) -> None:
    request = _request_for_mode(original_request, mode)

    with pytest.raises(KokoroError) as caught:
        normalize_build_request(request, registry)

    assert caught.value.code == "AUTHORING_MODE_UNSUPPORTED"


@pytest.mark.parametrize("mode", ["dossier", "researched", "hybrid"])
def test_normalize_non_original_request_cannot_be_public(
    mode: str,
    registry: SchemaRegistry,
    original_request: dict[str, Any],
) -> None:
    request = _request_for_mode(original_request, mode)
    request["requested_visibility"] = "public"

    with pytest.raises(KokoroError) as caught:
        normalize_build_request(request, registry)

    assert caught.value.code == "SCHEMA_VALIDATION_FAILED"


@pytest.mark.parametrize(
    "field,value",
    [
        ("namespace", "Original"),
        ("character_id", "rin/aster"),
        ("character_version", "version-one"),
    ],
)
def test_normalize_rejects_invalid_identity(
    field: str,
    value: str,
    registry: SchemaRegistry,
    original_request: dict[str, Any],
) -> None:
    original_request[field] = value

    with pytest.raises(KokoroError) as caught:
        normalize_build_request(original_request, registry)

    assert caught.value.code == "SCHEMA_VALIDATION_FAILED"


@pytest.mark.parametrize(
    "locales",
    [
        ["zh-CN", "en-US"],
        ["zh-CN", "en-US", "fr-FR"],
        ["zh-CN", "en-US", "en-US"],
    ],
)
def test_normalize_requires_exact_first_class_locales(
    locales: list[str],
    registry: SchemaRegistry,
    original_request: dict[str, Any],
) -> None:
    original_request["requested_locales"] = locales

    with pytest.raises(KokoroError) as caught:
        normalize_build_request(original_request, registry)

    assert caught.value.code == "SCHEMA_VALIDATION_FAILED"


def test_normalize_rejects_invalid_visibility(
    registry: SchemaRegistry, original_request: dict[str, Any]
) -> None:
    original_request["requested_visibility"] = "internal"

    with pytest.raises(KokoroError) as caught:
        normalize_build_request(original_request, registry)

    assert caught.value.code == "SCHEMA_VALIDATION_FAILED"


@pytest.mark.parametrize("value", [True, [], "request"])
def test_normalize_rejects_json_values_that_are_not_objects(
    value: object, registry: SchemaRegistry
) -> None:
    with pytest.raises(KokoroError) as caught:
        normalize_build_request(value, registry)  # type: ignore[arg-type]

    assert caught.value.code == "SCHEMA_VALIDATION_FAILED"


def test_normalize_rejects_non_json_values_safely(registry: SchemaRegistry) -> None:
    with pytest.raises(KokoroError) as caught:
        normalize_build_request({"invalid": object()}, registry)

    assert caught.value.code == "INVALID_PACK_DATA"


def test_validate_authoring_pack_reports_character_identity_mismatch(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    source["character_id"] = "another-character"

    report = validate_authoring_pack(original_request, source, registry)

    assert report["valid"] is False
    assert report["hard_failures"] == [
        {
            "code": "AUTHORING_IDENTITY_MISMATCH",
            "path": ["character_id"],
            "message": "Source character ID does not match the build request.",
        }
    ]


def test_validate_authoring_pack_reports_character_version_mismatch(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    source["character_version"] = "2.0.0"

    report = validate_authoring_pack(original_request, source, registry)

    assert [item["code"] for item in report["hard_failures"]] == [
        "AUTHORING_VERSION_MISMATCH"
    ]
    assert report["hard_failures"][0]["path"] == ["character_version"]


def test_validate_original_requires_authored_original_evidence(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    source["evidence"]["authored_original"] = False

    report = validate_authoring_pack(original_request, source, registry)

    assert [item["code"] for item in report["hard_failures"]] == [
        "AUTHORING_ORIGINAL_EVIDENCE_REQUIRED"
    ]
    assert report["hard_failures"][0]["path"] == [
        "evidence",
        "authored_original",
    ]


def test_validate_original_prohibits_externally_sourced_claims(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    source["evidence"]["claims"] = [
        {
            "statement": "A claim presented as external canon.",
            "source": "external-canon",
        }
    ]

    report = validate_authoring_pack(original_request, source, registry)

    assert [item["code"] for item in report["hard_failures"]] == [
        "AUTHORING_EXTERNAL_CANON_PROHIBITED"
    ]
    assert report["hard_failures"][0]["path"] == [
        "evidence",
        "claims",
        0,
        "source",
    ]


def test_validate_original_allows_creative_brief_claim_source(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    source["evidence"]["claims"] = [
        {
            "statement": "A restrained systems architect.",
            "source": "creative_brief",
        }
    ]

    report = validate_authoring_pack(original_request, source, registry)

    assert report["valid"] is True
    assert report["hard_failures"] == []


def test_validate_dossier_requires_typed_user_dossier_evidence(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    request = _request_for_mode(original_request, "dossier")
    source["evidence"] = {"authored_original": False, "claims": []}

    report = validate_authoring_pack(request, source, registry)

    assert [item["code"] for item in report["hard_failures"]] == [
        "AUTHORING_DOSSIER_EVIDENCE_REQUIRED"
    ]
    assert report["hard_failures"][0]["path"] == ["evidence", "claims"]


def test_validate_dossier_rejects_claim_relabelled_as_external_canon(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    request = _request_for_mode(original_request, "dossier")
    source["evidence"] = {
        "authored_original": False,
        "claims": [
            {"statement": "Quoted assertion", "source": "user_dossier"},
            {"statement": "Relabelled assertion", "source": "external-canon"},
        ],
    }

    report = validate_authoring_pack(request, source, registry)

    assert [item["code"] for item in report["hard_failures"]] == [
        "AUTHORING_DOSSIER_CANON_PROHIBITED"
    ]
    assert report["hard_failures"][0]["path"] == [
        "evidence",
        "claims",
        1,
        "source",
    ]


def test_validate_dossier_rejects_authored_original_flag(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    request = _request_for_mode(original_request, "dossier")
    source["evidence"] = {
        "authored_original": True,
        "claims": [
            {"statement": "Quoted assertion", "source": "user_dossier"}
        ],
    }

    report = validate_authoring_pack(request, source, registry)

    assert [item["code"] for item in report["hard_failures"]] == [
        "AUTHORING_DOSSIER_ORIGINAL_PROVENANCE_PROHIBITED"
    ]
    assert report["hard_failures"][0]["path"] == [
        "evidence",
        "authored_original",
    ]


def test_validate_dossier_rejects_claim_copied_into_immutable_identity(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    request = _request_for_mode(original_request, "dossier")
    source["evidence"] = {
        "authored_original": False,
        "claims": [
            {"statement": "systems architect", "source": "user_dossier"}
        ],
    }

    report = validate_authoring_pack(request, source, registry)

    assert [item["code"] for item in report["hard_failures"]] == [
        "AUTHORING_IDENTITY_PROVENANCE_COLLAPSE"
    ]
    assert report["hard_failures"][0]["path"] == ["identity", "role"]


def test_validate_dossier_allows_explicit_identity_override(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    request = _request_for_mode(original_request, "dossier")
    request["inputs"].append(
        {"type": "user_override", "content": "systems architect"}
    )
    source["evidence"] = {
        "authored_original": False,
        "claims": [
            {"statement": "systems architect", "source": "user_dossier"}
        ],
    }

    report = validate_authoring_pack(request, source, registry)

    assert report["valid"] is True
    assert report["hard_failures"] == []


@pytest.mark.parametrize(
    "source_path,replacement,code",
    [
        (
            ("namespace",),
            "another-namespace",
            "AUTHORING_NAMESPACE_MISMATCH",
        ),
        (
            ("identity", "display_name"),
            "Another Name",
            "AUTHORING_DISPLAY_NAME_MISMATCH",
        ),
    ],
)
def test_validate_authoring_pack_reports_complete_target_identity_mismatch(
    source_path: tuple[str, ...],
    replacement: str,
    code: str,
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    target: dict[str, Any] = source
    for component in source_path[:-1]:
        target = target[component]
    target[source_path[-1]] = replacement

    report = validate_authoring_pack(original_request, source, registry)

    assert [item["code"] for item in report["hard_failures"]] == [code]
    assert report["hard_failures"][0]["path"] == list(source_path)


@pytest.mark.parametrize("locale", ["zh-CN", "en-US", "ja-JP"])
def test_validate_authoring_pack_reports_missing_locale_coverage(
    locale: str,
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    source["locales"].pop(locale)

    report = validate_authoring_pack(original_request, source, registry)

    assert report["locale_coverage"][locale] is False
    assert [item["code"] for item in report["hard_failures"]] == [
        "AUTHORING_LOCALE_MISSING"
    ]
    assert report["hard_failures"][0]["path"] == ["locales", locale]


@pytest.mark.parametrize("locale", ["zh-CN", "en-US", "ja-JP"])
def test_validate_authoring_pack_requires_locale_in_every_expression(
    locale: str,
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    source["expressions"]["restrained_diagnosis"].pop(locale)

    report = validate_authoring_pack(original_request, source, registry)

    assert report["locale_coverage"][locale] is False
    assert [item["code"] for item in report["hard_failures"]] == [
        "AUTHORING_LOCALE_MISSING"
    ]
    assert report["hard_failures"][0]["path"] == ["expressions", locale]


def test_validate_authoring_pack_returns_valid_warning_only_report(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    report = validate_authoring_pack(original_request, source, registry)

    assert report["valid"] is True
    assert report["hard_failures"] == []
    assert [item["code"] for item in report["advisory_findings"]] == [
        "AUTHORING_SPARSE_EXAMPLES"
    ]
    assert report["locale_coverage"] == {
        "zh-CN": True,
        "en-US": True,
        "ja-JP": True,
    }
    assert report["provenance_counts"] == {
        "evidence": 0,
        "derived_profile": 1,
        "user_override": 0,
    }
    registry.validate("build-validation-report", report)


def test_validate_authoring_pack_caps_findings_to_report_schema_limit(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    source["evidence"] = {
        "authored_original": False,
        "claims": [
            {
                "claim_id": f"claim-{index}",
                "statement": f"External claim {index}",
                "source": "external-canon",
            }
            for index in range(256)
        ],
    }

    report = validate_authoring_pack(original_request, source, registry)

    assert report["valid"] is False
    assert len(report["hard_failures"]) == 256
    registry.validate("build-validation-report", report)


def test_validate_authoring_pack_findings_are_complete_and_sorted(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    source["character_id"] = "another-character"
    source["evidence"] = {
        "authored_original": False,
        "claims": [{"statement": "Claim", "source": "external-canon"}],
    }
    source["locales"].pop("ja-JP")

    first = validate_authoring_pack(original_request, source, registry)
    second = validate_authoring_pack(original_request, source, registry)

    assert first == second
    assert all(
        set(item) == {"code", "path", "message"}
        for item in first["hard_failures"]
    )
    assert first["hard_failures"] == sorted(
        first["hard_failures"],
        key=lambda item: (
            item["code"],
            json.dumps(item["path"], separators=(",", ":")),
            item["message"],
        ),
    )


def test_validate_authoring_pack_does_not_mutate_inputs(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    request_before = deepcopy(original_request)
    source_before = deepcopy(source)

    validate_authoring_pack(original_request, source, registry)

    assert original_request == request_before
    assert source == source_before
