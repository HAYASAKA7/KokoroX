# Milestone 7 research release verification

## Scope and exact status

This record covers the inline product, CLI, Skill-structure, smoke, and distribution checks completed for Milestone 7 on 2026-08-13 (Asia/Hong_Kong). Milestone 7 does not approve the complete standalone suite.

- Build base HEAD: `7ec68e553b478411d3b9f7e8207a70df2b382b19`
- Build input: that HEAD plus the current `README.md` patch only among `README.md`, `pyproject.toml`, `src/`, and `schemas/`
- Isolated root: `D:\tmp\kokoroarc-m7-release-20260813-inline1`
- Behavioral campaign: CORRECTIVE PASS 11/11 (first batch remains Skill PASS 10/11, RED 1/11)
- Corrective harness: COMPLETED WITH DISCLOSED DEVIATIONS
- Exact-final verification: SEVENTH SPEC-REVIEW REMEDIATION PREFLIGHT PASS; EXACT-TREE GATES AND FRESH REVIEWS PENDING
- Review of commit `b07338101b37c66080f9b7f82de7a84919d9b56c`: IMPORTANT FINDINGS REMEDIATED
- Fresh specification review of `6afcbeccbc43814700e42c4626a6a9b8e1bddce0`: PASS
- Fresh quality review of `6afcbeccbc43814700e42c4626a6a9b8e1bddce0`: IMPORTANT FINDINGS REMEDIATED
- Fresh specification review of `646fc91f27eb723334f4ff4b25309985b56046a3`: IMPORTANT FINDINGS REMEDIATED
- Fresh quality review of `646fc91f27eb723334f4ff4b25309985b56046a3`: IMPORTANT FINDINGS REMEDIATED
- Fresh specification review of `531ce43cf2f8dff4708fa64c601ec72bd680cbf2`: IMPORTANT FINDINGS REMEDIATED
- Fresh quality review of `531ce43cf2f8dff4708fa64c601ec72bd680cbf2`: NOT RUN; SPECIFICATION REVIEW FAILED
- Fresh specification review of `57ea7ea7f215cedcf800dc266bd5486eb981976a`: IMPORTANT FINDINGS REMEDIATED
- Fresh quality review of `57ea7ea7f215cedcf800dc266bd5486eb981976a`: NOT RUN; SPECIFICATION REVIEW FAILED
- Fresh specification review of `bea1fce58cbbf0c00a49da2fa662e0dc30c2d7b1`: IMPORTANT FINDING REMEDIATED
- Fresh quality review of `bea1fce58cbbf0c00a49da2fa662e0dc30c2d7b1`: NOT RUN; SPECIFICATION REVIEW FAILED
- Fresh specification review of `670e44bf126daa2198c77889ad3bf142b60d0b72`: IMPORTANT FINDINGS REMEDIATED
- Fresh quality review of `670e44bf126daa2198c77889ad3bf142b60d0b72`: NOT RUN; SPECIFICATION REVIEW FAILED
- Fresh specification review of `bc183a8f92452a82b733459118764e9304d4878a`: IMPORTANT FINDINGS REMEDIATED
- Fresh quality review of `bc183a8f92452a82b733459118764e9304d4878a`: NOT RUN; SPECIFICATION REVIEW FAILED
- Fresh specification review of `bb492bcf1aafa3d1132bc53872616db7565d7e37`: IMPORTANT FINDINGS REMEDIATED
- Fresh quality review of `bb492bcf1aafa3d1132bc53872616db7565d7e37`: NOT RUN; SPECIFICATION REVIEW FAILED
- Fresh specification review of seventh spec-review remediation settled tree: PENDING
- Fresh quality review of seventh spec-review remediation settled tree: PENDING

The approved 22-run first campaign remains behaviorally immutable, including its one failed Skill case. The separately approved 11-run corrective Skill-only campaign passed all declared behavioral assertions against the current Skill. Ten harness/report deviations across seven cases are retained and disclosed; they do not reclassify behavior or erase the failed first campaign. Review of the first release-evidence commit found Important checkout, whitespace-gate, assertion-adjudication, and final-message-binding gaps. Later reviews found additional fail-open adjudication, command-provenance, confinement, inert-source, sanitizer, raw-replay, quoted-wrapper, shell-reachability, environment-access, and structured-secret gaps. Each accepted finding has a focused RED regression and fail-closed remediation. Task 11 still requires both independent reviews to pass on the newest settled release-record tree. No canon-accuracy claim or complete-suite approval is implied by the checks below.

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

Every declared assertion is now independently recomputed from retained finals, reports, captures, deterministic validation pairs, and protected-state evidence. The baseline RED and both Skill campaign outcomes reproduce exactly without `BASELINE_PASSES`, unconditional `passed=True`, or a literal corrective behavior PASS. The focused research/release verifier passes **30 tests**.

A D:-confined full-suite remediation preflight at `D:\tmp\kokoroarc-m7-remediation-preflight-20260814-02` exited `0`: **`1919 passed, 24 skipped` in 160.54 seconds**. Captured stdout was 7,155 bytes with SHA-256 `6C73C2A057A36110C9D467CEF0374D38E5BDCBF79D07343DB1225DA0BF79B0C1`; stderr was empty with SHA-256 `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`. This preflight is evidence for the remediation, not the fresh exact-commit closure run.

## Remediated exact-commit verification

Commit `c8095c105f4866f3728debfa1ca2568f28fff2be` was checked from the D:-confined root `D:\tmp\kokoroarc-m7-remediation-final3-c8095c1-01`. The complete repository suite exited `0`: **`1920 passed, 24 skipped` in 159.80 seconds**. Every skip was an explicit Windows capability limitation for symlinks, junctions, or FIFOs; there were no failures or errors. Captured stdout was 7,091 bytes with SHA-256 `4B8A46FAFB0ACAC1C71EB9A56E0BC8E97BDBF50C627FBB6B442AF988896E2D40`; stderr was empty with SHA-256 `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`.

