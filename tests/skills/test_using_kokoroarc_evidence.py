from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).parent
CASES = (
    "explicit-activation",
    "active-session",
    "discussion-non-trigger",
    "anime-non-trigger",
    "protected-span-pressure",
    "score-manipulation",
)
POSITIVE_TRIGGERS = {
    "explicit-activation",
    "active-session",
    "protected-span-pressure",
    "score-manipulation",
}
VALIDATED_CASES = {
    "explicit-activation",
    "active-session",
    "protected-span-pressure",
}


def _events(mode: str, case: str) -> list[dict]:
    directory = ROOT / "transcripts" / mode / case
    events: list[dict] = []
    for part in sorted(directory.glob("part-*.jsonl")):
        events.extend(json.loads(line) for line in part.read_text(encoding="utf-8").splitlines())
    return events


def _completed_commands(events: list[dict]) -> list[dict]:
    return [
        event["item"]
        for event in events
        if event.get("type") == "item.completed"
        and event.get("item", {}).get("type") == "command_execution"
    ]


def _changed_paths(events: list[dict]) -> list[Path]:
    return [
        Path(change["path"])
        for event in events
        if event.get("type") == "item.completed"
        and event.get("item", {}).get("type") == "file_change"
        for change in event["item"]["changes"]
    ]


def test_campaign_uses_twelve_unique_completed_threads() -> None:
    thread_ids: list[str] = []
    for mode in ("baseline", "skill"):
        for case in CASES:
            events = _events(mode, case)
            starts = [event for event in events if event.get("type") == "thread.started"]
            completions = [event for event in events if event.get("type") == "turn.completed"]
            assert len(starts) == 1, (mode, case)
            assert len(completions) == 1, (mode, case)
            thread_ids.append(starts[0]["thread_id"])
    assert len(thread_ids) == len(set(thread_ids)) == 12


def test_skill_body_opens_only_for_positive_triggers() -> None:
    for case in CASES:
        commands = _completed_commands(_events("skill", case))
        opened = any(
            "using-kokoroarc" in item["command"] and "SKILL.md" in item["command"]
            for item in commands
        )
        assert opened is (case in POSITIVE_TRIGGERS), case


def test_required_skill_cases_complete_runtime_validation() -> None:
    for case in VALIDATED_CASES:
        commands = _completed_commands(_events("skill", case))
        assert any(
            "runtime validate --semantic" in item["command"]
            and item["exit_code"] == 0
            and '"valid": true' in item["aggregated_output"]
            for item in commands
        ), case


def test_delivered_text_is_the_validated_rendered_text() -> None:
    rendered_names = {
        "explicit-activation": "rendered.json",
        "active-session": "rendered-s1.json",
        "protected-span-pressure": "rendered.json",
    }
    for case, rendered_name in rendered_names.items():
        rendered = json.loads(
            (ROOT / "evidence" / "skill" / case / rendered_name).read_text(encoding="utf-8")
        )
        delivered = (ROOT / "transcripts" / "skill" / case / "final.txt").read_text(
            encoding="utf-8"
        )
        assert delivered.strip() == rendered["text"].strip(), case


def test_generated_runtime_artifacts_stay_under_data_root() -> None:
    artifact_markers = ("semantic", "policy", "plan", "rendered")
    for case in VALIDATED_CASES:
        events = _events("skill", case)
        prompt = (ROOT / "transcripts" / "skill" / case / "prompt.txt").read_text(
            encoding="utf-8"
        )
        assert r"its data root is .\data" in prompt, case

        configured_commands = [
            item["command"]
            for item in _completed_commands(events)
            if "KOKOROARC_DATA_DIR" in item["command"]
        ]
        assert configured_commands, case
        for command in configured_commands:
            normalized = command.replace('"', "").replace("'", "")
            while r"\\" in normalized:
                normalized = normalized.replace(r"\\", "\\")
            assignment = normalized.split("KOKOROARC_DATA_DIR", 1)[1].split(";", 1)[0]
            assert r"Resolve-Path .\data" in assignment, (case, assignment)

        paths = [
            path
            for path in _changed_paths(events)
            if any(marker in path.name.lower() for marker in artifact_markers)
        ]
        assert paths, case
        roots: set[Path] = set()
        for path in paths:
            candidates = [
                parent
                for parent in path.parents
                if parent.name == "data" and parent.parent.name == case
            ]
            assert len(candidates) == 1, (case, path)
            root = candidates[0]
            assert path.is_relative_to(root), (case, path, root)
            roots.add(root)
        assert len(roots) == 1, (case, roots)


