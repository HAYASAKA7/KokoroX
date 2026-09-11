"""Validate rendered output deterministically and select bounded fallbacks."""

from __future__ import annotations

from collections.abc import Mapping
import re
from math import isfinite
import sys
from typing import Any

from kokorox import __version__
from kokorox.errors import KokoroError
from kokorox.language_tags import PRESERVE, is_channel_language, is_language_tag


FALLBACK_ACTIONS = {
    0: "repair_segments",
    1: "reduce_switches",
    2: "lower_intensity",
    3: "neutral_renderer",
}

_ARTIFACT_ID = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}\Z", re.ASCII)
_SEGMENT_ID = re.compile(r"^s[1-9][0-9]*\Z", re.ASCII)
_SEMANTIC_KEY = re.compile(
    r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*\Z", re.ASCII
)
_MAX_VIOLATIONS = 128
_MAX_RENDERED_TEXT = 100_000
_MAX_SEGMENTS = 128
_MAX_SWITCHES = sys.maxsize
_PLAN_SEGMENT_KEYS = frozenset(
    {"id", "channel", "target_language", "semantic_keys", "expression_intent"}
)
_RENDERED_SEGMENT_KEYS = frozenset(
    {"id", "channel", "target_language", "semantic_keys"}
)
#: A segment carrying one pack-authored line instead of formed content. It has
#: no semantic keys because the model composed none of it.
_FIXED_SEGMENT_KEYS = frozenset({"id", "channel", "target_language", "fixed_line"})
_FIXED_LINE_KEYS = frozenset({"intent", "index", "text"})
#: Lines the pack wrote are the only thing this channel carries. Formed content
#: here is what let the answer inherit the pack's locale instead of the
#: reader's.
_FIXED_ONLY_CHANNEL = "character_dialogue"
_RENDERED_KEYS = frozenset({"text", "segments", "switch_count"})
_CHANNELS = frozenset(
    {
        "character_dialogue",
        "conclusion",
        "technical_explanation",
        "recommendations",
        "warnings",
        "technical_terms",
        "commands",
        "file_paths",
        "exact_errors",
        "code_identifiers",
    }
)
_SEMANTIC_KEYS = frozenset(
    {"conclusion", "explanation", "recommendations", "warnings"}
)
_REDUCED_SEMANTIC_KEYS = frozenset({"immutable_spans", "warnings"})
_FULL_SEMANTIC_KEYS = frozenset(
    {
        "schema_version",
        "artifact_id",
        "created_by",
        "scenario",
        "conclusion",
        "explanation",
        "recommendations",
        "warnings",
        "immutable_spans",
        "format_constraints",
    }
)
_REDUCED_PLAN_KEYS = frozenset({"max_switches", "segments"})
_FULL_PLAN_KEYS = frozenset(
    {
        "schema_version",
        "artifact_id",
        "created_by",
        "primary_language",
        "segments",
        "protected_spans",
        "max_switches",
        "min_primary_ratio",
    }
)


def _is_ratio(value: Any) -> bool:
    """Return whether `value` is a finite number within 0..1 inclusive."""

    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and isfinite(value)
        and 0 <= value <= 1
    )


#: `<algorithm>:<hex>` -- what a content digest looks like when it is written
#: into a span list instead of the string the digest was taken from.
_DIGEST_SPAN = re.compile(r"^[a-z0-9][a-z0-9-]{1,15}:[0-9a-f]{32,128}\Z", re.ASCII)


def _clamped_attempt(attempt: int) -> int:
    """Return `attempt` clamped onto the ladder, rejecting unbounded input."""

    if (
        isinstance(attempt, bool)
        or not isinstance(attempt, int)
        or abs(attempt) > sys.maxsize
    ):
        raise KokoroError(
            "INVALID_FALLBACK_ATTEMPT",
            "Fallback attempt must be a bounded integer.",
        )
    return min(max(attempt, 0), 3)


def fallback_action(attempt: int) -> str:
    """Return a fallback action after clamping a safe integer attempt."""
    return FALLBACK_ACTIONS[_clamped_attempt(attempt)]


