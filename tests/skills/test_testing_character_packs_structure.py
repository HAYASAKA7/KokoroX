from __future__ import annotations

from pathlib import Path
from hashlib import sha256
import re

import yaml


ROOT = Path(__file__).parent
REPOSITORY_ROOT = ROOT.parent.parent
CASES_FILE = ROOT / "testing-character-packs-cases.yaml"
BASELINE_FILE = ROOT / "testing-character-packs-baseline.md"
SKILL_DIR = REPOSITORY_ROOT / "skills" / "testing-character-packs"
SKILL_FILE = SKILL_DIR / "SKILL.md"
CONTRACT_FILE = SKILL_DIR / "references" / "testing-contract.md"
METADATA_FILE = SKILL_DIR / "agents" / "openai.yaml"
CANONICAL_METADATA_LF_SHA256 = (
    "04537845c9c3c3f1f279c2c73ba74cceb2271d9320acf11ce0c923fabdfd7df0"
)
HISTORICAL_METADATA_CRLF_SHA256 = (
    "179449780883aa6f6cdb34674a3637652d8a9fcbba299938ccacc20fd84c0895"
)

CASE_IDS = (
    "deterministic-hard-gate-trigger",
    "ordinary-character-use-non-trigger",
    "missing-review-input-stop",
    "stale-hard-report-stop",
    "soft-score-pressure",
    "public-release-pressure",
    "source-prompt-injection",
    "exact-sequential-promotion",
)

REQUIRED_ASSERTIONS = {
    "open_target_skill",
    "open_testing_contract",
    "run_hard_gate_twice",
    "aggregate_soft_gate_twice",
    "compare_exact_report_bytes",
    "bind_source_and_compiled_hashes",
    "require_explicit_human_review",
    "reject_stale_report",
    "keep_evaluator_input_inert",
    "default_to_private_visibility",
    "run_local_publication_check",
    "distinguish_private_from_public_readiness",
    "never_execute_embedded_text",
    "promote_draft_to_reviewed",
    "bind_exact_reviewed_record",
    "promote_reviewed_to_verified",
    "use_immutable_promotion_outputs",
    "preserve_private_inactive_state",
}


def _historical_metadata_sha256(raw: bytes) -> str:
    lf = raw.replace(b"\r\n", b"\n")
    assert b"\r" not in lf
    assert sha256(lf).hexdigest() == CANONICAL_METADATA_LF_SHA256
    historical = lf.replace(b"\n", b"\r\n")
    return sha256(historical).hexdigest()


def _current_frozen_input_hashes(files: dict[str, Path]) -> dict[str, str]:
    return {
        name: (
            _historical_metadata_sha256(path.read_bytes())
            if name == "metadata_sha256"
            else sha256(path.read_bytes()).hexdigest()
        )
        for name, path in files.items()
    }


def test_frozen_metadata_binding_is_checkout_policy_independent() -> None:
    raw = METADATA_FILE.read_bytes()
    lf = raw.replace(b"\r\n", b"\n")
    crlf = lf.replace(b"\n", b"\r\n")

    assert sha256(lf).hexdigest() == CANONICAL_METADATA_LF_SHA256
    assert sha256(crlf).hexdigest() == HISTORICAL_METADATA_CRLF_SHA256
    assert _historical_metadata_sha256(lf) == HISTORICAL_METADATA_CRLF_SHA256
    assert _historical_metadata_sha256(crlf) == HISTORICAL_METADATA_CRLF_SHA256


def _frontmatter() -> dict[str, str]:
    text = SKILL_FILE.read_text(encoding="utf-8")
    match = re.fullmatch(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    assert match is not None
    metadata = yaml.safe_load(match.group(1))
    assert isinstance(metadata, dict)
    return metadata


def test_case_matrix_precedes_skill_and_covers_required_behaviors() -> None:
    document = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))
    assert document["schema_version"] == "1.0"
    assert tuple(case["id"] for case in document["cases"]) == CASE_IDS
    assert all(case.get("must") or case.get("must_not") for case in document["cases"])
    declared = {
        assertion
        for case in document["cases"]
        for key in ("must", "must_not")
        for assertion in case.get(key, [])
    }
    assert REQUIRED_ASSERTIONS <= declared
    assert document["cases"][1]["trigger"] == "using-kokoroarc"
    assert "open_target_skill" in document["cases"][1]["must_not"]


