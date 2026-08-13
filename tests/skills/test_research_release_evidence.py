from __future__ import annotations

import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
RESULTS_PATH = ROOT / "tests" / "skills" / "researching-characters-results.md"
EVIDENCE_PATH = ROOT / "tests" / "skills" / "research-release-verification.md"


def _section(document: str, heading: str) -> str:
    marker = f"## {heading}\n"
    start = document.index(marker) + len(marker)
    remainder = document[start:]
    next_heading = re.search(r"^## ", remainder, flags=re.MULTILINE)
    return remainder if next_heading is None else remainder[: next_heading.start()]


def test_readme_documents_repository_local_research_boundary() -> None:
    section = _section(
        README,
        "Research a named character with the repository-local Skill",
    )
    for text in (
        "skills/researching-characters/SKILL.md",
        "$researching-characters",
        "continuity",
        "spoiler",
        "private",
        "Research Bundle",
        "artifact ID",
        "SHA-256",
        "$authoring-character-packs",
        "Milestones 8 and 9",
        "global installation",
        "default bindings",
        "memory",
        "publication",
    ):
        assert text in section


def test_results_document_does_not_claim_unexecuted_campaign() -> None:
    results = RESULTS_PATH.read_text(encoding="utf-8")
    assert "Status: **PENDING**" in results
    assert "22 fresh evaluator runs" in results
    assert "no behavioral PASS or remediation claim" in results
    assert "no subagents" in results


def test_release_evidence_records_smoke_and_exact_milestone_boundary() -> None:
    evidence = EVIDENCE_PATH.read_text(encoding="utf-8")
    for text in (
        "98EA5B94262E95638D71F62230BA7CFA93FBD663164E5CB6182A9FFB1E828826",
        "dca74da0f38393f2235b681f41d5af2c4d6af2edce46377401bc06e582fc4fea",
        "build_status: research",
        "visibility: private",
        "activation_allowed: false",
        "authoring_allowed: true",
        "Milestone 7 does not approve the complete standalone suite",
        "Behavioral campaign: PENDING",
        "Independent specification review: PENDING",
        "Independent quality review: PENDING",
    ):
        assert text in evidence


def test_release_evidence_records_current_inline_verification_without_closure() -> None:
    evidence = EVIDENCE_PATH.read_text(encoding="utf-8")
    for text in (
        r"D:\tmp\kokoroarc-m7-release-20260813-inline3",
        "1903 passed, 24 skipped",
        "79479F425A7B3285A7AC8903EE632817359178F78EB91A522603EC9991724E97",
        "131F898CECE54C94ACDAE77DA0D061C3EB6191F6CED1D6B7C8BEE21E981C9441",
        "All three validators exited `0` and printed `Skill is valid!`",
        "exact-final verification remains pending",
    ):
        assert text in evidence


def test_release_evidence_binds_current_skill_files() -> None:
    evidence = EVIDENCE_PATH.read_text(encoding="utf-8")
    for relative in (
        "skills/researching-characters/SKILL.md",
        "skills/researching-characters/references/research-contract.md",
        "skills/researching-characters/agents/openai.yaml",
    ):
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest().upper()
        assert f"`{relative}` | `{digest}`" in evidence


def test_release_evidence_records_distribution_inventory() -> None:
    evidence = EVIDENCE_PATH.read_text(encoding="utf-8")
    for module in (
        "kokoroarc/research/bundles.py",
        "kokoroarc/research/requests.py",
        "kokoroarc/research/storage.py",
        "kokoroarc/research/validation.py",
        "kokoroarc/research/workspace.py",
    ):
        assert module in evidence
    for schema in (
        "research-bundle.schema.json",
        "research-claim.schema.json",
        "research-conflict.schema.json",
        "research-coverage.schema.json",
        "research-request.schema.json",
        "research-source-record.schema.json",
        "research-validation-report.schema.json",
        "research-workspace.schema.json",
    ):
        assert schema in evidence
    assert re.search(r"Wheel entries: `\d+`", evidence)
    assert re.search(r"sdist entries: `\d+`", evidence)