def _bounded_string(value: Any, maximum: int) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _segment_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 128
        and _SEGMENT_ID.fullmatch(value) is not None
    )


def _is_enum_string(value: Any, choices: frozenset[str]) -> bool:
    return isinstance(value, str) and value in choices


def _semantic_keys(value: Any) -> list[str] | None:
    if not isinstance(value, list) or not 1 <= len(value) <= 4:
        return None
    if any(
        not isinstance(item, str)
        or len(item) > 128
        or _SEMANTIC_KEY.fullmatch(item) is None
        for item in value
    ):
        return None
    if len(set(value)) != len(value):
        return None
    return list(value)


def _safe_segment_id(value: Any) -> str | None:
    return value if _segment_id(value) else None


def _semantic_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 128
        and _SEMANTIC_KEY.fullmatch(value) is not None
    )


def _artifact_id_value(value: Any) -> bool:
    return isinstance(value, str) and _ARTIFACT_ID.fullmatch(value) is not None


def _artifact_suffix(value: Any, namespace: str) -> str | None:
    if not _artifact_id_value(value) or not value.startswith(namespace):
        return None
    suffix = value[len(namespace) :]
    if not suffix or _ARTIFACT_ID.fullmatch(suffix) is None:
        return None
    return suffix


def _created_by(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value.keys()) == {"component", "version"}
        and value.get("component") == "kokorox"
        and _bounded_string(value.get("version"), 64)
    )


def _string_list(
    value: Any,
    *,
    minimum: int = 0,
    maximum: int,
    unique: bool = False,
    semantic_ids: bool = False,
) -> list[str] | None:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        return None
    if semantic_ids:
        if any(not _semantic_id(item) for item in value):
            return None
    elif any(not _bounded_string(item, 4000) for item in value):
        return None
    if unique and len(set(value)) != len(value):
        return None
    return list(value)


def _plan_segment_contract_valid(segment: Any) -> bool:
    if not isinstance(segment, Mapping):
        return False
    if "fixed_line" in segment:
        return (
            set(segment.keys()) == _FIXED_SEGMENT_KEYS
            and _segment_id(segment.get("id"))
            and segment.get("channel") == _FIXED_ONLY_CHANNEL
            and is_language_tag(segment.get("target_language"))
            and _fixed_line(segment.get("fixed_line")) is not None
        )
    keys = set(segment.keys())
    required = {"id", "channel", "target_language", "semantic_keys"}
    semantic_keys = _semantic_keys(segment.get("semantic_keys"))
    return (
        required.issubset(keys)
        and keys.issubset(_PLAN_SEGMENT_KEYS)
        and _segment_id(segment.get("id"))
        and _is_enum_string(segment.get("channel"), _CHANNELS)
        and is_channel_language(segment.get("target_language"))
        and semantic_keys is not None
        and all(key in _SEMANTIC_KEYS for key in semantic_keys)
        and (
            "expression_intent" not in segment
            or _semantic_id(segment.get("expression_intent"))
        )
    )


def _segments_contract_valid(value: Any, *, nonempty: bool) -> bool:
    minimum = 1 if nonempty else 0
    if not isinstance(value, list) or not minimum <= len(value) <= _MAX_SEGMENTS:
        return False
    if any(not _plan_segment_contract_valid(segment) for segment in value):
        return False
    signatures = [
        (
            segment["id"],
            segment["channel"],
            segment["target_language"],
            tuple(segment.get("semantic_keys", ())),
            "expression_intent" in segment,
            segment.get("expression_intent"),
            tuple(sorted((segment.get("fixed_line") or {}).items())),
        )
        for segment in value
    ]
    return len(set(signatures)) == len(signatures)


