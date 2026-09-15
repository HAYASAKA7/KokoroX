from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest

from kokorox.authoring.requests import normalize_build_request
from kokorox.authoring.validation import validate_authoring_pack
from kokorox.errors import KokoroError
from kokorox.research.bundles import canonical_hash
from kokorox.research.validation import timeline_label
from kokorox.schemas import SchemaRegistry
from kokorox import __version__


@pytest.fixture
def registry() -> SchemaRegistry:
    return SchemaRegistry(Path("schemas/v1"))


@pytest.fixture
def original_request() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_id": "original/rin-aster/build-request",
        "created_by": {"component": "kokorox", "version": __version__},
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


@pytest.fixture
def complete_research_bundle() -> dict[str, Any]:
    return json.loads(
        Path("tests/fixtures/research/complete/bundle.json").read_text(
            encoding="utf-8"
        )
    )


def _research_authoring_case(
    original_request: dict[str, Any],
    source: dict[str, Any],
    bundle: dict[str, Any],
    mode: str = "researched",
) -> tuple[dict[str, Any], dict[str, Any]]:
    request = deepcopy(original_request)
    request.update(
        {
            "artifact_id": "research/aoi-kisaragi-fixture/build-request",
            "mode": mode,
            "namespace": bundle["namespace"],
            "character_id": bundle["character_id"],
            "display_name": bundle["display_name"],
            "continuity": bundle["continuity"],
            # Prose on the request side; the bundle cutoff in rendered form.
            "timeline": timeline_label(bundle["timeline_cutoff"]),
            "spoiler_scope": bundle["spoiler_scope"],
            "inputs": [
                {
                    "type": "research_bundle",
                    "artifact_id": bundle["artifact_id"],
                    "sha256": bundle["bundle_hash"],
                }
            ],
        }
    )
    researched_source = deepcopy(source)
    researched_source.update(
        {
            "artifact_id": "research/aoi-kisaragi-fixture/source",
            "namespace": bundle["namespace"],
            "character_id": bundle["character_id"],
        }
    )
    researched_source["identity"]["display_name"] = bundle["display_name"]
    researched_source["evidence"] = {
        "authored_original": False,
        "claims": [
            {"claim_id": "claim-role", "source": "research_bundle"}
        ],
    }
    if mode == "hybrid":
        request["inputs"].append(
            {"type": "user_override", "content": "Prefer quieter delivery."}
        )
        researched_source["evidence"]["claims"].append(
            {
                "statement": "Prefer quieter delivery.",
                "source": "user_override",
                "quote": "Prefer quieter delivery.",
            }
        )
    return request, researched_source


