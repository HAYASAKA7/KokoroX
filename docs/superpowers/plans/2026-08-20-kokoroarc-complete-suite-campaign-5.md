# KokoroArc Complete-Suite Campaign 5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task by task. Use
> `superpowers:test-driven-development` for every behavior or policy change,
> `superpowers:systematic-debugging` for any unexpected failure, and
> `superpowers:verification-before-completion` before every commit or success
> claim.

**Goal:** Produce a fully verified, exact-byte-reproducible proposed5 campaign
draft and approval envelope without creating campaign roots or launching a
provider process.

**Architecture:** Commit a canonical harness checkpoint whose 141
approval-bound files are LF-stable in both the preparation worktree and a fresh
`core.autocrlf=true` checkout. Reuse and revalidate the closed seven-wheel
offline wheelhouse, rebuild KokoroArc at the fixed release epoch, then freeze
only the non-approval-bound campaign metadata against the canonical harness
commit. Run all preapproval, replay, packaging, validator, checkout, and
absence gates on the exact frozen draft before presenting its hashes.

**Tech Stack:** Python 3.14, pytest, PyYAML, JSON Schema, Git, PowerShell 7,
`build`, and the existing KokoroArc complete-suite campaign harness.

---

## Safety and identity constants

Use these exact paths and identities throughout the plan:

```text
Repository worktree:
D:\Projects\AI\KokoroArc\.worktrees\standalone-suite

Campaign ID:
2026-08-20-proposed5

Proposed raw root, which must remain absent:
D:\tmp\kokoroarc-m9-task18-campaign-20260820-approved5

Proposed retained root, which must remain absent:
tests/skills/evidence/complete-suite/approved5

Reusable dependency wheelhouse:
D:\tmp\kokoroarc-proposed4-wheelhouse-788e86a-01

Task 17 KokoroArc wheel SHA-256:
61ef3a5ff7201eebbcc6d6fb1c88016ce6de8cf74ab38592c0206ed72db4e1e5

Expected wheelhouse manifest SHA-256:
0753050ecf612684fec5102e993253c74842ec618bfcc086a025f5dee69bbba2
```

Never invoke `tests/skills/run_complete_suite_campaign.py` with an approved
campaign hash during this plan. Never create either proposed5 root. Never
modify approved1 through approved4 evidence. Provider execution requires a
later, explicit approval of the exact proposed5 envelope.

For test commands, first set the source import root in the current PowerShell
process:

```powershell
$env:PYTHONPATH = (Resolve-Path 'src').Path
```

Use a new unique subdirectory of `D:\tmp` for every pytest `--basetemp`, build,
install, and checkout operation. Do not remove or overwrite a pre-existing
temporary root.

## Task 1: Add checkout-policy and proposed5 RED tests

**Files:**

- Modify: `tests/skills/test_complete_suite_campaign_structure.py`
- Test: `tests/skills/test_complete_suite_campaign_structure.py`

- [ ] **Step 1: Change the campaign identity and roots asserted by the
  structure test**

Change `test_complete_suite_campaign_state_is_closed_and_nonexecuted` to
require:

```python
assert document["campaign_id"] == "2026-08-20-proposed5"
assert document["status"] == "draft_not_approved"
assert document["user_approval"] is None
```

Change the asserted isolation roots to:

```python
"raw_root": "D:\\tmp\\kokoroarc-m9-task18-campaign-20260820-approved5",
"retained_root": "tests/skills/evidence/complete-suite/approved5",
```

Keep the existing zero execution counters and 24-run policy assertions.
Retain the conditional frozen-input validation so an empty draft can become a
fully frozen draft without weakening the test.

- [ ] **Step 2: Add an approval-bound LF policy test**

Import `subprocess` and the campaign runner module in the structure test. Add
`test_approval_bound_checkout_policy_is_explicit_and_current_bytes_are_lf`.
The test must:

1. call `runner.approval_bound_paths()` and require exactly 141 sorted unique
   paths;
2. invoke `git check-attr text eol -- $batch` for bounded batches drawn from
   those 141 paths;