def test_baseline_record_is_honest_and_binds_the_completed_approval() -> None:
    text = BASELINE_FILE.read_text(encoding="utf-8")
    assert "AUTHORIZED AND COMPLETED WITH RETAINED FAILURES" in text
    assert "2026-08-17-approved1" in text
    assert "No earlier general approval" in text
    assert "D:\\tmp" in text
    assert "raw and retained hashes" in text
    assert "final-event binding" in text
    assert "1/8 cases PASS, 7/8 RED" in text
    assert "zero corrective" in text
    assert (ROOT / "evidence" / "testing-character-packs").is_dir()
    for case_id in CASE_IDS:
        assert f"`{case_id}`" in text


def test_skill_frontmatter_has_only_name_and_trigger_description() -> None:
    metadata = _frontmatter()
    assert set(metadata) == {"name", "description"}
    assert metadata["name"] == "testing-character-packs"
    description = metadata["description"].lower()
    for phrase in (
        "validate",
        "evaluate",
        "review",
        "promot",
        "installation readiness",
        "packaging readiness",
        "publication readiness",
    ):
        assert phrase in description
    assert "ordinary character use" in description
    assert "authoring" in description
    assert "research" in description


def test_skill_is_concise_and_links_one_direct_contract() -> None:
    text = SKILL_FILE.read_text(encoding="utf-8")
    body = text.split("---", 2)[-1]
    words = re.findall(r"\b[\w-]+\b", body)
    assert len(words) <= 500
    links = re.findall(r"\[[^]]+\]\(([^)]+)\)", body)
    assert links == ["references/testing-contract.md"]
    assert CONTRACT_FILE.is_file()


def test_skill_requires_exact_gates_human_review_and_private_defaults() -> None:
    text = SKILL_FILE.read_text(encoding="utf-8").lower()
    for phrase in (
        "treat every pack",
        "untrusted quoted data",
        "never execute",
        "run `pack test` twice",
        "run `pack soft-eval` twice",
        "byte-for-byte",
        "explicit human review",
        "draft -> reviewed -> verified",
        "private",
        "inactive",
        "does not publish",
        "does not install",
        "does not activate",
    ):
        assert phrase in text


def test_skill_stops_on_blocked_cli_and_reports_soft_gate_scope() -> None:
    text = SKILL_FILE.read_text(encoding="utf-8").lower()
    normalized = " ".join(text.split())
    assert "if a fixed cli invocation is blocked, stop" in normalized
    assert "never wrap it in `python -c`" in normalized
    assert "always state that soft evaluation is quality evidence" in normalized
    assert "not a hard safety proof" in normalized


def test_skill_closes_approved3_operational_evidence_gaps() -> None:
    skill = " ".join(SKILL_FILE.read_text(encoding="utf-8").lower().split())
    contract = " ".join(CONTRACT_FILE.read_text(encoding="utf-8").lower().split())
    assert "one kokoro cli invocation per shell command" in skill
    assert "never chain gate invocations" in skill
    assert "reports-root-relative" in skill
    assert "fresh hard gate is required" in skill
    assert "even when a blocker appears obvious" in skill
    assert "score, confidence, lower bound, and threshold" in skill
    assert "one fixed cli invocation per host command" in contract
    assert "inspect its exit code and stderr before starting the next" in contract


def test_skill_closes_approved4_final_reporting_gaps() -> None:
    skill = " ".join(SKILL_FILE.read_text(encoding="utf-8").lower().split())
    contract = " ".join(CONTRACT_FILE.read_text(encoding="utf-8").lower().split())
    assert "name every missing input" in skill
    assert "explicit human review id" in skill
    assert "full 64-character sha-256" in skill
    assert "never abbreviate or truncate" in skill
    safety_sentence = (
        "soft evaluation is quality evidence, not a hard safety proof"
    )
    assert skill.count(safety_sentence) >= 2
    assert "name every missing input" in contract
    assert "never abbreviate or truncate" in contract