def _semantic_contract_valid(value: Mapping[str, Any]) -> bool:
    keys = set(value.keys())
    reduced = keys == _REDUCED_SEMANTIC_KEYS
    full = keys == _FULL_SEMANTIC_KEYS
    if not reduced and not full:
        return False

    span_limit = 64 if full else 128
    if _string_list(
        value.get("immutable_spans"), maximum=span_limit, unique=True
    ) is None:
        return False
    if _string_list(value.get("warnings"), maximum=64) is None:
        return False
    if reduced:
        return True

    return (
        value.get("schema_version") == "1.0"
        and _artifact_suffix(value.get("artifact_id"), "semantic/") is not None
        and _created_by(value.get("created_by"))
        and _semantic_id(value.get("scenario"))
        and _bounded_string(value.get("conclusion"), 4000)
        and _string_list(
            value.get("explanation"), minimum=1, maximum=64
        )
        is not None
        and _string_list(
            value.get("recommendations"), minimum=1, maximum=64
        )
        is not None
        and _string_list(
            value.get("format_constraints"),
            maximum=64,
            unique=True,
            semantic_ids=True,
        )
        is not None
    )


def _plan_contract_valid(value: Mapping[str, Any]) -> bool:
    keys = set(value.keys())
    reduced = keys == _REDUCED_PLAN_KEYS
    full = keys == _FULL_PLAN_KEYS
    if not reduced and not full:
        return False
    max_switches = value.get("max_switches")
    if (
        isinstance(max_switches, bool)
        or not isinstance(max_switches, int)
        or not 0 <= max_switches <= _MAX_SWITCHES
        or not _segments_contract_valid(value.get("segments"), nonempty=True)
    ):
        return False
    if reduced:
        return True
    return (
        value.get("schema_version") == "1.0"
        and _artifact_suffix(value.get("artifact_id"), "plan/") is not None
        and _created_by(value.get("created_by"))
        and is_language_tag(value.get("primary_language"))
        and _is_ratio(value.get("min_primary_ratio"))
        and _string_list(
            value.get("protected_spans"), maximum=128, unique=True
        )
        is not None
    )


