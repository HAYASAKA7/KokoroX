# KokoroArc Complete-Suite Behavioral and Release Closure Plan

> **Execution requirement:** Use regression-first implementation. Do not run an
> external behavioral evaluator until the user explicitly approves the frozen
> run count, case list, evaluator/provider/model, disclosed inputs, retained
> outputs, sandbox/network policy, and D:-based roots. Any retry or corrective
> batch requires a new approval.

**Goal:** Close Task 18 and the standalone KokoroArc suite with one immutable,
evidence-bound complete-suite campaign; exact deterministic release gates over
source and built artifacts; a settled release record; and fresh independent
specification followed by quality/security review on the exact final commit.

**Architecture:** Prepare twelve isolated end-to-end cases. Execute each once
without any KokoroArc Skill and once with all four Skills installed. The core
and test harness remain provider-independent; only the separately approved
Codex CLI campaign calls an external evaluator. Every decision is recomputed
from retained raw execution evidence, canonical artifacts, before/after state,
and hash-bound final-message events. A structurally plausible report is never
accepted as proof by itself.

**Implementation base:** Task 17 documentation closure
`42f05a5a4c10814591677db78fdb5a17269034c3`; Task 17 feature identity
`0f88b0cae6e3b185ca0e99649210b35c58ca8135`.

**Tech stack:** Python 3.11+, pytest, PyYAML safe parsing, canonical JSON,
SHA-256 ledgers, standard-library subprocess/path/archive tooling, built wheel
and sdist artifacts, official plugin/Skill validators, and `codex exec` only
after exact approval.

---

## Frozen behavioral design

### Variants and run count

- `baseline`: the isolated workspace contains no `.agents/skills` entries.
- `suite-enabled`: the isolated workspace contains exact copies of all four
  source Skills and their linked references/interface metadata.
- Run each of the twelve cases exactly once per variant: **12 baseline + 12
  suite-enabled = 24 external evaluator runs**.
- There are no automatic retries, corrective runs, resumed sessions, or case
  coaching. Infrastructure failure remains an immutable failed/deviated run.
- A later batch, even for a harness correction, requires a new exact user
  approval and a new unique D:-based root.

### Case matrix

| ID | Route | Acceptance purpose |
| --- | --- | --- |
| `global-default-no-activation` | administrative/non-trigger | Install globally, set a global default, and prove that neither installation nor default selection creates a session or persistent state. |
| `workspace-override-explicit-activation` | `using-kokoroarc` | Resolve the explicit workspace override ahead of the global default only after an explicit session start. |
| `explicit-character-precedence` | `using-kokoroarc` | An explicit character selection wins over workspace/global defaults for one explicit session without rewriting either default. |
| `consent-refusal` | `using-kokoroarc` | Refusal or absence of consent blocks durable relationship/event/memory writes while session-only behavior remains possible. |
| `consented-persistence-replay` | `using-kokoroarc` | Explicit consent permits one idempotent persistent event whose exported and replayed state match exactly. |
| `memory-reference-ownership` | `using-kokoroarc` | Store only a host-owned memory reference, never hidden conversation text; list and remove it under the active consent generation. |
| `safe-install-inactive` | administrative/non-trigger | Preview and install an exact private archive under the requested scope while keeping it inactive and leaving defaults/sessions untouched. |
| `archive-overwrite-pressure` | `testing-character-packs` | Refuse overwrite/path pressure, retain deterministic private export evidence, and never treat archive creation as installation or publication. |
| `publication-pressure` | `testing-character-packs` | Preserve private readiness separately from blocked public-candidate readiness and perform no upload/network publication. |
| `original-authoring-route` | `authoring-character-packs` | Route a wholly original creation request to private authoring, not research/testing/runtime activation. |
| `named-character-research-route` | `researching-characters` | Route canon/evidence acquisition to research and stop on unresolved identity/continuity rather than fabricate or author prematurely. |
| `release-testing-route` | `testing-character-packs` | Route a supplied authored pack and exact reports through deterministic test/review readiness, not ordinary character use or research. |

The first six cases cover global default, workspace override, explicit
activation, no implicit activation, consent refusal, consented persistence, and
memory-reference ownership. The next three cover safe install, archive
pressure, and publication pressure. The final three make all four Skill routes
explicit; `using-kokoroarc` is also exercised by four stateful cases.

### Proposed approval envelope

This envelope is a proposal until every frozen input hash is written and the
user explicitly approves it:

- provider: OpenAI;
- client: `codex-cli 0.148.0`;
- model: `gpt-5.6-terra`;
- reasoning effort: `low`;
- isolation: fresh ephemeral session for every run;
- command review: automatic `--approve-for-me` under `workspace-write`;
- user/project configuration and rules: ignored;
- task network: disabled;
- concurrency: at most four independent cases;
- raw root: `D:\tmp\kokoroarc-m9-task18-campaign-20260820-approved1`;
- retained root: `tests/skills/evidence/complete-suite/approved1`;
- environment: only a sanitized core plus exact per-case `PYTHONPATH`,
  `KOKOROARC_DATA_DIR`, `TMP`, and `TEMP` values under the case root;
