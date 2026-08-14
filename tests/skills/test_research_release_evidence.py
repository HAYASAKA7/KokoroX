from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
RESULTS_PATH = ROOT / "tests" / "skills" / "researching-characters-results.md"
EVIDENCE_PATH = ROOT / "tests" / "skills" / "research-release-verification.md"
GIT_ATTRIBUTES_PATH = ROOT / ".gitattributes"
TASK_11_BASE = "274c5a57051b8ee31d95deab11ae26d00707911a"


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
    assert "Exact raw Codex `final_answer`" in results
    assert "independently recomputes every assertion outcome" in results
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
        "Exact-final verification: SEVENTH SPEC-REVIEW REMEDIATION PREFLIGHT PASS; EXACT-TREE GATES AND FRESH REVIEWS PENDING",
        "Fresh specification review of `6afcbeccbc43814700e42c4626a6a9b8e1bddce0`: PASS",
        "Fresh quality review of `6afcbeccbc43814700e42c4626a6a9b8e1bddce0`: IMPORTANT FINDINGS REMEDIATED",
        "Fresh specification review of `646fc91f27eb723334f4ff4b25309985b56046a3`: IMPORTANT FINDINGS REMEDIATED",
        "Fresh quality review of `646fc91f27eb723334f4ff4b25309985b56046a3`: IMPORTANT FINDINGS REMEDIATED",
        "Fresh specification review of `531ce43cf2f8dff4708fa64c601ec72bd680cbf2`: IMPORTANT FINDINGS REMEDIATED",
        "Fresh quality review of `531ce43cf2f8dff4708fa64c601ec72bd680cbf2`: NOT RUN; SPECIFICATION REVIEW FAILED",
        "Fresh specification review of `57ea7ea7f215cedcf800dc266bd5486eb981976a`: IMPORTANT FINDINGS REMEDIATED",
        "Fresh quality review of `57ea7ea7f215cedcf800dc266bd5486eb981976a`: NOT RUN; SPECIFICATION REVIEW FAILED",
        "Fresh specification review of `bea1fce58cbbf0c00a49da2fa662e0dc30c2d7b1`: IMPORTANT FINDING REMEDIATED",
        "Fresh quality review of `bea1fce58cbbf0c00a49da2fa662e0dc30c2d7b1`: NOT RUN; SPECIFICATION REVIEW FAILED",
        "Fresh specification review of `670e44bf126daa2198c77889ad3bf142b60d0b72`: IMPORTANT FINDINGS REMEDIATED",
        "Fresh quality review of `670e44bf126daa2198c77889ad3bf142b60d0b72`: NOT RUN; SPECIFICATION REVIEW FAILED",
        "Fresh specification review of `bc183a8f92452a82b733459118764e9304d4878a`: IMPORTANT FINDINGS REMEDIATED",
        "Fresh quality review of `bc183a8f92452a82b733459118764e9304d4878a`: NOT RUN; SPECIFICATION REVIEW FAILED",
        "Fresh specification review of `bb492bcf1aafa3d1132bc53872616db7565d7e37`: IMPORTANT FINDINGS REMEDIATED",
        "Fresh quality review of `bb492bcf1aafa3d1132bc53872616db7565d7e37`: NOT RUN; SPECIFICATION REVIEW FAILED",
        "Fresh specification review of seventh spec-review remediation settled tree: PENDING",
        "Fresh quality review of seventh spec-review remediation settled tree: PENDING",
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


def test_release_evidence_retains_superseded_settled_exact_final_result() -> None:
    evidence = EVIDENCE_PATH.read_text(encoding="utf-8")
    for text in (
        r"D:\tmp\kokoroarc-m7-release-20260814-final2",
        "1913 passed, 24 skipped",
        "8A7450B26067B2ED88EC14599FC66C892B3B75F08396051D675BA2C0C7F5E119",
        "0F9D3B900E26B47E8F7C8A077931600351D051708881F473DBAF0C076E29ED6D",
        "2F22933EA8326B706DA77C7FE6EF0A36747246BE406F7A290DA59B071DA64FDF",
        "4E1ADA14555CCF663C9E87545AC476013E8726E43D3E894FF4CBF469E2C54776",
        "historical candidate reported **PASS**",
        "invalidated it for Task 11 closure",
    ):
        assert text in evidence