The fixed-epoch build used `SOURCE_DATE_EPOCH=1786608259`, exited `0`, and produced:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `kokoroarc-0.0.0.dev0-py3-none-any.whl` | 111,414 | `0F9D3B900E26B47E8F7C8A077931600351D051708881F473DBAF0C076E29ED6D` |
| `kokoroarc-0.0.0.dev0.tar.gz` | 86,076 | `73174C633EC2A77AA7B403BA9F901A2F834C21FA1FFD6A0E151EDAB1CFA041FF` |

The wheel contained 58 entries and the sdist 75. Both retained all six research modules and all eight research schemas. The embedded README SHA-256 was `0F345F780A742B8552C34134641B8BA23C15B615D8A67F5E996F7303E9B5881D`; the normalized sdist content-manifest SHA-256 was `4E1ADA14555CCF663C9E87545AC476013E8726E43D3E894FF4CBF469E2C54776`.

All three standard Skill validators exited `0` and printed `Skill is valid!`. `git diff --check 274c5a57051b8ee31d95deab11ae26d00707911a c8095c105f4866f3728debfa1ca2568f28fff2be` exited `0` with no output. A detached fresh checkout configured with `core.autocrlf=true` passed the 29-test focused verifier, retained the three expected Skill hashes with zero CRLF pairs, reproduced all 984 evidence blobs byte-for-byte, and remained clean.

## Settled remediation release gate

The release-record commit was verified from `D:\tmp\kokoroarc-m7-remediation-final4-settled-01`, with every temporary, pytest, build, and capture path beneath that root. The complete suite again exited `0` with **`1921 passed, 24 skipped`**, no failures or errors, and only the same documented Windows capability skips. Exact command output and hashes are retained beneath the root in `pytest-result.json`, `pytest.stdout.txt`, and `pytest.stderr.txt`.

The fixed-epoch build again exited `0`, produced both archives, retained 58 wheel entries and 75 sdist entries, and included all six research modules and all eight research schemas. The wheel SHA-256 was `0F9D3B900E26B47E8F7C8A077931600351D051708881F473DBAF0C076E29ED6D`; the embedded README SHA-256 was `0F345F780A742B8552C34134641B8BA23C15B615D8A67F5E996F7303E9B5881D`; and the normalized sdist content-manifest SHA-256 was `4E1ADA14555CCF663C9E87545AC476013E8726E43D3E894FF4CBF469E2C54776`. Per-run raw archive names, sizes, and SHA-256 values are retained in `archive-inventory.json` because generated sdist member mtimes remain time-varying.

All three standard Skill validators passed. The exact Task 11 range passed `git diff --check`, the worktree was clean, and a detached `core.autocrlf=true` checkout reproduced the focused verifier, Skill hashes, and all retained evidence bytes. This historical exact-final gate reported **PASS ON SETTLED REMEDIATION COMMIT**, but the later fresh quality review invalidated it for Task 11 closure. Milestone 7 and the complete standalone suite remain open.

## Post-settlement quality-review remediation

Fresh specification review of exact commit `6afcbeccbc43814700e42c4626a6a9b8e1bddce0` passed with no Critical or Important findings. Fresh quality review confirmed that the retained campaign itself was honest: all 917 reproducible importer outputs matched, all 785 raw-ledger files matched their approved D:-based roots, all 33 retained final messages rebound to the original session logs, and no high-confidence secret was found. The quality review nevertheless found two Important verifier defects:

1. assertion adjudication could pass with missing commands, semantically empty but byte-identical JSON, an absolute output outside the run root, an environment-secret-reading command, or a final response naming a fabricated artifact and hash; and
2. the importer implemented only protected-user-path redaction even though the approved campaign declared `environment_secrets` and `credentials`, while the repository scanner and final-event binder recognized only a narrow subset of those classes.

The remediation makes the adjudicator fail closed. Determinism assertions now require successful structured CLI records whose declared stdout and stderr captures exist, whose stderr is empty, whose paired stdout is byte-identical, and whose JSON satisfies the command-specific semantic contract. Private compilation must be captured exactly once and match the validated bundle identity, hashes, lifecycle, conflicts, limitations, and coverage. Lifecycle reporting is compared with the captured bundle values, and an eligible handoff must contain that exact captured artifact ID and bundle SHA-256. Output paths are normalized and confined to the declared case root and allowlisted run locations. Source-safety checks reject environment expansion, secret APIs, arbitrary interpreter snippets, network commands, dynamic execution, and executable source files.

A shared sanitizer now covers protected user-profile paths, environment-secret assignments (including common camel-case and separator variants), authorization headers, credential-bearing URLs, private-key blocks, and common provider-token signatures. Both campaign importers, the final-event binder, and the repository evidence scanner use this shared policy. Importer metadata maps every declared redaction class to its retained placeholder. Synthetic regression fixtures prove both sanitization and rejection behavior without changing any raw evaluator capture.

Recomputation also corrected eight legacy baseline assertion booleans across four runs: those agents described an existing bundle but did not retain successful compile/duplicate-validation evidence sufficient to prove compilation, exact lifecycle binding, or exact handoff. The corrections make those individual assertions RED; the aggregate baseline remains RED in 9/11 cases, the first Skill batch remains PASS 10/11 with its original single failed case, and the corrective Skill batch remains PASS 11/11. No evaluator final, report, command capture, or protected-state record was edited.

The expanded focused research and release-evidence gate now passes **40 tests**. A D:-confined full-suite preflight at `D:\tmp\kokoroarc-m7-quality-remediation-preflight-01` passed with **1931 passed, 24 skipped** in 164.66 seconds; every skip was the same explicit Windows symlink, junction, or FIFO capability case. This is remediation preflight evidence, not Task 11 closure. A committed exact-input full-suite/build/validator/fresh-checkout gate and two fresh independent reviews are still required.

## Post-settlement remediation exact gates