def _request_for_mode(
    original_request: dict[str, Any], mode: str
) -> dict[str, Any]:
    request = deepcopy(original_request)
    request["mode"] = mode
    if mode in {"researched", "hybrid"}:
        request.update(
            {
                "continuity": "fixture-primary",
                "timeline": "episode-01",
                "spoiler_scope": "episode-01 only",
            }
        )
    if mode == "dossier":
        request["inputs"] = [
            {"type": "user_dossier", "content": "A private user dossier."}
        ]
    elif mode == "researched":
        request["inputs"] = [
            {
                "type": "research_bundle",
                "artifact_id": (
                    "research/aoi-kisaragi-fixture/research/0123456789abcdef"
                ),
                "sha256": "a" * 64,
            }
        ]
    elif mode == "hybrid":
        request["inputs"] = [
            {
                "type": "research_bundle",
                "artifact_id": (
                    "research/aoi-kisaragi-fixture/research/0123456789abcdef"
                ),
                "sha256": "a" * 64,
            },
            {"type": "user_override", "content": "Prefer quieter delivery."}
        ]
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
def test_normalize_accepts_research_backed_modes(
    mode: str,
    registry: SchemaRegistry,
    original_request: dict[str, Any],
) -> None:
    request = _request_for_mode(original_request, mode)

    normalized = normalize_build_request(request, registry)

    assert normalized["mode"] == mode
    assert normalized["requested_visibility"] == "private"


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
        [],
        ["zh-CN", "en-US", "en-US"],
        ["zh-CN", "fr_FR"],
    ],
)
def test_normalize_rejects_malformed_or_duplicate_locales(
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


@pytest.mark.parametrize(
    "mode,source_label,expected_code",
    [
        ("original", "External Canon", "AUTHORING_EXTERNAL_CANON_PROHIBITED"),
        ("dossier", "canonical_fact", "AUTHORING_DOSSIER_CANON_PROHIBITED"),
    ],
)
def test_validate_normalizes_structural_canon_source_labels(
    mode: str,
    source_label: str,
    expected_code: str,
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    request = _request_for_mode(original_request, mode)
    claims = []
    if mode == "dossier":
        source["evidence"]["authored_original"] = False
        claims.append(
            {"statement": "Quoted assertion", "source": "user_dossier", "quote": "private user dossier"}
        )
    claims.append({"statement": "Relabelled assertion", "source": source_label})
    source["evidence"]["claims"] = claims

    report = validate_authoring_pack(request, source, registry)

    assert [item["code"] for item in report["hard_failures"]] == [
        expected_code
    ]


@pytest.mark.parametrize(
    "mode,source_label",
    [
        ("original", "Creative Brief"),
        ("original", "user-override"),
        ("dossier", "User Dossier"),
        ("dossier", "creative-brief"),
        ("dossier", "USER_OVERRIDE"),
    ],
)
def test_validate_allows_normalized_mode_specific_provenance_labels(
    mode: str,
    source_label: str,
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    request = _request_for_mode(original_request, mode)
    claims = []
    if mode == "dossier" and source_label != "User Dossier":
        claims.append(
            {"statement": "Quoted assertion", "source": "user_dossier", "quote": "private user dossier"}
        )
    claim = {"statement": "Typed assertion", "source": source_label}
    label = "_".join(source_label.casefold().replace("-", " ").split())
    if label == "user_override":
        request["inputs"].append({"type": "user_override", "content": "Typed assertion"})
        claim["quote"] = "Typed assertion"
    elif label == "user_dossier":
        claim["quote"] = "private user dossier"
    claims.append(claim)
    source["evidence"] = {
        "authored_original": mode == "original",
        "claims": claims,
    }

    report = validate_authoring_pack(request, source, registry)

    assert report["valid"] is True
    assert report["hard_failures"] == []


@pytest.mark.parametrize("mode", ["original", "dossier"])
@pytest.mark.parametrize(
    "claim",
    [
        {"statement": "Unknown assertion", "source": "canon"},
        {"statement": "Unknown assertion", "source": "official canon"},
        {"statement": "Unknown assertion", "source": "canonical source"},
        {
            "statement": "Unknown assertion",
            "source": "external canonical fact",
        },
        "Untyped assertion",
    ],
)
def test_validate_fails_closed_for_unknown_or_untyped_claim_provenance(
    mode: str,
    claim: object,
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    request = _request_for_mode(original_request, mode)
    claims = []
    if mode == "dossier":
        claims.append(
            {"statement": "Quoted assertion", "source": "user_dossier", "quote": "private user dossier"}
        )
    claims.append(claim)
    source["evidence"] = {
        "authored_original": mode == "original",
        "claims": claims,
    }

    report = validate_authoring_pack(request, source, registry)

    expected_code = (
        "AUTHORING_EXTERNAL_CANON_PROHIBITED"
        if mode == "original"
        else "AUTHORING_DOSSIER_CANON_PROHIBITED"
    )
    assert [item["code"] for item in report["hard_failures"]] == [
        expected_code
    ]


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
            {"statement": "Quoted assertion", "source": "user_dossier", "quote": "private user dossier"},
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
            {"statement": "Quoted assertion", "source": "user_dossier", "quote": "private user dossier"}
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
            {"statement": "systems architect", "source": "user_dossier", "quote": "private user dossier"}
        ],
    }

    report = validate_authoring_pack(request, source, registry)

    assert [item["code"] for item in report["hard_failures"]] == [
        "AUTHORING_IDENTITY_PROVENANCE_COLLAPSE"
    ]
    assert report["hard_failures"][0]["path"] == ["identity", "role"]


@pytest.mark.parametrize(
    "identity_value,claim_statement",
    [
        ("systems architect", "Systems Architect"),
        ("systems architect", "systems  architect"),
        ("systems architect", "systems architect."),
        ("Caf\u00e9 architect", "Cafe\u0301 architect"),
    ],
)
def test_validate_dossier_normalizes_identity_collapse_equality(
    identity_value: str,
    claim_statement: str,
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    request = _request_for_mode(original_request, "dossier")
    source["identity"]["role"] = identity_value
    source["evidence"] = {
        "authored_original": False,
        "claims": [
            {"statement": claim_statement, "source": "user_dossier", "quote": "private user dossier"}
        ],
    }

    report = validate_authoring_pack(request, source, registry)

    assert [item["code"] for item in report["hard_failures"]] == [
        "AUTHORING_IDENTITY_PROVENANCE_COLLAPSE"
    ]
    assert report["hard_failures"][0]["path"] == ["identity", "role"]


def test_validate_dossier_normalizes_explicit_identity_override(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    request = _request_for_mode(original_request, "dossier")
    request["inputs"].append(
        {"type": "user_override", "content": "  SYSTEMS  ARCHITECT!  "}
    )
    source["evidence"] = {
        "authored_original": False,
        "claims": [
            {"statement": "Systems Architect.", "source": "user_dossier", "quote": "private user dossier"}
        ],
    }

    report = validate_authoring_pack(request, source, registry)

    assert report["valid"] is True
    assert report["hard_failures"] == []


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
            {"statement": "systems architect", "source": "user_dossier", "quote": "private user dossier"}
        ],
    }

    report = validate_authoring_pack(request, source, registry)

    assert report["valid"] is True
    assert report["hard_failures"] == []


def test_validate_dossier_identity_collapse_ignores_non_dossier_claims(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    request = _request_for_mode(original_request, "dossier")
    request["inputs"].append(
        {"type": "creative_brief", "content": "systems architect"}
    )
    source["evidence"] = {
        "authored_original": False,
        "claims": [
            {"statement": "Quoted assertion", "source": "user_dossier", "quote": "private user dossier"},
            {"statement": "systems architect", "source": "creative_brief"},
        ],
    }
    registry.validate("character-build-request", request)
    registry.validate("character-source", source)

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
    """A locale the pack declares must actually be authored."""
    for locale_set in source["expressions"].values():
        locale_set.pop(locale, None)

    report = validate_authoring_pack(original_request, source, registry)

    assert report["locale_coverage"][locale] is False
    assert [item["code"] for item in report["hard_failures"]] == [
        "AUTHORING_LOCALE_MISSING"
    ]
    assert report["hard_failures"][0]["path"] == ["expressions", locale]


def test_validate_authoring_pack_allows_a_locale_subset(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    """Packs declare the locales they author; three are not required."""
    source["locales"].pop("ja-JP")
    for locale_set in source["expressions"].values():
        locale_set.pop("ja-JP", None)

    report = validate_authoring_pack(original_request, source, registry)

    assert set(report["locale_coverage"]) == {"zh-CN", "en-US"}
    assert all(report["locale_coverage"].values())
    assert [
        item for item in report["hard_failures"]
        if item["code"] == "AUTHORING_LOCALE_MISSING"
    ] == []


def test_validate_authoring_pack_names_a_requested_locale_the_pack_omits(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    """The request asked for three locales; a pack authoring two says which."""
    source["locales"].pop("ja-JP")
    for locale_set in source["expressions"].values():
        locale_set.pop("ja-JP", None)

    report = validate_authoring_pack(original_request, source, registry)

    assert report["valid"] is True
    assert report["hard_failures"] == []
    assert [
        item["path"]
        for item in report["advisory_findings"]
        if item["code"] == "AUTHORING_REQUESTED_LOCALE_UNAUTHORED"
    ] == [["locales", "ja-JP"]]


def test_validate_authoring_pack_is_silent_when_every_locale_is_authored(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    report = validate_authoring_pack(original_request, source, registry)

    assert [
        item
        for item in report["advisory_findings"]
        if item["code"] == "AUTHORING_REQUESTED_LOCALE_UNAUTHORED"
    ] == []


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
        "evidence_by_source": {
            "creative_brief": 0,
            "research_bundle": 0,
            "user_dossier": 0,
            "user_override": 0,
            "unrecognized": 0,
        },
        "derived_profile": 1,
        "user_override": 0,
    }
    assert report["artifact_id"] == "original/rin-aster/build-validation"
    registry.validate("build-validation-report", report)


def test_validate_authoring_pack_bounds_overlong_report_artifact_id(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    original_request["artifact_id"] = "build-request"
    original_request["namespace"] = "a" * 64
    original_request["character_id"] = "b" * 64
    source["artifact_id"] = "source"
    source["namespace"] = original_request["namespace"]
    source["character_id"] = original_request["character_id"]
    registry.validate("character-build-request", original_request)
    registry.validate("character-source", source)

    first = validate_authoring_pack(original_request, source, registry)
    second = validate_authoring_pack(original_request, source, registry)

    assert first == second
    assert first["artifact_id"].startswith("build-validation/")
    assert len(first["artifact_id"]) <= 128
    registry.validate("build-validation-report", first)


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


@pytest.mark.parametrize("mode", ["researched", "hybrid"])
def test_validate_authoring_pack_accepts_exact_eligible_research_bundle(
    mode: str,
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
    complete_research_bundle: dict[str, Any],
) -> None:
    request, researched_source = _research_authoring_case(
        original_request,
        source,
        complete_research_bundle,
        mode,
    )
    registry.validate("character-build-request", request)
    registry.validate("character-source", researched_source)

    report = validate_authoring_pack(
        request,
        researched_source,
        registry,
        research_bundle=complete_research_bundle,
    )

    assert report["valid"] is True
    assert report["hard_failures"] == []
    registry.validate("build-validation-report", report)


@pytest.mark.parametrize(
    "field,value,expected_code",
    [
        (
            "artifact_id",
            "research/aoi-kisaragi-fixture/research/other",
            "RESEARCH_BUNDLE_IDENTITY_MISMATCH",
        ),
        ("sha256", "0" * 64, "RESEARCH_BUNDLE_HASH_MISMATCH"),
    ],
)
def test_validate_authoring_pack_rejects_inexact_bundle_binding(
    field: str,
    value: str,
    expected_code: str,
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
    complete_research_bundle: dict[str, Any],
) -> None:
    request, researched_source = _research_authoring_case(
        original_request, source, complete_research_bundle
    )
    request["inputs"][0][field] = value

    report = validate_authoring_pack(
        request,
        researched_source,
        registry,
        research_bundle=complete_research_bundle,
    )

    assert report["valid"] is False
    assert expected_code in {
        finding["code"] for finding in report["hard_failures"]
    }


@pytest.mark.parametrize(
    "request_field,bundle_field,expected_code",
    [
        ("namespace", "namespace", "RESEARCH_BUNDLE_IDENTITY_MISMATCH"),
        ("character_id", "character_id", "RESEARCH_BUNDLE_IDENTITY_MISMATCH"),
        ("display_name", "display_name", "RESEARCH_BUNDLE_IDENTITY_MISMATCH"),
        ("continuity", "continuity", "RESEARCH_BUNDLE_CONTINUITY_MISMATCH"),
        ("timeline", "timeline_cutoff", "RESEARCH_BUNDLE_TIMELINE_MISMATCH"),
        ("spoiler_scope", "spoiler_scope", "RESEARCH_BUNDLE_SPOILER_MISMATCH"),
    ],
)
def test_validate_authoring_pack_rejects_bundle_scope_mismatch(
    request_field: str,
    bundle_field: str,
    expected_code: str,
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
    complete_research_bundle: dict[str, Any],
) -> None:
    request, researched_source = _research_authoring_case(
        original_request, source, complete_research_bundle
    )
    request[request_field] = f"different-{complete_research_bundle[bundle_field]}"

    report = validate_authoring_pack(
        request,
        researched_source,
        registry,
        research_bundle=complete_research_bundle,
    )

    assert expected_code in {
        finding["code"] for finding in report["hard_failures"]
    }


def test_validate_authoring_pack_rejects_partial_research_bundle(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    partial = json.loads(
        Path("tests/fixtures/research/partial/bundle.json").read_text(
            encoding="utf-8"
        )
    )
    request, researched_source = _research_authoring_case(
        original_request, source, partial
    )

    report = validate_authoring_pack(
        request,
        researched_source,
        registry,
        research_bundle=partial,
    )

    assert "RESEARCH_BUNDLE_INELIGIBLE" in {
        finding["code"] for finding in report["hard_failures"]
    }


def test_validate_authoring_pack_rejects_unbound_research_claim(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
    complete_research_bundle: dict[str, Any],
) -> None:
    request, researched_source = _research_authoring_case(
        original_request, source, complete_research_bundle
    )
    researched_source["evidence"]["claims"][0]["claim_id"] = "invented-claim"

    report = validate_authoring_pack(
        request,
        researched_source,
        registry,
        research_bundle=complete_research_bundle,
    )

    assert "AUTHORING_RESEARCH_CLAIM_UNBOUND" in {
        finding["code"] for finding in report["hard_failures"]
    }


def test_validate_authoring_pack_rejects_embellished_research_reference(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
    complete_research_bundle: dict[str, Any],
) -> None:
    request, researched_source = _research_authoring_case(
        original_request, source, complete_research_bundle
    )
    researched_source["evidence"]["claims"][0]["notes"] = (
        "This must not ride along with a reference."
    )

    report = validate_authoring_pack(
        request,
        researched_source,
        registry,
        research_bundle=complete_research_bundle,
    )

    assert "AUTHORING_RESEARCH_CLAIM_UNBOUND" in {
        finding["code"] for finding in report["hard_failures"]
    }


def test_validate_authoring_pack_rejects_unresolved_bundle_conflict(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
    complete_research_bundle: dict[str, Any],
) -> None:
    unresolved = deepcopy(complete_research_bundle)
    unresolved["conflicts"][0]["status"] = "unresolved"
    unresolved["conflicts"][0]["selected_claim_ids"] = []
    unresolved["conflicts"][0].pop("resolution_rationale")
    unresolved["conflicts"][0]["incompatibility_rationale"] = (
        "The claims name different roles."
    )
    unhashed = dict(unresolved)
    unhashed.pop("bundle_hash")
    unresolved["bundle_hash"] = canonical_hash(unhashed)
    request, researched_source = _research_authoring_case(
        original_request, source, unresolved
    )

    report = validate_authoring_pack(
        request,
        researched_source,
        registry,
        research_bundle=unresolved,
    )

    assert "RESEARCH_BUNDLE_CONFLICT_UNRESOLVED" in {
        finding["code"] for finding in report["hard_failures"]
    }


@pytest.mark.parametrize(
    "field,value",
    [("visibility", "public"), ("activation_allowed", True)],
)
def test_validate_authoring_pack_rejects_invalid_bundle_lifecycle(
    field: str,
    value: object,
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
    complete_research_bundle: dict[str, Any],
) -> None:
    invalid = deepcopy(complete_research_bundle)
    invalid[field] = value
    request, researched_source = _research_authoring_case(
        original_request, source, invalid
    )

    report = validate_authoring_pack(
        request,
        researched_source,
        registry,
        research_bundle=invalid,
    )

    assert "RESEARCH_BUNDLE_INVALID" in {
        finding["code"] for finding in report["hard_failures"]
    }


def test_validate_authoring_pack_rejects_stale_internal_bundle_hash(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
    complete_research_bundle: dict[str, Any],
) -> None:
    changed = deepcopy(complete_research_bundle)
    changed["limitations"] = ["Changed after hashing."]
    request, researched_source = _research_authoring_case(
        original_request, source, changed
    )

    report = validate_authoring_pack(
        request,
        researched_source,
        registry,
        research_bundle=changed,
    )

    assert "RESEARCH_BUNDLE_INVALID" in {
        finding["code"] for finding in report["hard_failures"]
    }


def test_hybrid_user_override_cannot_rewrite_bundle_claim_id(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
    complete_research_bundle: dict[str, Any],
) -> None:
    request, researched_source = _research_authoring_case(
        original_request,
        source,
        complete_research_bundle,
        "hybrid",
    )
    researched_source["evidence"]["claims"][1]["claim_id"] = "claim-role"

    report = validate_authoring_pack(
        request,
        researched_source,
        registry,
        research_bundle=complete_research_bundle,
    )

    assert "AUTHORING_RESEARCH_FACT_OVERRIDE" in {
        finding["code"] for finding in report["hard_failures"]
    }


def test_provenance_counts_keep_private_assertions_apart_from_sourced_facts(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    """One evidence total hid what the dossier mode exists to keep separate."""

    request = _request_for_mode(original_request, "dossier")
    source["evidence"] = {
        "authored_original": False,
        "claims": [
            {"statement": "Quoted assertion", "source": "user_dossier", "quote": "private user dossier"},
            {"statement": "Second assertion", "source": "user_dossier", "quote": "private user dossier"},
            {"statement": "Relabelled assertion", "source": "external-canon"},
        ],
    }

    report = validate_authoring_pack(request, source, registry)

    counts = report["provenance_counts"]
    assert counts["evidence"] == 3
    # A label the modes do not accept is counted, but never named.
    assert counts["evidence_by_source"] == {
        "creative_brief": 0,
        "research_bundle": 0,
        "user_dossier": 2,
        "user_override": 0,
        "unrecognized": 1,
    }
    assert sum(counts["evidence_by_source"].values()) == counts["evidence"]
    registry.validate("build-validation-report", report)


def test_validate_authoring_pack_refuses_a_closing_intent_the_pack_does_not_author(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    """A closing line nobody wrote would be a promise no turn can keep."""

    source["behavior"]["closing_expressions"] = ["task_completion"]

    report = validate_authoring_pack(original_request, source, registry)

    assert report["valid"] is False
    assert [
        item["path"]
        for item in report["hard_failures"]
        if item["code"] == "AUTHORING_CLOSING_EXPRESSION_UNKNOWN"
    ] == [["behavior", "closing_expressions", 0]]


def _dossier_claim_case(
    original_request: dict[str, Any], source: dict[str, Any], claim: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    request = _request_for_mode(original_request, "dossier")
    source["evidence"] = {"authored_original": False, "claims": [claim]}
    return request, source


@pytest.mark.parametrize(
    ("claim", "code"),
    [
        (
            {"statement": "Royal court librarian.", "source": "user_dossier"},
            "AUTHORING_USER_CLAIM_QUOTE_REQUIRED",
        ),
        (
            {"statement": "Royal court librarian.", "source": "user_dossier", "quote": "A p"},
            "AUTHORING_USER_CLAIM_QUOTE_REQUIRED",
        ),
        (
            {
                "statement": "Royal court librarian.",
                "source": "user_dossier",
                "quote": "royal court librarian",
            },
            "AUTHORING_USER_CLAIM_QUOTE_UNBOUND",
        ),
        (
            # The dossier's words, but labelled as an override nobody typed.
            {
                "statement": "A private dossier.",
                "source": "user_override",
                "quote": "private user dossier",
            },
            "AUTHORING_USER_CLAIM_QUOTE_UNBOUND",
        ),
    ],
)
def test_a_user_claim_must_quote_the_users_own_input(
    claim: dict[str, Any],
    code: str,
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    """A dossier claim the dossier never made validated on its label alone."""

    request, source = _dossier_claim_case(original_request, source, claim)
    if claim["source"] == "user_override":
        source["evidence"]["claims"].insert(
            0,
            {"statement": "Quoted assertion", "source": "user_dossier", "quote": "private user dossier"},
        )

    report = validate_authoring_pack(request, source, registry)

    assert [(item["code"], item["path"][-1]) for item in report["hard_failures"]] == [
        (code, "quote")
    ]
    registry.validate("character-source", source)


def test_a_quote_matches_across_reflowed_whitespace_and_unicode_forms(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    request, source = _dossier_claim_case(
        original_request,
        source,
        {"statement": "Keeps a dossier.", "source": "user_dossier", "quote": "private\n  user dossier"},
    )
    request["inputs"][0]["content"] = "A private user dossier, Cafe\u0301 notes."
    source["evidence"]["claims"].append(
        {"statement": "Keeps notes.", "source": "user_dossier", "quote": "Caf\u00e9 notes"}
    )

    report = validate_authoring_pack(request, source, registry)

    assert report["hard_failures"] == []


def test_a_whole_short_input_is_a_valid_quote(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    request, source = _dossier_claim_case(
        original_request,
        source,
        {"statement": "Quiet.", "source": "user_dossier", "quote": "静か"},
    )
    request["inputs"][0]["content"] = "静か"

    report = validate_authoring_pack(request, source, registry)

    assert report["hard_failures"] == []


def test_more_override_claims_than_override_inputs_is_advised(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
    complete_research_bundle: dict[str, Any],
) -> None:
    """Three override claims from one override input validated without a word."""

    request, researched_source = _research_authoring_case(
        original_request, source, complete_research_bundle, "hybrid"
    )
    for statement in ("Quieter.", "Much quieter."):
        researched_source["evidence"]["claims"].append(
            {"statement": statement, "source": "user_override", "quote": "quieter delivery"}
        )

    report = validate_authoring_pack(
        request,
        researched_source,
        registry,
        research_bundle=complete_research_bundle,
    )

    assert "AUTHORING_USER_OVERRIDE_CLAIMS_EXCEED_INPUTS" in {
        finding["code"] for finding in report["advisory_findings"]
    }
    assert not [
        finding
        for finding in report["hard_failures"]
        if finding["code"].startswith("AUTHORING_USER_CLAIM")
    ]


def test_a_pack_that_never_declares_closing_lines_is_advised(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    """A name guess missed wrap_up and flagged honest opening lines."""

    source["expressions"] = {
        **source["expressions"],
        "wrap_up": {locale: ["line"] for locale in source["locales"]},
        "standing_by": {locale: ["line"] for locale in source["locales"]},
    }
    source["behavior"] = {
        key: value for key, value in source.get("behavior", {}).items()
        if key != "closing_expressions"
    }

    undeclared = validate_authoring_pack(original_request, source, registry)
    source["behavior"] = {**source["behavior"], "closing_expressions": []}
    declared = validate_authoring_pack(original_request, source, registry)

    assert "AUTHORING_CLOSING_EXPRESSIONS_UNDECLARED" in [
        item["code"] for item in undeclared["advisory_findings"]
    ]
    assert "AUTHORING_CLOSING_EXPRESSIONS_UNDECLARED" not in [
        item["code"] for item in declared["advisory_findings"]
    ]


def test_a_cjk_quote_folded_across_yaml_lines_still_binds(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    """YAML folds a line break into a space the Chinese dossier never had."""

    import yaml

    request = _request_for_mode(original_request, "dossier")
    request["inputs"][0]["content"] = "她是皇家图书馆的管理员，讨厌吵闹的孩子。"
    folded = yaml.safe_load(
        "quote: >-\n  她是皇家图书馆的管理员，\n  讨厌吵闹的孩子\n"
    )["quote"]
    assert " " in folded
    source["evidence"] = {
        "authored_original": False,
        "claims": [{"statement": "A royal librarian.", "source": "user_dossier", "quote": folded}],
    }

    report = validate_authoring_pack(request, source, registry)

    assert report["hard_failures"] == []


@pytest.mark.parametrize(
    ("content", "quote", "binds"),
    [
        ("Kaede is not able to lie.", "is notable", False),
        ("Kaede does not like crowds.", "doesnot like crowds", False),
        ("Kaede does not like crowds.", "does not\n  like crowds", True),
        ("她是皇家图书馆的管理员，讨厌吵闹的孩子。", "她是皇家图书馆的管理员， 讨厌吵闹的孩子", True),
        ("凛は systems architect です。", "凛は systems architect です", True),
    ],
    ids=["no-space-join", "dropped-space", "reflowed-english", "folded-chinese", "mixed-script"],
)
def test_a_quote_keeps_its_word_boundaries(
    content: str,
    quote: str,
    binds: bool,
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
) -> None:
    """Removing all whitespace let "is notable" stand for "is not able"."""

    request = _request_for_mode(original_request, "dossier")
    request["inputs"][0]["content"] = content
    source["evidence"] = {
        "authored_original": False,
        "claims": [{"statement": "A claim.", "source": "user_dossier", "quote": quote}],
    }

    report = validate_authoring_pack(request, source, registry)

    unbound = "AUTHORING_USER_CLAIM_QUOTE_UNBOUND" in [
        item["code"] for item in report["hard_failures"]
    ]
    assert unbound is not binds


def test_a_user_claim_cannot_support_a_field_research_supports(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
    complete_research_bundle: dict[str, Any],
) -> None:
    """A quoted override contradicting claim-role validated under a new claim id."""

    request, researched_source = _research_authoring_case(
        original_request, source, complete_research_bundle, "hybrid"
    )
    researched_source["evidence"]["claims"][0]["supports"] = ["identity.role"]
    researched_source["evidence"]["claims"][1]["supports"] = ["identity.role"]
    registry.validate("character-source", researched_source)

    report = validate_authoring_pack(
        request, researched_source, registry, research_bundle=complete_research_bundle
    )

    assert [
        (finding["code"], finding["path"])
        for finding in report["hard_failures"]
        if finding["code"] == "AUTHORING_RESEARCH_FACT_OVERRIDE"
    ] == [("AUTHORING_RESEARCH_FACT_OVERRIDE", ["evidence", "claims", 1, "supports"])]


@pytest.mark.parametrize(
    ("role", "advised"),
    [("starship captain", True), ("observatory apprentice", False)],
)
def test_an_identity_value_its_cited_claim_does_not_state_is_advised(
    role: str,
    advised: bool,
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
    complete_research_bundle: dict[str, Any],
) -> None:
    request, researched_source = _research_authoring_case(
        original_request, source, complete_research_bundle
    )
    researched_source["identity"]["role"] = role
    researched_source["evidence"]["claims"][0]["supports"] = ["identity.role"]

    report = validate_authoring_pack(
        request, researched_source, registry, research_bundle=complete_research_bundle
    )

    codes = [finding["code"] for finding in report["advisory_findings"]]
    assert ("AUTHORING_IDENTITY_NOT_IN_CITED_CLAIM" in codes) is advised
    assert "AUTHORING_RESEARCH_CLAIM_UNBOUND" not in [
        finding["code"] for finding in report["hard_failures"]
    ]
    assert role not in json.dumps(report["advisory_findings"])


def test_supports_names_only_identity_fields(
    registry: SchemaRegistry, source: dict[str, Any]
) -> None:
    source["evidence"] = {
        "authored_original": True,
        "claims": [{"statement": "x", "source": "creative_brief", "supports": ["behavior.tone"]}],
    }

    with pytest.raises(KokoroError):
        registry.validate("character-source", source)


def test_an_uncited_identity_role_is_advised_in_research_modes(
    registry: SchemaRegistry,
    original_request: dict[str, Any],
    source: dict[str, Any],
    complete_research_bundle: dict[str, Any],
) -> None:
    """Without supports, a contradicting role validated with no word at all."""

    request, researched_source = _research_authoring_case(
        original_request, source, complete_research_bundle
    )

    uncited = validate_authoring_pack(
        request, researched_source, registry, research_bundle=complete_research_bundle
    )
    researched_source["evidence"]["claims"][0]["supports"] = ["identity.role"]
    cited = validate_authoring_pack(
        request, researched_source, registry, research_bundle=complete_research_bundle
    )

    assert ["identity", "role"] in [
        finding["path"]
        for finding in uncited["advisory_findings"]
        if finding["code"] == "AUTHORING_IDENTITY_UNCITED"
    ]
    assert ["identity", "role"] not in [
        finding["path"]
        for finding in cited["advisory_findings"]
        if finding["code"] == "AUTHORING_IDENTITY_UNCITED"
    ]