def test_release_evidence_records_important_review_remediation() -> None:
    evidence = EVIDENCE_PATH.read_text(encoding="utf-8")
    for text in (
        "Closure-review remediation after `b073381`",
        "b07338101b37c66080f9b7f82de7a84919d9b56c",
        "pins `skills/**` to LF",
        "cr-at-eol,-blank-at-eol,-blank-at-eof",
        "All 33 original evaluator threads",
        "`task_complete.last_agent_message`",
        "`lf_and_strip_terminal_lf`",
        "without `BASELINE_PASSES`",
        "30 tests",
        r"D:\tmp\kokoroarc-m7-remediation-preflight-20260814-02",
        "1919 passed, 24 skipped",
        "6C73C2A057A36110C9D467CEF0374D38E5BDCBF79D07343DB1225DA0BF79B0C1",
        "not the fresh exact-commit closure run",
    ):
        assert text in evidence


def test_release_evidence_records_remediated_exact_commit_gates() -> None:
    evidence = EVIDENCE_PATH.read_text(encoding="utf-8")
    for text in (
        "Remediated exact-commit verification",
        "c8095c105f4866f3728debfa1ca2568f28fff2be",
        r"D:\tmp\kokoroarc-m7-remediation-final3-c8095c1-01",
        "1920 passed, 24 skipped",
        "4B8A46FAFB0ACAC1C71EB9A56E0BC8E97BDBF50C627FBB6B442AF988896E2D40",
        "73174C633EC2A77AA7B403BA9F901A2F834C21FA1FFD6A0E151EDAB1CFA041FF",
        "Settled remediation release gate",
        r"D:\tmp\kokoroarc-m7-remediation-final4-settled-01",
        "1921 passed, 24 skipped",
        "PASS ON SETTLED REMEDIATION COMMIT",
        "archive-inventory.json",
        "later fresh quality review invalidated it for Task 11 closure",
    ):
        assert text in evidence


def test_release_evidence_records_post_settlement_quality_remediation() -> None:
    evidence = EVIDENCE_PATH.read_text(encoding="utf-8")
    for text in (
        "Post-settlement quality-review remediation",
        "all 917 reproducible importer outputs matched",
        "all 785 raw-ledger files matched",
        "all 33 retained final messages rebound",
        "semantically empty but byte-identical JSON",
        "fabricated artifact and hash",
        "A shared sanitizer now covers",
        "credential-bearing URLs",
        "eight legacy baseline assertion booleans across four runs",
        "aggregate baseline remains RED in 9/11 cases",
        "passes **40 tests**",
        r"D:\tmp\kokoroarc-m7-quality-remediation-preflight-01",
        "1931 passed, 24 skipped",
        "not Task 11 closure",
        "Post-settlement remediation exact gates",
        "ee5d2073b76d2760bbcf8838da8a2f7e80df6aa7",
        r"D:\tmp\kokoroarc-m7-quality-remediation-exact-ee5d207-01",
        "9019A197C95479E416D385FA3CB630191A79EBB4C9C0A3B414B897ED4377B31F",
        "EAC007AF8B70CD87354E5DC1C1B1B7CA8E743709F0F3F0D0A953AD2618381DA3",
        r"D:\tmp\kokoroarc-m7-fresh-checkout-ee5d207-01",
        "29BFB709927BFD3B65280102AB93BEE792891390333BE287756013FFD8E46C82",
        "all 984 retained evidence blobs byte-for-byte",
        r"D:\tmp\kokoroarc-m7-quality-remediation-settled-01",
        "PASS ON POST-SETTLEMENT REMEDIATION TREE; FRESH REVIEWS PENDING",
    ):
        assert text in evidence