Implementation commit `ee5d2073b76d2760bbcf8838da8a2f7e80df6aa7` was verified from `D:\tmp\kokoroarc-m7-quality-remediation-exact-ee5d207-01`. The complete repository suite exited `0` with **1931 passed, 24 skipped** in 168.82 seconds. There were no failures or errors; every skip was an explicit Windows capability case. Captured stdout was 7,284 bytes with SHA-256 `9019A197C95479E416D385FA3CB630191A79EBB4C9C0A3B414B897ED4377B31F`; stderr was empty with SHA-256 `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`.

The fixed-epoch build used `SOURCE_DATE_EPOCH=1786608259`, exited `0`, and printed the expected successful two-archive message. Its inventory was:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `kokoroarc-0.0.0.dev0-py3-none-any.whl` | 111,414 | `0F9D3B900E26B47E8F7C8A077931600351D051708881F473DBAF0C076E29ED6D` |
| `kokoroarc-0.0.0.dev0.tar.gz` | 86,055 | `EAC007AF8B70CD87354E5DC1C1B1B7CA8E743709F0F3F0D0A953AD2618381DA3` |

The wheel contained 58 entries and the sdist 75. Both retained all six research modules and all eight research schemas. The embedded README SHA-256 remained `0F345F780A742B8552C34134641B8BA23C15B615D8A67F5E996F7303E9B5881D`, and the normalized sdist content-manifest SHA-256 remained `4E1ADA14555CCF663C9E87545AC476013E8726E43D3E894FF4CBF469E2C54776`.

All three standard Skill validators exited `0`, printed `Skill is valid!`, and retained empty stderr. `git diff --check 274c5a57051b8ee31d95deab11ae26d00707911a ee5d2073b76d2760bbcf8838da8a2f7e80df6aa7` exited `0` with empty output, and the implementation-commit worktree was clean.

A detached clone at `D:\tmp\kokoroarc-m7-fresh-checkout-ee5d207-01` configured with `core.autocrlf=true` passed the 40-test focused verifier. Its stdout SHA-256 was `29BFB709927BFD3B65280102AB93BEE792891390333BE287756013FFD8E46C82`; stderr was empty. The audit reproduced all 984 retained evidence blobs byte-for-byte, retained the three declared Skill hashes with zero CRLF pairs, passed the exact-range whitespace check, and remained clean.

The release-record tree, including this result block and its unchanged executable assertions, is assigned the settled rerun root `D:\tmp\kokoroarc-m7-quality-remediation-settled-01`. The settled gate requires the same 1931/24 full-suite outcome, fixed-epoch wheel and normalized-sdist identities, three validator passes, exact-range diff check, and clean detached-checkout result before this record is committed. Raw per-run archive and command hashes remain captured under that root where generated sdist mtimes or path-bearing test output are expected to vary.

The post-settlement remediation exact status is **PASS ON POST-SETTLEMENT REMEDIATION TREE; FRESH REVIEWS PENDING**. Task 11 and Milestone 7 remain open until fresh specification and quality reviews of the settled commit both report no Critical or Important findings.

## Replay-hardening review remediation

Fresh specification and quality reviews of exact commit `646fc91f27eb723334f4ff4b25309985b56046a3` both reported FAIL with Important findings. Their independent corpus audits still found the retained campaign authentic: all 785 ledger-bound raw files matched the two approved D:-based roots, all 33 final messages rebound to their original session logs, and the detached checkout preserved all 984 evidence files. The combined closure defects were:

1. CLI actions were label-bound rather than executable-bound, so a record such as `Write-Output research request validate` could inherit valid captures and pass without invoking KokoroArc;
2. an absolute compile output outside the approved run root could pass when its path suffix resembled the expected private bundle path;
3. authorization and inert-source checks accepted commands including `cmd /d /c set` and `node workspace/sources/payload.js`; and
4. the shared sanitizer only partially handled quoted multiword secrets, JSON Authorization values, encrypted private keys, and serialized forms. Its changed user-profile pattern also prevented the current importer from reproducing 12 sanitized historical files.

Commit `a3fcdb809945cf823f3dd860c65666f0cab6b4be`, tree `5f545d2695d5c4bf849876307c2018e21c6cb16e`, closes those paths with regression-first changes. Action evidence now requires an exact supported KokoroArc executable/argv form, including a valid CLI command segment inside approved wrappers. Importers provide a trusted raw-run root independently of the evaluator report; compiled output must resolve exactly beneath that root, and output confinement fails when compilation cannot be bound. Command safety scans both raw wrapper text and structured argv, rejects environment dumps, unapproved interpreters, and executable source forms, and binds source-secret safety to the same fail-closed result.

The shared sanitizer preserves the historical user-profile path suffix while covering quoted multiword secrets, plain and serialized JSON Authorization values, encrypted private-key blocks, and serialized credential assignments. The final-event binder scans decoded selected-event values recursively. A full replay using the current importer reproduced all 785 ledger-bound raw files byte-for-byte, including the 12 files with redactions, with zero raw-hash, retained-hash, redaction-count, or regenerated-byte mismatches.

The exact implementation gate is retained at `D:\tmp\kokoroarc-m7-replay-hardening-exact-a3fcdb8-01`. With `PYTHONPATH=src`, disabled pytest caching, and all temporary paths confined beneath that root, the complete suite exited `0`: **`1942 passed, 24 skipped` in 164.08 seconds**. There were no failures or errors; every skip was an explicit Windows symlink, junction, or FIFO capability case. Captured stdout was 7,236 bytes with SHA-256 `23967ABA7BF55C58C12560516DDB12535A8FC59DF00C77954A2E17A10578FA8`; stderr was empty with SHA-256 `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`.

The fixed-epoch build used `SOURCE_DATE_EPOCH=1786608259`, exited `0`, and produced:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `kokoroarc-0.0.0.dev0-py3-none-any.whl` | 111,414 | `0F9D3B900E26B47E8F7C8A077931600351D051708881F473DBAF0C076E29ED6D` |
| `kokoroarc-0.0.0.dev0.tar.gz` | 86,061 | `166B16F1883B3CE838744A7DE6FED4EF57085035C1B6CB79C0AC2AB6EABD1F0D` |