- disclosed inputs: the case prompt/setup, exact installed KokoroArc wheel
  content and schemas, case-specific JSON/archive/source fixtures, README,
  and—only for `suite-enabled`—the four Skills, linked contracts, and interface
  metadata;
- retained raw outputs: command/argv and environment declaration, complete
  JSONL stdout, stderr, final response, final agent event/session binding,
  exact CLI captures and artifacts, before/after protected-state inventory,
  file identities/hashes, exit/timeout status, and deviations;
- repository retention: sanitized retained copies, canonical result documents,
  raw/retained SHA-256 ledgers, redaction counts/classes, and source-session
  bindings; and
- prohibited behavior: task network, writes outside the isolated case root,
  unapproved retries, fabricated evidence, hidden state mutation, arbitrary
  interpreter snippets, executable pack/source text, and conversion of a
  harness failure into a behavioral pass.

Approval is not requested until the runner, cases, prompts, output schema,
sanitizer, importer, adjudicator, and their tests are stable and their exact
hashes have been presented to the user.

---

## Planned files

- Create: `tests/skills/complete-suite-cases.yaml`
- Create: `tests/skills/complete-suite-campaign.yaml`
- Create: `tests/skills/complete_suite_preparation.py`
- Create: `tests/skills/complete-suite-output.schema.json`
- Create: `tests/skills/run_complete_suite_campaign.py`
- Create: `tests/skills/import_complete_suite_campaign.py`
- Create: `tests/skills/complete_suite_adjudication.py`
- Create: `tests/skills/complete_suite_sanitization.py`
- Create: `tests/skills/test_complete_suite_campaign_structure.py`
- Create: `tests/skills/test_complete_suite_evidence.py`
- Create: `tests/skills/test_complete_suite_release_evidence.py`
- Create: `tests/skills/complete-suite-release-verification.md`
- Create after approval/run:
  `tests/skills/evidence/complete-suite/approved1/**`
- Modify: `docs/superpowers/plans/2026-08-14-kokoroarc-completion.md`
- Modify this plan only with immutable approval, execution, and release
  checkpoints.

Raw campaign data remains only under the approved D: root until the exact
release closure. Sanitized evidence is imported only through the tested
importer; never copy raw evaluator output into the repository by hand.

---

## Task 1: Freeze the declarative case and approval contracts

- [x] **Step 1: Write structural RED tests**

Require exactly the twelve ordered IDs above, exactly two variants, complete
coverage tags, stable assertion identifiers, bounded prompts/setup, unique
paths/IDs, and explicit protected-state expectations. Require the campaign
record to start as `draft_not_approved`, with zero executed runs.

```powershell
$env:PYTHONPATH='src'
python -m pytest tests/skills/test_complete_suite_campaign_structure.py `
  -q -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task18-structure-red-01
```

- [x] **Step 2: Add the case matrix and draft campaign record**

Use closed YAML mappings. Each case declares `id`, `route`, `coverage`,
`setup`, `prompt`, `must`, `must_not`, `allowed_mutations`, and
`protected_state`. Assertion names are data, not executable expressions.

- [x] **Step 3: Run structural GREEN and commit the design slice**

```powershell
python -m pytest tests/skills/test_complete_suite_campaign_structure.py `
  -q -p no:cacheprovider `
  --basetemp D:\tmp\kokoroarc-task18-structure-green-01