3. require every path to be declared `text` with `eol=lf`;
4. read each current raw file with `Path.read_bytes()` and require that no
   file contains `b"\r\n"`; and
5. identify the failing relative path in every assertion without echoing file
   contents.

This test intentionally fails first because `MANIFEST.in` has no explicit LF
attribute and legacy worktree bytes still contain CRLF.

- [ ] **Step 3: Run the RED selection**

```powershell
python -B -m pytest tests/skills/test_complete_suite_campaign_structure.py::test_complete_suite_campaign_state_is_closed_and_nonexecuted tests/skills/test_complete_suite_campaign_structure.py::test_approval_bound_checkout_policy_is_explicit_and_current_bytes_are_lf -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-proposed5-red-01
```

Expected: both tests fail for the intended proposed4/checkout-policy reasons.
No provider process or proposed5 root may appear.

## Task 2: Create the canonical proposed5 harness state

**Files:**

- Modify: `.gitattributes`
- Modify: `tests/skills/complete-suite-campaign.yaml`
- Modify: `tests/skills/test_complete_suite_campaign_structure.py`
- Verify: all 141 paths returned by
  `tests/skills/run_complete_suite_campaign.py::approval_bound_paths`

- [ ] **Step 1: Pin `MANIFEST.in` to LF**

Add this rule next to the other distribution inputs:

```gitattributes
MANIFEST.in text eol=lf
```

- [ ] **Step 2: Convert the campaign record to an unapproved proposed5
  skeleton**

In `tests/skills/complete-suite-campaign.yaml`:

1. set `campaign_id: 2026-08-20-proposed5`;
2. set `status: draft_not_approved`;
3. change the raw and retained roots to the exact proposed5 paths;
4. replace the entire `frozen_inputs` mapping with `{}`;
5. set `user_approval: null`; and
6. preserve the zero execution mapping exactly.

Do not change cases, evaluator, prohibited operations, rerun policy, or the
24-run count.

- [ ] **Step 3: Normalize only approval-bound LF files**

Use `runner.approval_bound_paths()` as the exact allowlist. For each path whose
Git attributes are `text: set` and `eol: lf`, replace raw CRLF byte pairs with
LF. Do not decode/re-encode text, do not touch files outside the allowlist,
and do not alter lone CR bytes. Record the list and before/after SHA-256 values
under a unique `D:\tmp\kokoroarc-proposed5-normalize-01` audit directory, not
inside the repository.

After normalization, require all 141 raw files to be CRLF-free. Review
`git diff --numstat`, `git diff --summary`, and `git diff --check`; the expected
Git content delta is only the new `.gitattributes` rule, the proposed5 draft
record, and the test changes. LF normalization of already-normalized Git blobs
must not create unrelated semantic diffs.

- [ ] **Step 4: Run the focused GREEN selection**

```powershell
python -B -m pytest tests/skills/test_complete_suite_campaign_structure.py tests/skills/test_complete_suite_preparation.py::test_fixture_assets_are_built_inside_the_installed_runtime tests/skills/test_complete_suite_evidence.py::test_preparation_failure_import_is_zero_run_and_exactly_replayable -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-proposed5-green-01
```

Expected: pass, with only documented filesystem-capability skips if selected
tests reach those branches.

- [ ] **Step 5: Verify draft/root absence and the exact working diff**

```powershell
Test-Path 'D:\tmp\kokoroarc-m9-task18-campaign-20260820-approved5'
Test-Path 'tests/skills/evidence/complete-suite/approved5'
git diff --check
git status --short
```

Both `Test-Path` results must be `False`.

## Task 3: Commit the canonical harness checkpoint

**Files:**

- Modify: `.gitattributes`
- Modify: `tests/skills/complete-suite-campaign.yaml`
- Modify: `tests/skills/test_complete_suite_campaign_structure.py`
- Modify: `docs/superpowers/plans/2026-08-20-kokoroarc-complete-suite-closure.md`
- Modify: this plan only to record completed checkpoints