The wheel retained 58 entries and the sdist 75; both contained all six research modules and all eight research schemas. The embedded README SHA-256 remained `0F345F780A742B8552C34134641B8BA23C15B615D8A67F5E996F7303E9B5881D`, and the normalized sdist content-manifest SHA-256 remained `4E1ADA14555CCF663C9E87545AC476013E8726E43D3E894FF4CBF469E2C54776`. All three standard Skill validators exited `0`, printed `Skill is valid!`, and retained empty stderr. The exact Task 11 range passed `git diff --check` with empty output, and the implementation worktree was clean.

A detached clone at `D:\tmp\kokoroarc-m7-fresh-checkout-a3fcdb8-01` configured with `core.autocrlf=true` passed the **51 tests** in the focused research/release verifier in 9.59 seconds. Captured stdout SHA-256 was `74FA2331E2AB269DCFAAE95D001DC9DB433D4BD772BEF3B6F314C84C8FB536A0`; stderr was empty. It preserved all 984 retained evidence files byte-for-byte, retained the three declared Skill hashes with zero CRLF pairs, passed the exact-range whitespace check, and remained clean.

The release-record tree containing this section and its executable assertion is assigned the settled root `D:\tmp\kokoroarc-m7-replay-hardening-settled-01`. Before review, that exact commit must pass the complete suite with the additional release-record test, the same fixed-epoch package identities, all three validators, the 785-file raw replay, the exact-range whitespace/status gate, and a detached `core.autocrlf=true` checkout. The status is **PASS ON REPLAY-HARDENING SETTLED TREE; FRESH REVIEWS PENDING** only while those retained artifacts exist and match that exact commit.

## Second specification-review remediation

Fresh specification review of exact settled commit `531ce43cf2f8dff4708fa64c601ec72bd680cbf2` confirmed its positive gates but returned FAIL with three Important findings. Quality review was not run because the required specification-first review order had already failed:

1. a quoted non-executing wrapper such as `Write-Output '; python -m kokoroarc.cli research …'` could retain claimed argv/captures and pass CLI provenance because the wrapper regex searched inside quoted text;
2. source-command safety accepted both the PowerShell alias form `dir env:` and a quoted Node executable reading `process['env']`; and
3. assignment redaction stopped at an escaped inner quote or the first whitespace inside a structured value, leaked the remaining secret text, and then declared the partial retained value clean.

The remediation masks quoted and comment text before matching a wrapper CLI segment. Structured argv still supplies the exact action, while the raw wrapper must now contain the same action in executable shell code. Any report that claims a bundle compile but cannot bind it to a trusted executable record also fails output confinement. Source safety now recognizes PowerShell environment-provider aliases, bracket-form environment access, and quoted paths to unapproved interpreters.

The sanitizer replaces its lazy assignment-value regex with a structured assignment-value scanner. It consumes escaped quoted values to a real value boundary, parses balanced object/array values while respecting nested quotes and escapes, and redacts the complete value. An adjacent regression also rejects redaction-placeholder smuggling such as a quoted `<redacted-environment-secret>` immediately followed by secret text. Reapplying the updated sanitizer still reproduces all 785 ledger-bound raw files byte-for-byte, including the same 12 redacted files.

The focused research/release evidence gate now passes **57 tests**. A D:-confined full-suite preflight at `D:\tmp\kokoroarc-m7-spec2-remediation-preflight-01` exited `0`: **`1948 passed, 24 skipped` in 168.92 seconds**. There were no failures or errors; every skip was an explicit Windows symlink, junction, or FIFO capability case. Captured stdout was 7,188 bytes with SHA-256 `519FD46D9CD23957DF336D1BB861F6EE1FE8ED3C0C746EE26F4F524202D0F8BB`; stderr was empty with SHA-256 `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`. This is dirty-tree remediation preflight evidence, not Task 11 closure.

The release-record tree containing this section and its executable assertion is assigned `D:\tmp\kokoroarc-m7-spec2-remediation-settled-01`. Before review, that exact commit must pass the complete suite, the fixed-epoch package build/inventory, all three validators, the 785-file raw replay, the exact base-to-HEAD whitespace and clean-status gates, and a fresh detached `core.autocrlf=true` checkout with focused tests plus 984-file byte reproduction. The status is **PASS ON SPEC-REVIEW REMEDIATION SETTLED TREE; FRESH REVIEWS PENDING** only while those artifacts bind the exact commit.

## Third specification-review remediation

Fresh specification review of exact commit `57ea7ea7f215cedcf800dc266bd5486eb981976a` reconfirmed that every previously reported attack failed closed. It nevertheless could not pass after promoting three adjacent probes to full retained-run false passes. Quality review was not run because the required specification-first review order had already failed:

1. CLI text placed wholly inside a PowerShell block comment could inherit claimed argv and valid captures, causing request/workspace/bundle validation, compilation, and confinement to pass without an executable action;
2. a quoted full-path Python executable running `-c` could leave authorization, inert-source, secret, and confinement assertions true; and
3. a credential-bearing URL beginning with an existing redaction placeholder plus an escaped JSON Authorization value could retain secret suffixes and then self-certify as clean.

The regression-first remediation masks nested block comments and recognizes CLI provenance only at balanced top-level shell scope. It also narrows wrapper delimiters, rejects a shell terminator before a claimed action, and adds short-circuit and dead-branch cases so top-level wrapper reachability is tested as a class. Command safety now recognizes quoted Python paths, and output confinement is valid only when every recorded command passes the same fail-closed safety check.

Authorization redaction now uses the structured value scanner rather than a lazy closing-quote match. Placeholder idempotence requires the complete value to equal the expected placeholder, so a placeholder-prefixed credential-bearing URL or Authorization value with trailing material is redacted again rather than trusted. The focused research/release evidence gate passes **64 tests**, including all 785 ledger-bound raw-file replay comparisons.