def test_release_evidence_records_replay_hardening_review_remediation() -> None:
    evidence = EVIDENCE_PATH.read_text(encoding="utf-8")
    for text in (
        "Replay-hardening review remediation",
        "646fc91f27eb723334f4ff4b25309985b56046a3",
        "label-bound rather than executable-bound",
        "trusted raw-run root",
        "`cmd /d /c set`",
        "quoted multiword secrets",
        "all 785 ledger-bound raw files",
        "a3fcdb809945cf823f3dd860c65666f0cab6b4be",
        "5f545d2695d5c4bf849876307c2018e21c6cb16e",
        r"D:\tmp\kokoroarc-m7-replay-hardening-exact-a3fcdb8-01",
        "1942 passed, 24 skipped",
        "23967ABA7BF55C58C12560516DDB12535A8FC59DF00C77954A2E17A10578FA8",
        "166B16F1883B3CE838744A7DE6FED4EF57085035C1B6CB79C0AC2AB6EABD1F0D",
        r"D:\tmp\kokoroarc-m7-fresh-checkout-a3fcdb8-01",
        "51 tests",
        "74FA2331E2AB269DCFAAE95D001DC9DB433D4BD772BEF3B6F314C84C8FB536A0",
        r"D:\tmp\kokoroarc-m7-replay-hardening-settled-01",
        "PASS ON REPLAY-HARDENING SETTLED TREE; FRESH REVIEWS PENDING",
    ):
        assert text in evidence


def test_release_evidence_records_second_specification_review_remediation() -> None:
    evidence = EVIDENCE_PATH.read_text(encoding="utf-8")
    for text in (
        "Second specification-review remediation",
        "531ce43cf2f8dff4708fa64c601ec72bd680cbf2",
        "quoted non-executing wrapper",
        "`dir env:`",
        "`process['env']`",
        "structured assignment-value scanner",
        "redaction-placeholder smuggling",
        "passes **57 tests**",
        r"D:\tmp\kokoroarc-m7-spec2-remediation-preflight-01",
        "1948 passed, 24 skipped",
        "519FD46D9CD23957DF336D1BB861F6EE1FE8ED3C0C746EE26F4F524202D0F8BB",
        r"D:\tmp\kokoroarc-m7-spec2-remediation-settled-01",
        "PASS ON SPEC-REVIEW REMEDIATION SETTLED TREE; FRESH REVIEWS PENDING",
    ):
        assert text in evidence


def test_release_evidence_records_third_specification_review_remediation() -> None:
    evidence = EVIDENCE_PATH.read_text(encoding="utf-8")
    for text in (
        "Third specification-review remediation",
        "57ea7ea7f215cedcf800dc266bd5486eb981976a",
        "PowerShell block comment",
        "quoted full-path Python",
        "credential-bearing URL",
        "escaped JSON Authorization",
        "top-level wrapper reachability",
        "passes **64 tests**",
        r"D:\tmp\kokoroarc-m7-spec3-remediation-preflight-01",
        "1955 passed, 24 skipped",
        "C8D6F6ED7E9BF8C7FAF3159D0077AC6CF88CAEE3ABF79C319DE69BE9F87F3CE5",
        r"D:\tmp\kokoroarc-m7-spec3-remediation-settled-01",
        "PASS ON THIRD SPEC-REVIEW REMEDIATION SETTLED TREE; FRESH REVIEWS PENDING",
    ):
        assert text in evidence