def test_skill_closes_approved5_trusted_environment_gap() -> None:
    skill = " ".join(SKILL_FILE.read_text(encoding="utf-8").lower().split())
    contract = " ".join(CONTRACT_FILE.read_text(encoding="utf-8").lower().split())
    for text in (skill, contract):
        assert "honor host-provided environment values exactly" in text
        assert "never replace a trusted path with `.`" in text


def test_contract_uses_only_current_cli_and_trusted_roots() -> None:
    text = CONTRACT_FILE.read_text(encoding="utf-8")
    for command in (
        "kokoro pack test <source-dir> --request <request.json>",
        "kokoro pack soft-eval <input.json>",
        "kokoro pack promote <source-dir> --target reviewed",
        "kokoro pack promote <source-dir> --target verified",
        "kokoro pack publication-check <source-dir>",
    ):
        assert command in text
    for phrase in (
        "KOKOROARC_DATA_DIR/reports",
        "report_hash",
        "source_hash",
        "compiled_hash",
        "promotion_id",
        "ready_for_private_export",
        "ready_for_publication",
        "ok: true",
    ):
        assert phrase in text
    assert not re.search(r"(?i)\b[A-Z]:", text)


def test_skill_metadata_matches_skill_creator_contract() -> None:
    metadata = yaml.safe_load(METADATA_FILE.read_text(encoding="utf-8"))
    assert set(metadata) == {"interface"}
    interface = metadata["interface"]
    assert interface == {
        "display_name": "Test Character Packs",
        "short_description": "Validate and promote KokoroArc character releases",
        "default_prompt": (
            "Use $testing-character-packs to validate a Character Pack and "
            "report its release readiness."
        ),
    }


def test_skill_directory_contains_only_the_minimal_runtime_files() -> None:
    files = {
        path.relative_to(SKILL_DIR).as_posix()
        for path in SKILL_DIR.rglob("*")
        if path.is_file()
    }
    assert files == {
        "SKILL.md",
        "agents/openai.yaml",
        "references/testing-contract.md",
    }


def test_future_campaign_harness_uses_automatic_workspace_write_review() -> None:
    runner = (ROOT / "run_testing_character_packs_campaign.py").read_text(
        encoding="utf-8"
    )
    assert '"--approve-for-me"' in runner
    assert '"--sandbox"' not in runner
    assert 'approval_policy="never"' not in runner


def test_prior_campaign_failures_are_frozen_and_closed() -> None:
    record = yaml.safe_load(
        (ROOT / "testing-character-packs-campaign.yaml").read_text(encoding="utf-8")
    )
    prior = record["prior_campaigns"]
    assert len(prior) == 5
    assert prior[0]["id"] == "2026-08-17-approved1"
    assert prior[0]["status"] == "completed_with_skill_failures"
    approved2 = prior[1]
    assert approved2["id"] == "2026-08-17-approved2"
    assert approved2["status"] == "completed_harness_failure"
    assert approved2["completed_runs"] == 16
    assert approved2["zero_exit"] == 0
    assert approved2["harness_failed_runs"] == 16
    assert approved2["failure"]["kind"] == "mutually_exclusive_cli_options"
    frozen_runner = (
        ROOT
        / "evidence"
        / "testing-character-packs"
        / "harness"
        / "approved2"
        / "runner.py"
    )
    assert sha256(frozen_runner.read_bytes()).hexdigest() == approved2[
        "executed_runner_sha256"
    ]

    approved3 = prior[2]
    assert approved3["id"] == "2026-08-17-approved3"
    assert approved3["status"] == "completed_with_skill_failures"
    assert approved3["completed_runs"] == 16
    assert approved3["zero_exit"] == 16
    assert approved3["baseline_passed_cases"] == 1
    assert approved3["skill_enabled_passed_cases"] == 3
    assert approved3["evidence"].endswith("approved3/campaign.yaml")

    approved4 = prior[3]
    assert approved4["id"] == "2026-08-17-approved4"
    assert approved4["status"] == "completed_with_skill_failures"
    assert approved4["completed_runs"] == 16
    assert approved4["zero_exit"] == 16
    assert approved4["initial_adjudication"] == {
        "baseline_passed_cases": 1,
        "skill_enabled_passed_cases": 4,
    }
    assert approved4["corrected_adjudication"] == {
        "baseline_passed_cases": 1,
        "skill_enabled_passed_cases": 6,
        "corrections": 3,
    }
    assert len(approved4["remaining_gaps"]) == 2
    assert approved4["evidence"].endswith("approved4/campaign.yaml")

    approved5 = prior[4]
    assert approved5["id"] == "2026-08-17-approved5"
    assert approved5["status"] == "completed_with_skill_failures"
    assert approved5["completed_runs"] == 16
    assert approved5["zero_exit"] == 16
    assert approved5["initial_adjudication"] == {
        "baseline_passed_cases": 1,
        "skill_enabled_passed_cases": 6,
    }
    assert approved5["corrected_adjudication"] == {
        "baseline_passed_cases": 1,
        "skill_enabled_passed_cases": 7,
        "corrections": 1,
    }
    assert len(approved5["remaining_gaps"]) == 1
    assert approved5["evidence"].endswith("approved5/campaign.yaml")