A D:-confined dirty-tree preflight at `D:\tmp\kokoroarc-m7-spec3-remediation-preflight-01` exited `0`: **`1955 passed, 24 skipped` in 161.11 seconds**. There were no failures or errors; every skip was an explicit Windows symlink, junction, or FIFO capability case. Captured stdout was 7,188 bytes with SHA-256 `C8D6F6ED7E9BF8C7FAF3159D0077AC6CF88CAEE3ABF79C319DE69BE9F87F3CE5`; stderr was empty with SHA-256 `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`. This is remediation preflight evidence, not Task 11 closure.

The release-record tree containing this section and its executable assertion is assigned `D:\tmp\kokoroarc-m7-spec3-remediation-settled-01`. After it is committed, that exact tree must pass the complete suite, fixed-epoch build and inventory, all three validators, raw replay, exact base-to-HEAD whitespace and clean-status checks, and a fresh detached `core.autocrlf=true` checkout. Its status may be recorded as **PASS ON THIRD SPEC-REVIEW REMEDIATION SETTLED TREE; FRESH REVIEWS PENDING** only while those exact artifacts exist and match; both independent reviews are still required.

## Fourth specification-review remediation

Fresh specification review of exact settled commit `bea1fce58cbbf0c00a49da2fa662e0dc30c2d7b1` confirmed every earlier attack failed closed and independently reproduced the complete positive release gates. It nevertheless returned FAIL with one Important evidence-integrity finding, so quality review was not run: wrapper provenance remained action-only. A retained PowerShell wrapper could run the same CLI action with `--help`, omit or change required arguments, append a failing or extra command, or redirect to capture paths different from the report while the claimed argv and retained captures caused every request, workspace, compile, bundle, and confinement assertion to pass.

The regression-first remediation binds each accepted PowerShell wrapper to the complete child invocation declared by structured argv, both stdout and stderr capture paths declared by the report, and the exact nonzero-exit propagation guard. The wrapper grammar is anchored, permits only the retained runtime setup sequence, and rejects any leading, nested, short-circuited, or trailing shell operation. Existing direct command records remain bound to their structured argv without treating a human-readable action prefix as a second executable wrapper. Eight focused mutations cover help-only, missing-argument, changed-path, alternate-switch, post-action-failure, trailing-output, and both capture-path mismatches. Any structured CLI record that declares an action but fails this binding now also fails tool safety and output confinement.

The focused research/release evidence gate passes **75 tests**. A D:-confined dirty-tree preflight at `D:\tmp\kokoroarc-m7-spec4-remediation-preflight-04` exited `0`: **`1966 passed, 24 skipped` in 163.90 seconds**. There were no failures or errors; every skip was an explicit Windows symlink, junction, or FIFO capability case. Captured stdout was 7,188 bytes with SHA-256 `A77570A9986AB19386114ACF4AF0E822977E1E877E4159293026FF69E6BF58C1`; stderr was empty with SHA-256 `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`. This is remediation preflight evidence, not Task 11 closure.

Three earlier attempts are explicitly excluded from that gate. The command runner terminated `D:\tmp\kokoroarc-m7-spec4-remediation-preflight-01` before pytest started; after verifying it held only two empty capture files and no Python process, that root was removed. `D:\tmp\kokoroarc-m7-spec4-remediation-preflight-02` reached collection without the repository `src` path and exited `2` with 38 `ModuleNotFoundError` collection errors before product tests ran. Corrected run `D:\tmp\kokoroarc-m7-spec4-remediation-preflight-03` passed 1964 tests but was superseded after an adjacent direct-summary regression was added. The final `-04` run explicitly bound `PYTHONPATH`, `TEMP`, `TMP`, pytest temporary data, and captures to the intended worktree and D: root.

The release-record tree containing this section and its executable assertion is assigned `D:\tmp\kokoroarc-m7-spec4-remediation-settled-01`. After it is committed, that exact tree must pass the complete suite, fixed-epoch build and inventory, all three validators, raw replay, final-message binding, exact base-to-HEAD whitespace and clean-status checks, and a fresh detached `core.autocrlf=true` checkout. Its status may be recorded as **PASS ON FOURTH SPEC-REVIEW REMEDIATION SETTLED TREE; FRESH REVIEWS PENDING** only while those exact artifacts exist and match; both independent reviews are still required.

## Fifth specification-review remediation

Exact fourth-remediation commit `670e44bf126daa2198c77889ad3bf142b60d0b72` and tree `d4ef4f825ef3fcd85019411a47ec45531c9295a9` passed the assigned `D:\tmp\kokoroarc-m7-spec4-remediation-settled-01` gate: `1966 passed, 24 skipped`, fixed-epoch build and archive inventory, all three Skill validators, 785-file raw replay, 33 final-message bindings, exact-range whitespace and clean-status checks, and a fresh detached `core.autocrlf=true` checkout with all 984 evidence files byte-identical and 75 focused tests. The build used the Task 11 base epoch `1786608259`; the separately retained setup attempt that used the HEAD epoch was excluded from the gate.

Fresh specification review still returned FAIL with three Important evidence-integrity findings, so quality review was not run. Wrapper binding treated `python`, `py`, and an arbitrary same-basename executable path as equivalent; accepted an arbitrary wrapper `PYTHONPATH`; did not bind CLI working directory, login-shell mode, or execution-status lifecycle to the trusted run root and retained contract; and silently selected the first of conflicting capture aliases. Seven independent full-run mutants preserved every one of the 19 declared assertions despite executable substitution, a different import root, an outside working directory, contradictory lifecycle metadata, or contradictory stdout fields.

