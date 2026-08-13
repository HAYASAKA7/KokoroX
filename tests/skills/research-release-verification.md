# Milestone 7 research release verification

## Scope and exact status

This record covers the inline product, CLI, Skill-structure, smoke, and distribution checks completed for Milestone 7 on 2026-08-13 (Asia/Hong_Kong). Milestone 7 does not approve the complete standalone suite.

- Build base HEAD: `7ec68e553b478411d3b9f7e8207a70df2b382b19`
- Build input: that HEAD plus the current `README.md` patch only among `README.md`, `pyproject.toml`, `src/`, and `schemas/`
- Isolated root: `D:\tmp\kokoroarc-m7-release-20260813-inline1`
- Behavioral campaign: CORRECTIVE PASS 11/11 (first batch remains Skill PASS 10/11, RED 1/11)
- Corrective harness: COMPLETED WITH DISCLOSED DEVIATIONS
- Exact-final verification: REOPENED AFTER IMPORTANT REVIEW FINDINGS
- Review of commit `b07338101b37c66080f9b7f82de7a84919d9b56c`: IMPORTANT FINDINGS REMEDIATED
- Fresh exact-commit specification review: PENDING
- Fresh exact-commit quality review: PENDING

The approved 22-run first campaign remains behaviorally immutable, including its one failed Skill assertion. The separately approved 11-run corrective Skill-only campaign passed all declared behavioral assertions against the current Skill. Ten harness/report deviations across seven cases are retained and disclosed; they do not reclassify any behavior or erase the failed first campaign. Review of the first release-evidence commit found Important checkout, whitespace-gate, assertion-adjudication, and final-message-binding gaps. Those gaps are now remediated, but the prior exact-final result cannot close Task 11; a fresh settled-commit verification and two fresh independent reviews remain required. No canon-accuracy claim or complete-suite approval is implied by the checks below.

## Current Skill identity

| Artifact | SHA-256 |
| --- | --- |
| `skills/researching-characters/SKILL.md` | `AA08F7E8BB5DD78C2434AF0BD8878BB87D0CDBD7BAD0FB04CD40AA13149BEC21` |
| `skills/researching-characters/references/research-contract.md` | `9E4F2ABC63A29BF75F4291D5DB657B2908A75C00E8830F69A027CC1EED73B313` |
| `skills/researching-characters/agents/openai.yaml` | `093EB44756A018C1A8FFE856F4237E31D161E936AEEAF1DF2A452B3146785C3E` |

The focused structural suite completed with `8 passed`; the standard Skill validator exited `0` and printed `Skill is valid!` after the early-stop reporting correction.

The first approved Skill batch used the previous Skill SHA-256, `33B1BF3B8C98A97282295BFFE7EBE474D5EE43687378FF29E48DCABAC2239876`. It passed 10 of 11 cases and failed only `continuity-conflict-clarification` → `report_unresolved_evidence`; that exact failed output remains retained.

Approval `2026-08-13-approved2` then ran exactly 11 fresh Skill-only cases with the current hashes, unique evaluator threads, `fork_turns: none`, no baseline reruns, and no behavioral retries. Result: **PASS 11/11**. All seven operational cases retained 21 byte-identical JSON validation pairs with empty stderr and exactly one compilation per case. Protected product roots remained absent. The corrected continuity response now includes the required separate unresolved-evidence line.

The corrective evidence reports `completed_with_disclosed_deviations` for seven cases. The retained deviations include incomplete report/control fields, one inconsistent pre-launch exit field, incomplete command arrays, one absolute final-file field, and one post-response read of the ambient system verification Skill whose producing command was omitted from the raw report. One non-behavioral reminder was sent only after the spoiler workflow and `final.md` were complete so the evaluator would write its already-required report. Repository evidence preserves every affected capture and raw hash.

## Copy/paste deterministic CLI smoke

The run created fresh `temp`, `pytest`, `build-temp`, `smoke`, `smoke-data`, and `dist` directories beneath the isolated root. From the repository root:

```powershell
$releaseRoot='D:\tmp\kokoroarc-m7-release-20260813-inline1'
$smoke="$releaseRoot\smoke"
$env:PYTHONPATH=(Join-Path (Get-Location) 'src')
$env:KOKOROARC_DATA_DIR="$releaseRoot\smoke-data"
$env:TEMP="$releaseRoot\temp"
$env:TMP=$env:TEMP

python -m kokoroarc.cli research request validate --input tests/fixtures/research/complete/request.json --json 1> "$smoke\request-1.json" 2> "$smoke\request-1.stderr.txt"
python -m kokoroarc.cli research request validate --input tests/fixtures/research/complete/request.json --json 1> "$smoke\request-2.json" 2> "$smoke\request-2.stderr.txt"
python -m kokoroarc.cli research workspace validate --workspace tests/fixtures/research/complete --json 1> "$smoke\workspace-1.json" 2> "$smoke\workspace-1.stderr.txt"
python -m kokoroarc.cli research workspace validate --workspace tests/fixtures/research/complete --json 1> "$smoke\workspace-2.json" 2> "$smoke\workspace-2.stderr.txt"
python -m kokoroarc.cli research bundle compile --workspace tests/fixtures/research/complete --json 1> "$smoke\compile.json" 2> "$smoke\compile.stderr.txt"
$compiled=Get-Content -LiteralPath "$smoke\compile.json" -Raw | ConvertFrom-Json
python -m kokoroarc.cli research bundle validate --bundle $compiled.path --json 1> "$smoke\bundle-1.json" 2> "$smoke\bundle-1.stderr.txt"
python -m kokoroarc.cli research bundle validate --bundle $compiled.path --json 1> "$smoke\bundle-2.json" 2> "$smoke\bundle-2.stderr.txt"
```

All seven commands exited `0`; every stderr capture was empty. The paired request, workspace, and bundle stdout files were byte-identical. The returned lifecycle and gate were:

```text
build_status: research
visibility: private
activation_allowed: false
authoring_allowed: true
```

Coverage was `covered: 2`, `partial: 0`, `missing: 0`, `blocked: 0`; one resolved conflict and zero aggregate limitations were retained. The only top-level data entry created was `research`; no `drafts`, `compiled`, `installed`, `public`, `sessions`, `state`, `events`, `workspaces`, or `config` root appeared.

| Capture | SHA-256 |
| --- | --- |
| `request-1.json` | `1AABCC213501D6C54AA2A9A5B944F44894D33AF842F5868FD26AE258B3C7F9C2` |
| `workspace-1.json` | `3FC3272ED3F6E2155D0CFD187E664D910B2F88BE0E00CC3CEDFD65DFA41A50BD` |
| `compile.json` | `1B7989DA854E3C06CA4162F3EE58D63F0FC25921D97878F3AD648C169AD80A5D` |
| `bundle-1.json` | `3F7673D519C208A4F35DB994BD474EF9B2610AE83FF1D511C9D2B2AC5C46D8AC` |

The compiled artifact ID was `research/aoi-kisaragi-fixture/research/36c328d763dd4ca7`; its bundle hash was `dca74da0f38393f2235b681f41d5af2c4d6af2edce46377401bc06e582fc4fea`. The canonical seven-record transcript SHA-256 was `98EA5B94262E95638D71F62230BA7CFA93FBD663164E5CB6182A9FFB1E828826`.

## Distribution build and inventory

With `TEMP` and `TMP` set to the isolated `build-temp` directory:

```powershell
python -m build --outdir "$releaseRoot\dist"
```

The command exited `0` and built both archives.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `kokoroarc-0.0.0.dev0-py3-none-any.whl` | 111,414 | `E6D994BF60ADE76F019897E298E2C65D051C0B1F48843374CF0401CC21042D02` |
| `kokoroarc-0.0.0.dev0.tar.gz` | 86,035 | `33D20E8D7109C5C012938D150F4B268A7891B22D8F657ED7A85BFDB8FE1003B1` |

