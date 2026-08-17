# Milestone 8 testing release verification

## Scope and candidate identity

This record covers the deterministic testing, soft-evaluation aggregation,
review, promotion, publication-readiness, CLI, packaging, and Skill evidence for
Milestone 8. The candidate record was committed, its exact gates and ordered
reviews were completed, and the sole Minor review finding was fixed with a
RED/GREEN documentation regression. A later broader fresh-checkout Skill-suite
run exposed the checkout-policy defect disclosed below.
Milestone 8 closure is reopened until that remediation passes its exact gates.
Milestone 9 and the
complete standalone suite remain pending.

- Verification date: 2026-08-17 (Asia/Hong_Kong)
- Milestone 8 base commit: `0eb1a019bb3654810d9b4401cb4c55c7b33bec90`
- Smoke/full-suite product HEAD: `94b4edeaaab1d97f50902488dfea4e077c019a0a`
- Exact gated release commit: `6419307e61385de122bb7041f0863c1f0dad338a`
- Exact gated tree: `48769f4d5d861a4aa98b0011eaa49a8147c1950b`
- Fixed base epoch: `1786691951`
- Candidate smoke/suite root: `D:\tmp\kokoroarc-m8-release-20260817-candidate1`
- Superseding distribution root: `D:\tmp\kokoroarc-m8-release-20260817-candidate3`
- Exact gate root: `D:\tmp\kokoroarc-m8-release-exact-6419307-01`
- Exact detached checkout: `D:\tmp\kokoroarc-m8-release-exact-6419307-checkout-01`
- Behavioral result: baseline `1/8`; Skill-enabled `8/8`

The distribution candidate additionally contains the regression-first
`pyproject.toml` and archive-test remediation described below. No external
evaluator was run for Task 9. No retained behavioral output was rewritten.

## D:-confined deterministic CLI smoke

The candidate root was required not to exist. Fresh `temp`, `pytest`,
`build-temp`, `smoke`, `smoke-data`, `smoke-inputs`, and `dist` directories were
created beneath it. `PYTHONPATH`, `KOKOROARC_DATA_DIR`, `TEMP`, `TMP`, and
`KOKOROARC_TEMP_DIR` were then bound to the repository or that D:-based root.

The structured request, review attestation, and prepared soft-evaluation input
were generated deterministically from the repository's real Rin release fixture
helper. This preparation calls only local domain functions; it does not call an
evaluator, browse, install, activate, start a session, mutate relationship
state, or publish.

