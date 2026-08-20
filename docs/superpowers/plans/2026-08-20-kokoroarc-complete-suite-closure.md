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

- [ ] **Step 1: Assert the raw root is new and empty**

Resolve the exact D: root, reject links/reparse redirects or prior contents,
write the approval/campaign header, and stop if any frozen hash differs.

- [ ] **Step 2: Run 24 fresh sessions once**

Run 12 baseline and 12 suite-enabled sessions with at most four concurrent
workers. Do not retry, resume, remind, coach, or edit a case while the batch is
active.

- [ ] **Step 3: Seal raw execution state**

Write the raw campaign ledger, per-run hashes/status, complete deviations, and
campaign completion marker. Preserve failed outputs exactly.

## Task 7: Import, adjudicate, and record immutable behavior

- [ ] **Step 1: Import through the tested sanitizer only**

Regenerate retained evidence and ledgers from raw roots. Verify every retained
byte, redaction count, final-message binding, and protected-state hash.

- [ ] **Step 2: Adjudicate all declared assertions**

Produce per-case `result.json`, variant summaries, baseline-versus-suite delta,
and a campaign summary. Do not require baseline failures for a suite pass, but
record them honestly. Suite closure requires every suite-enabled case to pass;
any failed suite case remains failed until a separately approved corrective
batch.

- [ ] **Step 3: Disclose every deviation**

Separate evaluator behavior, harness failure, platform capability skip,
sanitization-only change, and review correction. No deviation may silently
change an assertion outcome.

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