- [ ] **Step 1: Run the complete pre-checkpoint harness test partition**

```powershell
python -B -m pytest tests/skills/test_complete_suite_campaign_structure.py tests/skills/test_complete_suite_preparation.py tests/skills/test_complete_suite_evidence.py tests/skills/test_complete_suite_release_evidence.py -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-proposed5-harness-01
```

Require every non-capability test to pass. Record exact pass/skip counts and
skip reasons in the closure plan.

- [ ] **Step 2: Re-run the isolated builder and zero-run failure regressions**

```powershell
python -B -m pytest tests/skills/test_complete_suite_preparation.py -k "fixture_assets and installed_runtime" tests/skills/test_complete_suite_evidence.py -k "preparation_failure" -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-proposed5-boundaries-01
```

Require installed-runtime origin checks to pass and zero-run replay to remain
exact.

- [ ] **Step 3: Audit and stage only the canonical checkpoint**

```powershell
git diff --check
git status --short
git diff -- .gitattributes tests/skills/complete-suite-campaign.yaml tests/skills/test_complete_suite_campaign_structure.py docs/superpowers/plans/2026-08-20-kokoroarc-complete-suite-closure.md docs/superpowers/plans/2026-08-20-kokoroarc-complete-suite-campaign-5.md
```

Confirm approved1-through-approved4 evidence is unchanged and proposed5 roots
remain absent. Stage only the five listed logical changes and inspect
`git diff --cached --check` plus `git diff --cached --stat`.

- [ ] **Step 4: Commit the canonical checkpoint**

```powershell
git commit -m "test: canonicalize complete-suite campaign 5 inputs"
```

Record `commit`, `tree`, and sole `parent`. This commit is the frozen
`harness_git` identity. No approval-bound file may change after this point;
only the non-approval-bound campaign YAML and checkpoint documentation may be
updated when the draft is frozen.

## Task 4: Prove fresh-checkout raw-byte equality

**Files:**

- Read: the 141 approval-bound files at the canonical harness commit
- Read: `.gitattributes`
- Test: `tests/skills/test_complete_suite_campaign_structure.py`

- [ ] **Step 1: Create a fresh detached D:-based checkout**

Create a new unique checkout directory below
`D:\tmp\kokoroarc-proposed5-checkout-01`. Configure that checkout with
`core.autocrlf=true`, detach it at the canonical harness commit, and require a
clean status. Do not use the approved4 reconstruction directory.

- [ ] **Step 2: Compare all 141 raw files**

From the preparation worktree, compute the sorted allowlist with
`runner.approval_bound_paths()`. For every path, compare raw size and SHA-256
between the preparation worktree and the fresh checkout. Require:

```text
path count = 141
missing = 0
extra = 0
size mismatches = 0
SHA-256 mismatches = 0
CRLF-bearing approval inputs = 0
```

Also require `git check-attr text eol` to report `text/set` and `eol/lf` for
every path in the fresh checkout.

- [ ] **Step 3: Run the focused test in the fresh checkout**

```powershell
python -B -m pytest tests/skills/test_complete_suite_campaign_structure.py -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-proposed5-checkout-tests-01
```

Require a clean checkout before and after the test. Preserve the byte-audit
summary under `D:\tmp`; do not add it to retained campaign evidence.

## Task 5: Revalidate and rebuild frozen distribution inputs

**Files:**

- Read: `pyproject.toml`
- Read: `MANIFEST.in`
- Read: `tests/skills/complete_suite_preparation.py`
- Read: `D:\tmp\kokoroarc-proposed4-wheelhouse-788e86a-01`

- [ ] **Step 1: Re-capture the existing wheelhouse**

Call `complete_suite_preparation.capture_runtime_wheelhouse` on the exact
wheelhouse path. Require seven flat wheels, the exact distribution set, no
extra entry, and manifest SHA-256
`0753050ecf612684fec5102e993253c74842ec618bfcc086a025f5dee69bbba2`.
This step is offline and must not invoke pip download or any network client.