```powershell
$releaseRoot='D:\tmp\kokoroarc-m8-release-20260817-candidate1'
$smoke="$releaseRoot\smoke"
$data="$releaseRoot\smoke-data"
$inputs="$releaseRoot\smoke-inputs"
$env:PYTHONPATH="$(Resolve-Path src);$(Resolve-Path tests)"
$env:KOKOROARC_DATA_DIR=$data
$env:TEMP="$releaseRoot\temp"
$env:TMP=$env:TEMP
$env:KOKOROARC_TEMP_DIR=$env:TEMP

python -c "from pathlib import Path; import conftest as f; from kokoroarc.packs.compiler import canonical_bytes as c; p=f._build_rin_verified_release('private'); e=p['evidence']; o=Path(r'$inputs'); v={'request.json':e['request'],'expected-hard.json':e['hard_report'],'review.json':e['review_attestation'],'soft-input.json':e['soft_evaluation_input'],'expected-soft.json':e['soft_evaluation_report']}; [(o/n).write_bytes(c(x)+b'\n') for n,x in v.items()]"

function Invoke-Capture {
    param([string]$Name,[string[]]$Arguments)
    python -m kokoroarc.cli @Arguments --json `
        1> "$smoke\$Name.stdout.json" `
        2> "$smoke\$Name.stderr.txt"
    if ($LASTEXITCODE -ne 0) { throw "$Name failed" }
}

Invoke-Capture hard-a @('pack','test','characters/original/rin-aster','--request',"$inputs\request.json",'--out','hard-a.json')
Invoke-Capture hard-b @('pack','test','characters/original/rin-aster','--request',"$inputs\request.json",'--out','hard-b.json')
Invoke-Capture soft-a @('pack','soft-eval',"$inputs\soft-input.json",'--out','soft-a.json')
Invoke-Capture soft-b @('pack','soft-eval',"$inputs\soft-input.json",'--out','soft-b.json')

$reviewedId='rin-m8-release-reviewed-01'
$reviewedOut="promotions/rin-aster/$reviewedId/promotion.json"
Invoke-Capture reviewed-1 @('pack','promote','characters/original/rin-aster','--target','reviewed','--promotion-id',$reviewedId,'--request',"$inputs\request.json",'--hard-report',"$data\reports\hard-a.json",'--review',"$inputs\review.json",'--out',$reviewedOut)
Invoke-Capture reviewed-2 @('pack','promote','characters/original/rin-aster','--target','reviewed','--promotion-id',$reviewedId,'--request',"$inputs\request.json",'--hard-report',"$data\reports\hard-a.json",'--review',"$inputs\review.json",'--out',$reviewedOut)

$verifiedId='rin-m8-release-verified-01'
$verifiedOut="promotions/rin-aster/$verifiedId/promotion.json"
$reviewedPath="$data\reports\promotions\rin-aster\$reviewedId\promotion.json"
Invoke-Capture verified-1 @('pack','promote','characters/original/rin-aster','--target','verified','--promotion-id',$verifiedId,'--request',"$inputs\request.json",'--hard-report',"$data\reports\hard-a.json",'--review',"$inputs\review.json",'--previous',$reviewedPath,'--soft-input',"$inputs\soft-input.json",'--soft-report',"$data\reports\soft-a.json",'--out',$verifiedOut)
Invoke-Capture verified-2 @('pack','promote','characters/original/rin-aster','--target','verified','--promotion-id',$verifiedId,'--request',"$inputs\request.json",'--hard-report',"$data\reports\hard-a.json",'--review',"$inputs\review.json",'--previous',$reviewedPath,'--soft-input',"$inputs\soft-input.json",'--soft-report',"$data\reports\soft-a.json",'--out',$verifiedOut)

$verifiedPath="$data\reports\promotions\rin-aster\$verifiedId\promotion.json"
Invoke-Capture publication-a @('pack','publication-check','characters/original/rin-aster','--promotion',$verifiedPath,'--request',"$inputs\request.json",'--hard-report',"$data\reports\hard-a.json",'--review',"$inputs\review.json",'--previous',$reviewedPath,'--soft-input',"$inputs\soft-input.json",'--soft-report',"$data\reports\soft-a.json",'--visibility','private','--out','publication-a.json')
Invoke-Capture publication-b @('pack','publication-check','characters/original/rin-aster','--promotion',$verifiedPath,'--request',"$inputs\request.json",'--hard-report',"$data\reports\hard-a.json",'--review',"$inputs\review.json",'--previous',$reviewedPath,'--soft-input',"$inputs\soft-input.json",'--soft-report',"$data\reports\soft-a.json",'--visibility','private','--out','publication-b.json')
```

The run completed 10 commands with ten zero exits and empty stderr. The two
hard reports, two soft reports, and two publication reports were pairwise
byte-identical. Both repeated promotion commands returned byte-identical stdout
and the same immutable record hash. The source pack and all prepared input files
were recursively hashed before and after the commands. Every protected data
root remained absent and `smoke-data` contained only `reports`:

```text
source_snapshot_match: true
input_snapshot_match: true
protected_roots_absent: true
ready_for_private_export: true
ready_for_publication: false
blockers: []
```

| Evidence | SHA-256 |
| --- | --- |
| Canonical ten-record stdout transcript | `7bf645816eb0cbd33a8433b6e6485078594f089a87588520fcdb32f53f7d50e7` |
| `hard-a.json` / `hard-b.json` | `b0f57b7552df1d88e144d965530afc3704102802788d6295920b18ffd3afe24f` |
| `soft-a.json` / `soft-b.json` | `f2ff67a32f2980385df16ebfd687302ce466417da05a710ab97cb9a42e108dc7` |
| Reviewed promotion record | `457fba5b2bc2ccb316de119c25ecb9ad5f8702b7b5d098f9f70c86e0fd3836f8` |
| Verified promotion record | `9a549e95d049ee21537d70b336b7a161cc0e5d3bf3ececa3f21080699877ea97` |
| `publication-a.json` / `publication-b.json` | `aa9f766e4387152d1f330050ed7759a6215ad9729ba7d73585420ef74f89ba2e` |
| Protected-before file | `c6fdcea9c4ceb8c0214e0a52938578f08f005b9768ee84c75ef08ba926096d2e` |
| Protected-after file | `7da8c46ade82c0eeb81d9f92900c35538fb4639e41b7d81525b4d45061c236db` |