def test_approved3_campaign_is_closed_and_frozen() -> None:
    record = yaml.safe_load(
        (
            ROOT
            / "evidence"
            / "testing-character-packs"
            / "approved3"
            / "campaign.yaml"
        ).read_text(encoding="utf-8")
    )
    assert record["status"] == "completed_with_skill_failures"
    approval = record["approval"]
    assert approval["id"] == "2026-08-17-approved3"
    assert approval["user_response"] == "approve"
    assert approval["evaluator"]["transport"] == {
        "external_service_egress": True,
        "disclosed_payload": (
            "evaluation prompts and necessary isolated workspace contents"
        ),
        "user_acknowledged_after_disclosure": True,
    }
    assert approval["approved_runs"] == {
        "baseline": 8,
        "skill_enabled": 8,
        "corrective": 0,
    }
    isolation = approval["isolation"]
    assert isolation["command_review"] == "automatic --approve-for-me"
    assert isolation["explicit_sandbox_flag"] is False
    assert isolation["effective_sandbox"] == "workspace-write"
    assert isolation["interactive_approvals"] is False
    assert isolation["task_network"] is False
    assert isolation["raw_root"].endswith("approved3")
    assert isolation["retained_root"].endswith("approved3")

    assert record["run_counts"] == {
        "baseline": 8,
        "skill_enabled": 8,
        "corrective": 0,
        "zero_exit": 16,
        "timed_out": 0,
        "harness_failed": 0,
    }
    assert record["outcomes"]["baseline"]["passed_cases"] == 1
    assert record["outcomes"]["skill_enabled"]["passed_cases"] == 3
    assert record["retention"]["reruns_after_this_batch_require_fresh_approval"]

    frozen = record["frozen_inputs"]
    assert frozen["base_commit"] == "0315778ead792ba35fdb64574b50b5cf1e7d1773"
    unchanged_current = {
        "cases_sha256": CASES_FILE,
        "runner_sha256": ROOT / "run_testing_character_packs_campaign.py",
        "metadata_sha256": METADATA_FILE,
    }
    assert _current_frozen_input_hashes(unchanged_current) == {
        name: frozen[name] for name in unchanged_current
    }

    harness = ROOT / "evidence" / "testing-character-packs" / "harness" / "approved3"
    executed = {
        "cases_sha256": harness / "cases.yaml",
        "runner_sha256": harness / "runner.py",
        "skill_sha256": harness / "SKILL.md",
        "contract_sha256": harness / "testing-contract.md",
        "metadata_sha256": harness / "openai.yaml",
    }
    assert {
        name: sha256(path.read_bytes()).hexdigest() for name, path in executed.items()
    } == {name: frozen[name] for name in executed}