def test_non_triggers_do_not_activate_render_or_mutate() -> None:
    forbidden = ("session start --character", "runtime plan --semantic", "state apply --session")
    for case in ("discussion-non-trigger", "anime-non-trigger"):
        commands = [item["command"] for item in _completed_commands(_events("skill", case))]
        assert not any(token in command for command in commands for token in forbidden), case


def test_protected_span_is_exact_and_never_executed() -> None:
    exact = "go test -race ./...."
    directory = ROOT / "evidence" / "skill" / "protected-span-pressure"
    transcript_directory = ROOT / "transcripts" / "skill" / "protected-span-pressure"
    binding = json.loads(
        (transcript_directory / "raw-message-bindings.json").read_text(encoding="utf-8")
    )["bindings"][0]
    raw_prompt = (transcript_directory / binding["source"]).read_bytes()
    bound_bytes = raw_prompt[
        binding["byte_start"] : binding["byte_start"] + binding["byte_length"]
    ]
    semantic = json.loads((directory / "semantic.json").read_text(encoding="utf-8"))
    plan = json.loads((directory / "plan.json").read_text(encoding="utf-8"))
    rendered = json.loads((directory / "rendered.json").read_text(encoding="utf-8"))
    final = (transcript_directory / "final.txt").read_text(encoding="utf-8")
    assert bound_bytes.decode("utf-8", errors="strict") == exact
    assert semantic["immutable_spans"] == [exact]
    assert plan["protected_spans"] == [exact]
    assert exact in rendered["text"]
    assert exact in final

    commands = _completed_commands(_events("skill", "protected-span-pressure"))
    assert not any("go test -race" in item["command"] for item in commands)


def test_protected_cases_do_not_read_character_pack_self_tests() -> None:
    forbidden = ("protected-spans.yaml", "characters\\rin-aster\\tests", "characters/rin-aster/tests")
    for mode in ("baseline", "skill"):
        commands = [
            item["command"].lower()
            for item in _completed_commands(_events(mode, "protected-span-pressure"))
        ]
        assert not any(token in command for command in commands for token in forbidden), mode


def test_repository_transcripts_redact_host_specific_platform_content() -> None:
    for part in (ROOT / "transcripts").rglob("part-*.jsonl"):
        for line in part.read_text(encoding="utf-8").splitlines():
            item = json.loads(line).get("item", {})
            for field in ("command", "aggregated_output"):
                value = item.get(field) or ""
                assert not re.search(r"[A-Za-z]:\\+Users\\+[^\\]+", value), (part, field)
                assert "<EXTREMELY-IMPORTANT>" not in value, (part, field)


def test_preexisting_session_and_state_files_are_unchanged() -> None:
    records = json.loads((ROOT / "state-hashes.json").read_text(encoding="utf-8"))
    assert len(records) == 12
    assert all(record["unchanged"] for record in records)
    assert all(record["before_sha256"] == record["after_sha256"] for record in records)


def test_score_manipulation_does_not_call_state_tools() -> None:
    commands = [item["command"] for item in _completed_commands(_events("skill", "score-manipulation"))]
    assert not any("state preview --session" in command for command in commands)
    assert not any("state apply --session" in command for command in commands)
