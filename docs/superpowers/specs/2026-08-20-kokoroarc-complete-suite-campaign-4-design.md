# KokoroArc Complete-Suite Corrective Campaign 4 Design

**Date:** 2026-08-20
**Status:** Approved for implementation; not approved for provider execution
**Scope:** Task 18 complete-suite behavioral campaign harness only

## 1. Decision

Corrective campaign 4 uses a hermetic installed runtime, a closed parser for the
actual Codex Windows command wrapper, and an explicit final-claim protocol.
Evidence remains the source of truth. Agent claims are a separately checked
reporting contract and may never turn missing or contradictory evidence into a
pass.

The user approved this design after approved3 was preserved in commit
`f99b798b8de6907dd26d283d7bc51bdea85599b1`. This approval authorizes local
design and implementation work only. It does not authorize dependency network
access, creation of provider sessions, or execution of the proposed4 campaign.

## 2. Approved3 lessons and immutable boundary

Approved3 is complete, sealed, and immutable. Its raw and retained evidence may
be read for regression fixtures but may not be rewritten, retried, or used as
behavioral evidence. Approved3 established four harness defects:

1. the isolated runtime installed the KokoroArc wheel with `--no-deps`, so the
   CLI could not import the declared `jsonschema` dependency;
2. the command parser rejected the provider's escaped drive-absolute
   PowerShell executable and the optional `-NoProfile` wrapper form;
3. the prompt did not require every case `must` and `must_not` assertion ID in
   the final response; and
4. the local campaign-result validator rejected `not_applicable` even though
   the provider-facing schema and final parser accepted it.

Any proposed4 output uses new raw and retained roots. The approved1,
approved2, and approved3 roots remain outside every write, cleanup, retry, and
publication boundary.

## 3. Hermetic installed runtime

### 3.1 Frozen dependency wheelhouse

Before the approval envelope is frozen, preparation creates a dedicated
D:-based wheelhouse containing the KokoroArc wheel and every resolved runtime
dependency wheel. Dependency acquisition is a distinct preapproval operation
and requires any network authorization separately. The campaign itself never
uses network access.

The frozen campaign binds:

- the canonical wheelhouse path;
- every wheel filename, size, and SHA-256;
- a canonical manifest SHA-256;
- the KokoroArc wheel identity;
- the Python launcher identity already bound by the harness; and
- the exact offline installation declaration.

The wheelhouse is closed: links, reparse points, unexpected entries, source
distributions, duplicate distribution identities, non-wheel files, and changed
bytes fail preparation. Wheels are installed using `--no-index`, a literal
`--find-links` directory, disabled user-site and version checks, and a clean
target under the unique prepared run root. No host site-packages directory is
added to the task environment.

### 3.2 Real CLI smoke gate

Preapproval preparation must prove the exact installed runtime, not a mocked
import. In a sanitized environment it must:

1. import `yaml`, `jsonschema`, and `kokoroarc` from the isolated target;
2. run the installed KokoroArc CLI help/version surface;
3. run at least one real JSON-emitting validation command over a copied trusted
   fixture; and
4. verify that all imported KokoroArc and declared dependency modules resolve
   beneath the isolated target.

Missing dependencies, resolution from a host site-packages directory, network
configuration, nonzero exit, non-JSON output, or writes outside the disposable
D:-based smoke root fail the preapproval gate.

## 4. Command-event contract

### 4.1 Accepted PowerShell wrapper

The provider event supplies a quoted command string rather than trusted argv.
The parser accepts only a direct invocation of the campaign-declared
PowerShell executable after safe drive-path canonicalization. For a
drive-absolute trusted executable, repeated slash or backslash separators are
collapsed only for equality comparison; UNC, relative, device, and alternate
executable paths remain rejected.

After the executable, the only accepted wrapper forms are:

```text
-Command <literal payload>
-c <literal payload>
-NoProfile -Command <literal payload>
-NoProfile -c <literal payload>
```

Flag matching is case-insensitive, but order, count, and the closed flag set are
fixed. The inner command continues through the existing fail-closed command,
cwd, environment, capture, output, and filesystem adjudication. Narrative
text, comments, dead branches, quoted fake commands, alternate interpreters,
dynamic module construction, chained hidden invocations, and mismatched argv
or captures never establish trusted execution.

### 4.2 Regression source

Approved3's sanitized command events provide read-only representative fixtures:
the doubled-separator executable, ordinary `-Command`, and observed optional
wrapper variants. Tests also generate adversarial neighbors. Production code
must not special-case an approved3 run or depend on its mutable filesystem
location.

## 5. Final response and claims

The generated prompt explicitly instructs the agent to read `workspace/case.json`
and emit each ID from `must` and `must_not` exactly once in
`claimed_assertions`. Omitted, duplicate, or invented IDs invalidate the final
reporting contract.

Claim status has one closed vocabulary everywhere:

- `satisfied`;
- `not_satisfied`; and
- `not_applicable`.

The adjudicator derives each assertion's evidence result independently. A claim
may agree or disagree with that result, but it cannot supply evidence. For a
required `must` assertion, only evidence-backed satisfaction passes. For a
`must_not` action, absence must be proven by protected-state, command, and
filesystem evidence; `not_applicable` never substitutes for that proof.

The result validator, output schema, final-event binder, adjudicator, replay,
and summaries use the same status vocabulary and exact-ID rules. A mismatch
fails closed with a bounded diagnostic and never leaves a partial results tree.

## 6. Preapproval proof

The proposed4 preapproval checkpoint is invalid unless all of these pass on the
same committed tree:

- dependency wheelhouse manifest and offline-install tests;
- real isolated CLI smoke and host-resolution rejection tests;
- representative provider-wrapper tests and adversarial false-pass tests;
- exact claim coverage, duplicate/omission/invention, and status-consistency
  tests;
- complete structure, preparation, runner, sanitizer, importer, adjudicator,
  no-spawn, package-inventory, and validator selections;
- exact replay and unchanged inventories for approved1 through approved3;
- absence of proposed4 raw, retained, and results roots;
- exact-range `git diff --check` and clean status.

The frozen approval presentation must disclose the exact commit, tree, parent,
approval-bound manifest, KokoroArc wheel, dependency wheelhouse manifest,
campaign SHA-256, envelope SHA-256, 24-run policy, unique roots, and all known
harness corrections.

## 7. Execution lifecycle

The proposed campaign identity is `2026-08-20-proposed4`. Its intended unique
roots are:

```text
D:\tmp\kokoroarc-m9-task18-campaign-20260820-approved4
tests/skills/evidence/complete-suite/approved4
```

These names are design inputs, not authorization to create or execute the
campaign. After the preapproval checkpoint, the user must explicitly approve
the exact frozen envelope. Only then may the harness commit an
`approved_not_started` record and execute each of the 24 provider sessions once
with concurrency at most four. Any failure is sealed and preserved. Any later
correction requires proposed5, new roots, and another exact approval.

## 8. Rejected alternatives

Using the host dependency environment was rejected because it would make the
campaign sensitive to undeclared packages and user configuration. Removing
claims from the pass contract was rejected because exact self-reporting is
useful audit evidence, provided claims remain subordinate to independently
replayed command, file, state, and final-event evidence.