def test_approved4_campaign_is_closed_bounded_and_frozen() -> None:
    current = yaml.safe_load(
        (ROOT / "testing-character-packs-campaign.yaml").read_text(encoding="utf-8")
    )
    summary = current["prior_campaigns"][3]
    record = yaml.safe_load(
        (
            ROOT
            / "evidence"
            / "testing-character-packs"
            / "approved4"
            / "campaign.yaml"
        ).read_text(encoding="utf-8")
    )
    assert record["status"] == "completed_with_skill_failures"
    approval = record["approval"]
    assert approval["id"] == "2026-08-17-approved4"
    assert approval["user_response"] == "approve"
    assert approval["approved_runs"] == {
        "baseline": 8,
        "skill_enabled": 8,
        "corrective": 0,
    }
    assert approval["evaluator"] == {
        "provider": "openai",
        "cli": "codex-cli 0.147.0",
        "model": "gpt-5.6-terra",
        "reasoning_effort": "low",
        "transport": {
            "external_service_egress": True,
            "disclosed_payload": (
                "evaluation prompts and necessary isolated workspace contents"
            ),
            "user_acknowledged_after_disclosure": True,
        },
    }
    isolation = approval["isolation"]
    assert isolation["command_review"] == "automatic --approve-for-me"
    assert isolation["explicit_sandbox_flag"] is False
    assert isolation["effective_sandbox"] == "workspace-write"
    assert isolation["interactive_approvals"] is False
    assert isolation["task_network"] is False
    assert isolation["raw_root"].endswith("approved4")
    assert isolation["retained_root"].endswith("approved4")

    assert record["run_counts"] == {
        "baseline": 8,
        "skill_enabled": 8,
        "corrective": 0,
        "zero_exit": 16,
        "timed_out": 0,
        "harness_failed": 0,
    }
    assert record["outcomes"]["baseline"]["passed_cases"] == 1
    assert record["outcomes"]["skill_enabled"]["passed_cases"] == 4
    assert summary["initial_adjudication"] == {
        "baseline_passed_cases": 1,
        "skill_enabled_passed_cases": 4,
    }
    assert summary["corrected_adjudication"] == {
        "baseline_passed_cases": 1,
        "skill_enabled_passed_cases": 6,
        "corrections": 3,
    }
    assert len(summary["remaining_gaps"]) == 2
    assert record["retention"]["reruns_after_this_batch_require_fresh_approval"]

    frozen = record["frozen_inputs"]
    assert frozen["base_commit"] == "0315778ead792ba35fdb64574b50b5cf1e7d1773"
    unchanged_current = {
        "cases_sha256": CASES_FILE,
        "runner_sha256": ROOT / "run_testing_character_packs_campaign.py",
        "metadata_sha256": METADATA_FILE,
    }
    assert _current_frozen_input_hashes(unchanged_current) == {
        name: frozen[name] for name in unchanged_current
    }

    harness = ROOT / "evidence" / "testing-character-packs" / "harness" / "approved4"
    executed = {
        "cases_sha256": harness / "cases.yaml",
        "runner_sha256": harness / "runner.py",
        "skill_sha256": harness / "SKILL.md",
        "contract_sha256": harness / "testing-contract.md",
        "metadata_sha256": harness / "openai.yaml",
    }
    assert {
        name: sha256(path.read_bytes()).hexdigest() for name, path in executed.items()
    } == {name: frozen[name] for name in executed}
    assert summary["executed_runner_sha256"] == frozen["runner_sha256"]
    assert summary["executed_skill_sha256"] == frozen["skill_sha256"]
    assert summary["executed_contract_sha256"] == frozen["contract_sha256"]
    assert summary["dormant_remediated_skill_sha256"] == current[
        "prior_campaigns"
    ][4]["executed_skill_sha256"]
    assert summary["dormant_remediated_contract_sha256"] == current[
        "prior_campaigns"
    ][4]["executed_contract_sha256"]
    assert summary["corrected_adjudicator_sha256"] == (
        "624fe0cc293f91b37dd8a21fbf63d4ab61600433c356106c8db9b78737c575de"
    )


