"""Build deterministic, schema-compatible language render plans."""

from __future__ import annotations

from collections.abc import Mapping
import json
from math import isfinite
import re
from typing import Any

from kokorox import __version__
from kokorox.errors import KokoroError
from kokorox.language_tags import is_channel_language, is_language_tag


_ARTIFACT_ID = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}\Z", re.ASCII)
_SEMANTIC_ID = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*\Z", re.ASCII)
_SEGMENT_SOURCES = (
    ("conclusion", "conclusion"),
    ("explanation", "technical_explanation"),
    ("recommendations", "recommendations"),
    ("warnings", "warnings"),
)


def _invalid_input(reason: str | None = None, **bounds: int) -> KokoroError:
    # A fixed reason and a numeric bound, never the input: they say what to
    # change without echoing what the caller passed.
    details: dict[str, Any] = {} if reason is None else {"reason": reason, **bounds}
    return KokoroError(
        "INVALID_RENDER_PLAN_INPUT",
        "Render plan input is invalid.",
        details=details,
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


_MAX_EXPRESSION_INTENTS = 8


def _validate_expression_intents(value: Any) -> tuple[str, ...]:
    """Accept one intent or several, in the order the turn calls for them."""

    if value is None:
        return ()
    candidates = [value] if isinstance(value, str) else value
    if not isinstance(candidates, (list, tuple)):
        raise _invalid_input("expression_intent_malformed")
    if not 1 <= len(candidates) <= _MAX_EXPRESSION_INTENTS:
        raise _invalid_input(
            "expression_intent_count",
            limit=_MAX_EXPRESSION_INTENTS,
            observed=len(candidates),
        )
    for candidate in candidates:
        if (
            not isinstance(candidate, str)
            or len(candidate) > 128
            or _SEMANTIC_ID.fullmatch(candidate) is None
        ):
            raise _invalid_input("expression_intent_malformed")
    if len(set(map(repr, candidates))) != len(candidates):
        raise _invalid_input("expression_intent_duplicate")
    return tuple(candidates)


def _closing_intents(context: Mapping[str, Any] | None) -> frozenset[str]:
    """The intents the pack says close a turn; every other one opens it."""

    if not isinstance(context, Mapping):
        return frozenset()
    declared = context.get("closing_expressions", [])
    if (
        not isinstance(declared, list)
        or len(declared) > 256
        or any(
            not isinstance(intent, str) or _SEMANTIC_ID.fullmatch(intent) is None
            for intent in declared
        )
    ):
        raise _invalid_input()
    return frozenset(declared)


_NEUTRAL_FALLBACK_LEVEL = 3


def _scenario_caps_neutral(context: Mapping[str, Any] | None) -> bool:
    if not isinstance(context, Mapping) or "scenarios" not in context:
        return False
    scenarios = context["scenarios"]
    if (
        not isinstance(scenarios, Mapping)
        or len(scenarios) > 128
        or any(not isinstance(config, Mapping) for config in scenarios.values())
    ):
        raise _invalid_input()
    return any(
        config.get("intensity_cap") == "neutral" for config in scenarios.values()
    )


def neutral_plan_reasons(
    context: Mapping[str, Any] | None, fallback_level: int = 0
) -> list[str]:
    """Say why a plan must be neutral, or return nothing when it need not be.

    Two rules said so and nothing enforced them. A scenario capped at
    `neutral` still planned the pack's lines, so an agent that honoured the
    cap by dropping them failed validation and one that ignored it passed.
    The ladder's last rung is the neutral renderer, but the plan the turn
    already had protected the authored lines, so no neutral render could
    ever validate against it.
    """

    if (
        isinstance(fallback_level, bool)
        or not isinstance(fallback_level, int)
        or not 0 <= fallback_level <= _NEUTRAL_FALLBACK_LEVEL
    ):
        raise _invalid_input("fallback_level_invalid")
    reasons: list[str] = []
    if _scenario_caps_neutral(context):
        reasons.append("intensity_cap")
    if fallback_level == _NEUTRAL_FALLBACK_LEVEL:
        reasons.append("fallback_level")
    return reasons


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


def _fixed_segment(
    intent: str | None,
    context: Mapping[str, Any] | None,
    route: Any,
) -> dict[str, Any] | None:
    """Return the pack's line for `intent`, or None when it authors none.

    The locale comes from the pack, not the reader: an authored line exists in
    the language it was written in, and rendering it in another would be the
    mechanical translation authoring forbids. `route` is the policy's dialogue
    channel; when it says `preserve` -- the default, since no policy compiled
    without the pack can name its locale -- the line is drawn from the locale
    the runtime context actually served. A pack that authors no line for
    this intent simply contributes none -- the persona is quieter and the
    answer still arrives.
    """

    if intent is None or not isinstance(context, Mapping):
        return None
    if route == "preserve":
        # "As written" -- and the context already knows which locale that was.
        route = context.get("persona_locale")
    if not isinstance(route, str) or not is_language_tag(route):
        return None
    expressions = context.get("expressions")
    if not isinstance(expressions, Mapping):
        return None
    locale_set = expressions.get(intent)
    if not isinstance(locale_set, Mapping):
        return None
    lines = locale_set.get(route)
    if not isinstance(lines, list) or not lines:
        return None
    text = lines[0]
    if not isinstance(text, str) or not 1 <= len(text) <= 2000:
        raise _invalid_input()
    return {
        # Provisional: the caller renumbers every segment once each line
        # takes its place at the front or the end.
        "id": "s1",
        "channel": "character_dialogue",
        "target_language": route,
        "fixed_line": {"intent": intent, "index": 0, "text": text},
    }


def build_render_plan(
    semantic: Mapping[str, Any],
    policy: Mapping[str, Any],
    expression_intent: str | list[str] | tuple[str, ...] | None = None,
    context: Mapping[str, Any] | None = None,
    fallback_level: int = 0,
) -> dict[str, Any]:
    """Return an ordered render plan detached from its semantic and policy inputs.

    A plan holds two kinds of segment. Semantic segments carry content the model
    formed this turn and follow the reader's language. A fixed segment carries
    one line the pack author wrote, in the locale they authored it in, copied
    verbatim from `context` -- the model never retypes it, and the planner adds
    it to `protected_spans` so validation rejects a translated catchphrase.

    `expression_intent` names the manners this turn calls for -- one, or several
    in order, since a turn can take an order and finish it. The first styles the
    conclusion. With a `context` that authors a line for an intent, the plan
    also emits that line on `character_dialogue`: before the answer, or after
    it when the pack lists the intent in `closing_expressions`. An intent with no
    authored line still counts and simply adds no segment, so a missing
    expression quiets the persona rather than blocking the delivery.

    A plan is neutral when the context's scenario caps intensity at
    `neutral` or `fallback_level` reaches the neutral renderer (3): it
    carries no authored lines and no intent, routes every semantic segment
    that is not `preserve` to the primary language, and allows no switches.
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
    intents = _validate_expression_intents(expression_intent)
    closing_intents = _closing_intents(context)
    neutral = bool(neutral_plan_reasons(context, fallback_level))

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

    # Carried onto the plan so the validator can enforce it. A policy that
    # declares a primary-language floor and never checks it promises nothing.
    min_primary_ratio = mixing.get("min_primary_ratio")
    if (
        isinstance(min_primary_ratio, bool)
        or not isinstance(min_primary_ratio, (int, float))
        or not isfinite(min_primary_ratio)
        or not 0 <= min_primary_ratio <= 1
    ):
        raise _invalid_input()

    for _, channel in _SEGMENT_SOURCES:
        if channel in channels:
            route = channels[channel]
            if not is_channel_language(route):
                raise _invalid_input()

    # The dialogue channel emits no semantic segment, so the loop above never
    # sees it -- but the fixed line is drawn from whatever locale it names, and
    # a junk route there must fail rather than quietly drop the persona.
    if "character_dialogue" in channels and not is_channel_language(
        channels["character_dialogue"]
    ):
        raise _invalid_input()

    # The conclusion is the answer, so it renders in the reader's language.
    # `runtime validate` enforces that too, but catching it only there leaves
    # the caller stranded: every fallback rung operates on the rendered
    # candidate, and none of them can change a plan. Refusing here fails at the
    # point where the mistake is both made and fixable -- recompile the policy
    # -- instead of after a render that could never validate.
    conclusion_channel = dict(_SEGMENT_SOURCES)["conclusion"]
    conclusion_route = channels.get(conclusion_channel)
    if (
        content["conclusion"]
        and isinstance(conclusion_route, str)
        and conclusion_route != primary_language
    ):
        raise KokoroError(
            "PLAN_CONCLUSION_LANGUAGE_MISMATCH",
            "The conclusion channel must route to the primary language.",
            details={
                "expected": primary_language,
                "actual": conclusion_route,
            },
        )

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
        if neutral and target_language != "preserve":
            target_language = primary_language
        segment: dict[str, Any] = {
            "id": f"s{len(segments) + 1}",
            "channel": channel,
            "target_language": target_language,
            "semantic_keys": [semantic_key],
        }
        if semantic_key == "conclusion" and intents and not neutral:
            segment["expression_intent"] = intents[0]
        segments.append(segment)

    opening: list[dict[str, Any]] = []
    closing: list[dict[str, Any]] = []
    for intent in () if neutral else intents:
        fixed = _fixed_segment(intent, context, channels.get("character_dialogue"))
        if fixed is None:
            continue
        # An opening line leads -- the character speaks, then answers. A closing
        # line follows the answer, so "done" is said once the work is shown.
        (closing if intent in closing_intents else opening).append(fixed)
    if opening or closing:
        segments = [*opening, *segments, *closing]
        for position, item in enumerate(segments, start=1):
            item["id"] = f"s{position}"
        for fixed in (*opening, *closing):
            line_text = fixed["fixed_line"]["text"]
            if line_text not in protected_spans:
                protected_spans = [*protected_spans, line_text]

    if not segments:
        raise _invalid_input()

    suffix = artifact_id[len("semantic/") :]
    forbidden = _forbidden_lines(context, protected_spans) if neutral else []
    plan: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact_id": f"plan/{suffix}",
        "created_by": {"component": "kokorox", "version": __version__},
        "primary_language": primary_language,
        "segments": segments,
        "protected_spans": protected_spans,
        "max_switches": 0 if neutral else max_switches,
        "min_primary_ratio": min_primary_ratio,
    }
    if forbidden:
        plan["forbidden_spans"] = forbidden
    return plan


_MAX_FORBIDDEN_SPANS = 128


def _forbidden_lines(
    context: Mapping[str, Any] | None, protected_spans: list[str]
) -> list[str]:
    """The pack's authored lines a neutral render must not speak.

    A neutral plan carried no lines, but nothing stopped a render against it
    from speaking both catchphrases and validating. A line the semantic
    result itself protects -- quoted as content -- is not forbidden.
    """

    if not isinstance(context, Mapping):
        return []
    expressions = context.get("expressions")
    if not isinstance(expressions, Mapping):
        return []
    lines: list[str] = []
    for intent in sorted(key for key in expressions if isinstance(key, str)):
        locale_set = expressions[intent]
        if not isinstance(locale_set, Mapping):
            continue
        for locale in sorted(key for key in locale_set if isinstance(key, str)):
            authored = locale_set[locale]
            if not isinstance(authored, list):
                continue
            for line in authored:
                if (
                    isinstance(line, str)
                    and 1 <= len(line) <= 4000
                    and line not in protected_spans
                    and line not in lines
                ):
                    lines.append(line)
    return lines[:_MAX_FORBIDDEN_SPANS]