The hard source hash was
`6d1024399a15918893e4a58362d64fc423bfb1e46cca9c166247fc245a8af071`;
the compiled hash was
`da6deff44e4636c0d0bdb2c2fee6437967e7065ea5534d8a75b40f1be1a21813`.

## Complete repository suite

The first candidate command used a ten-minute harness timeout. It was terminated
at that boundary and retained zero-byte buffered stdout and stderr, with no exit
capture. A diagnostic `--collect-only` run then completed normally with
**2,602 tests collected in 1.08s**, proving collection was not stuck. No product failure
was inferred from the harness timeout.

Exactly one corrected rerun used unbuffered output, a fresh basetemp, and a 20-minute
limit. It exited `0`: **2573 passed, 29 skipped in 629.74s**. Stderr was empty.

| Capture | Bytes | SHA-256 |
| --- | ---: | --- |
| `pytest-attempt2.stdout.txt` | complete | `4B1DEC7D764BF0214C0C8DC1091394E916E1F6180EFF454E2133A1854A389BEE` |
| `pytest-attempt2.stderr.txt` | 0 | `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855` |

All 29 skips explicitly report unavailable Windows filesystem capabilities:
file/directory symlink creation or POSIX symlink semantics, safe junction
creation, FIFO creation, or POSIX executable bits. There were no functional,
schema, security, evidence, or packaging skips.

This candidate suite preceded only the archive-membership regression and
`pyproject.toml` Skill-data remediation below. It is not the final exact-commit
suite; Task 9 requires a settled rerun after the release record is committed.

## Fixed-epoch distribution and inventory

The first fixed-epoch build at `SOURCE_DATE_EPOCH=1786691951` exposed an
acceptance failure: wheel and sdist contained the seven testing modules and six
Milestone 8 schemas but were missing every Skill file. A focused archive test
was added first and produced **1 failed**. `pyproject.toml` was then changed to
package all three files for each of the four Skills; the same test produced
**1 passed** and also checks exact archive bytes against repository bytes.

The corrected candidate-2 build was superseded after the checkout-policy audit
found that `pyproject.toml`, `src/**`, and `schemas/**` were not all pinned to LF.
After adding the scoped attributes and normalizing `pyproject.toml`, the
authoritative precommit build under
`D:\tmp\kokoroarc-m8-release-20260817-candidate3` contains:

- seven testing modules;
- six Milestone 8 schemas; and
- twelve Skill files: `SKILL.md`, `agents/openai.yaml`, and the directly linked
  contract for each of the four Skills.

| Artifact | Bytes | Entries | SHA-256 | Content-manifest SHA-256 |
| --- | ---: | ---: | --- | --- |
| Wheel | 194,757 | 83 | `16fc57205fca096cff52d25068d343d9f4bced8dd7f570b343ed4e0b82a13599` | `2843b3f6edf7694c9b9b52493fdeb3f01328bcb13170edb4af9ac4c56f4622fb` |
| sdist | 152,428 | 88 | `9f3669347e46ebbf30a9bb94cf65e1599fa4ddbeb36273770c63afcba6364ad2` | `16089d3fbb3f0f810b818a5e49836f852d3df58e90b1921ea0d31d5073263226` |

A second fixed-epoch build produced:

```text
wheel_exact: true
sdist_content_exact: true
```

The repeat wheel SHA-256 is exactly
`16fc57205fca096cff52d25068d343d9f4bced8dd7f570b343ed4e0b82a13599`.
Setuptools still assigns varying generated mtimes inside the gzip/tar envelope,
so the repeat raw sdist SHA-256 is
`1fec9c9a6c0e1456ae0b0af80e7f8f6c9a40c9265aa390f99e36101113fc8aec`;
after stripping only the top-level archive directory and recording each path,
size, and member SHA-256, both 88-file content manifests equal
`16089d3fbb3f0f810b818a5e49836f852d3df58e90b1921ea0d31d5073263226`.

