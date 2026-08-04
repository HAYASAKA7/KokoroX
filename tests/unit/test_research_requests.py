from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, cast
import unicodedata

import pytest

import kokoroarc.research.requests as research_requests
from kokoroarc.errors import KokoroError
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.research import normalize_research_request
from kokoroarc.schemas import SchemaRegistry


SCHEMA_ROOT = Path("schemas/v1")
FIXTURE = Path("tests/fixtures/research/complete/request.json")
UNRESOLVED_FIELDS = ("medium", "work", "adaptation", "continuity", "timeline_cutoff")
UNRESOLVED_VALUES = ("  UnKnOwN  ", "\tUNSPECIFIED\n", " Ambiguous ", "  MiXeD\t")
COUNT_LIMITS = {
    "aliases": 32,
    "research_questions": 128,
    "required_coverage_topics": 128,
    "user_assertions": 128,
    "constraints": 128,
}
SAFE_CANONICAL_MESSAGE = "Artifact cannot be represented as canonical JSON."


@pytest.fixture
def registry() -> SchemaRegistry:
    return SchemaRegistry(SCHEMA_ROOT)


@pytest.fixture
def complete_request() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def invalid_request(
    registry: SchemaRegistry, request: dict[str, Any]
) -> KokoroError:
    with pytest.raises(KokoroError) as raised:
        normalize_research_request(request, registry)
    return raised.value


def assert_safe_canonical_error(error: KokoroError, secrets: tuple[str, ...]) -> None:
    serialized_details = json.dumps(error.details, ensure_ascii=False, sort_keys=True)
    serialized_envelope = json.dumps(
        error.envelope(), ensure_ascii=False, sort_keys=True
    )
    assert error.code == "INVALID_PACK_DATA"
    assert str(error) == SAFE_CANONICAL_MESSAGE
    assert error.details == {"path": []}
    assert error.retryable is False
    assert error.envelope() == {
        "ok": False,
        "error": {
            "code": "INVALID_PACK_DATA",
            "message": SAFE_CANONICAL_MESSAGE,
            "retryable": False,
            "details": {"path": []},
        },
    }
    for secret in secrets:
        assert secret not in str(error)
        assert secret not in serialized_details
        assert secret not in serialized_envelope


def count_values(field: str, count: int) -> list[str]:
    prefixes = {
        "aliases": "Alias ",
        "research_questions": "Question ",
        "required_coverage_topics": "topic-",
        "user_assertions": "Assertion ",
        "constraints": "Constraint ",
    }
    return [f"{prefixes[field]}{index}" for index in range(count)]


def test_normalize_research_request_is_canonical_deep_copy_and_non_mutating(
    registry: SchemaRegistry, complete_request: dict[str, Any]
) -> None:
    complete_request.pop("requested_visibility")
    before = deepcopy(complete_request)

    first = normalize_research_request(complete_request, registry)
    second = normalize_research_request(complete_request, registry)

    assert first == second
    assert canonical_bytes(first) == canonical_bytes(second)
    assert complete_request == before
    assert first["requested_visibility"] == "private"
    assert first is not complete_request
    assert first["created_by"] is not complete_request["created_by"]
    assert first["research_questions"] is not complete_request["research_questions"]

    first["created_by"]["version"] = "changed"
    first["research_questions"][0] = "Changed question"
    assert complete_request == before


def test_explicit_requested_visibility_is_preserved(
    registry: SchemaRegistry, complete_request: dict[str, Any]
) -> None:
    assert complete_request["requested_visibility"] == "private"

    normalized = normalize_research_request(complete_request, registry)

    assert normalized["requested_visibility"] == complete_request["requested_visibility"]


