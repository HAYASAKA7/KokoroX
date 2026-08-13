# Milestone 7 research release verification

## Scope and exact status

This record covers the inline product, CLI, Skill-structure, smoke, and distribution checks completed for Milestone 7 on 2026-08-13 (Asia/Hong_Kong). Milestone 7 does not approve the complete standalone suite.

- Build base HEAD: `7ec68e553b478411d3b9f7e8207a70df2b382b19`
- Build input: that HEAD plus the current `README.md` patch only among `README.md`, `pyproject.toml`, `src/`, and `schemas/`
- Isolated root: `D:\tmp\kokoroarc-m7-release-20260813-inline1`
- Behavioral campaign: PENDING
- Independent specification review: PENDING
- Independent quality review: PENDING

Because the required 22 external evaluator runs and two independent closure reviews have not run, Task 11 and Milestone 7 remain open. No campaign PASS, canon-accuracy claim, or complete-suite approval is implied by the checks below.

## Current Skill identity

| Artifact | SHA-256 |
| --- | --- |
| `skills/researching-characters/SKILL.md` | `33B1BF3B8C98A97282295BFFE7EBE474D5EE43687378FF29E48DCABAC2239876` |
| `skills/researching-characters/references/research-contract.md` | `9E4F2ABC63A29BF75F4291D5DB657B2908A75C00E8830F69A027CC1EED73B313` |
| `skills/researching-characters/agents/openai.yaml` | `093EB44756A018C1A8FFE856F4237E31D161E936AEEAF1DF2A452B3146785C3E` |

Structural verification completed with `7 passed`; the standard Skill validator exited `0` and printed `Skill is valid!`.

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

This is a verified inline checkpoint, not Task 11 closure. Because campaign artifacts and independent reviews are absent, exact-final verification remains pending until those release inputs are settled.

## Verified product gates before this record

- Task 8 exact research-to-authoring gate: `380 passed, 7 skipped`.
- Full unit regression after Task 8: `1411 passed, 3 skipped`.
- Task 9 research security/storage/CLI gate: `118 passed, 4 skipped`.
- Broad research plus authoring gate: `866 passed, 11 skipped`.
- All skips were documented platform capability cases for Windows symlink/FIFO behavior.

These results were obtained before the release-document changes. The current inline checkpoint above supplies a fresh full repository suite, three Skill validators, and distribution build. Exact-final reruns and diff/status checks still must run after all Task 11 evidence is settled.

## Remaining closure gates

1. Obtain exact approval and run the 22-case behavioral campaign with fresh isolated evaluator threads.
2. Verify retained transcripts, hashes, assertion mappings, and product-state snapshots with executable tests.
3. After the campaign evidence is settled, rerun the exact-final full repository suite and clean build.
4. Obtain fresh independent specification and quality reviews on the exact final commit.
5. Close Milestone 7 only after every gate reports PASS.

Until then, Behavioral campaign: PENDING. Independent specification review: PENDING. Independent quality review: PENDING.