## Four separate Skill validations

The installed Skill Creator `quick_validate.py` ran in four separate Python
processes. Each exited `0`, emitted the stated validator result, and had empty
stderr.

| Skill file | SHA-256 | Validator |
| --- | --- | --- |
| `skills/using-kokoroarc/SKILL.md` | `c643503c3cab5ffa1d7eddfbf64a1f3650e52aa179f49d47e62ec9400c629ac0` | Skill is valid! |
| `skills/authoring-character-packs/SKILL.md` | `a6318161baab6666a58c465c9f781b04c0bc01203643af1362f13dfef6240c1e` | Skill is valid! |
| `skills/researching-characters/SKILL.md` | `aa08f7e8bb5dd78c2434af0bd8878bb87d0cdbd7bad0fb04cd40aa13149bec21` | Skill is valid! |
| `skills/testing-character-packs/SKILL.md` | `72381d9b0ab71ce988d9313bf0960f8577878369ff969697ead0dfa3a166fedb` | Skill is valid! |

Archive inventory also proved byte equality for every metadata and contract
file, not only the four `SKILL.md` files.

## Exact-commit closure gates

The settled candidate was committed as
`6419307e61385de122bb7041f0863c1f0dad338a`, tree
`48769f4d5d861a4aa98b0011eaa49a8147c1950b`, with parent
`94b4edeaaab1d97f50902488dfea4e077c019a0a`. The exact base-to-HEAD
`git diff --check` passed and both the source worktree and detached checkout
were clean.

### Exact D:-confined smoke

The ten documented CLI commands ran once under
`D:\tmp\kokoroarc-m8-release-exact-6419307-01`. All ten command exit captures
were `0`, all ten stderr captures were empty, paired hard/soft/publication
reports and promotion retry envelopes were exact, source/input snapshots were
unchanged, and the only data-root entry was `reports`.

The surrounding first audit wrapper exited nonzero only after those successful
commands because it indexed a one-element PowerShell scalar as though it were
an array. That wrapper-only failure is retained. A corrected read-only audit
used the existing captures, rewrote no CLI output, and ran no command again:

```text
audit_attempt: 2
commands_rerun: 0
failed: []
passed: true
```

| Exact smoke evidence | SHA-256 |
| --- | --- |
| Raw ordered stdout transcript | `5c669ed699214062a2bdff7a374d16710e52543fdf3bba2169363730a6c48c4a` |
| Hard report file | `b0f57b7552df1d88e144d965530afc3704102802788d6295920b18ffd3afe24f` |
| Soft report file | `f2ff67a32f2980385df16ebfd687302ce466417da05a710ab97cb9a42e108dc7` |
| Reviewed record canonical bytes | `457fba5b2bc2ccb316de119c25ecb9ad5f8702b7b5d098f9f70c86e0fd3836f8` |
| Verified record canonical bytes | `9a549e95d049ee21537d70b336b7a161cc0e5d3bf3ececa3f21080699877ea97` |
| Publication report file | `aa9f766e4387152d1f330050ed7759a6215ad9729ba7d73585420ef74f89ba2e` |
| Before snapshot | `ba99686607b714b4aa1820e131a89abae289b110cbeb190c2c60d1c56fe7ac9a` |
| After snapshot | `95ec6dc076145ad0cd3f3b5811eb92e7ccca736be93272c577e7f88a88fbf89b` |

The hard report retained source hash
`6d1024399a15918893e4a58362d64fc423bfb1e46cca9c166247fc245a8af071`
and compiled hash
`da6deff44e4636c0d0bdb2c2fee6437967e7065ea5534d8a75b40f1be1a21813`.
Private readiness was true, public readiness was false, and blockers were empty.

### Exact full suite and checkout

The exact suite exited `0`: **2,580 passed, 29 skipped in 599.06s**. Every skip
identified a Windows filesystem capability: symlink/junction creation, FIFO
creation, POSIX symlink behavior, or POSIX executable bits. Stderr was empty.