Wheel entries: `58`. sdist entries: `75`. The sdist README SHA-256 was `0F345F780A742B8552C34134641B8BA23C15B615D8A67F5E996F7303E9B5881D`, matching the identified build input.

Both archives included the full research module set:

```text
kokoroarc/research/__init__.py
kokoroarc/research/bundles.py
kokoroarc/research/requests.py
kokoroarc/research/storage.py
kokoroarc/research/validation.py
kokoroarc/research/workspace.py
```

Both included all eight research schemas:

```text
research-bundle.schema.json
research-claim.schema.json
research-conflict.schema.json
research-coverage.schema.json
research-request.schema.json
research-source-record.schema.json
research-validation-report.schema.json
research-workspace.schema.json
```

Task 9 separately installed the wheel outside the repository and ran all four research CLI leaves successfully.

## Current inline verification checkpoint

The following commands ran against base HEAD `7ec68e553b478411d3b9f7e8207a70df2b382b19` plus the current Task 11 release-document and evidence-test patches. The product and package inputs were the same base-plus-`README.md` identity documented above. The authorized operational root was `D:\tmp\kokoroarc-m7-release-20260813-inline3`.

```powershell
$env:PYTHONPATH='src'
python -m pytest -q --basetemp D:\tmp\kokoroarc-m7-release-20260813-inline3\pytest -p no:cacheprovider
```

The complete repository suite exited `0`: `1903 passed, 24 skipped` in 205.82 seconds. Every skip named a Windows capability limitation involving symlinks, junctions, or FIFOs; there were no failures or errors.

A fresh distribution build then exited `0` and printed `Successfully built kokoroarc-0.0.0.dev0.tar.gz and kokoroarc-0.0.0.dev0-py3-none-any.whl`:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `kokoroarc-0.0.0.dev0-py3-none-any.whl` | 111,414 | `79479F425A7B3285A7AC8903EE632817359178F78EB91A522603EC9991724E97` |
| `kokoroarc-0.0.0.dev0.tar.gz` | 86,042 | `131F898CECE54C94ACDAE77DA0D061C3EB6191F6CED1D6B7C8BEE21E981C9441` |

The fresh wheel again contained 58 entries; the sdist contained 75 entries and embedded the same README SHA-256, `0F345F780A742B8552C34134641B8BA23C15B615D8A67F5E996F7303E9B5881D`. Archive-level SHA-256 values are recorded per run because build metadata is time-varying; archive membership and embedded input identity are checked independently.

The standard Skill validator ran separately for `skills/using-kokoroarc`, `skills/authoring-character-packs`, and `skills/researching-characters`. All three validators exited `0` and printed `Skill is valid!`.

This is a verified inline checkpoint, not Task 11 closure. The current corrected Skill now has an approved 11/11 behavioral batch, but this checkpoint predates the final corrective-evidence import. Independent reviews are absent, and exact-final verification remains pending against the settled release inputs.

## Exact-final candidate after corrective evidence

Candidate root: `D:\tmp\kokoroarc-m7-release-20260813-final1`. Input identity: base HEAD `274c5a57051b8ee31d95deab11ae26d00707911a` plus the complete corrective campaign import, current Skill correction, executable evidence checks, and the corrective-status documentation that preceded this result block.

The full repository suite ran with `PYTHONPATH=src`, pytest caching disabled, and `TEMP`, `TMP`, `KOKOROARC_TEMP_DIR`, and `--basetemp` confined beneath the candidate root. It exited `0`: **`1912 passed, 24 skipped` in 164.80 seconds**. All 24 skips were explicit Windows capability cases for symlinks, junctions, or FIFOs. There were no failures or errors. Captured pytest stdout was 6,995 bytes with SHA-256 `F60198B48BAA0203C5882CD62AECF76B24FB863E0A27AD1D2BFE0A1DFF6912C6`; stderr was empty with SHA-256 `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`.

The clean build exited `0` and produced:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `kokoroarc-0.0.0.dev0-py3-none-any.whl` | 111,414 | `A573C408B6B9492DA5A204AE31FA302A346FE7BFECD219D2A4724141D6F37AC5` |
| `kokoroarc-0.0.0.dev0.tar.gz` | 86,038 | `8CED76118C774ABE209F8CB176F4AAB783B57C01A5162812C0ACF4DDB74B2668` |