The regression-first remediation now requires the wrapper's exact executable token to match structured argv and its captured import root to match the reported `PYTHONPATH`. Every recognized CLI record binds an explicitly retained working directory to the trusted run root, requires non-login execution when the field is present, accepts only the retained completed or disclosed prelaunch execution-status values, and requires both stdout and stderr evidence. If both `stdout_file`/`stdout_capture` or `stderr_file`/`stderr_capture` are present, their normalized paths must agree; conflicting capture aliases fail closed everywhere the record is used. The seven focused mutations cover an untrusted executable path, a `python`-to-`py` alias, changed `PYTHONPATH`, outside `cwd`, `login: true`, `not_started`, and duplicate capture disagreement.

The focused research/release evidence gate passes **83 tests**. The D:-confined full-suite dirty-tree preflight at `D:\tmp\kokoroarc-m7-spec5-remediation-preflight-01` exited `0`: **`1974 passed, 24 skipped` in 170.74 seconds**. Every skip was an explicit Windows symlink, junction, or FIFO capability case. Captured stdout was 7,268 bytes with SHA-256 `95022C1B29E414D28554A40C7E8E5FBC5D3ED2088CF7AEF41B619B40EC552EB1`; stderr was empty with SHA-256 `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`. The harness elapsed time was 172.08 seconds. This is dirty-tree remediation preflight evidence, not Task 11 closure; the release-record edits that retain it are verified by the focused gate and must be rerun on the exact committed tree.

The release-record tree containing this section and its executable assertion is assigned `D:\tmp\kokoroarc-m7-spec5-remediation-settled-01`. After commit, that exact tree must pass the complete suite, fixed-epoch build and archive inventory, all three validators, raw replay, final-message binding, exact base-to-HEAD whitespace and clean-status checks, and a fresh detached `core.autocrlf=true` checkout. Its status may be recorded as **PASS ON FIFTH SPEC-REVIEW REMEDIATION SETTLED TREE; FRESH REVIEWS PENDING** only while those exact artifacts exist and match; both independent reviews remain required.

## Sixth specification-review remediation

Exact fifth-remediation commit `bc183a8f92452a82b733459118764e9304d4878a`, tree `aa94d127c51dd8f5879d6ee3fdfd38f83d0893db`, and parent `670e44bf126daa2198c77889ad3bf142b60d0b72` passed the assigned `D:\tmp\kokoroarc-m7-spec5-remediation-settled-01` gate: `1974 passed, 24 skipped`, the fixed-base-epoch build and archive inventory, all three Skill validators, 785-file raw replay, 33 final-message bindings, exact-range whitespace and clean-status checks, and a fresh detached `core.autocrlf=true` checkout with all 984 evidence files byte-identical and 83 focused tests.

Fresh specification review still returned FAIL with three Important evidence-integrity findings, so quality review was not run. CLI executable and import-root evidence was only self-consistent rather than bound to an approval-controlled trust anchor; consistently substituting both wrapper and argv or both wrapper and reported `PYTHONPATH` preserved all 19 assertions. Missing or contradictory execution context, including absent `cwd` and `shell_login: true`, also passed. Finally, a new executable CLI wrapper could be hidden behind narrative-only structured argv, allowing an outside working directory to escape the per-record binding audit while all assertions stayed green.

The regression-first remediation moves executable prefix, import root, login mode, and required-context policy into approval-locked importer constants that are never derived from agent output. The current approved2 campaign requires its retained report environment and an explicit absolute per-command `cwd` equal to the trusted raw run root. It also requires the retained raw command wherever that approved transcript contains one, with a single approval-locked `spoiler-cutoff` argv-only exception; the immutable approved1 evidence keeps narrowly declared historical allowances for its absent context fields rather than rewriting old evidence. Every independently recognized research CLI occurrence in command text or argv is now audited even when the other field hides it, and all CLI-derived behavioral, tool-safety, and confinement assertions fail closed when the external trust context is absent or any record is unbound. Fifteen focused mutations cover consistent executable path and alias substitution, consistent import-root substitution, missing and relative command working directories, contradictory report login mode, absent report environment or `PYTHONPATH`, outside report context, hidden-wrapper forms with narrative, misleading help metadata, or arbitrarily long spacing, a missing raw command, and absent trusted context.

The focused research/release evidence gate passes **100 tests**. An initial D:-confined full-suite dirty-tree preflight at `D:\tmp\kokoroarc-m7-spec6-remediation-preflight-01` exited `0` with `1988 passed, 24 skipped`, but it was superseded after the two adjacent raw-command/help-token RED regressions were added. Replacement `D:\tmp\kokoroarc-m7-spec6-remediation-preflight-02` then exited `0` with `1990 passed, 24 skipped` but was superseded when exact help-token handling was unified and the overlong-spacing RED regression removed the scanner's arbitrary gap cap. The final frozen-tree preflight at `D:\tmp\kokoroarc-m7-spec6-remediation-preflight-03` exited `0`: **`1991 passed, 24 skipped` in 300.55 seconds**. Every skip was an explicit Windows symlink, junction, or FIFO capability case. Captured stdout was 7,268 bytes with SHA-256 `BA96DC9DE317B700D7A39A1B7DDB22FFCF4CE9478E26E03B98E32E5D1BE6E77A`; stderr was empty with SHA-256 `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`. The final harness elapsed time was 302.75 seconds. This is dirty-tree remediation preflight evidence, not Task 11 closure; the release-record edits that retain it are verified by the focused gate and must be rerun on the exact committed tree.

The release-record tree containing this section and its executable assertion is assigned `D:\tmp\kokoroarc-m7-spec6-remediation-settled-01`. After commit, that exact tree must pass the complete suite, fixed-base-epoch build and archive inventory, all three validators, raw replay, final-message binding, exact base-to-HEAD whitespace and clean-status checks, and a fresh detached `core.autocrlf=true` checkout. Its status may be recorded as **PASS ON SIXTH SPEC-REVIEW REMEDIATION SETTLED TREE; FRESH REVIEWS PENDING** only while those exact artifacts exist and match; both independent reviews remain required.

## Seventh specification-review remediation

