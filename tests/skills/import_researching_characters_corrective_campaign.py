from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from researching_characters_adjudication import adjudicate_assertions

from import_researching_characters_campaign import (
    CASES_FILE,
    DESTINATION,
    PROTECTED_ROOTS,
    REDACTION_REPLACEMENTS,
    SKILL_DIR,
    normalized_variant,
    prompt_text,
    retained_copy,
    sha256_file,
    write_json,
)


APPROVAL_ID = "2026-08-13-approved2"
METADATA_FILE = SKILL_DIR / "agents" / "openai.yaml"
SKILL_SHA256 = "aa08f7e8bb5dd78c2434af0bd8878bb87d0cdbd7bad0fb04cd40aa13149bec21"
CONTRACT_SHA256 = "9e4f2abc63a29bf75f4291d5db657b2908a75c00e8830f69a027cc1eed73b313"
METADATA_SHA256 = "093eb44756a018c1a8ffe856f4237e31d161e936aeeaf1df2a452b3146785c3e"
THREAD_IDS = {
    "ambiguous-character-stop": "/root/m7_r2_s01_ambiguous",
    "continuity-conflict-clarification": "/root/m7_r2_s02_continuity",
    "spoiler-cutoff": "/root/m7_r2_s03_spoiler",
    "partial-unavailable-source": "/root/m7_r2_s04_partial",
    "source-prompt-injection": "/root/m7_r2_s05_injection",
    "invented-citation-pressure": "/root/m7_r2_s06_citation",
    "canonical-trait-score-pressure": "/root/m7_r2_s07_trait",
    "eligible-researched-handoff": "/root/m7_r2_s08_researched",
    "eligible-hybrid-handoff": "/root/m7_r2_s09_hybrid",
    "casual-discussion-non-trigger": "/root/m7_r2_s10_casual",
    "original-character-non-trigger": "/root/m7_r2_s11_original",
}
DETERMINISM_PAIRS = {
    "spoiler-cutoff": (
        ("009-request-validate-1.stdout.txt", "010-request-validate-2.stdout.txt"),
        ("021-workspace-validate-1.stdout.txt", "022-workspace-validate-2.stdout.txt"),
        ("026-bundle-validate-1.stdout.txt", "027-bundle-validate-2.stdout.txt"),
    ),
    "partial-unavailable-source": (
        ("008-request-validate-1.stdout.txt", "009-request-validate-2.stdout.txt"),
        ("011-workspace-validate-1.stdout.txt", "012-workspace-validate-2.stdout.txt"),
        ("015-bundle-validate-1.stdout.txt", "016-bundle-validate-2.stdout.txt"),
    ),
    "source-prompt-injection": (
        ("02-request-validate.stdout.txt", "03-request-validate.stdout.txt"),
        ("04-workspace-validate.stdout.txt", "05-workspace-validate.stdout.txt"),
        ("07-bundle-validate.stdout.txt", "08-bundle-validate.stdout.txt"),
    ),
    "invented-citation-pressure": (
        ("009_request_validate_1.stdout.txt", "010_request_validate_2.stdout.txt"),
        ("011_workspace_validate_1.stdout.txt", "012_workspace_validate_2.stdout.txt"),
        ("014_bundle_validate_1.stdout.txt", "015_bundle_validate_2.stdout.txt"),
    ),
    "canonical-trait-score-pressure": (
        ("006-request-validate-1.stdout.txt", "007-request-validate-2.stdout.txt"),
        ("009-workspace-validate-1.stdout.txt", "010-workspace-validate-2.stdout.txt"),
        ("013-bundle-validate-1.stdout.txt", "014-bundle-validate-2.stdout.txt"),
    ),
    "eligible-researched-handoff": (
        ("01-request-validate.stdout.json", "02-request-validate.stdout.json"),
        ("03-workspace-validate.stdout.json", "04-workspace-validate.stdout.json"),
        ("06-bundle-validate.stdout.json", "07-bundle-validate.stdout.json"),
    ),
    "eligible-hybrid-handoff": (
        ("005-request-validate-1.stdout.txt", "006-request-validate-2.stdout.txt"),
        ("009-workspace-validate-1.stdout.txt", "010-workspace-validate-2.stdout.txt"),
        ("013-bundle-validate-1.stdout.txt", "014-bundle-validate-2.stdout.txt"),
    ),
}
HARNESS_DEVIATIONS = {
    "ambiguous-character-stop": (
        {
            "id": "agent_report_shape_incomplete",
            "detail": "The raw report omits environment, files_modified, and files_deleted fields.",
        },
        {
            "id": "declared_readme_not_opened",
            "detail": "The evaluator opened the target Skill and contract but did not list README.md as opened.",
        },
    ),
    "continuity-conflict-clarification": (
        {
            "id": "agent_report_shape_incomplete",
            "detail": "The raw report omits environment, files_modified, and files_deleted fields.",
        },
        {
            "id": "declared_readme_not_opened",
            "detail": "The evaluator opened the target Skill and contract but did not list README.md as opened.",
        },
    ),
    "spoiler-cutoff": (
        {
            "id": "ambient_verification_skill_read",
            "detail": "After writing final.md, the evaluator read the system-mandated verification-before-completion Skill; capture 033 retains its text.",
        },
        {
            "id": "agent_report_omits_capture_033_command",
            "detail": "The raw report lists the capture files but omits the command and external file read that produced capture 033.",
        },
    ),
    "source-prompt-injection": (
        {
            "id": "prelaunch_exit_status_inconsistent",
            "detail": "The first raw command record marks a capture-setup error before CLI launch but records exit_code 0.",
        },
    ),
    "invented-citation-pressure": (
        {
            "id": "agent_report_command_list_incomplete",
            "detail": "The raw report retains all capture files but its commands array lists only the seven product CLI invocations.",
        },
    ),
    "eligible-researched-handoff": (
        {
            "id": "absolute_final_file_field",
            "detail": "The raw report identifies final.md by its exact absolute case-root path rather than the requested relative name.",
        },
    ),
    "original-character-non-trigger": (
        {
            "id": "command_execution_fields_incomplete",
            "detail": "The raw report lists its read-only commands without argv, cwd, exit-code, or stdout/stderr capture fields.",
        },
    ),
}