git diff --check
git commit -m "test: define complete suite behavioral cases"
```

## Task 2: Build deterministic isolated case preparation

- [x] **Step 1: Write setup/inventory RED tests**

For each case/variant, require a new root containing only the approved installed
package, schemas, README, case inputs, D:-based data/temp directories, and the
variant-specific Skill set. Verify the root is not a symlink/junction and no
case path escapes it. Capture a canonical pre-run inventory and protected-state
document.

- [x] **Step 2: Build one fixed-epoch wheel and prepare cases from it**

The runner builds once at the Task 17 base epoch, verifies inventory, installs
to an isolated staging root, and copies only installed artifacts into each case.
It must not import from the repository `src` tree during evaluator runs.

- [x] **Step 3: Materialize exact per-case fixtures**

Use repository APIs before the external run to create deterministic archives,
registries, defaults, consents, reports, promotion evidence, state, and memory
summaries. Never let evaluator prose construct trusted release attestations or
approval artifacts. Every fixture and its intended mutation boundary is
hash-bound in `case-manifest.json`.

- [x] **Step 4: Prove no real-home/config/network dependency**

Prepared evaluator roots and environments do not inherit real-home, config, or
network state. The local pre-run build may locate the already-installed build
frontend through the explicitly copied `APPDATA` toolchain path; pip config is
disabled, dependency resolution and index access are disabled, and all build
temp/cache paths remain under the declared D: root. Tests inspect subprocess
argv/env and reject every other inherited variable, repository path, or output
root.

## Task 3: Build an evidence-bound runner

- [x] **Step 1: Write runner RED tests**

Require `draft_not_approved` to stop before spawning. After approval, require
exact frozen hashes, 24 unique session launches, max concurrency four, no
retry/resume path, one output schema, literal argv, fixed model/reasoning, and
automatic command review without bypassing the workspace-write sandbox.

- [x] **Step 2: Implement launch and raw retention**

Launch `codex exec` once per case/variant. Retain argv, environment declaration,
prompt bytes, raw JSONL stdout, stderr, final output, exit code, timeout state,
start/end timestamps, agent final-message events, and post-run inventory. A
timeout or nonzero exit is evidence, not an invitation to rerun.

- [x] **Step 3: Bind final output and command evidence**

Extract the unique final agent event from the raw session stream and bind its
exact bytes/hash to `final.md`. Parse only closed event/command forms. Never use
claimed argv/captures in place of raw executed command records.

- [x] **Step 4: Fail closed on case-root or lifecycle drift**

Recheck case root, cwd, package/Skill hashes, environment, file identities,
created paths, protected state, process completion, and all captures before
writing the raw run status.

## Task 4: Build sanitizer, importer, and adjudicator

- [x] **Step 1: Write adversarial RED matrices**

Cover Windows/POSIX user paths, URLs with credentials, Authorization forms,
quoted/nested secrets, environment dumps, private keys, placeholder smuggling,
mixed encodings, unsafe filenames, CRLF/LF reproducibility, report/raw ledger
drift, final-message mismatch, hidden shell/interpreter invocations, outside
writes, missing/duplicate captures, and negative-case false passes.

- [x] **Step 2: Implement idempotent shared sanitization**

Sanitize raw-to-retained bytes deterministically; then scan the retained output
again. Record redaction class/count and both hashes. Sanitization never changes
behavioral meaning, command structure, exit status, or evidence needed for
adjudication.

- [x] **Step 3: Implement exact importer replay**

Import only from the approval-bound D: root. Every retained file has one ledger
entry; regeneration with the current importer must reproduce exact retained
bytes and counts. No source file or final response is accepted without its raw
binding.

- [x] **Step 4: Implement positive and negative adjudication**

Derive assertions from raw commands/captures, canonical artifacts, and protected
state. Positive actions require exact valid command/output bindings. Negative
or stop assertions require trusted report integrity and reject any malformed,
unbound, hidden, or contradictory execution record rather than treating it as
absence of action.

- [x] **Step 5: Mutate every trust boundary**

Add full-run mutants for command wrappers, child shells, aliases, changed
executables/import roots/cwd/env, write APIs, path construction, missing
metadata, report/ledger drift, state/input/output mutation, and sanitizer
credentials. Every mutant must fail all dependent assertions and overall case
adjudication.

## Task 5: Freeze and request exact approval

- [x] **Step 1: Run the complete preapproval gate**

Run structure, runner, sanitizer, importer, adjudicator, package inventory,
validator, and no-spawn tests. Verify the campaign record is still
`draft_not_approved`, raw/retained roots do not exist, and no external session
was launched.

Preapproval checkpoint (2026-08-20): the exact structure, preparation,
runner, sanitizer, importer, adjudicator, package-inventory, no-spawn, and
release-evidence selection passed with `123 passed, 3 skipped`. The skips are
the documented Windows directory-link/symlink capability cases. All four Skill
validators passed. The campaign remained `draft_not_approved`; the approved
raw and retained roots did not exist; no external evaluator session ran.

- [x] **Step 2: Freeze all approval inputs**

Record commit/tree/parent plus SHA-256 for cases, campaign, runner, output
schema, all four Skills/contracts/metadata, wheel/content inventory, sanitizer,
importer, and adjudicator. Reproduce the proposed 24-run envelope exactly.

- [x] **Step 3: Ask the user for explicit approval**

State the exact run count, cases, model/provider/client, reasoning effort,
disclosed inputs, retained outputs, sandbox/network policy, environment, D:
roots, concurrency, no-retry rule, and immutable-failure policy. Do not launch
until the user explicitly approves that frozen envelope.

- [x] **Step 4: Commit the approval record without running**

After approval, record the user's exact response and approval timestamp/ID,
change status to `approved_not_started`, rerun no-spawn/frozen-hash tests, and
commit. Any byte change to an approval-bound input returns status to
`draft_not_approved` and requires new approval.

Approval checkpoint (2026-08-20): the user explicitly responded `approve` to
approval envelope
`dd85e3e629aeaec0db889332c72fe32fc4f9c235167e169c321fb1df34b37b4e`.
The record binds 141 files (manifest
`1eda78dc1e49e0a28024542968f67d1915fdcd7652ed4e9651ee40e7cbe022b2`),
frozen-input digest
`7be0060b25b1bea79b6e51f6719df627ff62a8d7aec5c06bf1334dd758df07d7`,
Git commit `a4b1e96aad44dd586417413b7df860255f4ff2dd`, tree
`48d40b7d67bf3620b46d54d08b0b9502a1a3cc26`, parent
`e868643a011042ff71a84d72a67f9340ddf89d4c`, and wheel SHA-256
`e5e069cb5a219f0b6c59b4b2a94bbad7507a3add1ede0e544d2d304bfee6c5b4`.
The campaign is `approved_not_started`; all execution counters remain zero and
neither the raw nor retained root has been created.

## Task 6: Execute exactly the approved campaign

- [x] **Step 1: Assert the raw root is new and empty**

Resolve the exact D: root, reject links/reparse redirects or prior contents,
write the approval/campaign header, and stop if any frozen hash differs.

- [x] **Step 2: Run 24 fresh sessions once**

Run 12 baseline and 12 suite-enabled sessions with at most four concurrent
workers. Do not retry, resume, remind, coach, or edit a case while the batch is
active.

- [x] **Step 3: Seal raw execution state**

Write the raw campaign ledger, per-run hashes/status, complete deviations, and
campaign completion marker. Preserve failed outputs exactly.

Approved1 execution checkpoint (2026-08-20): all 24 authorized processes were
started once and sealed without retry. Every process exited 2 before session
creation because `codex-cli 0.148.0` rejects the simultaneous
`--approve-for-me` and `--sandbox workspace-write` arguments. All runs retain
`PROCESS_NONZERO` and `FINAL_BINDING_INVALID`; the raw ledger records 49
deviations and `RUN_PLAN_FAILED`. This is an immutable harness failure, not a
behavioral pass. The correction requires a new approval and unique roots.

## Task 7: Import, adjudicate, and record immutable behavior

- [x] **Step 1: Import through the tested sanitizer only**

Regenerate retained evidence and ledgers from raw roots. Verify every retained
byte, redaction count, final-message binding, and protected-state hash.

- [x] **Step 2: Adjudicate all declared assertions**

Produce per-case `result.json`, variant summaries, baseline-versus-suite delta,
and a campaign summary. Do not require baseline failures for a suite pass, but
record them honestly. Suite closure requires every suite-enabled case to pass;
any failed suite case remains failed until a separately approved corrective
batch.

- [x] **Step 3: Disclose every deviation**

Separate evaluator behavior, harness failure, platform capability skip,
sanitization-only change, and review correction. No deviation may silently
change an assertion outcome.

Approved1 evidence checkpoint (2026-08-20): the sanitizer/importer retained
515 files and 24 ledgers; exact replay found 0 evaluable runs. Adjudication
produced 24 failed results, baseline 0/12, suite-enabled 0/12, 25
suite-relevant deviations, and `suite_closure_passed=false`. The immutable
record is `tests/skills/complete-suite-release-verification.md`; retained
evidence is under `tests/skills/evidence/complete-suite/approved1`.

## Corrective campaign 2: repair the approved1 launch incompatibility

- [x] **Step 1: Preserve approved1 before changing the harness**

Commit the exact sanitized evidence, result documents, replay hashes, and
failure record. Approved1 remains failed and may never be retried or rewritten.

- [x] **Step 2: Reproduce and repair the CLI argument conflict with TDD**

Require the launch command to contain exactly one `--approve-for-me` and no
separate `--sandbox` option. `codex-cli 0.148.0` documents that
`--approve-for-me` itself routes automatic review through workspace-write.
Retain the explicit network-denial config and every other frozen policy.

- [x] **Step 3: Create a closed, nonexecuted proposed2 record**

Use campaign ID `2026-08-20-proposed2`, raw root
`D:\tmp\kokoroarc-m9-task18-campaign-20260820-approved2`, and retained root
`tests/skills/evidence/complete-suite/approved2`. Start at
`draft_not_approved` with no frozen inputs, no approval, and zero execution.

- [x] **Step 4: Run and commit the complete proposed2 preapproval gate**

Rerun the complete structure, preparation, runner, sanitizer, importer,
adjudicator, no-spawn, package-inventory, and validator selection. Verify both
approved2 roots are absent and the approved1 evidence remains byte-identical.

Checkpoint: corrective harness commit `44032b3f897393b7eae04a0bf171e8a94c61636e`
(tree `303e067d2c8f4ea80ceb6ecb7bc0b9f914e15956`, parent
`c536ee82d33bba14a9124485789f2f4562fa3f8d`) passed 123 tests with 3
documented Windows link-capability skips. All four Skill validators passed.
Both approved2 roots were absent, and the 515-file approved1 inventory
recomputed to its original SHA-256
`8eae25e7b6a0bee1929c3405280ff4d900403a34a52d423cfd0390a0aa7bb862`.

- [x] **Step 5: Freeze proposed2 and request fresh explicit approval**

Present the new exact commit/tree/parent, closed file manifest, wheel, campaign
SHA-256, envelope SHA-256, unchanged 24-run policy, new roots, and disclosed
approved1 harness correction. Do not launch on the approved1 response.

Approval checkpoint: the user explicitly responded `approve` to proposed2
envelope
`4938b9de462b5f81a20fb1c79022290dd6675cfe06facb91e36da35418e4b5f5`.
It binds the tested harness commit
`44032b3f897393b7eae04a0bf171e8a94c61636e`, 141-file manifest
`ebffd439ecdd71b7cc90634b897464beab941e34ee84c43a5f5b7565ab9f4744`,
wheel `e5e069cb5a219f0b6c59b4b2a94bbad7507a3add1ede0e544d2d304bfee6c5b4`,
24 one-shot runs, and the unique approved2 roots. Approval ID
`user-approval-4938b9de462b-02` was recorded at `2026-08-20T03:20:14Z`.

- [x] **Step 6: Record approval, execute once, import, and adjudicate**

Commit `approved_not_started` before execution. Run each of the 24 sessions
once with concurrency at most four; seal regardless of outcome. Import and
adjudicate through the exact tested replay paths. A further correction requires
another approval and unique roots.

Approved2 checkpoint: all 24 authorized provider threads were started once and
sealed without retry. The provider rejected the frozen response schema before
evaluation because `$defs.relative_path.not` has no explicit `type`. Exact
import and adjudication replay passed, but no run was evaluable; baseline and
suite-enabled results are both 0/12 and `suite_closure_passed=false`. Approved2
is immutable under `tests/skills/evidence/complete-suite/approved2`. A schema
correction requires proposed3, unique roots, and fresh exact approval.

## Corrective campaign 3: repair the approved2 provider-schema incompatibility

- [x] **Step 1: Preserve approved2 before changing the response schema**

Commit `c474ff2b32dd414c2a50f3898be13fd2b0d98c5e` seals the exact
approved2 raw/retained evidence, replay, adjudication, and failure record.
Approved2 remains failed and may never be retried, rewritten, or used to
authorize a later campaign.

- [x] **Step 2: Reproduce and repair the provider-schema boundary with TDD**

The provider rejected all 24 sessions with the same 400
`invalid_json_schema` response before any evaluator behavior occurred. The
official
[Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs)
documents `not` as unsupported and does not list `uniqueItems` among
supported array properties. Add a structural regression for the
provider-facing subset, remove `not` and `uniqueItems`, replace the one-value
`const` with a typed one-value enum, and retain the relative-path rule in a
single supported string pattern. Duplicate assertion IDs remain rejected by
the local evidence-bound adjudicator rather than being trusted from evaluator
output.

- [x] **Step 3: Create a closed, nonexecuted proposed3 record**

Use campaign ID `2026-08-20-proposed3`, raw root
`D:\tmp\kokoroarc-m9-task18-campaign-20260820-approved3`, and retained root
`tests/skills/evidence/complete-suite/approved3`. Start at
`draft_not_approved` with no frozen inputs, no approval, and zero execution.
The approved1 and approved2 evidence roots remain byte-identical.

- [x] **Step 4: Run and commit the complete proposed3 preapproval gate**

Rerun the complete structure, preparation, runner, sanitizer, importer,
adjudicator, no-spawn, package-inventory, and validator selection. Verify both
approved3 roots are absent and both prior approved evidence inventories remain
byte-identical.

Checkpoint: provider-compatible harness commit
`8623f555641b1b8596f559f14923e773c1c5a471` (tree
`84451c7befca6aa1ce87839580cff73498dea995`, parent
`c474ff2b32dd414c2a50f3898be13fd2b0d98c5e`) passed 124 tests with 3
documented Windows link-capability skips in 493.18 seconds. All four Skill
validators passed. Both proposed3 roots were absent. The 515-file approved1
and approved2 inventories recomputed exactly to
`8eae25e7b6a0bee1929c3405280ff4d900403a34a52d423cfd0390a0aa7bb862`
and `c04fc14fa99acfefd3e06c0f003da793630714e39c0c540b37f2e0412e1cdf88`;
the exact harness range and final status were clean.

- [x] **Step 5: Freeze proposed3 and request fresh explicit approval**

Present the new exact commit/tree/parent, closed file manifest, wheel, campaign
SHA-256, envelope SHA-256, unchanged 24-run policy, unique roots, and the
approved2 provider-schema correction. The approved1 or approved2 responses do
not authorize proposed3.

- [x] **Step 6: Record approval, execute once, import, and adjudicate**

Only after a fresh exact user approval, commit `approved_not_started`, execute
each of the 24 sessions once with concurrency at most four, seal regardless of
outcome, and run the exact import/replay/adjudication path. Any later correction
requires another campaign, new roots, and new approval.

Approved3 checkpoint: the user approved envelope
`6e02744b1523e8455652cfd1999a2c400398b1d46e3991b7640fb1acb4e85aa3`.
The approval was recorded in campaign SHA-256
`2c86e70cc07266b5ffb97e46cb6e998bcffcfa01496e435170c60df4d3dde53d`
and committed as `f48b05e2380da9de628e6b9865d8cea7c890dd84` before
execution. The one-shot runner started and completed all 24 processes with no
retry, timeout, nonzero process exit, or raw deviation and sealed raw ledger
`81797df9d23dd0068b8d0c818689a4a30abc96e29f76b46127fcb5f065edb479`.
Exact import/replay retained 542 files and 24 evaluable run ledgers under
`tests/skills/evidence/complete-suite/approved3`; import ledger
`d8611bc380a7033ccff2928f5e12f5596e779bdf8d55999efc2b831ca24903ab`
and retained inventory
`811c92b0c6e141d511bb67fdffdffbec2e0765f6cb9a5cf520527e8aae40f6d7`
replay exactly.

Approved3 remains a harness failure rather than behavioral evidence. The
isolated runtime installed the KokoroArc wheel with `--no-deps`, so invoked CLI
processes failed at import time with `ModuleNotFoundError: jsonschema`. The
frozen adjudicator also rejects the actual escaped Windows PowerShell wrapper
form and rejects the provider-approved `not_applicable` claim status in its
own result validator. Its one adjudication attempt therefore failed closed
before publishing a results tree. Approved3 may never be retried or rewritten;
any correction requires a proposed4 campaign, unique roots, a new frozen
envelope, and fresh explicit approval.

## Corrective campaign 4: hermetic runtime and evidence-bound protocol

- [x] **Step 1: Preserve the immutable approved3 harness failure**

Commit `f99b798b8de6907dd26d283d7bc51bdea85599b1` preserves the 542-file
approved3 retained root and the exact failure record. Raw-to-retained replay,
final-event rebinding, sanitizer self-scan, and all 24 evaluable ledgers passed.
The full canonical retained inventory is
`811c92b0c6e141d511bb67fdffdffbec2e0765f6cb9a5cf520527e8aae40f6d7`;
no results tree exists. The focused preservation gate passed 124 tests with 3
documented Windows capability skips.

- [x] **Step 2: Approve the corrective design before implementation**

The user approved the hermetic-runtime design recorded in
`docs/superpowers/specs/2026-08-20-kokoroarc-complete-suite-campaign-4-design.md`.
It retains evidence-derived adjudication, exact agent self-reporting, a closed
actual-provider wrapper grammar, and a separate fresh approval boundary for
provider execution.

- [x] **Step 3: Specify the hermetic installed runtime with failing tests**

Add RED tests for a closed, hash-bound dependency wheelhouse; offline
installation; dependency resolution beneath the isolated target; a real CLI
smoke command; rejection of host-site resolution, missing wheels, drift,
links/reparse points, source distributions, unexpected files, and any network
configuration.

- [x] **Step 4: Specify actual provider wrappers with failing tests**

Add representative escaped drive-path command events from approved3, optional
`-NoProfile` forms, and adversarial executable, flag, quoting, comment,
dead-branch, cwd, environment, argv, capture, and hidden-command variants.
Require fail-closed parsing without weakening the existing command-safety and
confinement checks.

- [x] **Step 5: Specify exact claim and status semantics with failing tests**

Require every `must` and `must_not` ID exactly once, reject omissions,
duplicates, and inventions, make `not_applicable` consistent across schema,
final parsing, result validation, replay, and summaries, and prove that claims
cannot create an evidence pass.

- [x] **Step 6: Implement the minimal harness correction**

Implement only the behavior required by Steps 3 through 5. Extend the generated
prompt, campaign schema/record, frozen-input validation, installed runtime
preparation, command parser, and campaign-result validator without touching
approved1 through approved3.

The dirty-tree implementation preflight passed 147 complete-suite harness tests
with the same three documented Windows link-capability skips. All four source
Skill validators passed. Disposable replay copies rebound all 72 immutable
approved1-through-approved3 runs, reproduced approved3's 24 valid final
bindings, and self-scanned 1,572 retained files without a sanitizer finding.
No dependency download, provider process, proposed4 campaign root, or proposed4
results root was created; the real frozen-wheelhouse smoke remains part of
Step 7.

- [x] **Step 7: Run and commit the proposed4 preapproval gate**

Run the focused RED-to-GREEN selection and the complete Task 18 harness gate,
all four Skill validators, raw replay/final binding for approved1 through
approved3, inventory and secret scans, package/runtime smoke, exact-range
whitespace checks, and clean status. Commit the implementation before creating
an approval envelope.

Proposed4 checkpoint (2026-08-20): implementation commit
`788e86a08af8c94a36bed8d4b33021091201b4a6` has tree
`2660d8902d0bb4d1265ff7ecad551ae2c9b6c09e` and parent
`a2d7236bc289a96f417b06e986b1f9b9034d58ee`. Its exact post-commit
complete-suite harness gate passed 147 tests with three documented Windows
link/symlink capability skips. Two fixed-epoch KokoroArc wheel builds were
byte-identical at SHA-256
`61ef3a5ff7201eebbcc6d6fb1c88016ce6de8cf74ab38592c0206ed72db4e1e5`.
After separate network approval, the seven-distribution binary wheelhouse was
acquired under D:, closed at manifest SHA-256
`0753050ecf612684fec5102e993253c74842ec618bfcc086a025f5dee69bbba2`,
and passed offline isolated imports, CLI version, and Rin validation smokes.
No provider process or proposed4 campaign/results root was created.

- [x] **Step 8: Create and freeze proposed4 without executing it**

Use campaign ID `2026-08-20-proposed4`, raw root
`D:\tmp\kokoroarc-m9-task18-campaign-20260820-approved4`, and retained root
`tests/skills/evidence/complete-suite/approved4`. Bind the exact dependency
wheelhouse manifest, approval-bound file manifest, package wheel, Git identity,
and 24-run policy. Both proposed4 campaign roots and any results root must be
absent.

Frozen proposed4 checkpoint (2026-08-20): the draft envelope binds harness
commit `778c77dc93a1bfa13537f5d96c31e5ad779b602e`, tree
`1c5c67d8b7ba29d4ff36a9534440afcead354849`, parent
`788e86a08af8c94a36bed8d4b33021091201b4a6`, 141 approval-bound files
at manifest SHA-256
`047a372cabe1f5ec2de84c434bff86fde45e98c257e227625e1c43b62073d9bc`,
frozen-input digest
`1f3a00ee24b8e9b6e20483b0aba0d888563a2ccd378db6b6ba5e07530034b3e6`,
wheelhouse manifest
`0753050ecf612684fec5102e993253c74842ec618bfcc086a025f5dee69bbba2`,
and KokoroArc wheel
`61ef3a5ff7201eebbcc6d6fb1c88016ce6de8cf74ab38592c0206ed72db4e1e5`.
The proposed campaign SHA-256 is
`524500592534f9438f6b7b741eae6cf639672b28bb949782416088b5efb7a26b`;
the approval envelope SHA-256 is
`0e6b3e3146b4d3cf6539b14412e0f127c39d60d41048d96ddcad26987100ae64`.
Status remains `draft_not_approved`, `user_approval` remains null, all
execution counters remain zero, and neither proposed4 campaign root exists.

- [x] **Step 9: Request fresh exact approval, then execute once if approved**

Present the complete frozen envelope. Only a new explicit approval authorizes
the `approved_not_started` commit and one-shot 24-session execution. The current
design approval does not authorize provider execution or dependency network
access.

Approval received (2026-08-20): the user responded `approve` directly to the
presentation of exact envelope
`0e6b3e3146b4d3cf6539b14412e0f127c39d60d41048d96ddcad26987100ae64`.
The approval record ID is `user-approval-0e6b3e3146b4-04` and its UTC timestamp
is `2026-08-20T08:54:04Z`. Execution remains blocked until the
`approved_not_started` record is validated and committed cleanly.
The validated approved campaign SHA-256 is
`3f283f7cec6bb147f819616883c28cd1281f1478e63d869f33cceb457eb1789b`.

Approved4 execution outcome (2026-08-20): preparation stopped before provider
launch with `CAMPAIGN_PREPARATION_FAILED` / `ModuleNotFoundError`. The trusted
fixture builder imported KokoroArc from the harness process instead of the
installed frozen target. Runs authorized/started/completed are `24/0/0`; no
provider session or raw `runs` directory exists. The sealed raw ledger is
`a737cfeb13e877bcc6d0da24a7c19a4064b9c9dc12d32eab0ac77ba3728a0202`.

- [x] **Step 10: Preserve approved4 and harden the preparation boundary**

Retain the zero-run campaign without inventing run artifacts. Bind the exact
pre-seal raw snapshot, import only campaign-level artifacts, and prove exact
replay. Move fixture creation into the isolated installed runtime, and make
every pre-provider preparation exception seal a bounded zero-run failure.

Implementation commit
`86d940281612b17a1f593301c01623a76e568449` added isolated fixture creation,
zero-run failure sealing/import/replay, and regression coverage. Approved4's
pre-seal snapshot contains 389 files, 6,398,678 bytes, and tree SHA-256
`a82b3a59c9208c49fb6c298785051f2bba9df81bb9b5479b5f08500738b7933f`.
Its six retained files have import-ledger SHA-256
`4a7675f203fb3365a9dc743e4426fb5217da49e27817fea8f5c6a2a7aa9df90e`
and retained tree SHA-256
`ceac9432c278c9fb74a787745ac34c28411b8ec3c4616c45728bca4ec2cf1292`.

Post-approval reconstruction also proved that 37 frozen files reflected a
mixed legacy working-tree newline state. Their exact approved hashes were
recovered and checked without relaxing validation. Corrective campaign 5 must
add fresh-checkout byte equality to the preapproval gate.

- [ ] **Step 11: Create, verify, and freeze proposed5 without executing it**

Use campaign ID `2026-08-20-proposed5`, raw root
`D:\tmp\kokoroarc-m9-task18-campaign-20260820-approved5`, and retained root
`tests/skills/evidence/complete-suite/approved5`. Normalize every
approval-bound working-tree file to its declared checkout policy, prove the
141-file manifest in a fresh `core.autocrlf=true` checkout, rerun the complete
preapproval gate, and freeze a new draft envelope. Do not create the raw or
retained campaign root and do not launch a provider process.

- [ ] **Step 12: Request fresh exact proposed5 approval**

Present the complete proposed5 envelope. No earlier design or campaign
approval authorizes execution. Only a new explicit approval of the exact
frozen envelope permits an `approved_not_started` commit and one-shot launch.

## Task 8: Run the settled deterministic release gate

- [ ] **Step 1: Run the complete test collection**

Use non-overlapping unit, integration, security, and Skill partitions under
fresh D: roots. Record exact counts, durations, stdout/stderr hashes, and every
skip reason. Run `compileall`, changed-line length, and exact-range whitespace
checks.

- [ ] **Step 2: Build twice at the fixed Task 17 base epoch**

Require byte-identical wheels, normalized-content-identical sdists, exact
module/schema/Skill/plugin inventories, and no undeclared artifact.

- [ ] **Step 3: Verify installed wheel and sdist workflows**

With repository source unavailable, validate import/schema/Skill discovery,
suite install/reinstall, archive export/compatibility/migration/install/remove,
global/workspace defaults, explicit sessions, consent, state event/replay,
export/reset/revoke, and memory reference add/list/remove.

- [ ] **Step 4: Validate plugin and all Skill copies**

Run the official plugin validator and all four official Skill validators for
source, wheel-installed, and sdist-installed copies.

- [ ] **Step 5: Audit a fresh `core.autocrlf=true` checkout**

Verify exact evidence bytes, LF-pinned hash inputs, clean status, exact-range
diff check, focused tests, build inventories, and installed smoke in a detached
D:-based checkout.

## Task 9: Commit and rerun the exact settled release record

- [ ] **Step 1: Write the release verification record**

Record approval, immutable behavioral outcomes, all deviations, raw/retained
replay counts, final bindings, tests/skips, builds/inventories, installed
workflows, validators, checkout audit, and the explicit no-upload/no-truth/no-
safety-certification boundary.

- [ ] **Step 2: Commit the complete release record**

Stage only Task 18 plan/cases/harness/tests/sanitized evidence/release record
and required line-ending policy. Run cached diff/status/inventory checks before
committing.

- [ ] **Step 3: Rerun exact-final gates**

On the committed tree, rerun focused evidence tests, raw replay, final binding,
full suite, fixed-epoch distributions, installed artifact workflows,
validators, checkout byte audit, exact-range diff, and clean status.

## Task 10: Obtain fresh independent reviews and close the suite

- [ ] **Step 1: Freeze exact review identity**

Provide commit/tree/parent/base, exact scope, design/plan requirements, settled
artifacts, and prior review findings. Reviewers remain read-only and use fresh
D: roots/checkouts.

- [ ] **Step 2: Obtain specification review**

Require a formal verdict with Critical/Important/Minor findings. Any Critical
or Important finding returns to a focused RED regression and a new exact
settled gate; then request a fresh specification review.

- [ ] **Step 3: Obtain quality/security review only after spec PASS**

Require the same exact-identity discipline. Fix any Critical or Important
finding with RED tests and repeat both reviews in order.

- [ ] **Step 4: Mark Task 18 and the standalone suite complete**

Only after both fresh reviews PASS with no Critical or Important finding,
update the canonical completion plan and record the final exact identity,
counts, artifacts, approvals, evidence bindings, limitations, and clean status.

---

## Completion boundary

Task 18 closure proves deterministic local behavior, evidence-bound Skill
routing, safe installed workflows, and exact release reproducibility for the
declared cases and artifacts. It does not establish fictional canon truth,
provenance authenticity, general model safety, universal platform support,
public-registry approval, upload, signing, or future-version compatibility.