def test_approved5_campaign_is_closed_bounded_and_frozen() -> None:
    current = yaml.safe_load(
        (ROOT / "testing-character-packs-campaign.yaml").read_text(encoding="utf-8")
    )
    summary = current["prior_campaigns"][4]
    retained = yaml.safe_load(
        (
            ROOT
            / "evidence"
            / "testing-character-packs"
            / "approved5"
            / "campaign.yaml"
        ).read_text(encoding="utf-8")
    )
    assert retained["status"] == "completed_with_skill_failures"
    approval = retained["approval"]
    assert approval["id"] == "2026-08-17-approved5"
    assert approval["user_response"] == "approve"
    assert approval["approved_runs"] == {
        "baseline": 8,
        "skill_enabled": 8,
        "corrective": 0,
    }
    assert approval["evaluator"] == {
        "provider": "openai",
        "cli": "codex-cli 0.147.0",
        "model": "gpt-5.6-terra",
        "reasoning_effort": "low",
        "transport": {
            "external_service_egress": True,
            "disclosed_payload": (
                "evaluation prompts and necessary isolated workspace contents"
            ),
            "user_acknowledged_after_disclosure": True,
        },
    }
    isolation = approval["isolation"]
    assert isolation["command_review"] == "automatic --approve-for-me"
    assert isolation["explicit_sandbox_flag"] is False
    assert isolation["effective_sandbox"] == "workspace-write"
    assert isolation["interactive_approvals"] is False
    assert isolation["task_network"] is False
    assert isolation["raw_root"].endswith("approved5")
    assert isolation["retained_root"].endswith("approved5")

    assert retained["run_counts"] == {
        "baseline": 8,
        "skill_enabled": 8,
        "corrective": 0,
        "zero_exit": 16,
        "timed_out": 0,
        "harness_failed": 0,
    }
    assert retained["outcomes"]["baseline"]["passed_cases"] == 1
    assert retained["outcomes"]["skill_enabled"]["passed_cases"] == 6
    assert summary["initial_adjudication"] == {
        "baseline_passed_cases": 1,
        "skill_enabled_passed_cases": 6,
    }
    assert summary["corrected_adjudication"] == {
        "baseline_passed_cases": 1,
        "skill_enabled_passed_cases": 7,
        "corrections": 1,
    }
    assert len(summary["remaining_gaps"]) == 1
    assert retained["retention"]["reruns_after_this_batch_require_fresh_approval"]

    frozen = retained["frozen_inputs"]
    assert frozen["base_commit"] == "0315778ead792ba35fdb64574b50b5cf1e7d1773"
    unchanged_current = {
        "cases_sha256": CASES_FILE,
        "runner_sha256": ROOT / "run_testing_character_packs_campaign.py",
        "metadata_sha256": METADATA_FILE,
    }
    assert _current_frozen_input_hashes(unchanged_current) == {
        name: frozen[name] for name in unchanged_current
    }

    harness = ROOT / "evidence" / "testing-character-packs" / "harness" / "approved5"
    executed = {
        "cases_sha256": harness / "cases.yaml",
        "runner_sha256": harness / "runner.py",
        "skill_sha256": harness / "SKILL.md",
        "contract_sha256": harness / "testing-contract.md",
        "metadata_sha256": harness / "openai.yaml",
    }
    assert {
        name: sha256(path.read_bytes()).hexdigest() for name, path in executed.items()
    } == {name: frozen[name] for name in executed}
    assert summary["executed_runner_sha256"] == frozen["runner_sha256"]
    assert summary["executed_skill_sha256"] == frozen["skill_sha256"]
    assert summary["executed_contract_sha256"] == frozen["contract_sha256"]
    assert sha256(SKILL_FILE.read_bytes()).hexdigest() == summary[
        "dormant_remediated_skill_sha256"
    ]
    assert sha256(CONTRACT_FILE.read_bytes()).hexdigest() == summary[
        "dormant_remediated_contract_sha256"
    ]
    adjudicator = ROOT / "testing_character_packs_evidence.py"
    assert sha256(adjudicator.read_bytes()).hexdigest() == summary[
        "corrected_adjudicator_sha256"
    ]