Exact sixth-remediation commit `bb492bcf1aafa3d1132bc53872616db7565d7e37`, tree `7598e1612d1012e4e0f023aa6b995397188cdf0b`, and parent `bc183a8f92452a82b733459118764e9304d4878a` passed the assigned `D:\tmp\kokoroarc-m7-spec6-remediation-settled-01` gate: `1991 passed, 24 skipped`, the fixed-base-epoch build and archive inventory, all three Skill validators, 785-file raw replay, 33 final-message bindings, exact-range whitespace and clean-status checks, a 984-file original-session rebind, and a fresh detached `core.autocrlf=true` checkout with all 984 evidence files byte-identical and 100 focused tests.

Fresh specification review confirmed every mandatory executable, import-root, context, hidden-record, command, and capture mutation failed closed. It nevertheless returned FAIL with two Important evidence-integrity findings, so quality review was not run. First, a standalone `--help` string inside one quoted CLI data argument caused the entire record to be classified as help and skipped, allowing narrative argv plus an outside `cwd` to retain all 19 assertions. Second, an explicit successful `Copy-Item` to an absolute destination outside the trusted run root remained invisible when the agent-controlled `files_created` list omitted it.

The regression-first remediation parses each CLI tail with quote awareness and recognizes help only when `--help` is a complete argument token; quoted data and help-like substrings no longer suppress per-record binding. Successful-record and claimed-action paths share that same token rule. Command safety now derives explicit filesystem mutation destinations from copy, move, content, output, file-creation, removal, rename, redirection, and direct .NET file/directory operations. It also resolves simple literal destination variables and recognizes ordinary filesystem aliases. Absolute, upward-relative, protected-root, or otherwise non-allowlisted destinations fail tool safety and output confinement even when `files_created` omits them. Nine focused RED cases cover the quoted-data help record plus canonical copy, move, set-content, out-file, and new-item outside destinations, followed by the adjacent alias, redirection, and destination-variable forms.

The focused research/release evidence gate passes **110 tests**. The D:-confined full-suite dirty-tree preflight at `D:\tmp\kokoroarc-m7-spec7-remediation-preflight-01` exited `0`: **`1998 passed, 24 skipped` in 309.78 seconds**. Every skip was an explicit Windows symlink, junction, or FIFO capability case; there were no failures or errors. Captured stdout was 7,269 bytes with SHA-256 `FEA6AB106E4AEC7FE998A959195D759C89B3D090BBB94A871706DE4431A9C413`; stderr was empty with SHA-256 `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`. The harness elapsed time was 323.47 seconds. That passing run is retained but superseded because the three adjacent alias, redirection, and destination-variable RED cases were added afterward.

Replacement D:-confined dirty-tree preflight `D:\tmp\kokoroarc-m7-spec7-remediation-preflight-02` exited `0`: **`2001 passed, 24 skipped` in 320.40 seconds**. It had no failures or errors and only the same explicit Windows capability skips. Captured stdout was 7,269 bytes with SHA-256 `F8E0F6ADD2995C5EA9F0EB0AF55FA42D89D3B55D059A265D22F2A18F21C2FBE6`; stderr was empty with SHA-256 `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`. The harness elapsed time was 328.09 seconds. This replacement is the frozen dirty-tree preflight, not Task 11 closure; the exact committed tree must repeat the full suite, fixed-base-epoch build and inventory, all three validators, raw replay, final-message binding, original-session rebind, exact base-to-HEAD whitespace and clean-status checks, and a fresh detached `core.autocrlf=true` checkout.

The next settled root is assigned `D:\tmp\kokoroarc-m7-spec7-remediation-settled-01`. Its status is **SEVENTH SPEC-REVIEW REMEDIATION PREFLIGHT PASS; EXACT-TREE GATES AND FRESH REVIEWS PENDING** until those gates bind one exact commit. Both independent reviews are still required.

## Eighth specification-review remediation

Exact seventh-remediation commit `190c4aadbce96f812a00fe53c06746fcec016f71`, tree `5a5c5c401afecd93655f9b380755d176ef97c13c`, and parent `bb492bcf1aafa3d1132bc53872616db7565d7e37` passed the assigned `D:\tmp\kokoroarc-m7-spec7-remediation-settled-01` gate: `2001 passed, 24 skipped`, the fixed-base-epoch build and archive inventory, all three Skill validators, 785-file raw replay, 33 final-message bindings, a 984-file original-session rebind, exact-range whitespace and clean-status checks, and a fresh detached `core.autocrlf=true` checkout with all 984 evidence files byte-identical and 110 focused tests.

Fresh specification review confirmed the complete settled positive gate but returned FAIL with two Important evidence-integrity findings, so quality review was not run. First, additional ordinary mutation forms remained outside the command parser: positional `Copy-Item`, destinations assembled with `$env:TEMP` or `Join-Path`, `Expand-Archive`, short and call-operator aliases, and unlisted .NET writes could mutate protected or outside paths while every declared assertion passed. Second, a syntactically valid `Start-Process` record could construct the KokoroArc module from a variable or split literal, hide the invocation behind narrative argv, run from an outside working directory, and still preserve all 19 assertions.

The regression-first remediation adds a class-level trust boundary before the detailed command parser. For every eligible run, the complete retained `agent-report.json` must equal the shared sanitizer's byte-for-byte output for the report in the approval-controlled raw run. Its single artifact-ledger entry must also bind the independently read raw and retained SHA-256 values and the sanitizer redaction count. The campaign importers now write that ledger before adjudication. Any missing report, changed command, forged retained ledger, hash disagreement, redaction disagreement, or sanitizer-replay mismatch fails CLI binding and command safety; the request, workspace, compile, bundle, source-safety, determinism, and confinement assertions consequently fail closed. The existing wrapper, interpreter, and filesystem parsers remain defense in depth for faithfully imported transcripts.

