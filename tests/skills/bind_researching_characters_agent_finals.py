from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from researching_characters_sanitization import contains_sensitive_material


HERE = Path(__file__).resolve().parent
DEFAULT_EVIDENCE_ROOT = HERE / "evidence" / "researching-characters"
NORMALIZATION = "lf_and_strip_terminal_lf"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def normalized_final(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def write_json(path: Path, value: object, newline: str = "\n") -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))


def session_agent_path(meta: dict) -> str | None:
    agent_path = meta.get("agent_path")
    if isinstance(agent_path, str):
        return agent_path
    source = meta.get("source")
    if not isinstance(source, dict):
        return None
    subagent = source.get("subagent")
    if not isinstance(subagent, dict):
        return None
    spawn = subagent.get("thread_spawn")
    if not isinstance(spawn, dict):
        return None
    value = spawn.get("agent_path")
    return value if isinstance(value, str) else None


def load_session(path: Path) -> tuple[list[bytes], list[dict], dict]:
    raw_lines = path.read_bytes().splitlines(keepends=True)
    if not raw_lines or any(not line.endswith(b"\n") for line in raw_lines):
        raise RuntimeError(f"session log must be LF-terminated JSONL: {path}")
    values = [json.loads(line.decode("utf-8")) for line in raw_lines]
    first = values[0]
    if first.get("type") != "session_meta" or not isinstance(
        first.get("payload"), dict
    ):
        raise RuntimeError(f"missing session metadata: {path}")
    return raw_lines, values, first["payload"]


def indexed_sessions(session_root: Path) -> dict[str, list[Path]]:
    indexed: dict[str, list[Path]] = {}
    for path in sorted(session_root.rglob("*.jsonl")):
        try:
            _lines, _values, meta = load_session(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError):
            continue
        agent_path = session_agent_path(meta)
        if agent_path is not None:
            indexed.setdefault(agent_path, []).append(path)
    return indexed


def response_text(payload: dict) -> str | None:
    content = payload.get("content")
    if not isinstance(content, list):
        return None
    texts = [
        item.get("text")
        for item in content
        if isinstance(item, dict)
        and item.get("type") == "output_text"
        and isinstance(item.get("text"), str)
    ]
    return texts[0] if len(texts) == 1 else None


def select_final_events(
    values: list[dict], expected: str
) -> tuple[list[int], list[dict]]:
    final_indexes = []
    for index, value in enumerate(values):
        payload = value.get("payload")
        if (
            value.get("type") == "event_msg"
            and isinstance(payload, dict)
            and payload.get("type") == "agent_message"
            and payload.get("phase") == "final_answer"
        ):
            final_indexes.append(index)
    if not final_indexes:
        raise RuntimeError("session contains no final-answer agent event")
    agent_index = final_indexes[-1]
    agent = values[agent_index]
    message = agent["payload"].get("message")
    if not isinstance(message, str) or normalized_final(message) != normalized_final(
        expected
    ):
        raise RuntimeError("last final-answer event does not match retained final.md")

    response_index = None
    complete_index = None
    for index in range(agent_index + 1, len(values)):
        value = values[index]
        payload = value.get("payload")
        if not isinstance(payload, dict):
            continue
        if (
            response_index is None
            and value.get("type") == "response_item"
            and payload.get("type") == "message"
            and payload.get("role") == "assistant"
            and payload.get("phase") == "final_answer"
            and response_text(payload) == message
        ):
            response_index = index
            continue
        if (
            response_index is not None
            and value.get("type") == "event_msg"
            and payload.get("type") == "task_complete"
            and payload.get("last_agent_message") == message
        ):
            complete_index = index
            break
    if response_index is None or complete_index is None:
        raise RuntimeError("final answer lacks matching response/task-complete events")

    selected_indexes = [agent_index, response_index, complete_index]
    return selected_indexes, [values[index] for index in selected_indexes]


def bind_run(
    run: dict,
    evidence_root: Path,
    sessions: dict[str, list[Path]],
) -> None:
    paths = sessions.get(run["thread_id"], [])
    if len(paths) != 1:
        raise RuntimeError(
            f"expected one session for {run['thread_id']}, found {len(paths)}"
        )
    session_path = paths[0]
    raw_lines, values, meta = load_session(session_path)
    run_root = evidence_root.joinpath(*run["evidence_dir"].split("/"))
    final = (run_root / "final.md").read_text(encoding="utf-8")
    selected_indexes, selected_events = select_final_events(values, final)

    selected_lines = [raw_lines[index] for index in selected_indexes]
    retained = b"".join(selected_lines)
    retained_text = retained.decode("utf-8")
    decoded_strings: list[str] = []

    def collect_strings(value: object) -> None:
        if isinstance(value, str):
            decoded_strings.append(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                collect_strings(key)
                collect_strings(item)
        elif isinstance(value, list):
            for item in value:
                collect_strings(item)

    for event in selected_events:
        collect_strings(event)
    if contains_sensitive_material(retained_text) or any(
        contains_sensitive_material(value) for value in decoded_strings
    ):
        raise RuntimeError(f"final event contains forbidden sensitive material: {session_path}")

    events_path = run_root / "agent-final-events.jsonl"
    events_path.write_bytes(retained)
    summary = {
        "schema_version": "1.0",
        "source": "codex_session_log",
        "session_id": meta["id"],
        "agent_path": run["thread_id"],
        "selected_final_answer_is_last": True,
        "newline_normalization": NORMALIZATION,
        "source_line_numbers": [index + 1 for index in selected_indexes],
        "event_line_sha256": [sha256_bytes(line) for line in selected_lines],
        "session_log_sha256": sha256_file(session_path),
        "session_meta_line_sha256": sha256_bytes(raw_lines[0]),
        "final_answer_event_count": sum(
            event.get("type") == "event_msg"
            and isinstance(event.get("payload"), dict)
            and event["payload"].get("type") == "agent_message"
            and event["payload"].get("phase") == "final_answer"
            for event in values
        ),
        "selected_event_timestamps": [event.get("timestamp") for event in selected_events],
    }
    session_summary = run_root / "agent-final-session.json"
    write_json(session_summary, summary)

    result_path = run_root / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["newline_normalization"] = NORMALIZATION
    write_json(result_path, result, newline="\r\n")

    run["agent_final_events_sha256"] = sha256_file(events_path)
    run["agent_final_session_sha256"] = sha256_file(session_summary)
    run["result_sha256"] = sha256_file(result_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_root", type=Path)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    args = parser.parse_args()
    session_root = args.session_root.resolve()
    evidence_root = args.evidence_root.resolve()
    campaign_file = evidence_root / "campaign.yaml"
    if not session_root.is_dir():
        raise SystemExit(f"missing Codex session root: {session_root}")
    if not campaign_file.is_file():
        raise SystemExit(f"missing research campaign evidence: {campaign_file}")

    campaign = yaml.safe_load(campaign_file.read_text(encoding="utf-8"))
    sessions = indexed_sessions(session_root)
    for run in campaign["runs"]:
        bind_run(run, evidence_root, sessions)
    campaign_text = yaml.safe_dump(campaign, sort_keys=False, allow_unicode=True)
    campaign_file.write_bytes(campaign_text.replace("\n", "\r\n").encode("utf-8"))


if __name__ == "__main__":
    main()
