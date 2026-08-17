from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Any

import yaml

from researching_characters_sanitization import (
    CREDENTIAL_REPLACEMENT,
    ENVIRONMENT_SECRET_REPLACEMENT,
    USER_PROFILE_REPLACEMENT,
)
from testing_character_packs_evidence import (
    adjudicate_assertions,
    bind_final_event,
    sanitize_artifact,
    sha256_bytes,
)


HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parents[1]
CASES_FILE = HERE / "testing-character-packs-cases.yaml"
APPROVAL_FILE = HERE / "testing-character-packs-campaign.yaml"
RUNNER_FILE = HERE / "run_testing_character_packs_campaign.py"
SKILL_ROOT = REPOSITORY_ROOT / "skills" / "testing-character-packs"
EVIDENCE_ROOT = HERE / "evidence" / "testing-character-packs"
VARIANTS = ("baseline", "skill-enabled")
RAW_FILES = (
    ("prompt.txt", "prompt.md", False),
    ("final.txt", "final.md", False),
    ("session.jsonl", "session.jsonl", True),
    ("stderr.txt", "stderr.txt", True),
    ("command.json", "command.json", True),
    ("run-status.json", "run-status.json", False),
    ("protected-before.json", "protected-before.json", False),
    ("protected-after.json", "protected-after.json", False),
    ("data-inventory.json", "data-inventory.json", False),
)


