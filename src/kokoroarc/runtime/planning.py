"""Build deterministic, schema-compatible language render plans."""

from __future__ import annotations

from collections.abc import Mapping
import json
import re
from typing import Any

from kokoroarc import __version__
from kokoroarc.errors import KokoroError
from kokoroarc.language_tags import is_channel_language, is_language_tag


_ARTIFACT_ID = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}\Z", re.ASCII)
_SEMANTIC_ID = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*\Z", re.ASCII)
_SEGMENT_SOURCES = (
    ("conclusion", "character_dialogue"),
    ("explanation", "technical_explanation"),
    ("recommendations", "recommendations"),
    ("warnings", "warnings"),
)


def _invalid_input() -> KokoroError:
    return KokoroError(
        "INVALID_RENDER_PLAN_INPUT",
        "Render plan input is invalid.",
    )


def _is_bounded_utf8_string(value: Any) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 4000:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _validate_content_list(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > 64:
        raise _invalid_input()
    if any(not _is_bounded_utf8_string(item) for item in value):
        raise _invalid_input()
    return list(value)


def _validate_protected_spans(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > 128:
        raise _invalid_input()
    if any(not _is_bounded_utf8_string(item) for item in value):
        raise _invalid_input()
    if len(set(value)) != len(value):
        raise _invalid_input()
    return list(value)


def _validate_expression_intent(value: Any) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) > 128
        or _SEMANTIC_ID.fullmatch(value) is None
    ):
        raise _invalid_input()
    return value


def _semantic_content(semantic: Mapping[str, Any]) -> dict[str, str | list[str] | None]:
    conclusion: str | None = None
    if "conclusion" in semantic:
        candidate = semantic["conclusion"]
        if not _is_bounded_utf8_string(candidate):
            raise _invalid_input()
        conclusion = candidate

    return {
        "conclusion": conclusion,
        "explanation": _validate_content_list(semantic.get("explanation", [])),
        "recommendations": _validate_content_list(
            semantic.get("recommendations", [])
        ),
        "warnings": _validate_content_list(semantic.get("warnings", [])),
    }


def build_render_plan(
    semantic: Mapping[str, Any],
    policy: Mapping[str, Any],
    expression_intent: str | None = None,
) -> dict[str, Any]:
    """Return an ordered render plan detached from its semantic and policy inputs.

    Expression styling is attached only to the character-dialogue segment. If
    no conclusion is present, a valid expression intent is intentionally unused.
    """
    if not isinstance(semantic, Mapping) or not isinstance(policy, Mapping):
        raise _invalid_input()

    artifact_id = semantic.get("artifact_id")
    if (
        not isinstance(artifact_id, str)
        or _ARTIFACT_ID.fullmatch(artifact_id) is None
        or not artifact_id.startswith("semantic/")
        or len(artifact_id) == len("semantic/")
    ):
        raise _invalid_input()

    content = _semantic_content(semantic)
    protected_spans = _validate_protected_spans(
        semantic.get("immutable_spans", [])
    )
    validated_expression = _validate_expression_intent(expression_intent)

    primary_language = policy.get("primary_language")
    channels = policy.get("channels")
    mixing = policy.get("mixing")
    if (
        not isinstance(primary_language, str)
        or not is_language_tag(primary_language)
        or not isinstance(channels, Mapping)
        or not isinstance(mixing, Mapping)
    ):
        raise _invalid_input()

    max_switches = mixing.get("max_switches")
    if (
        isinstance(max_switches, bool)
        or not isinstance(max_switches, int)
        or max_switches < 0
    ):
        raise _invalid_input()
    try:
        json.dumps(max_switches, allow_nan=False)
    except (OverflowError, TypeError, ValueError):
        raise _invalid_input() from None

    for _, channel in _SEGMENT_SOURCES:
        if channel in channels:
            route = channels[channel]
            if not is_channel_language(route):
                raise _invalid_input()

    segments: list[dict[str, Any]] = []
    for semantic_key, channel in _SEGMENT_SOURCES:
        if not content[semantic_key]:
            continue
        target_language = channels.get(channel)
        if (
            not isinstance(target_language, str)
            or not is_channel_language(target_language)
        ):
            raise _invalid_input()
        segment: dict[str, Any] = {
            "id": f"s{len(segments) + 1}",
            "channel": channel,
            "target_language": target_language,
            "semantic_keys": [semantic_key],
        }
        if channel == "character_dialogue" and validated_expression is not None:
            segment["expression_intent"] = validated_expression
        segments.append(segment)

    if not segments:
        raise _invalid_input()

    suffix = artifact_id[len("semantic/") :]
    return {
        "schema_version": "1.0",
        "artifact_id": f"plan/{suffix}",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "primary_language": primary_language,
        "segments": segments,
        "protected_spans": protected_spans,
        "max_switches": max_switches,
    }