def test_release_evidence_records_fourth_specification_review_remediation() -> None:
    evidence = EVIDENCE_PATH.read_text(encoding="utf-8")
    for text in (
        "Fourth specification-review remediation",
        "bea1fce58cbbf0c00a49da2fa662e0dc30c2d7b1",
        "action-only",
        "complete child invocation",
        "stdout and stderr capture paths",
        "nonzero-exit propagation guard",
        "passes **75 tests**",
        r"D:\tmp\kokoroarc-m7-spec4-remediation-preflight-04",
        "1966 passed, 24 skipped",
        "A77570A9986AB19386114ACF4AF0E822977E1E877E4159293026FF69E6BF58C1",
        r"D:\tmp\kokoroarc-m7-spec4-remediation-settled-01",
        "PASS ON FOURTH SPEC-REVIEW REMEDIATION SETTLED TREE; FRESH REVIEWS PENDING",
    ):
        assert text in evidence


def test_release_evidence_records_fifth_specification_review_remediation() -> None:
    evidence = EVIDENCE_PATH.read_text(encoding="utf-8")
    for text in (
        "Fifth specification-review remediation",
        "670e44bf126daa2198c77889ad3bf142b60d0b72",
        "exact executable token",
        "reported `PYTHONPATH`",
        "trusted run root",
        "login-shell",
        "execution-status",
        "conflicting capture aliases",
        "seven focused mutations",
        r"D:\tmp\kokoroarc-m7-spec5-remediation-preflight-01",
        "1974 passed, 24 skipped",
        "95022C1B29E414D28554A40C7E8E5FBC5D3ED2088CF7AEF41B619B40EC552EB1",
        r"D:\tmp\kokoroarc-m7-spec5-remediation-settled-01",
        "PASS ON FIFTH SPEC-REVIEW REMEDIATION SETTLED TREE; FRESH REVIEWS PENDING",
    ):
        assert text in evidence


def test_release_evidence_records_sixth_specification_review_remediation() -> None:
    evidence = EVIDENCE_PATH.read_text(encoding="utf-8")
    for text in (
        "Sixth specification-review remediation",
        "bc183a8f92452a82b733459118764e9304d4878a",
        "aa94d127c51dd8f5879d6ee3fdfd38f83d0893db",
        "approval-controlled trust anchor",
        "approval-locked importer constants",
        "immutable approved1 evidence",
        "current approved2 campaign",
        "single approval-locked `spoiler-cutoff` argv-only exception",
        "explicit absolute per-command `cwd`",
        "Every independently recognized research CLI occurrence",
        "Fifteen focused mutations",
        "missing raw command",
        "misleading help metadata",
        "arbitrarily long spacing",
        "100 tests",
        r"D:\tmp\kokoroarc-m7-spec6-remediation-preflight-01",
        "1988 passed, 24 skipped",
        "superseded after the two adjacent raw-command/help-token RED regressions",
        r"D:\tmp\kokoroarc-m7-spec6-remediation-preflight-02",
        "1990 passed, 24 skipped",
        "overlong-spacing RED regression removed the scanner's arbitrary gap cap",
        r"D:\tmp\kokoroarc-m7-spec6-remediation-preflight-03",
        "1991 passed, 24 skipped",
        "BA96DC9DE317B700D7A39A1B7DDB22FFCF4CE9478E26E03B98E32E5D1BE6E77A",
        r"D:\tmp\kokoroarc-m7-spec6-remediation-settled-01",
        "PASS ON SIXTH SPEC-REVIEW REMEDIATION SETTLED TREE; FRESH REVIEWS PENDING",
    ):
        assert text in evidence