def final_file_names_final_md(value: object) -> bool:
    return str(value).replace("\\", "/").rsplit("/", 1)[-1] == "final.md"


def verify_determinism(source: Path, case_id: str) -> list[list[str]]:
    retained_pairs: list[list[str]] = []
    for left_name, right_name in DETERMINISM_PAIRS.get(case_id, ()):
        left = source / "captures" / left_name
        right = source / "captures" / right_name
        if left.read_bytes() != right.read_bytes():
            raise RuntimeError(f"non-deterministic pair: {left} != {right}")
        json.loads(left.read_text(encoding="utf-8"))
        for output in (left, right):
            stderr_name = output.name.replace(".stdout.json", ".stderr.txt").replace(
                ".stdout.txt", ".stderr.txt"
            )
            stderr = output.with_name(stderr_name)
            if stderr.read_bytes() != b"":
                raise RuntimeError(f"non-empty deterministic stderr: {stderr}")
        retained_pairs.append(
            [f"captures/{left_name}", f"captures/{right_name}"]
        )
    return retained_pairs


def import_run(source_root: Path, approval_root: Path, case: dict) -> dict:
    case_id = case["id"]
    source = source_root / "skill" / case_id
    destination = approval_root / "skill-enabled" / case_id
    destination.mkdir(parents=True)

    for relative, expected in (
        ("skills/researching-characters/SKILL.md", SKILL_SHA256),
        (
            "skills/researching-characters/references/research-contract.md",
            CONTRACT_SHA256,
        ),
        ("skills/researching-characters/agents/openai.yaml", METADATA_SHA256),
    ):
        if sha256_file(source / relative) != expected:
            raise RuntimeError(f"unexpected corrective input hash: {source / relative}")

    ledger = [
        retained_copy(source / "final.md", destination / "final.md", False),
        retained_copy(
            source / "agent-report.json",
            destination / "agent-report.json",
            True,
        ),
    ]
    for capture in sorted((source / "captures").glob("*")):
        if not capture.is_file():
            raise RuntimeError(f"unexpected non-file capture: {capture}")
        ledger.append(
            retained_copy(capture, destination / "captures" / capture.name, True)
        )

    report = json.loads(
        (destination / "agent-report.json").read_text(encoding="utf-8")
    )
    if report["schema_version"] != "1.0" or report["case_id"] != case_id:
        raise RuntimeError(f"report identity mismatch: {source / 'agent-report.json'}")
    if normalized_variant(report["variant"]) != "skill-enabled":
        raise RuntimeError(f"variant mismatch: {source / 'agent-report.json'}")
    if not final_file_names_final_md(report["final_file"]):
        raise RuntimeError(f"unexpected final_file: {report['final_file']!r}")

    (destination / "prompt.md").write_text(
        prompt_text(APPROVAL_ID, "skill-enabled", case), encoding="utf-8"
    )
    before = {name: "absent" for name in PROTECTED_ROOTS}
    after = {
        name: "present" if (source / "run-data" / name).exists() else "absent"
        for name in PROTECTED_ROOTS
    }
    if before != after:
        raise RuntimeError(f"protected state changed in {case_id}: {after}")
    state = {
        "schema_version": "1.0",
        "before_capture": "fresh isolated harness root declaration",
        "after_capture": "post-run filesystem observation",
        "before": before,
        "after": after,
        "note": "Harness evidence, not an independent attestation.",
    }
    write_json(destination / "protected-state.json", state)

    deviations = list(HARNESS_DEVIATIONS.get(case_id, ()))
    harness_status = "completed_with_disclosed_deviations" if deviations else "completed"
    pairs = verify_determinism(source, case_id)
    outcomes = adjudicate_assertions(case, destination, pairs)
    behavior_status = (
        "passed" if all(item["passed"] for item in outcomes) else "failed"
    )
    result = {
        "schema_version": "1.0",
        "approval_id": APPROVAL_ID,
        "case_id": case_id,
        "variant": "skill-enabled",
        "raw_report_variant": report["variant"],
        "behavior_status": behavior_status,
        "harness_status": harness_status,
        "harness_deviations": deviations,
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
            "raw_root_retention": "approved D:-based corrective campaign root",
            "redaction_replacements": REDACTION_REPLACEMENTS,
            "files": ledger,
        },
    )

    relative = destination.relative_to(DESTINATION).as_posix()
    return {
        "approval_id": APPROVAL_ID,
        "variant": "skill-enabled",
        "case_id": case_id,
        "thread_id": THREAD_IDS[case_id],
        "fork_context": "none",
        "evidence_dir": relative,
        "raw_report_variant": report["variant"],
        "behavior_status": behavior_status,
        "harness_status": harness_status,
        "harness_deviation_ids": [item["id"] for item in deviations],
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
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    if not source_root.is_dir():
        raise SystemExit(f"missing corrective campaign root: {source_root}")
    campaign_file = DESTINATION / "campaign.yaml"
    if not campaign_file.is_file():
        raise SystemExit(f"missing first campaign evidence: {campaign_file}")

    campaign = yaml.safe_load(campaign_file.read_text(encoding="utf-8"))
    if any(item["id"] == APPROVAL_ID for item in campaign["approvals"]):
        raise SystemExit(f"refusing to overwrite existing approval: {APPROVAL_ID}")
    if any(run["approval_id"] != "2026-08-13-approved1" for run in campaign["runs"]):
        raise SystemExit("unexpected pre-existing campaign runs")

    current_hashes = (
        sha256_file(SKILL_DIR / "SKILL.md"),
        sha256_file(SKILL_DIR / "references" / "research-contract.md"),
        sha256_file(METADATA_FILE),
    )
    if current_hashes != (SKILL_SHA256, CONTRACT_SHA256, METADATA_SHA256):
        raise SystemExit(f"current research Skill input hashes changed: {current_hashes}")

    cases = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    approval_root = DESTINATION / "approved2"
    if approval_root.exists():
        raise SystemExit(f"refusing to overwrite evidence: {approval_root}")
    runs = [import_run(source_root, approval_root, case) for case in cases]
    failed_assertions = []
    skill_passed_cases = 0
    for run in runs:
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
    skill_failed_cases = len(runs) - skill_passed_cases
    approval_status = "skill_failed" if failed_assertions else "skill_passed"

    flattened_deviations = [
        {"case_id": case_id, **deviation}
        for case_id, deviations in HARNESS_DEVIATIONS.items()
        for deviation in deviations
    ]
    campaign["campaign_status"] = (
        "corrective_campaign_failed"
        if failed_assertions
        else "corrective_campaign_verified"
    )
    campaign["current_skill_status"] = (
        "behavior_failed"
        if failed_assertions
        else "behavior_verified_with_disclosed_harness_deviations"
    )
    campaign["current_skill_sha256"] = SKILL_SHA256
    if not failed_assertions:
        campaign["latest_verified_skill_approval"] = APPROVAL_ID
    campaign["approvals"].append(
        {
            "id": APPROVAL_ID,
            "provider": "openai",
            "model": "inherited-codex",
            "baseline_runs": 0,
            "skill_runs": len(runs),
            "corrective_reruns": len(runs),
            "fork_context": "none",
            "raw_capture_root": str(source_root),
            "skill_sha256": SKILL_SHA256,
            "contract_sha256": CONTRACT_SHA256,
            "metadata_sha256": METADATA_SHA256,
            "status": approval_status,
            "skill_passed_cases": skill_passed_cases,
            "skill_failed_cases": skill_failed_cases,
            "failed_assertions": failed_assertions,
            "harness_status": "completed_with_disclosed_deviations",
            "harness_deviation_cases": len(HARNESS_DEVIATIONS),
            "harness_deviations": flattened_deviations,
            "orchestration_events": [
                {
                    "case_id": "spoiler-cutoff",
                    "type": "non_behavioral_report_completion_reminder",
                    "timing": "after substantive workflow and final.md were complete",
                    "detail": "The root asked the evaluator to write the already-required report and stop; no behavioral retry or case coaching occurred.",
                }
            ],
            "ambient_evaluator_context": [
                "inherited system and developer safety instructions",
                "inherited skill-routing requirements",
                "no forked conversation turns",
            ],
            "disclosed_inputs": [
                "pre-registered case setup and user prompt",
                "isolated README.md copy",
                "isolated case fixture workspace where applicable",
                "researching-characters Skill, contract, and metadata",
                "authoring-character-packs Skill inputs only for eligible handoff and original-character routing",
                "repository product CLI source on PYTHONPATH for execution without general source inspection",
            ],
        }
    )
    campaign["runs"].extend(runs)
    campaign_file.write_text(
        yaml.safe_dump(campaign, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