- [ ] **Step 2: Rebuild KokoroArc twice at the fixed release epoch**

Use two new D:-based source checkouts of the canonical harness commit and the
fixed Task 17 `SOURCE_DATE_EPOCH`. Build wheel and sdist twice with bytecode and
build directories under unique D: roots. Require both wheels to be
byte-identical and the KokoroArc wheel SHA-256 to equal
`61ef3a5ff7201eebbcc6d6fb1c88016ce6de8cf74ab38592c0206ed72db4e1e5`.
Require normalized sdist contents and package inventories to match.

- [ ] **Step 3: Prove offline installed-runtime behavior**

Install only from the closed wheelhouse into a new D:-based target with
`--no-index`, `--find-links`, `--only-binary=:all:`, `--no-deps` as appropriate
for the already closed dependency set. With repository source absent from
`sys.path`, require:

1. `kokoroarc` module origins resolve below the installed target;
2. `python -m kokoroarc.cli --version` reports the frozen version;
3. CLI help succeeds;
4. real Rin source validation succeeds; and
5. isolated fixture generation succeeds and leaves the installed target
   inventory unchanged.

Re-capture the wheelhouse after these smokes and require the manifest to be
unchanged.

## Task 6: Freeze proposed5 against the canonical checkpoint

**Files:**

- Modify: `tests/skills/complete-suite-campaign.yaml`
- Read: `tests/skills/run_complete_suite_campaign.py`
- Test: `tests/skills/test_complete_suite_campaign_structure.py`

- [ ] **Step 1: Generate exact frozen inputs from existing pure helpers**

Use `runner.approval_bound_paths()` and `runner.freeze_file_entries()` in the
preparation worktree. Capture schema version `1.0`, the exact canonical
checkpoint commit/tree/parent recorded in Task 3, the 141 sorted raw
size/SHA-256 records, the revalidated KokoroArc wheel record, and the
revalidated seven-wheel manifest.

Before writing the campaign YAML, call `runner.verify_frozen_files()` against
the preparation worktree and the detached autocrlf checkout. Require exact
success in both locations.

- [ ] **Step 2: Replace only `frozen_inputs` in the draft record**

Keep `status: draft_not_approved`, `user_approval: null`, zero execution
counters, proposed5 identity, and proposed5 roots. Serialize the YAML
deterministically with the same PyYAML policy used for proposed4. Review that
the campaign file itself is not returned by `approval_bound_paths()` and that
no approval-bound file changed after the canonical checkpoint.

- [ ] **Step 3: Validate the frozen draft without launching**

Run the structure test and directly load the record to compute:

1. campaign canonical SHA-256;
2. approval-envelope SHA-256 via
   `runner.approval_envelope_sha256(campaign)`;
3. frozen file-manifest digest;
4. wheelhouse inventory digest; and
5. the exact 24-run disclosure.

Do not call `runner.execute_campaign`, `runner.prepare_approved_campaign`, or
the provider executable. Both proposed5 roots must still be absent.

- [ ] **Step 4: Commit the frozen draft metadata**

```powershell
git diff --check
git diff -- tests/skills/complete-suite-campaign.yaml
git status --short
git commit -m "test: freeze complete-suite campaign 5 draft"
```

Stage the campaign record plus only documentation needed to record the frozen
identity. The `harness_git` value remains the preceding canonical checkpoint,
not this metadata commit.

## Task 7: Run the exact preapproval release gate

**Files:**

- Test: `tests/skills/test_complete_suite_campaign_structure.py`
- Test: `tests/skills/test_complete_suite_preparation.py`
- Test: `tests/skills/test_complete_suite_evidence.py`
- Test: `tests/skills/test_complete_suite_release_evidence.py`
- Verify: all approved1-through-approved4 retained evidence
- Verify: all four source Skills and plugin metadata

- [ ] **Step 1: Run the complete Task 18 harness selection**

```powershell
python -B -m pytest tests/skills/test_complete_suite_campaign_structure.py tests/skills/test_complete_suite_preparation.py tests/skills/test_complete_suite_evidence.py tests/skills/test_complete_suite_release_evidence.py -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-proposed5-final-harness-01
```