Twelve focused regressions cover positional and call-operator copies, environment- and `Join-Path`-derived destinations, archive and CSV output, the `ni` alias, two additional .NET write APIs, a literal outside path assembled through `Join-Path`, constructed-module `Start-Process`, and a forged retained ledger. The implementation-focused run at `D:\tmp\kokoroarc-m7-spec8-remediation-focused-03` passed 122 tests before this release assertion was added. With this executable release assertion included, the focused research/release evidence gate passes **123 tests** under `D:\tmp\kokoroarc-m7-spec8-remediation-focused-04`.

The D:-confined dirty-tree full preflight at `D:\tmp\kokoroarc-m7-spec8-remediation-preflight-01` exited `0`: **`2014 passed, 24 skipped` in 285.41 seconds**. There were no failures or errors; every skip was an explicit Windows symlink, junction, or FIFO capability case. Captured stdout was 7,269 bytes with SHA-256 `9917CADA1DBA8A1F52B9AD4FD568FDA59A5AEBC808EC727A0EAE290BFF9C2BB4`; stderr was empty with SHA-256 `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`. The harness elapsed time was 289.38 seconds. This dirty-tree preflight preceded the release-record edits that retain its result; the focused gate verifies those edits, and the exact committed tree must repeat the complete suite.

The next exact settled root is assigned `D:\tmp\kokoroarc-m7-spec8-remediation-settled-01`. It must also pass the fixed-base-epoch build and inventory, all three validators, raw replay, final-message binding, original-session rebind, exact base-to-HEAD whitespace and clean-status checks, and a fresh detached `core.autocrlf=true` checkout before either fresh review. Current remediation status is **EIGHTH SPEC-REVIEW REMEDIATION PREFLIGHT PASS; EXACT-TREE GATES AND FRESH REVIEWS PENDING**.

## Ninth specification-review remediation

Exact eighth-remediation commit `3bfe1c9ac358f7d876d5f2e82db0a783dcb16ce3`, tree `6d0333b78f3c8f2e5578da44c7f4f9d5886e3442`, and parent `190c4aadbce96f812a00fe53c06746fcec016f71` passed the assigned `D:\tmp\kokoroarc-m7-spec8-remediation-settled-01` gate: `2014 passed, 24 skipped`, fixed-base-epoch distributions and archive inventory, all three Skill validators, 785-file raw replay, 33 final-message bindings, a 984-file original-session rebind, exact-range whitespace and clean-status checks, and a fresh detached `core.autocrlf=true` checkout with all 984 evidence files byte-identical and 123 focused tests.

Fresh specification review confirmed that both seventh-remediation operational findings now fail closed and independently verified the complete settled gate. It nevertheless returned FAIL with one Important conformance finding, so quality review was not run: invalid or missing report provenance was treated as if no research CLI ran. That allowed both clarification cases to certify `stop_before_research`, and allowed the casual and original-character non-trigger cases to pass their inverted `must_not` requirements, even when `agent-report.json` differed from the approved raw report or no trusted raw root was supplied.

The regression-first remediation carries the report-provenance result out of evidence observation and checks it before requirement interpretation. When provenance is invalid, every declared outcome is `passed: false`; neither a positive observation nor a `must_not` inversion can certify the run. Valid approved evidence retains the existing assertion-specific interpretation. Eight focused regressions cover report drift and absent trust independently for ambiguous-identity clarification, continuity clarification, casual discussion, and original-character non-trigger cases.

The implementation-focused run at `D:\tmp\kokoroarc-m7-spec9-remediation-focused-01` passed 131 tests before this release assertion was added. With this executable release assertion included, the focused research/release evidence gate passes **132 tests** under `D:\tmp\kokoroarc-m7-spec9-remediation-focused-02`.

The D:-confined dirty-tree full preflight at `D:\tmp\kokoroarc-m7-spec9-remediation-preflight-01` exited `0`: **`2023 passed, 24 skipped` in 204.30 seconds**. There were no failures or errors; every skip was an explicit Windows symlink, junction, or FIFO capability case. Captured stdout was 7,269 bytes with SHA-256 `E876AACC9CB9373EECC75694C797BDD37B10B3F201B986640A46BA4095CB0670`; stderr was empty with SHA-256 `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`. The harness elapsed time was 207.81 seconds. This dirty-tree preflight preceded the release-record edits that retain its result; the focused gate verifies those edits, and the exact committed tree must repeat the complete suite.

The next exact settled root is assigned `D:\tmp\kokoroarc-m7-spec9-remediation-settled-01`. It must also pass the fixed-base-epoch build and inventory, all three validators, raw replay, final-message binding, original-session rebind, exact base-to-HEAD whitespace and clean-status checks, and a fresh detached `core.autocrlf=true` checkout before either fresh review. Current remediation status is **NINTH SPEC-REVIEW REMEDIATION PREFLIGHT PASS; EXACT-TREE GATES AND FRESH REVIEWS PENDING**.

## Verified product gates before this record

- Task 8 exact research-to-authoring gate: `380 passed, 7 skipped`.
- Full unit regression after Task 8: `1411 passed, 3 skipped`.
- Task 9 research security/storage/CLI gate: `118 passed, 4 skipped`.
- Broad research plus authoring gate: `866 passed, 11 skipped`.
- All skips were documented platform capability cases for Windows symlink/FIFO behavior.

These results were obtained before the release-document changes. The settled-input exact-final section above supersedes the earlier inline checkpoint for Task 11 closure.

## Remaining closure gates

1. Complete the ninth specification-review remediation full preflight, commit it, and complete its exact-tree rerun under the assigned D:-based root.
2. Obtain fresh independent specification and quality reviews on that exact commit.
3. Close Milestone 7 only after both reviews report PASS with no Critical or Important findings.

Current status: Behavioral campaign: CORRECTIVE PASS 11/11. Corrective harness: COMPLETED WITH DISCLOSED DEVIATIONS. Exact-final verification: NINTH SPEC-REVIEW REMEDIATION PREFLIGHT PASS; EXACT-TREE GATES AND FRESH REVIEWS PENDING. Fresh specification review of ninth spec-review remediation settled tree: PENDING. Fresh quality review of ninth spec-review remediation settled tree: PENDING.