```text
pytest_outcome: 2580 passed / 29 skipped
stdout_sha256: cc4f9c5d9698d292f0ca23c44881db48645e506c329f3975408b79f7d485f432
stderr_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

A local detached checkout of the exact commit used `core.autocrlf=true`. All
80 distribution inputs were LF with zero CRLF/mixed violations, status was
clean, and its focused evidence/archive gate reported **8 passed in 9.85s**.
Each of the four Skills separately returned `Skill is valid!`, exit `0`, and
empty stderr.

### Exact fixed-epoch distribution

Two builds from the detached LF checkout used `SOURCE_DATE_EPOCH=1786691951`.
Every required byte matched the checkout: seven testing modules, six release
schemas, and all twelve files in the four current Skill directories.

| Artifact | Bytes | Entries | SHA-256 | Content-manifest SHA-256 |
| --- | ---: | ---: | --- | --- |
| Wheel | 193,850 | 83 | `d6adc0abe91b38df2a9467a05a0dfe3e08b2c8402801ee66358d10601f904e99` | `94dc843baacedd31b5cd4b4ff96e5f68203ac9d70fe76019b8e9c0e7885b9d1d` |
| sdist | 149,926 | 88 | `30dccb700196c7002691a01757bedf0f184457fd805fae783cdc3be8a2d5be5a` | `86d61d51d9ce9ac446b2b491e256d926f3c20df4c7328ff7d3745d99c9d5cba6` |

The repeat wheel was byte-identical. Setuptools again varied only generated
sdist container metadata: the repeat raw sdist was 149,954 bytes with SHA-256
`48777d05cdf9862666fd2a31791123acd3b171bb5f0b0b1ab15ba2a3c2efa5fd`,
while its sorted path/size/member-hash manifest remained exactly
`86d61d51d9ce9ac446b2b491e256d926f3c20df4c7328ff7d3745d99c9d5cba6`.

The exact wheel was installed without dependencies outside the checkout. Its
Milestone 8 `pack test` command passed with empty stderr, the imported module
resolved from that isolated installation, every release schema was present,
and the summary recorded `installed_skill_files: 12` with zero byte mismatch.

### Ordered exact reviews

- Specification review: **PASS**, with no Critical, Important, or Minor finding.
- Quality/security review: **PASS_WITH_MINOR**, with no Critical or Important
  finding. Its sole `README_SOFTBREAK_WORD_SPLIT` Minor was reproduced by a
  focused RED assertion and fixed GREEN by keeping `publication-readiness`
  contiguous in this closure change.

## Post-closure checkout-policy remediation

Documentation closure commit
`1f4cd77abd958b6a3a37a1751dd76825d05f317b` passed its nine-test focused
evidence/archive gate and all four Skill validators from a clean detached
`core.autocrlf=true` checkout. The broader `tests/skills` gate was then run from
that same exact checkout and exited `1`: **4 failed, 262 passed in 71.18s**.
Stderr was empty, status remained clean, and the stdout SHA-256 was
`72af248b0bc51fb21528793c4443335b37bd7b6ef8e2eb3bea94a4858b7e2cb7`.

All four failures were the approved3 through approved6 frozen-campaign
structure checks. The campaigns executed and retained `openai.yaml` as raw
CRLF bytes with SHA-256
`179449780883aa6f6cdb34674a3637652d8a9fcbba299938ccacc20fd84c0895`.
The released `skills/testing-character-packs/agents/openai.yaml` is the same
text committed under `skills/** text eol=lf`; its canonical LF SHA-256 is
`04537845c9c3c3f1f279c2c73ba74cceb2271d9320acf11ce0c923fabdfd7df0`.
The original source worktree still held its pre-normalization CRLF file, so a
raw-current-byte assertion passed there but failed correctly in a fresh LF
checkout.

The regression-first remediation distinguishes those two boundaries. The
retained harness copies remain byte-exact CRLF and continue to be checked by
their historical raw hash. The released metadata remains canonical LF. A
checkout-portable assertion proves that LF and CRLF forms differ only by line
endings and project to the exact historical execution hash.
No retained evaluator output was rewritten, no external evaluator was rerun,
and no Skill instruction or product behavior changed.

The closure change contains documentation and executable evidence assertions,
not Milestone 9 product behavior. Its checked status is accepted only after a
fresh exact focused recheck and ordered closure review confirm the committed
delta. Milestone 8 closure remains reopened for the exact remediation gates.
Milestone 9 and the complete standalone suite remain pending.