@pytest.mark.parametrize("field", UNRESOLVED_FIELDS)
@pytest.mark.parametrize("sentinel", UNRESOLVED_VALUES)
def test_rejects_every_unresolved_identity_and_continuity_sentinel_without_payload_leaks(
    registry: SchemaRegistry,
    complete_request: dict[str, Any],
    field: str,
    sentinel: str,
) -> None:
    sensitive = "SENSITIVE ASSERTION AND SOURCE PAYLOAD"
    complete_request[field] = sentinel
    complete_request["user_assertions"] = [sensitive]

    error = invalid_request(registry, complete_request)

    assert error.code == "RESEARCH_CONTINUITY_UNRESOLVED"
    assert error.details == {"field": field}
    assert sensitive not in str(error)
    assert sensitive not in json.dumps(error.details)


def test_multiple_unresolved_fields_report_first_contract_field_deterministically(
    registry: SchemaRegistry, complete_request: dict[str, Any]
) -> None:
    for field in reversed(UNRESOLVED_FIELDS):
        complete_request[field] = " MIXED "

    first = invalid_request(registry, complete_request)
    second = invalid_request(registry, complete_request)

    assert first.code == second.code == "RESEARCH_CONTINUITY_UNRESOLVED"
    assert first.details == second.details == {"field": "medium"}


@pytest.mark.parametrize("field", UNRESOLVED_FIELDS)
def test_explicit_not_applicable_is_not_treated_as_unresolved(
    registry: SchemaRegistry, complete_request: dict[str, Any], field: str
) -> None:
    complete_request[field] = "not_applicable"

    normalized = normalize_research_request(complete_request, registry)

    assert normalized[field] == "not_applicable"


def test_unicode_code_points_and_user_order_are_preserved_exactly(
    registry: SchemaRegistry, complete_request: dict[str, Any]
) -> None:
    decomposed = "Cafe\u0301"
    assert decomposed != unicodedata.normalize("NFC", decomposed)
    complete_request["display_name"] = decomposed
    complete_request["user_assertions"] = ["雪の観測者", decomposed, "Ａｏｉ"]
    complete_request["research_questions"] = ["Second?", "First?", "Third?"]

    normalized = normalize_research_request(complete_request, registry)

    assert normalized["display_name"] == decomposed
    assert [ord(character) for character in normalized["display_name"]] == [
        ord(character) for character in decomposed
    ]
    assert normalized["user_assertions"] == complete_request["user_assertions"]
    assert normalized["research_questions"] == complete_request["research_questions"]


def test_duplicate_order_is_retained_when_the_supplied_schema_permits_it(
    tmp_path: Path, complete_request: dict[str, Any]
) -> None:
    schema = json.loads(
        (SCHEMA_ROOT / "research-request.schema.json").read_text(encoding="utf-8")
    )
    schema["properties"]["research_questions"].pop("uniqueItems")
    schema["properties"]["user_assertions"].pop("uniqueItems")
    (tmp_path / "research-request.schema.json").write_text(
        json.dumps(schema), encoding="utf-8"
    )
    permissive_registry = SchemaRegistry(tmp_path)
    complete_request["research_questions"] = ["Repeated?", "Repeated?", "Last?"]
    complete_request["user_assertions"] = ["same", "same", "different"]

    normalized = normalize_research_request(complete_request, permissive_registry)

    assert normalized["research_questions"] == ["Repeated?", "Repeated?", "Last?"]
    assert normalized["user_assertions"] == ["same", "same", "different"]


@pytest.mark.parametrize("field,limit", COUNT_LIMITS.items())
def test_schema_maximum_counts_are_accepted(
    registry: SchemaRegistry,
    complete_request: dict[str, Any],
    field: str,
    limit: int,
) -> None:
    complete_request[field] = count_values(field, limit)

    normalized = normalize_research_request(complete_request, registry)

    assert normalized[field] == complete_request[field]


@pytest.mark.parametrize("field,limit", COUNT_LIMITS.items())
def test_schema_over_limit_counts_are_rejected(
    registry: SchemaRegistry,
    complete_request: dict[str, Any],
    field: str,
    limit: int,
) -> None:
    complete_request[field] = count_values(field, limit + 1)

    error = invalid_request(registry, complete_request)

    assert error.code == "SCHEMA_VALIDATION_FAILED"