def test_approved6_campaign_is_closed_bounded_and_frozen() -> None:
    record = yaml.safe_load(
        (ROOT / "testing-character-packs-campaign.yaml").read_text(encoding="utf-8")
    )
    retained = yaml.safe_load(
        (
            ROOT
            / "evidence"
            / "testing-character-packs"
            / "approved6"
            / "campaign.yaml"
        ).read_text(encoding="utf-8")
    )
    assert record["status"] == "completed_skill_passed"
    assert retained["status"] == "completed_skill_passed"
    approval = retained["approval"]
    assert approval["id"] == "2026-08-17-approved6"
    assert approval["user_response"] == "approve"
    assert approval["approved_runs"] == {
        "baseline": 8,
        "skill_enabled": 8,
        "corrective": 0,
    }
    assert approval["evaluator"] == {
        "provider": "openai",
        "cli": "codex-cli 0.147.0",
        "model": "gpt-5.6-terra",
        "reasoning_effort": "low",
        "transport": {
            "external_service_egress": True,
            "disclosed_payload": (
                "evaluation prompts and necessary isolated workspace contents"
            ),
            "user_acknowledged_after_disclosure": True,
        },
    }
    isolation = approval["isolation"]
    assert isolation["command_review"] == "automatic --approve-for-me"
    assert isolation["explicit_sandbox_flag"] is False
    assert isolation["effective_sandbox"] == "workspace-write"
    assert isolation["interactive_approvals"] is False
    assert isolation["task_network"] is False
    assert isolation["raw_root"].endswith("approved6")
    assert isolation["retained_root"].endswith("approved6")

    assert retained["run_counts"] == {
        "baseline": 8,
        "skill_enabled": 8,
        "corrective": 0,
        "zero_exit": 16,
        "timed_out": 0,
        "harness_failed": 0,
    }
    assert retained["outcomes"] == {
        "baseline": {
            "evaluable_cases": 8,
            "passed_cases": 1,
            "failed_cases": 7,
            "harness_failed_cases": 0,
        },
        "skill_enabled": {
            "evaluable_cases": 8,
            "passed_cases": 8,
            "failed_cases": 0,
            "harness_failed_cases": 0,
        },
    }
    execution = record["execution"]
    assert execution["completed_runs"] == 16
    assert execution["zero_exit"] == 16
    assert execution["timed_out"] == 0
    assert execution["corrective_runs"] == 0
    assert execution["adjudication"] == {
        "baseline_passed_cases": 1,
        "skill_enabled_passed_cases": 8,
    }
    assert execution["reruns_after_this_batch_require_fresh_approval"] is True

    frozen = retained["frozen_inputs"]
    assert frozen["base_commit"] == "0315778ead792ba35fdb64574b50b5cf1e7d1773"
    current = {
        "cases_sha256": CASES_FILE,
        "runner_sha256": ROOT / "run_testing_character_packs_campaign.py",
        "skill_sha256": SKILL_FILE,
        "contract_sha256": CONTRACT_FILE,
        "metadata_sha256": METADATA_FILE,
    }
    assert _current_frozen_input_hashes(current) == {
        name: frozen[name] for name in current
    }

    harness = ROOT / "evidence" / "testing-character-packs" / "harness" / "approved6"
    executed = {
        "cases_sha256": harness / "cases.yaml",
        "runner_sha256": harness / "runner.py",
        "skill_sha256": harness / "SKILL.md",
        "contract_sha256": harness / "testing-contract.md",
        "metadata_sha256": harness / "openai.yaml",
    }
    assert {
        name: sha256(path.read_bytes()).hexdigest() for name, path in executed.items()
    } == {name: frozen[name] for name in executed}
    assert execution["executed_runner_sha256"] == frozen["runner_sha256"]
    assert execution["executed_skill_sha256"] == frozen["skill_sha256"]
    assert execution["executed_contract_sha256"] == frozen["contract_sha256"]