def test_release_evidence_records_seventh_specification_review_remediation() -> None:
    evidence = EVIDENCE_PATH.read_text(encoding="utf-8")
    for text in (
        "Seventh specification-review remediation",
        "bb492bcf1aafa3d1132bc53872616db7565d7e37",
        "7598e1612d1012e4e0f023aa6b995397188cdf0b",
        "quoted CLI data argument",
        "absolute destination outside the trusted run root",
        "quote awareness",
        "complete argument token",
        "explicit filesystem mutation destinations",
        "Nine focused RED cases",
        "passes **110 tests**",
        r"D:\tmp\kokoroarc-m7-spec7-remediation-preflight-01",
        "1998 passed, 24 skipped",
        "FEA6AB106E4AEC7FE998A959195D759C89B3D090BBB94A871706DE4431A9C413",
        "superseded because the three adjacent alias, redirection, and destination-variable RED cases were added afterward",
        r"D:\tmp\kokoroarc-m7-spec7-remediation-preflight-02",
        "2001 passed, 24 skipped",
        "F8E0F6ADD2995C5EA9F0EB0AF55FA42D89D3B55D059A265D22F2A18F21C2FBE6",
        r"D:\tmp\kokoroarc-m7-spec7-remediation-settled-01",
        "SEVENTH SPEC-REVIEW REMEDIATION PREFLIGHT PASS; EXACT-TREE GATES AND FRESH REVIEWS PENDING",
    ):
        assert text in evidence


def test_release_evidence_records_eighth_specification_review_remediation() -> None:
    evidence = EVIDENCE_PATH.read_text(encoding="utf-8")
    for text in (
        "Eighth specification-review remediation",
        "190c4aadbce96f812a00fe53c06746fcec016f71",
        "5a5c5c401afecd93655f9b380755d176ef97c13c",
        "positional `Copy-Item`",
        "`Start-Process`",
        "approval-controlled raw run",
        "`agent-report.json`",
        "raw and retained SHA-256",
        "redaction count",
        "Twelve focused regressions",
        "passes **123 tests**",
        r"D:\tmp\kokoroarc-m7-spec8-remediation-focused-03",
        r"D:\tmp\kokoroarc-m7-spec8-remediation-preflight-01",
        "2014 passed, 24 skipped",
        "9917CADA1DBA8A1F52B9AD4FD568FDA59A5AEBC808EC727A0EAE290BFF9C2BB4",
        "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855",
        r"D:\tmp\kokoroarc-m7-spec8-remediation-settled-01",
        "EIGHTH SPEC-REVIEW REMEDIATION PREFLIGHT PASS; EXACT-TREE GATES AND FRESH REVIEWS PENDING",
    ):
        assert text in evidence


def test_release_evidence_records_ninth_specification_review_remediation() -> None:
    evidence = EVIDENCE_PATH.read_text(encoding="utf-8")
    for text in (
        "Ninth specification-review remediation",
        "3bfe1c9ac358f7d876d5f2e82db0a783dcb16ce3",
        "6d0333b78f3c8f2e5578da44c7f4f9d5886e3442",
        "invalid or missing report provenance",
        "`must_not`",
        "before requirement interpretation",
        "Eight focused regressions",
        "passes **132 tests**",
        r"D:\tmp\kokoroarc-m7-spec9-remediation-focused-01",
        r"D:\tmp\kokoroarc-m7-spec9-remediation-preflight-01",
        "2023 passed, 24 skipped",
        "E876AACC9CB9373EECC75694C797BDD37B10B3F201B986640A46BA4095CB0670",
        "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855",
        r"D:\tmp\kokoroarc-m7-spec9-remediation-settled-01",
        "NINTH SPEC-REVIEW REMEDIATION PREFLIGHT PASS; EXACT-TREE GATES AND FRESH REVIEWS PENDING",
    ):
        assert text in evidence


def test_research_skill_and_evidence_are_checkout_byte_stable() -> None:
    attributes = GIT_ATTRIBUTES_PATH.read_text(encoding="utf-8").splitlines()
    assert "skills/** text eol=lf" in attributes
    assert (
        "tests/skills/evidence/researching-characters/** -text "
        "whitespace=cr-at-eol,-blank-at-eol,-blank-at-eof"
    ) in attributes


def test_exact_task_11_range_has_no_undeclared_whitespace_errors() -> None:
    checked = subprocess.run(
        ["git", "diff", "--check", TASK_11_BASE, "HEAD"],
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr


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