def test_unknown_fields_are_rejected(
    registry: SchemaRegistry, complete_request: dict[str, Any]
) -> None:
    complete_request["unknown_field"] = True

    error = invalid_request(registry, complete_request)

    assert error.code == "SCHEMA_VALIDATION_FAILED"


@pytest.mark.parametrize(
    "field,value",
    [
        ("aliases", "Aoi"),
        ("medium", 7),
        ("research_questions", {"question": "What role?"}),
        ("user_assertions", [None]),
    ],
)
def test_invalid_field_types_are_rejected(
    registry: SchemaRegistry,
    complete_request: dict[str, Any],
    field: str,
    value: Any,
) -> None:
    complete_request[field] = value

    error = invalid_request(registry, complete_request)

    assert error.code == "SCHEMA_VALIDATION_FAILED"


def test_invalid_root_type_is_rejected(registry: SchemaRegistry) -> None:
    error = invalid_request(registry, cast(dict[str, Any], ["not", "an", "object"]))

    assert error.code == "SCHEMA_VALIDATION_FAILED"


def test_schema_validation_error_does_not_leak_assertion_or_source_payload(
    registry: SchemaRegistry, complete_request: dict[str, Any]
) -> None:
    sensitive = "SENSITIVE_ASSERTION_SOURCE_PAYLOAD"
    complete_request["user_assertions"] = [sensitive * 200]

    error = invalid_request(registry, complete_request)

    serialized_details = json.dumps(error.details, ensure_ascii=False)
    assert error.code == "SCHEMA_VALIDATION_FAILED"
    assert sensitive not in str(error)
    assert sensitive not in serialized_details
    assert error.details == {
        "schema": "research-request",
        "path": ["user_assertions", 0],
    }


@pytest.mark.parametrize(
    "payload,secrets",
    [
        (
            {
                "SENSITIVE_ASSERTION_BRANCH": {
                    "SENSITIVE_SOURCE_OBJECT_KEY": object()
                }
            },
            ("SENSITIVE_ASSERTION_BRANCH", "SENSITIVE_SOURCE_OBJECT_KEY"),
        ),
        (
            {"PRIVATE_SOURCE_PAYLOAD_KEY": float("nan")},
            ("PRIVATE_SOURCE_PAYLOAD_KEY",),
        ),
    ],
)
def test_canonicalization_errors_do_not_leak_nested_attacker_controlled_paths(
    registry: SchemaRegistry,
    complete_request: dict[str, Any],
    payload: object,
    secrets: tuple[str, ...],
) -> None:
    complete_request["user_assertions"] = cast(Any, [payload])

    error = invalid_request(registry, complete_request)

    assert_safe_canonical_error(error, secrets)


def test_ordinary_canonical_incompatibility_uses_fixed_empty_safe_path(
    registry: SchemaRegistry, complete_request: dict[str, Any]
) -> None:
    complete_request["constraints"] = cast(Any, [object()])

    error = invalid_request(registry, complete_request)

    assert_safe_canonical_error(error, ())


def test_non_invalid_pack_kokoro_error_from_canonicalizer_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    registry: SchemaRegistry,
    complete_request: dict[str, Any],
) -> None:
    expected = KokoroError("UNEXPECTED_CANONICAL_ERROR", "Programmer fault.")

    def raise_unexpected(value: object) -> bytes:
        raise expected

    monkeypatch.setattr(research_requests, "canonical_bytes", raise_unexpected)

    with pytest.raises(KokoroError) as raised:
        normalize_research_request(complete_request, registry)

    assert raised.value is expected


def test_non_kokoro_canonicalizer_fault_is_not_caught(
    monkeypatch: pytest.MonkeyPatch,
    registry: SchemaRegistry,
    complete_request: dict[str, Any],
) -> None:
    expected = RuntimeError("Programmer fault.")

    def raise_unexpected(value: object) -> bytes:
        raise expected

    monkeypatch.setattr(research_requests, "canonical_bytes", raise_unexpected)

    with pytest.raises(RuntimeError) as raised:
        normalize_research_request(complete_request, registry)

    assert raised.value is expected