def _sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _retained_copy(
    source: Path,
    raw_run: Path,
    destination: Path,
    retained_run: Path,
    *,
    allow_redaction: bool,
) -> dict[str, Any]:
    raw = source.read_bytes()
    retained, redaction_count = sanitize_artifact(raw)
    if redaction_count and not allow_redaction:
        raise RuntimeError(f"unexpected redaction in immutable artifact: {source}")
    if sanitize_artifact(retained) != (retained, 0):
        raise RuntimeError(f"sanitizer is not idempotent for: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(retained)
    return {
        "path": destination.relative_to(retained_run).as_posix(),
        "raw_path": source.relative_to(raw_run).as_posix(),
        "raw_sha256": sha256_bytes(raw),
        "retained_sha256": sha256_bytes(retained),
        "redaction_count": redaction_count,
    }


def _copy_frozen_inputs(
    approval: dict[str, Any],
    retained_name: str,
) -> dict[str, str]:
    frozen = approval["frozen_inputs"]
    sources = {
        "approval.yaml": APPROVAL_FILE,
        "cases.yaml": CASES_FILE,
        "runner.py": RUNNER_FILE,
        "SKILL.md": SKILL_ROOT / "SKILL.md",
        "testing-contract.md": SKILL_ROOT / "references" / "testing-contract.md",
        "openai.yaml": SKILL_ROOT / "agents" / "openai.yaml",
    }
    expected = {
        "cases.yaml": frozen["cases_sha256"],
        "runner.py": frozen["runner_sha256"],
        "SKILL.md": frozen["skill_sha256"],
        "testing-contract.md": frozen["contract_sha256"],
        "openai.yaml": frozen["metadata_sha256"],
    }
    destination = EVIDENCE_ROOT / "harness" / retained_name
    hashes: dict[str, str] = {}
    for name, source in sources.items():
        digest = _sha256(source)
        if name in expected and digest != expected[name]:
            raise RuntimeError(f"frozen input changed before import: {name}")
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[f"harness/{retained_name}/{name}"] = digest
    return hashes


def _copy_reports(
    raw_run: Path,
    retained_run: Path,
    ledger: list[dict[str, Any]],
) -> None:
    reports = raw_run / "data" / "reports"
    if not reports.exists():
        return
    for source in sorted(reports.rglob("*")):
        if source.is_symlink() or (not source.is_file() and not source.is_dir()):
            raise RuntimeError(f"unsafe report artifact: {source}")
        if not source.is_file():
            continue
        relative = source.relative_to(reports)
        ledger.append(
            _retained_copy(
                source,
                raw_run,
                retained_run / "artifacts" / "reports" / relative,
                retained_run,
                allow_redaction=True,
            )
        )


def _import_run(
    raw_root: Path,
    retained_batch: Path,
    approval_id: str,
    variant: str,
    case: dict[str, Any],
    completed: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    raw_run = raw_root / variant / case["id"]
    retained_run = retained_batch / variant / case["id"]
    retained_run.mkdir(parents=True)
    raw_status = _load_json(raw_run / "run-status.json")
    if raw_status != completed[(variant, case["id"])]:
        raise RuntimeError(f"completed-run/status mismatch: {variant}/{case['id']}")
    for field, name in (
        ("prompt_sha256", "prompt.txt"),
        ("session_sha256", "session.jsonl"),
        ("stderr_sha256", "stderr.txt"),
    ):
        if raw_status[field] != _sha256(raw_run / name):
            raise RuntimeError(f"status hash mismatch for {variant}/{case['id']}/{name}")
    final_path = raw_run / "final.txt"
    if raw_status["final_sha256"] is None:
        if final_path.exists():
            raise RuntimeError(f"unbound final output for {variant}/{case['id']}")
    elif not final_path.is_file() or raw_status["final_sha256"] != _sha256(final_path):
        raise RuntimeError(f"status hash mismatch for {variant}/{case['id']}/final.txt")

    evaluable = (
        raw_status["exit_code"] == 0
        and not raw_status["timed_out"]
        and final_path.is_file()
        and (raw_run / "session.jsonl").stat().st_size > 0
    )
    if raw_status["exit_code"] == 0 and not evaluable:
        raise RuntimeError(f"zero-exit run lacks evaluator evidence: {variant}/{case['id']}")
    if evaluable:
        bind_final_event(
            (raw_run / "session.jsonl").read_bytes(),
            final_path.read_bytes(),
        )
    ledger: list[dict[str, Any]] = []
    for raw_name, retained_name, allow_redaction in RAW_FILES:
        source = raw_run / raw_name
        if not source.exists() and raw_name == "final.txt":
            continue
        ledger.append(
            _retained_copy(
                source,
                raw_run,
                retained_run / retained_name,
                retained_run,
                allow_redaction=allow_redaction,
            )
        )
    _copy_reports(raw_run, retained_run, ledger)

    session = (retained_run / "session.jsonl").read_bytes()
    binding: dict[str, Any] | None = None
    if evaluable:
        final = (retained_run / "final.md").read_bytes()
        binding = bind_final_event(session, final)
        _write_json(retained_run / "agent-final-session.json", binding)
        lines = session.splitlines(keepends=True)
        selected = b"".join(
            lines[index - 1] for index in binding["source_line_numbers"]
        )
        if sanitize_artifact(selected) != (selected, 0):
            raise RuntimeError(
                f"final event contains sensitive material: {variant}/{case['id']}"
            )
        (retained_run / "agent-final-events.jsonl").write_bytes(selected)

    before = _load_json(retained_run / "protected-before.json")
    after = _load_json(retained_run / "protected-after.json")
    inventory = _load_json(retained_run / "data-inventory.json")
    protected = {
        "schema_version": "1.0",
        "before": before,
        "after": after,
        "equal": before == after,
        "before_sha256": _sha256(retained_run / "protected-before.json"),
        "after_sha256": _sha256(retained_run / "protected-after.json"),
    }
    _write_json(retained_run / "protected-state.json", protected)
    declared_assertions = [
        *case.get("must", []),
        *case.get("must_not", []),
    ]
    assertions = (
        adjudicate_assertions(
            case,
            session,
            (retained_run / "final.md").read_bytes(),
            before,
            after,
            inventory,
        )
        if evaluable
        else []
    )
    failures = (
        [item["id"] for item in assertions if not item["passed"]]
        if evaluable
        else declared_assertions
    )
    harness_status = (
        "completed"
        if evaluable
        else (
            "process_failed_before_evaluator_start"
            if not session and raw_status["exit_code"] != 0
            else "process_failed"
        )
    )
    result = {
        "schema_version": "1.0",
        "approval_id": approval_id,
        "variant": variant,
        "case_id": case["id"],
        "harness_status": harness_status,
        "evaluator_exit_code": raw_status["exit_code"],
        "timed_out": raw_status["timed_out"],
        "protected_state_equal": before == after,
        "adjudication_status": "completed" if evaluable else "not_evaluable",
        "declared_assertions": declared_assertions,
        "assertions": assertions,
        "failed_assertions": failures,
        "passed": evaluable and not failures,
    }
    _write_json(retained_run / "result.json", result)
    _write_json(
        retained_run / "artifact-ledger.json",
        {
            "schema_version": "1.0",
            "raw_root_retention": "approved D:-based campaign root",
            "redaction_replacements": {
                "environment_secrets": ENVIRONMENT_SECRET_REPLACEMENT,
                "credentials": CREDENTIAL_REPLACEMENT,
                "protected_absolute_paths": USER_PROFILE_REPLACEMENT,
            },
            "files": ledger,
        },
    )
    relative = retained_run.relative_to(EVIDENCE_ROOT).as_posix()
    return {
        "approval_id": approval_id,
        "variant": variant,
        "case_id": case["id"],
        "thread_id": binding["thread_id"] if binding else None,
        "evidence_dir": relative,
        "exit_code": raw_status["exit_code"],
        "timed_out": raw_status["timed_out"],
        "evaluable": evaluable,
        "passed": evaluable and not failures,
        "failed_assertions": failures,
        "prompt_raw_sha256": raw_status["prompt_sha256"],
        "session_raw_sha256": raw_status["session_sha256"],
        "final_raw_sha256": raw_status["final_sha256"],
        "session_retained_sha256": _sha256(retained_run / "session.jsonl"),
        "final_retained_sha256": (
            _sha256(retained_run / "final.md") if evaluable else None
        ),
        "result_sha256": _sha256(retained_run / "result.json"),
        "artifact_ledger_sha256": _sha256(
            retained_run / "artifact-ledger.json"
        ),
        "agent_final_events_sha256": (
            _sha256(retained_run / "agent-final-events.jsonl") if evaluable else None
        ),
        "agent_final_session_sha256": (
            _sha256(retained_run / "agent-final-session.json") if evaluable else None
        ),
        "protected_state_sha256": _sha256(retained_run / "protected-state.json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_root", type=Path)
    args = parser.parse_args()
    raw_root = args.raw_root.resolve()
    if not raw_root.is_dir():
        raise SystemExit(f"missing approved raw root: {raw_root}")

    approval = yaml.safe_load(APPROVAL_FILE.read_text(encoding="utf-8"))
    approval_id = approval["approval"]["id"]
    retained_name = Path(
        approval["approval"]["isolation"]["retained_root"]
    ).name
    if (
        not retained_name.startswith("approved")
        or not retained_name.removeprefix("approved").isdigit()
        or not approval_id.endswith(f"-{retained_name}")
    ):
        raise SystemExit("active approval does not target its numbered evidence root")
    retained_batch = EVIDENCE_ROOT / retained_name
    retained_harness = EVIDENCE_ROOT / "harness" / retained_name
    if retained_batch.exists() or retained_harness.exists():
        raise SystemExit(f"refusing to overwrite retained approval: {approval_id}")
    cases = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    if str(raw_root) != approval["approval"]["isolation"]["raw_root"]:
        raise SystemExit("raw root is not the approval-locked root")
    expected = [
        (variant, case["id"])
        for variant in VARIANTS
        for case in cases
    ]
    completed_values = _load_json(raw_root / "completed-runs.json")
    completed = {
        (item["variant"], item["case_id"]): item for item in completed_values
    }
    if list(completed) != expected or len(completed_values) != 16:
        raise SystemExit("completed run set differs from approved run set")
    prepared = _load_json(raw_root / "prepared-manifest.json")
    if prepared["approval_id"] != approval_id:
        raise SystemExit("prepared manifest approval differs from active approval")
    if prepared["campaign_sha256"] != _sha256(APPROVAL_FILE):
        raise SystemExit("prepared manifest is not bound to the active approval")
    if prepared["case_sha256"] != _sha256(CASES_FILE):
        raise SystemExit("prepared manifest is not bound to the case matrix")
    if [(item["variant"], item["case_id"]) for item in prepared["runs"]] != expected:
        raise SystemExit("prepared manifest run set differs from approved run set")

    try:
        frozen_artifacts = _copy_frozen_inputs(approval, retained_name)
        runs = [
            _import_run(
                raw_root,
                retained_batch,
                approval_id,
                variant,
                case,
                completed,
            )
            for variant in VARIANTS
            for case in cases
        ]
        retained_batch.mkdir(parents=True, exist_ok=True)
        batch_artifacts: dict[str, str] = {}
        for name in ("prepared-manifest.json", "completed-runs.json"):
            raw = (raw_root / name).read_bytes()
            retained, redaction_count = sanitize_artifact(raw)
            if retained != raw or redaction_count:
                raise RuntimeError(f"unexpected redaction in batch artifact: {name}")
            (retained_batch / name).write_bytes(retained)
            batch_artifacts[name] = sha256_bytes(retained)
        outcomes: dict[str, dict[str, int]] = {}
        for variant in VARIANTS:
            selected = [run for run in runs if run["variant"] == variant]
            evaluable = [run for run in selected if run["evaluable"]]
            passed = sum(run["passed"] for run in evaluable)
            outcomes[variant.replace("-", "_")] = {
                "evaluable_cases": len(evaluable),
                "passed_cases": passed,
                "failed_cases": len(evaluable) - passed,
                "harness_failed_cases": len(selected) - len(evaluable),
            }
        harness_failed = sum(not run["evaluable"] for run in runs)
        stderr_hashes = {
            run["variant"] + "/" + run["case_id"]: _sha256(
                raw_root / run["variant"] / run["case_id"] / "stderr.txt"
            )
            for run in runs
        }
        unique_stderr_hashes = set(stderr_hashes.values())
        known_option_failure = (
            harness_failed == 16
            and {run["exit_code"] for run in runs} == {2}
            and len(unique_stderr_hashes) == 1
            and b"cannot be used with '--approve-for-me'"
            in (
                raw_root
                / runs[0]["variant"]
                / runs[0]["case_id"]
                / "stderr.txt"
            ).read_bytes()
        )
        if harness_failed and not known_option_failure:
            raise RuntimeError("unclassified evaluator harness failure")
        failure = (
            {
                "kind": "mutually_exclusive_cli_options",
                "exit_code": 2,
                "stderr_sha256": next(iter(unique_stderr_hashes)),
                "detail": (
                    "codex-cli rejected --sandbox workspace-write combined with "
                    "--approve-for-me before evaluator startup"
                ),
            }
            if known_option_failure
            else None
        )
        campaign = {
            "schema_version": "1.0",
            "status": (
                "completed_harness_failure"
                if harness_failed
                else (
                    "completed_with_skill_failures"
                    if outcomes["skill_enabled"]["failed_cases"]
                    else "completed_skill_passed"
                )
            ),
            "approval": approval["approval"],
            "approval_response_sha256": sha256(b"approve").hexdigest(),
            "frozen_inputs": approval["frozen_inputs"],
            "frozen_artifacts": frozen_artifacts,
            "batch_artifacts": batch_artifacts,
            "run_counts": {
                "baseline": 8,
                "skill_enabled": 8,
                "corrective": 0,
                "zero_exit": sum(run["exit_code"] == 0 for run in runs),
                "timed_out": sum(run["timed_out"] for run in runs),
                "harness_failed": harness_failed,
            },
            "outcomes": outcomes,
            "deviations": [
                "process_ids_not_captured",
                *(
                    ["mutually_exclusive_sandbox_and_automatic_review_flags"]
                    if known_option_failure
                    else []
                ),
            ],
            "failure": failure,
            "retention": approval["approval"]["retention"],
            "runs": runs,
        }
        campaign_text = yaml.safe_dump(
            campaign,
            sort_keys=False,
            allow_unicode=True,
        )
        (retained_batch / "campaign.yaml").write_text(
            campaign_text,
            encoding="utf-8",
            newline="\n",
        )
    except Exception:
        if retained_batch.exists():
            shutil.rmtree(retained_batch)
        if retained_harness.exists():
            shutil.rmtree(retained_harness)
        raise

    print(
        f"IMPORTED RUNS={len(runs)} "
        f"ZERO_EXIT={sum(run['exit_code'] == 0 for run in runs)} "
        f"HARNESS_FAILED={harness_failed}"
    )


if __name__ == "__main__":
    main()
