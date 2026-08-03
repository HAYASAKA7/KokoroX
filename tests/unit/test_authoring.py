from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from kokoroarc.authoring.requests import normalize_build_request
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