Record exact pass, skip, duration, stdout, and stderr evidence. Investigate any
non-capability skip or failure before proceeding.

- [ ] **Step 2: Replay every immutable retained campaign**

Run the real replay paths for approved1, approved2, approved3, and approved4.
Require their committed file inventories, import-ledger hashes, raw/retained
bindings, run counts, final-event bindings, adjudication results, and approved4
zero-run outcome to reproduce exactly. Use disposable D:-based copies for any
replay that needs a writable destination. Never write into the retained roots.

- [ ] **Step 3: Run validators and static checks**

Run:

1. the official validator for each of the four source Skills;
2. plugin manifest validation;
3. package archive inventory checks;
4. bounded secret scanning over source and retained evidence;
5. `python -B -m compileall -q src tests` with `PYTHONPYCACHEPREFIX` below
   `D:\tmp`;
6. changed-line maximum length checks;
7. `git diff --check` for the exact Task 18 base-to-draft range; and
8. `git status --short`.

No validator may rewrite the source or create bytecode in the repository.

- [ ] **Step 4: Repeat the fresh-checkout and wheel smoke on the exact draft**

Create another fresh `core.autocrlf=true` D:-based checkout. Re-run the 141
raw-byte comparisons, focused campaign tests, fixed-wheel manifest audit,
offline installed CLI/Rin/fixture smokes, exact-range diff check, and clean
status. Require the computed campaign and envelope hashes to equal the values
from Task 6.

- [ ] **Step 5: Prove the no-launch boundary**

Require all of the following:

```text
proposed5 raw root exists = false
proposed5 retained root exists = false
proposed5 results root exists = false
provider sessions created = 0
runs started = 0
runs completed = 0
user approval = null
status = draft_not_approved
```

Inspect the exact Git diff and status. Any unexpected file or root invalidates
the draft.

## Task 8: Record and present the exact envelope

**Files:**

- Modify: `docs/superpowers/plans/2026-08-20-kokoroarc-complete-suite-closure.md`
- Modify: this plan
- Read: `tests/skills/complete-suite-campaign.yaml`

- [ ] **Step 1: Record verified identities**

Append the exact frozen checkpoint details to the closure plan and this plan:

- canonical harness commit/tree/parent;
- frozen metadata commit/tree/parent;
- approval-bound file count and manifest digest;
- fresh-checkout mismatch counts;
- wheel and wheelhouse hashes;
- test pass/skip counts;
- approved1-through-approved4 replay results;
- campaign SHA-256;
- approval-envelope SHA-256; and
- explicit root-absence/no-launch evidence.

Documentation must not claim provider execution, behavioral success, or suite
completion.

- [ ] **Step 2: Commit and re-run the final narrow gate**

Commit only the verification-record update. Then re-run structure tests,
frozen-file verification in both checkouts, wheelhouse capture, campaign/envelope
hash computation, `git diff --check`, and clean status. The documentation
commit must not change any approval-bound byte or either frozen hash.

- [ ] **Step 3: Present the exact approval envelope and stop**

Present the user with:

1. campaign and envelope SHA-256 values;
2. evaluator/model/reasoning configuration;
3. 12 baseline plus 12 suite-enabled runs;
4. full disclosed inputs, retained outputs, and prohibited operations;
5. unique raw and retained roots;
6. canonical harness and wheelhouse identities;
7. preapproval verification results; and
8. the statement that this approval would authorize one
   `approved_not_started` commit and one-shot execution only.

Do not infer approval from the design approval or any earlier `approve`
message. Stop and wait for a new explicit response to the exact proposed5
envelope.

## Completion boundary

This plan is complete only when the proposed5 draft is frozen, reproducible in
a fresh autocrlf checkout, fully preapproval-verified, committed, clean, and
presented without provider execution. Campaign execution, evidence import,
behavioral adjudication, release completion, merge, push, upload, signing, or
public distribution are outside this plan and require their own authorized
steps.