class _Violations:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(
        self,
        code: str,
        message: str,
        *,
        segment_id: str | None = None,
        path: list[str | int] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if len(self.items) >= _MAX_VIOLATIONS:
            return
        violation: dict[str, Any] = {"code": code, "message": message}
        if segment_id is not None and _segment_id(segment_id):
            violation["segment_id"] = segment_id
        if path is not None:
            safe_path = [
                item
                for item in path[:32]
                if (isinstance(item, int) and not isinstance(item, bool) and item >= 0)
                or _bounded_string(item, 128)
            ]
            violation["path"] = safe_path
        if details is not None:
            violation["details"] = details
        self.items.append(violation)


def _duplicate_planned_ids(plan: Any) -> list[str]:
    if not isinstance(plan, Mapping):
        return []
    segments = plan.get("segments")
    if not isinstance(segments, list):
        return []
    seen: set[str] = set()
    duplicates: list[str] = []
    for segment in segments[:_MAX_SEGMENTS]:
        if not isinstance(segment, Mapping):
            continue
        segment_id = segment.get("id")
        if not _segment_id(segment_id):
            continue
        if segment_id in seen and segment_id not in duplicates:
            duplicates.append(segment_id)
        seen.add(segment_id)
    return duplicates


def _artifact_id(plan: Any) -> str:
    if not isinstance(plan, Mapping):
        return "validation/result"
    source = plan.get("artifact_id")
    suffix = _artifact_suffix(source, "plan/")
    if suffix is None:
        return "validation/result"
    candidate = f"validation/{suffix}"
    if _ARTIFACT_ID.fullmatch(candidate) is None:
        return "validation/result"
    return candidate


def _fixed_line(value: Any) -> dict[str, Any] | None:
    """Return a well-formed fixed line, or None."""

    if not isinstance(value, Mapping) or set(value.keys()) != _FIXED_LINE_KEYS:
        return None
    intent = value.get("intent")
    index = value.get("index")
    text = value.get("text")
    if (
        not _semantic_id(intent)
        or isinstance(index, bool)
        or not isinstance(index, int)
        or not 0 <= index <= 63
        or not _bounded_string(text, 2000)
    ):
        return None
    return {"intent": intent, "index": index, "text": text}


def _validate_fixed_segment(
    segment: Mapping[str, Any],
    index: int,
    violations: _Violations,
    *,
    path_root: str,
) -> dict[str, Any] | None:
    segment_id = _safe_segment_id(segment.get("id"))
    line = _fixed_line(segment.get("fixed_line"))
    if (
        segment_id is None
        or segment.get("channel") != _FIXED_ONLY_CHANNEL
        # Not `is_channel_language`: an authored line exists in some language,
        # and `preserve` would name none.
        or not is_language_tag(segment.get("target_language"))
        or line is None
    ):
        violations.add(
            "INVALID_FIXED_SEGMENT",
            "Fixed segment has an invalid shape.",
            segment_id=segment_id,
            path=[path_root, "segments", index],
        )
        return None
    return {
        "id": segment_id,
        "channel": _FIXED_ONLY_CHANNEL,
        "target_language": segment["target_language"],
        "semantic_keys": [],
        "fixed_line": line,
    }


def _validate_planned_segment(
    segment: Any, index: int, violations: _Violations
) -> dict[str, Any] | None:
    if not isinstance(segment, Mapping):
        violations.add(
            "INVALID_PLANNED_SEGMENT",
            "Planned segment must be an object.",
            path=["plan", "segments", index],
        )
        return None
    if "fixed_line" in segment:
        return _validate_fixed_segment(
            segment, index, violations, path_root="plan"
        )
    keys = set(segment.keys())
    required = {"id", "channel", "target_language", "semantic_keys"}
    segment_id = _safe_segment_id(segment.get("id"))
    semantic_keys = _semantic_keys(segment.get("semantic_keys"))
    if (
        not required.issubset(keys)
        or not keys.issubset(_PLAN_SEGMENT_KEYS)
        or segment_id is None
        or not _is_enum_string(segment.get("channel"), _CHANNELS)
        or segment.get("channel") == _FIXED_ONLY_CHANNEL
        or not is_channel_language(segment.get("target_language"))
        or semantic_keys is None
        or any(key not in _SEMANTIC_KEYS for key in semantic_keys)
        or (
            "expression_intent" in segment
            and not _semantic_id(segment.get("expression_intent"))
        )
    ):
        violations.add(
            "INVALID_PLANNED_SEGMENT",
            "Planned segment has an invalid shape.",
            segment_id=segment_id,
            path=["plan", "segments", index],
        )
        return None
    return {
        "id": segment_id,
        "channel": segment["channel"],
        "target_language": segment["target_language"],
        "semantic_keys": semantic_keys,
    }


def _validate_rendered_segment(
    segment: Any, index: int, violations: _Violations
) -> dict[str, Any] | None:
    if not isinstance(segment, Mapping):
        violations.add(
            "INVALID_RENDERED_SEGMENT",
            "Rendered segment must be an object.",
            path=["rendered", "segments", index],
        )
        return None
    if "fixed_line" in segment:
        return _validate_fixed_segment(
            segment, index, violations, path_root="rendered"
        )
    segment_id = _safe_segment_id(segment.get("id"))
    semantic_keys = _semantic_keys(segment.get("semantic_keys"))
    if (
        set(segment.keys()) != _RENDERED_SEGMENT_KEYS
        or segment_id is None
        or not _is_enum_string(segment.get("channel"), _CHANNELS)
        or segment.get("channel") == _FIXED_ONLY_CHANNEL
        or not is_channel_language(segment.get("target_language"))
        or semantic_keys is None
        or any(key not in _SEMANTIC_KEYS for key in semantic_keys)
    ):
        violations.add(
            "INVALID_RENDERED_SEGMENT",
            "Rendered segment has an invalid shape.",
            segment_id=segment_id,
            path=["rendered", "segments", index],
        )
        return None
    return {
        "id": segment_id,
        "channel": segment["channel"],
        "target_language": segment["target_language"],
        "semantic_keys": semantic_keys,
    }


def validate_rendered_output(
    rendered: Any,
    semantic: Any,
    plan: Any,
    *,
    attempt: int = 0,
) -> dict[str, Any]:
    """Return a schema-compatible, deterministic hard-validation result.

    `attempt` is how many times this candidate has already failed. Validation
    is stateless -- it cannot know -- so the caller owns the count, and
    `fallback_level` reports the rung that count lands on. Returning a constant
    here would pin every caller to `repair_segments` and put the neutral
    renderer, the bottom of the ladder, out of reach.
    """

    level = _clamped_attempt(attempt)
    violations = _Violations()
    advisories = _Violations()

    # Duplicate planned IDs are intentionally the first reported condition.
    for segment_id in _duplicate_planned_ids(plan):
        violations.add(
            "DUPLICATE_SEGMENT_ID",
            "Planned segment ID is duplicated.",
            segment_id=segment_id,
        )

    rendered_mapping = isinstance(rendered, Mapping)
    semantic_mapping = isinstance(semantic, Mapping)
    plan_mapping = isinstance(plan, Mapping)
    semantic_is_full_artifact = (
        semantic_mapping and set(semantic.keys()) == _FULL_SEMANTIC_KEYS
    )
    plan_is_full_artifact = plan_mapping and set(plan.keys()) == _FULL_PLAN_KEYS
    if not rendered_mapping:
        violations.add("INVALID_RENDERED", "Rendered output must be an object.")
    if not semantic_mapping:
        violations.add("INVALID_SEMANTIC", "Semantic input must be an object.")
    elif not _semantic_contract_valid(semantic):
        violations.add(
            "INVALID_SEMANTIC", "Semantic input violates its artifact contract."
        )
    if not plan_mapping:
        violations.add("INVALID_PLAN", "Render plan must be an object.")
    elif not _plan_contract_valid(plan):
        violations.add("INVALID_PLAN", "Render plan violates its artifact contract.")

    if semantic_is_full_artifact and plan_is_full_artifact:
        semantic_suffix = _artifact_suffix(semantic.get("artifact_id"), "semantic/")
        plan_suffix = _artifact_suffix(plan.get("artifact_id"), "plan/")
        if (
            semantic_suffix is not None
            and plan_suffix is not None
            and semantic_suffix != plan_suffix
        ):
            violations.add(
                "ARTIFACT_SUFFIX_MISMATCH",
                "Semantic and render-plan artifact suffixes differ.",
                details={"expected": semantic_suffix, "actual": plan_suffix},
            )

    text: str | None = None
    rendered_segments: list[Any] = []
    switch_count: int | None = None
    if rendered_mapping:
        if set(rendered.keys()) != _RENDERED_KEYS:
            violations.add(
                "INVALID_RENDERED",
                "Rendered output has an invalid shape.",
            )
        candidate_text = rendered.get("text")
        if not isinstance(candidate_text, str) or len(candidate_text) > _MAX_RENDERED_TEXT:
            violations.add(
                "INVALID_RENDERED_TEXT", "Rendered text must be a bounded string."
            )
        else:
            try:
                candidate_text.encode("utf-8")
            except UnicodeEncodeError:
                violations.add(
                    "INVALID_RENDERED_TEXT",
                    "Rendered text must contain valid Unicode.",
                )
            else:
                text = candidate_text

        candidate_segments = rendered.get("segments")
        if (
            not isinstance(candidate_segments, list)
            or len(candidate_segments) > _MAX_SEGMENTS
        ):
            violations.add(
                "INVALID_RENDERED_SEGMENTS",
                "Rendered segments must be a bounded list.",
            )
        else:
            rendered_segments = candidate_segments

        candidate_switch_count = rendered.get("switch_count")
        if (
            isinstance(candidate_switch_count, bool)
            or not isinstance(candidate_switch_count, int)
            or not 0 <= candidate_switch_count <= _MAX_SWITCHES
        ):
            violations.add(
                "INVALID_SWITCH_COUNT", "Rendered switch count is invalid."
            )
        else:
            switch_count = candidate_switch_count

    immutable_spans: list[str] = []
    semantic_spans_usable = False
    warnings_required = False
    if semantic_mapping:
        candidate_spans = semantic.get("immutable_spans", [])
        semantic_is_full = _FULL_SEMANTIC_KEYS.issubset(set(semantic.keys()))
        span_limit = 64 if semantic_is_full else 128
        if not isinstance(candidate_spans, list) or len(candidate_spans) > span_limit:
            violations.add(
                "INVALID_IMMUTABLE_SPANS",
                "Immutable spans must be a bounded list.",
            )
        elif any(not _bounded_string(span, 4000) for span in candidate_spans):
            violations.add(
                "INVALID_IMMUTABLE_SPANS", "Immutable spans are invalid."
            )
        else:
            semantic_spans_usable = True
            immutable_spans = list(candidate_spans)
            if len(set(candidate_spans)) != len(candidate_spans):
                violations.add(
                    "INVALID_IMMUTABLE_SPANS",
                    "Immutable spans must be unique.",
                )

        candidate_warnings = semantic.get("warnings", [])
        if not isinstance(candidate_warnings, list) or len(candidate_warnings) > 64:
            violations.add("INVALID_WARNINGS", "Warnings must be a bounded list.")
        elif any(not _bounded_string(warning, 4000) for warning in candidate_warnings):
            violations.add("INVALID_WARNINGS", "Warnings are invalid.")
        else:
            warnings_required = bool(candidate_warnings)

    planned_segments: list[Any] = []
    plan_protected_spans: list[str] = []
    plan_spans_usable = False
    max_switches: int | None = None
    min_primary_ratio: float | None = None
    plan_primary_language: str | None = None
    if plan_mapping:
        plan_is_full = "protected_spans" in plan
        candidate_segments = plan.get("segments")
        if (
            not isinstance(candidate_segments, list)
            or len(candidate_segments) > _MAX_SEGMENTS
        ):
            violations.add(
                "INVALID_PLANNED_SEGMENTS",
                "Planned segments must be a bounded list.",
            )
        else:
            planned_segments = candidate_segments

        candidate_max_switches = plan.get("max_switches")
        if (
            isinstance(candidate_max_switches, bool)
            or not isinstance(candidate_max_switches, int)
            or not 0 <= candidate_max_switches <= _MAX_SWITCHES
        ):
            violations.add(
                "INVALID_MAX_SWITCHES", "Planned switch limit is invalid."
            )
        else:
            max_switches = candidate_max_switches

        # Absent on reduced plans, which carry only segments and the switch
        # limit; the floor is then simply not enforced.
        if "min_primary_ratio" in plan:
            candidate_ratio = plan.get("min_primary_ratio")
            if not _is_ratio(candidate_ratio):
                violations.add(
                    "INVALID_MIN_PRIMARY_RATIO",
                    "Planned primary-language floor is invalid.",
                )
            else:
                min_primary_ratio = float(candidate_ratio)
        candidate_primary = plan.get("primary_language")
        if is_language_tag(candidate_primary):
            plan_primary_language = candidate_primary

        if plan_is_full:
            candidate_plan_spans = plan.get("protected_spans")
            if (
                isinstance(candidate_plan_spans, list)
                and len(candidate_plan_spans) <= 128
                and all(
                    _bounded_string(span, 4000) for span in candidate_plan_spans
                )
            ):
                plan_spans_usable = True
                plan_protected_spans = list(candidate_plan_spans)

    # A plan protects what the caller declared, plus every line the pack
    # authored. The pack's lines are not in the Semantic Result and should not
    # be -- the model composed none of them -- so the plan carries strictly
    # more, in order, rather than exactly the same.
    planned_fixed_texts = [
        segment["fixed_line"]["text"]
        for segment in planned_segments
        if isinstance(segment, Mapping)
        and isinstance(segment.get("fixed_line"), Mapping)
        and isinstance(segment["fixed_line"].get("text"), str)
    ]
    if plan_mapping and "protected_spans" in plan:
        expected_spans = [*immutable_spans]
        # Not `text`: that name holds the rendered output, and rebinding it
        # here made the span check compare a line against itself.
        for line_text in planned_fixed_texts:
            if line_text not in expected_spans:
                expected_spans.append(line_text)
        if (
            semantic_spans_usable
            and plan_spans_usable
            and plan_protected_spans != expected_spans
        ):
            violations.add(
                "PROTECTED_SPAN_MISMATCH",
                "Plan protected spans differ from the semantic spans and "
                "the pack lines it carries.",
            )

    enforced_spans: list[str] = []
    for span in [*immutable_spans, *plan_protected_spans]:
        if span not in enforced_spans:
            enforced_spans.append(span)
    if text is not None:
        for span in enforced_spans:
            if span not in text:
                violations.add(
                    "MISSING_PROTECTED_SPAN",
                    "Rendered text omitted an immutable span.",
                    details={"protected_span": span},
                )

    # A digest in the span list protects only the digest. The check is literal
    # containment, so printing the hash satisfies it while the string the hash
    # stood for goes unconstrained -- writing it wrong returns green.
    #
    # This cannot be a violation: a user asking about a checksum has a genuine
    # reason to protect one. But they protect other literals too, so a set that
    # is entirely digests has no honest reading. Advisory, and only then.
    if enforced_spans and all(
        _DIGEST_SPAN.fullmatch(span) is not None for span in enforced_spans
    ):
        advisories.add(
            "PROTECTED_SPANS_ALL_DIGESTS",
            "Every immutable span is a digest, so no literal is protected.",
            details={"protected_span": enforced_spans[0]},
        )

    if switch_count is not None and max_switches is not None:
        if switch_count > max_switches:
            violations.add(
                "TOO_MANY_SWITCHES",
                "Rendered output exceeds the planned switch limit.",
                details={"limit": max_switches, "observed": switch_count},
            )

    valid_planned: list[dict[str, Any]] = []
    for index, segment in enumerate(planned_segments):
        validated = _validate_planned_segment(segment, index, violations)
        if validated is not None:
            valid_planned.append(validated)

    # The conclusion is the answer. A pack's authored locales decide which
    # expression material `runtime context` offers -- that fallback lives in
    # `persona_locale` -- not what language the answer is written in. Routing
    # the conclusion to an authored locale delivers the one load-bearing
    # sentence in a language the reader may not read while the supporting
    # detail around it is correctly translated, and the ratio check cannot see
    # it: three of four segments still carry the primary language.
    if plan_primary_language is not None:
        for segment in valid_planned:
            if "conclusion" not in segment["semantic_keys"]:
                continue
            if segment["target_language"] != plan_primary_language:
                violations.add(
                    "CONCLUSION_LANGUAGE_MISMATCH",
                    "The conclusion must render in the primary language.",
                    segment_id=segment["id"],
                    details={
                        "semantic_key": "conclusion",
                        "expected": plan_primary_language,
                        "actual": segment["target_language"],
                    },
                )

    if (
        min_primary_ratio is not None
        and plan_primary_language is not None
        and valid_planned
    ):
        # Only the zero case is checkable here, and it is exact rather than a
        # proxy: rendered segments carry no per-segment text, so the share of
        # primary-language content cannot be measured -- but if no segment is
        # routed to the primary language at all, that share is 0 whatever the
        # segment sizes are. Any floor above 0 is then definitely unmet. A
        # count-based ratio would instead misjudge small plans, where one
        # non-primary segment out of two reads as 50% regardless of length.
        #
        # Protected channels carry preserved source text rather than prose in
        # any language, so they sit outside this entirely.
        routed = [
            segment["target_language"]
            for segment in valid_planned
            if segment["target_language"] != PRESERVE
        ]
        if (
            routed
            and min_primary_ratio > 0
            and plan_primary_language not in routed
        ):
            violations.add(
                "PRIMARY_LANGUAGE_ABSENT",
                "No planned segment renders in the primary language.",
                # The floor is deliberately not reported. It gates whether this
                # check runs, but nothing compares a share against it, and a
                # `limit` beside an `observed` reads as a threshold that was
                # measured. Report only what was counted.
                details={
                    "expected": plan_primary_language,
                    "observed": 0,
                },
            )

    if semantic_is_full_artifact:
        planned_semantic_keys = {
            semantic_key
            for segment in valid_planned
            for semantic_key in segment["semantic_keys"]
        }
        populated_keys = (
            ("conclusion", bool(semantic.get("conclusion"))),
            ("explanation", bool(semantic.get("explanation"))),
            ("recommendations", bool(semantic.get("recommendations"))),
        )
        for semantic_key, populated in populated_keys:
            if populated and semantic_key not in planned_semantic_keys:
                violations.add(
                    "MISSING_SEMANTIC_ROUTE",
                    "A populated semantic field has no planned route.",
                    details={"semantic_key": semantic_key},
                )

    valid_rendered: list[dict[str, Any]] = []
    for index, segment in enumerate(rendered_segments):
        validated = _validate_rendered_segment(segment, index, violations)
        if validated is not None:
            valid_rendered.append(validated)

    rendered_counts: dict[str, int] = {}
    for segment in valid_rendered:
        segment_id = segment["id"]
        rendered_counts[segment_id] = rendered_counts.get(segment_id, 0) + 1
    for segment_id, count in rendered_counts.items():
        if count > 1:
            violations.add(
                "DUPLICATE_RENDERED_SEGMENT_ID",
                "Rendered segment ID is duplicated.",
                segment_id=segment_id,
            )

    planned_by_id: dict[str, dict[str, Any]] = {}
    for segment in valid_planned:
        planned_by_id.setdefault(segment["id"], segment)
    rendered_ids: set[str] = set()
    for actual in valid_rendered:
        segment_id = actual["id"]
        rendered_ids.add(segment_id)
        expected = planned_by_id.get(segment_id)
        if expected is None:
            violations.add(
                "UNEXPECTED_SEGMENT_ID",
                "Rendered segment is not present in the plan.",
                segment_id=segment_id,
            )
            continue
        if actual["channel"] != expected["channel"]:
            violations.add(
                "CHANNEL_MISMATCH",
                "Rendered segment channel differs from the plan.",
                segment_id=segment_id,
            )
        if actual["target_language"] != expected["target_language"]:
            violations.add(
                "LANGUAGE_MISMATCH",
                "Rendered segment language differs from the plan.",
                segment_id=segment_id,
            )
        if actual.get("fixed_line") != expected.get("fixed_line"):
            violations.add(
                "FIXED_LINE_MISMATCH",
                "Rendered fixed line differs from the plan.",
                segment_id=segment_id,
            )
        actual_keys = set(actual["semantic_keys"])
        expected_keys = set(expected["semantic_keys"])
        for semantic_key in expected["semantic_keys"]:
            if semantic_key not in actual_keys:
                violations.add(
                    "MISSING_SEMANTIC_KEY",
                    "Rendered segment omitted a planned semantic key.",
                    segment_id=segment_id,
                    details={"semantic_key": semantic_key},
                )
        for semantic_key in actual["semantic_keys"]:
            if semantic_key not in expected_keys:
                violations.add(
                    "UNEXPECTED_SEMANTIC_KEY",
                    "Rendered segment includes an unplanned semantic key.",
                    segment_id=segment_id,
                    details={"semantic_key": semantic_key},
                )

    warning_plans = [
        segment for segment in valid_planned if segment["channel"] == "warnings"
    ]
    for expected in valid_planned:
        if expected["id"] in rendered_ids:
            continue
        if expected["channel"] == "warnings":
            continue
        violations.add(
            "MISSING_SEGMENT",
            "A planned rendered segment is missing.",
            segment_id=expected["id"],
        )
    if not warning_plans and warnings_required:
        violations.add(
            "MISSING_WARNING",
            "Required warning route or content is missing.",
        )
    for expected in warning_plans:
        matched = any(
            actual["id"] == expected["id"]
            and actual["channel"] == "warnings"
            and "warnings" in actual["semantic_keys"]
            for actual in valid_rendered
        )
        if not matched:
            violations.add(
                "MISSING_WARNING",
                "Required warning route or content is missing.",
                segment_id=expected["id"],
            )

    valid = not violations.items
    return {
        "schema_version": "1.0",
        "artifact_id": _artifact_id(plan),
        "created_by": {"component": "kokorox", "version": __version__},
        "valid": valid,
        "violations": violations.items,
        "advisories": advisories.items,
        "fallback_level": None if valid else level,
    }