The wheel again contained 58 entries and the sdist 75. Both contained all six research modules and all eight research schemas; the sdist README SHA-256 remained `0F345F780A742B8552C34134641B8BA23C15B615D8A67F5E996F7303E9B5881D`.

All three standard validators separately exited `0` and printed `Skill is valid!` for `skills/using-kokoroarc`, `skills/authoring-character-packs`, and `skills/researching-characters`. `git diff --check` exited `0`; its only output was the repository's LF-to-CRLF conversion warning. `git status --short` contained only the intended Task 11 Skill, plan, release-document, evidence-test, importer, and retained campaign-evidence paths.

Two fixed-epoch calibration builds used `SOURCE_DATE_EPOCH=1786608259`, the base commit timestamp. Their wheel bytes were reproducible at SHA-256 `0F9D3B900E26B47E8F7C8A077931600351D051708881F473DBAF0C076E29ED6D`. Setuptools still assigned current mtimes to generated sdist entries, so raw sdist archives differed; after excluding only member mtimes, both produced the same 75-entry content-manifest SHA-256, `4E1ADA14555CCF663C9E87545AC476013E8726E43D3E894FF4CBF469E2C54776`. Per-run raw sdist hashes remain authoritative for each captured build.

This candidate does not itself close Task 11: the result block and its executable assertions are post-run release-record changes. A final settled-input rerun and both independent reviews remain required.

## Settled-input exact-final verification

Final root: `D:\tmp\kokoroarc-m7-release-20260814-final2`. This rerun included the corrective campaign evidence, all disclosed harness deviations, the candidate release record, and its executable assertions. All temporary, pytest, build, and capture paths remained beneath the final D:-based root.

The complete repository suite exited `0`: **`1913 passed, 24 skipped` in 160.54 seconds**. Every skip was again an explicit Windows capability limitation for symlinks, junctions, or FIFOs. There were no failures or errors. Captured stdout was 6,995 bytes with SHA-256 `8A7450B26067B2ED88EC14599FC66C892B3B75F08396051D675BA2C0C7F5E119`; stderr was empty with SHA-256 `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`.

The final clean build used `SOURCE_DATE_EPOCH=1786608259`, exited `0`, and printed `Successfully built kokoroarc-0.0.0.dev0.tar.gz and kokoroarc-0.0.0.dev0-py3-none-any.whl`:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `kokoroarc-0.0.0.dev0-py3-none-any.whl` | 111,414 | `0F9D3B900E26B47E8F7C8A077931600351D051708881F473DBAF0C076E29ED6D` |
| `kokoroarc-0.0.0.dev0.tar.gz` | 86,031 | `2F22933EA8326B706DA77C7FE6EF0A36747246BE406F7A290DA59B071DA64FDF` |

The wheel contained 58 entries and the sdist 75. Both retained all six research modules and all eight research schemas. The embedded README SHA-256 was `0F345F780A742B8552C34134641B8BA23C15B615D8A67F5E996F7303E9B5881D`; the normalized sdist content-manifest SHA-256 was `4E1ADA14555CCF663C9E87545AC476013E8726E43D3E894FF4CBF469E2C54776`. The wheel SHA-256 matched both fixed-epoch calibration builds byte-for-byte.

The standard validator separately exited `0` and printed `Skill is valid!` for all three Skills. `git diff --check` exited `0`; only LF-to-CRLF conversion notices were printed. The intended-change audit contained only Task 11's current research Skill correction, plan/release documents, baseline/results records, evidence tests, two reproducible importers, and retained approved1/approved2 campaign evidence.

The commit-preparation audit additionally treats `tests/skills/evidence/researching-characters/**` as byte-exact data via `.gitattributes` `-text`. This is required because the retained evaluator outputs include intentional trailing whitespace or terminal blank lines and their raw bytes are hash-bound. `git diff --cached --check` passes for every non-evidence path; the evidence subtree is deliberately excluded from whitespace normalization and its executable checks independently recompute every retained-file SHA-256.

