from __future__ import annotations

import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
RESULTS_PATH = ROOT / "tests" / "skills" / "researching-characters-results.md"
EVIDENCE_PATH = ROOT / "tests" / "skills" / "research-release-verification.md"
GIT_ATTRIBUTES_PATH = ROOT / ".gitattributes"


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


def test_results_document_records_corrective_pass_without_claiming_closure() -> None:
    results = RESULTS_PATH.read_text(encoding="utf-8")
    assert (
        "Status: **CORRECTIVE BEHAVIORAL CAMPAIGN PASS; "
        "MILESTONE 7 CLOSURE PENDING**"
    ) in results
    assert "exactly 22 fresh evaluator runs" in results
    assert "PASS 10/11, RED 1/11" in results
    assert "sole failed declared assertion" in results
    assert "exactly 11 fresh Skill-only corrective runs" in results
    assert "Corrective Skill result: **PASS 11/11**" in results
    assert "ten deviations across seven cases" in results
    assert "Task 11 and Milestone 7 remain open" in results


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
        "Behavioral campaign: CORRECTIVE PASS 11/11",
        "Corrective harness: COMPLETED WITH DISCLOSED DEVIATIONS",
        "Exact-final verification: PASS",
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


def test_release_evidence_records_corrective_exact_final_candidate() -> None:
    evidence = EVIDENCE_PATH.read_text(encoding="utf-8")
    for text in (
        r"D:\tmp\kokoroarc-m7-release-20260813-final1",
        "274c5a57051b8ee31d95deab11ae26d00707911a",
        "1912 passed, 24 skipped",
        "F60198B48BAA0203C5882CD62AECF76B24FB863E0A27AD1D2BFE0A1DFF6912C6",
        "A573C408B6B9492DA5A204AE31FA302A346FE7BFECD219D2A4724141D6F37AC5",
        "8CED76118C774ABE209F8CB176F4AAB783B57C01A5162812C0ACF4DDB74B2668",
        "0F9D3B900E26B47E8F7C8A077931600351D051708881F473DBAF0C076E29ED6D",
        "4E1ADA14555CCF663C9E87545AC476013E8726E43D3E894FF4CBF469E2C54776",
        "A final settled-input rerun and both independent reviews remain required",
    ):
        assert text in evidence


def test_release_evidence_records_settled_exact_final_pass() -> None:
    evidence = EVIDENCE_PATH.read_text(encoding="utf-8")
    for text in (
        r"D:\tmp\kokoroarc-m7-release-20260814-final2",
        "1913 passed, 24 skipped",
        "8A7450B26067B2ED88EC14599FC66C892B3B75F08396051D675BA2C0C7F5E119",
        "0F9D3B900E26B47E8F7C8A077931600351D051708881F473DBAF0C076E29ED6D",
        "2F22933EA8326B706DA77C7FE6EF0A36747246BE406F7A290DA59B071DA64FDF",
        "4E1ADA14555CCF663C9E87545AC476013E8726E43D3E894FF4CBF469E2C54776",
        "Exact-final verification is therefore **PASS**",
        "independent specification and quality reviews remain the two closure gates",
    ):
        assert text in evidence


def test_retained_research_evidence_is_checkout_byte_stable() -> None:
    attributes = GIT_ATTRIBUTES_PATH.read_text(encoding="utf-8").splitlines()
    assert "tests/skills/evidence/researching-characters/** -text" in attributes


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
