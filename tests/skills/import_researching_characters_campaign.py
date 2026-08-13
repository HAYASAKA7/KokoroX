from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from researching_characters_adjudication import adjudicate_assertions
from researching_characters_sanitization import (
    CREDENTIAL_REPLACEMENT,
    ENVIRONMENT_SECRET_REPLACEMENT,
    USER_PROFILE_REPLACEMENT as REDACTION_REPLACEMENT,
    sanitize_sensitive_bytes,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CASES_FILE = HERE / "researching-characters-cases.yaml"
SKILL_DIR = ROOT / "skills" / "researching-characters"
DESTINATION = HERE / "evidence" / "researching-characters"
PROTECTED_ROOTS = (
    "drafts",
    "compiled",
    "installed",
    "public",
    "sessions",
    "state",
    "events",
    "workspaces",
    "config",
)
THREAD_IDS = {
    "baseline": {
        "ambiguous-character-stop": "/root/m7_b01_ambiguous",
        "continuity-conflict-clarification": "/root/m7_b02_continuity",
        "spoiler-cutoff": "/root/m7_b03_spoiler",
        "partial-unavailable-source": "/root/m7_b04_partial",
        "source-prompt-injection": "/root/m7_b05_injection",
        "invented-citation-pressure": "/root/m7_b06_citation",
        "canonical-trait-score-pressure": "/root/m7_b07_trait",
        "eligible-researched-handoff": "/root/m7_b08_researched",
        "eligible-hybrid-handoff": "/root/m7_b09_hybrid",
        "casual-discussion-non-trigger": "/root/m7_b10_casual",
        "original-character-non-trigger": "/root/m7_b11_original",
    },
    "skill-enabled": {
        "ambiguous-character-stop": "/root/m7_s01_ambiguous",
        "continuity-conflict-clarification": "/root/m7_s02_continuity",
        "spoiler-cutoff": "/root/m7_s03_spoiler",
        "partial-unavailable-source": "/root/m7_s04_partial",
        "source-prompt-injection": "/root/m7_s05_injection",
        "invented-citation-pressure": "/root/m7_s06_citation",
        "canonical-trait-score-pressure": "/root/m7_s07_trait",
        "eligible-researched-handoff": "/root/m7_s08_researched",
        "eligible-hybrid-handoff": "/root/m7_s09_hybrid",
        "casual-discussion-non-trigger": "/root/m7_s10_casual",
        "original-character-non-trigger": "/root/m7_s11_original",
    },
}
DETERMINISM_PAIRS = {
    "spoiler-cutoff": (
        ("001-request-validate.stdout.txt", "002-request-validate.stdout.txt"),
        ("003-workspace-validate.stdout.txt", "004-workspace-validate.stdout.txt"),
        ("006-bundle-validate.stdout.txt", "007-bundle-validate.stdout.txt"),
    ),
    "partial-unavailable-source": (
        ("03-request-validate.stdout.json", "04-request-validate.stdout.json"),
        ("05-workspace-validate.stdout.json", "06-workspace-validate.stdout.json"),
        ("08-bundle-validate.stdout.json", "09-bundle-validate.stdout.json"),
    ),
    "source-prompt-injection": (
        ("request-validate-1.stdout.json", "request-validate-2.stdout.json"),
        ("workspace-validate-1.stdout.json", "workspace-validate-2.stdout.json"),
        ("bundle-validate-1.stdout.json", "bundle-validate-2.stdout.json"),
    ),
    "invented-citation-pressure": (
        ("request-validate-1.stdout.json", "request-validate-2.stdout.json"),
        ("workspace-validate-1.stdout.json", "workspace-validate-2.stdout.json"),
        ("bundle-validate-1.stdout.json", "bundle-validate-2.stdout.json"),
    ),
    "canonical-trait-score-pressure": (
        ("request-validate-1.stdout.txt", "request-validate-2.stdout.txt"),
        ("workspace-validate-2.stdout.txt", "workspace-validate-3.stdout.txt"),
        ("bundle-validate-1.stdout.txt", "bundle-validate-2.stdout.txt"),
    ),
    "eligible-researched-handoff": (
        ("request-validation-1.stdout.json", "request-validation-2.stdout.json"),
        ("workspace-validation-1.stdout.json", "workspace-validation-2.stdout.json"),
        ("bundle-validation-1.stdout.json", "bundle-validation-2.stdout.json"),
    ),
    "eligible-hybrid-handoff": (
        ("request-validate-1.stdout.json", "request-validate-2.stdout.json"),
        ("workspace-validate-1.stdout.json", "workspace-validate-2.stdout.json"),
        ("bundle-validate-1.stdout.json", "bundle-validate-2.stdout.json"),
    ),
}
APPROVED_SKILL_SHA256 = "33b1bf3b8c98a97282295bffe7ebe474d5ee43687378ff29e48dcabac2239876"
APPROVED_CONTRACT_SHA256 = "9e4f2abc63a29bf75f4291d5db657b2908a75c00e8830f69a027cc1eed73b313"
APPROVED_METADATA_SHA256 = "093eb44756a018c1a8ffe856f4237e31d161e936aeeaf1df2a452b3146785c3e"
REDACTION_REPLACEMENTS = {
    "environment_secrets": ENVIRONMENT_SECRET_REPLACEMENT,
    "credentials": CREDENTIAL_REPLACEMENT,
    "protected_absolute_paths": REDACTION_REPLACEMENT,
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def sanitize(raw: bytes) -> tuple[bytes, int]:
    return sanitize_sensitive_bytes(raw)


def retained_copy(source: Path, destination: Path, allow_redaction: bool) -> dict:
    raw = source.read_bytes()
    retained, redaction_count = sanitize(raw)
    if redaction_count and not allow_redaction:
        raise RuntimeError(f"final response unexpectedly needs redaction: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(retained)
    return {
        "path": destination.name if destination.parent.name != "captures" else f"captures/{destination.name}",
        "raw_sha256": sha256_bytes(raw),
        "retained_sha256": sha256_bytes(retained),
        "redaction_count": redaction_count,
    }


def prompt_text(approval_id: str, variant: str, case: dict) -> str:
    return (
        "# Retained evaluator case prompt\n\n"
        f"- Approval: `{approval_id}`\n"
        f"- Case: `{case['id']}`\n"
        f"- Variant: `{variant}`\n"
        "- Forked conversation context: `none`\n\n"
        "## Setup\n\n"
        f"{case['setup']}\n\n"
        "## User prompt\n\n"
        f"{case['prompt']}\n\n"
        "## Capture boundary\n\n"
        "This file preserves the declared setup and user prompt verbatim from the "
        "pre-registered case file. Harness control instructions are represented by "
        "the approval and run metadata, not rewritten as user content.\n"
    )


def normalized_variant(value: str) -> str:
    if value == "baseline":
        return value
    if value.casefold() in {"skill", "skill-enabled"}:
        return "skill-enabled"
    raise RuntimeError(f"unknown raw report variant: {value!r}")


def import_run(
    source_root: Path,
    approval_root: Path,
    approval_id: str,
    source_variant: str,
    variant: str,
    case: dict,
) -> dict:
    source = source_root / source_variant / case["id"]
    destination = approval_root / variant / case["id"]
    destination.mkdir(parents=True)

    ledger = []
    ledger.append(retained_copy(source / "final.md", destination / "final.md", False))
    ledger.append(
        retained_copy(source / "agent-report.json", destination / "agent-report.json", True)
    )
    captures = source / "captures"
    for capture in sorted(captures.glob("*")):
        if not capture.is_file():
            raise RuntimeError(f"unexpected non-file capture: {capture}")
        ledger.append(
            retained_copy(capture, destination / "captures" / capture.name, True)
        )

    report = json.loads((destination / "agent-report.json").read_text(encoding="utf-8"))
    if report["case_id"] != case["id"]:
        raise RuntimeError(f"case mismatch in {source / 'agent-report.json'}")
    if normalized_variant(report["variant"]) != variant:
        raise RuntimeError(f"variant mismatch in {source / 'agent-report.json'}")
    if report["final_file"] != "final.md":
        raise RuntimeError(f"unexpected final file in {source / 'agent-report.json'}")

    (destination / "prompt.md").write_text(
        prompt_text(approval_id, variant, case), encoding="utf-8"
    )
    before = {name: "absent" for name in PROTECTED_ROOTS}
    after = {
        name: "present" if (source / "run-data" / name).exists() else "absent"
        for name in PROTECTED_ROOTS
    }
    state = {
        "schema_version": "1.0",
        "before_capture": "fresh isolated harness root declaration",
        "after_capture": "post-run filesystem observation",
        "before": before,
        "after": after,
        "note": "Harness evidence, not an independent attestation.",
    }
    write_json(destination / "protected-state.json", state)

    pairs = []
    if variant == "skill-enabled" and case["id"] in DETERMINISM_PAIRS:
        pairs = [
            [f"captures/{left}", f"captures/{right}"]
            for left, right in DETERMINISM_PAIRS[case["id"]]
        ]
    outcomes = adjudicate_assertions(case, destination, pairs)

    result = {
        "schema_version": "1.0",
        "approval_id": approval_id,
        "case_id": case["id"],
        "variant": variant,
        "raw_report_variant": report["variant"],
        "harness_status": "completed",
        "newline_normalization": "lf_and_strip_terminal_lf",
        "assertions": outcomes,
        "protected_state_before": before,
        "protected_state_after": after,
    }
    write_json(destination / "result.json", result)
    write_json(
        destination / "artifact-ledger.json",
        {
            "schema_version": "1.0",
            "raw_root_retention": "approved D:-based campaign root",
            "redaction_replacements": REDACTION_REPLACEMENTS,
            "files": ledger,
        },
    )

    relative = destination.relative_to(DESTINATION).as_posix()
    return {
        "approval_id": approval_id,
        "variant": variant,
        "case_id": case["id"],
        "thread_id": THREAD_IDS[variant][case["id"]],
        "fork_context": "none",
        "evidence_dir": relative,
        "raw_report_variant": report["variant"],
        "prompt_sha256": sha256_file(destination / "prompt.md"),
        "final_sha256": sha256_file(destination / "final.md"),
        "agent_report_sha256": sha256_file(destination / "agent-report.json"),
        "result_sha256": sha256_file(destination / "result.json"),
        "protected_state_sha256": sha256_file(destination / "protected-state.json"),
        "artifact_ledger_sha256": sha256_file(destination / "artifact-ledger.json"),
        "determinism_pairs": pairs,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--approval-id", default="2026-08-13-approved1")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    if DESTINATION.exists():
        raise SystemExit(f"refusing to overwrite existing evidence root: {DESTINATION}")
    if not source_root.is_dir():
        raise SystemExit(f"missing source campaign root: {source_root}")

    cases = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    approval_root = DESTINATION / "approved1"
    runs = []
    for source_variant, variant in (
        ("baseline", "baseline"),
        ("skill", "skill-enabled"),
    ):
        for case in cases:
            runs.append(
                import_run(
                    source_root,
                    approval_root,
                    args.approval_id,
                    source_variant,
                    variant,
                    case,
                )
            )

    current_skill = sha256_file(SKILL_DIR / "SKILL.md")
    skill_runs = [run for run in runs if run["variant"] == "skill-enabled"]
    failed_assertions = []
    skill_passed_cases = 0
    for run in skill_runs:
        result = json.loads(
            (DESTINATION / run["evidence_dir"] / "result.json").read_text(
                encoding="utf-8"
            )
        )
        failures = [item["id"] for item in result["assertions"] if not item["passed"]]
        if failures:
            failed_assertions.extend(
                {"case_id": run["case_id"], "id": assertion}
                for assertion in failures
            )
        else:
            skill_passed_cases += 1
    skill_failed_cases = len(skill_runs) - skill_passed_cases
    approval_status = "skill_failed" if failed_assertions else "skill_passed"
    campaign = {
        "schema_version": "1.0",
        "campaign_status": "corrective_rerun_required",
        "current_skill_status": "awaiting_exact_approval_and_fresh_skill_runs",
        "current_skill_sha256": current_skill,
        "latest_verified_skill_approval": None,
        "retained_fields": [
            "prompt",
            "agent_final",
            "agent_report",
            "command_stdout",
            "command_stderr",
            "protected_state",
            "assertion_results",
        ],
        "redactions": [
            "environment_secrets",
            "credentials",
            "protected_absolute_paths",
        ],
        "approvals": [
            {
                "id": args.approval_id,
                "provider": "openai",
                "model": "inherited-codex",
                "baseline_runs": sum(run["variant"] == "baseline" for run in runs),
                "skill_runs": len(skill_runs),
                "corrective_reruns": 0,
                "fork_context": "none",
                "raw_capture_root": str(source_root),
                "skill_sha256": APPROVED_SKILL_SHA256,
                "contract_sha256": APPROVED_CONTRACT_SHA256,
                "metadata_sha256": APPROVED_METADATA_SHA256,
                "status": approval_status,
                "skill_passed_cases": skill_passed_cases,
                "skill_failed_cases": skill_failed_cases,
                "failed_assertions": failed_assertions,
                "disclosed_inputs": [
                    "pre-registered case setup and user prompt",
                    "isolated README.md copy",
                    "isolated case fixture workspace where applicable",
                    "researching-characters Skill, contract, and metadata for target Skill runs",
                    "authoring-character-packs Skill inputs only for eligible handoff and original-character routing",
                    "repository product CLI source on PYTHONPATH for execution without general source inspection",
                ],
            }
        ],
        "runs": runs,
    }
    DESTINATION.mkdir(parents=True, exist_ok=True)
    (DESTINATION / "campaign.yaml").write_text(
        yaml.safe_dump(campaign, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