Because this section and its focused executable assertion were the only post-gate edits at that time, the product code, schemas, Skills, retained evaluator artifacts, and broad test corpus exercised by the settled-input run were unchanged. The focused release-evidence tests were rerun after recording these values. That historical candidate reported **PASS**, but later independent review invalidated it for Task 11 closure because the exact committed range and fresh-checkout evidence did not satisfy all declared gates.

## Closure-review remediation after `b073381`

Review of exact commit `b07338101b37c66080f9b7f82de7a84919d9b56c` found four Important closure gaps:

1. only `skills/using-kokoroarc/**` was pinned to LF, so a fresh Windows checkout with `core.autocrlf=true` changed the current research Skill bytes and broke its retained SHA-256 binding;
2. `git diff --check 274c5a57051b8ee31d95deab11ae26d00707911a b073381` reported CR-at-EOL and intentional raw-capture whitespace across the byte-exact evidence subtree, contradicting the recorded exact-range gate;
3. both campaign importers assigned assertion truth from constants instead of deriving it from retained evidence; and
4. `final.md` was only named by the evaluator report, not independently compared with the platform's final agent message.

The remediation pins `skills/**` to LF and gives the raw campaign subtree a scoped Git whitespace policy: `cr-at-eol,-blank-at-eol,-blank-at-eof`. Raw evaluator files remain `-text` and byte-exact. The exact Task 11 range is now an executable `git diff --check` regression, while fresh-checkout coverage verifies the Skill and evidence hashes under Windows autocrlf behavior.

All 33 original evaluator threads were located through their non-sensitive `agent_path` in the local Codex session records. Each run now retains the exact raw JSONL records for the platform `final_answer` event, matching assistant response item, and `task_complete.last_agent_message`, plus a session identity/hash record. The verifier proves all three message fields are identical and compares them with `final.md` using only `lf_and_strip_terminal_lf`. No evaluator rerun was needed, and no raw evaluator final, report, or command capture was edited.

Every declared assertion is now independently recomputed from retained finals, reports, captures, deterministic validation pairs, and protected-state evidence. The baseline RED and both Skill campaign outcomes reproduce exactly without `BASELINE_PASSES`, unconditional `passed=True`, or a literal corrective behavior PASS. The focused research/release verifier passes **28 tests**.

A D:-confined full-suite remediation preflight at `D:\tmp\kokoroarc-m7-remediation-preflight-20260814-02` exited `0`: **`1919 passed, 24 skipped` in 160.54 seconds**. Captured stdout was 7,155 bytes with SHA-256 `6C73C2A057A36110C9D467CEF0374D38E5BDCBF79D07343DB1225DA0BF79B0C1`; stderr was empty with SHA-256 `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`. This preflight is evidence for the remediation, not the fresh exact-commit closure run.

## Verified product gates before this record

- Task 8 exact research-to-authoring gate: `380 passed, 7 skipped`.
- Full unit regression after Task 8: `1411 passed, 3 skipped`.
- Task 9 research security/storage/CLI gate: `118 passed, 4 skipped`.
- Broad research plus authoring gate: `866 passed, 11 skipped`.
- All skips were documented platform capability cases for Windows symlink/FIFO behavior.

These results were obtained before the release-document changes. The settled-input exact-final section above supersedes the earlier inline checkpoint for Task 11 closure.

## Remaining closure gates

1. Commit the exact Milestone 7 release evidence.
2. Obtain fresh independent specification and quality reviews on that exact commit.
3. Close Milestone 7 only after every remaining gate reports PASS.

Current status: Behavioral campaign: CORRECTIVE PASS 11/11. Corrective harness: COMPLETED WITH DISCLOSED DEVIATIONS. Exact-final verification: REOPENED AFTER IMPORTANT REVIEW FINDINGS. Fresh exact-commit specification review: PENDING. Fresh exact-commit quality review: PENDING.
