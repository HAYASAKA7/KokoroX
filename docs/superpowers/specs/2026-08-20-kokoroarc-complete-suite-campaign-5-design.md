# KokoroArc Complete-Suite Corrective Campaign 5 Design

**Date:** 2026-08-20
**Status:** Approved for implementation, including the canonical-LF
distribution revision; not approved for provider execution
**Scope:** Task 18 complete-suite behavioral campaign preparation only

## 1. Decision

Corrective campaign 5 preserves the approved4 runtime, parser, claim, and
evidence contracts while fixing its two preparation defects:

1. trusted fixture assets are generated only inside the validated installed
   runtime; and
2. every approval-bound raw file is byte-identical in the preparation
   worktree and a fresh `core.autocrlf=true` checkout.

The campaign remains draft-only until a new exact envelope is presented and
the user explicitly approves that envelope. Design approval and this
implementation checkpoint do not authorize provider execution.

## 2. Immutable predecessor boundary

Approved4 is sealed with 24 runs authorized, zero started, and zero completed.
Its raw and retained roots are immutable and remain outside all proposed5
write, cleanup, import, and result paths. Approved4 may be read only to verify
its retained replay and unchanged inventory.

Campaign 5 uses these unique roots:

```text
D:\tmp\kokoroarc-m9-task18-campaign-20260820-approved5
tests/skills/evidence/complete-suite/approved5
```

Neither root may exist during preapproval or envelope presentation.

## 3. Canonical checkout bytes

The repository's `.gitattributes` file is the checkout policy. Every
approval-bound path with `text eol=lf` is normalized to LF in the preparation
worktree. `MANIFEST.in` receives an explicit `text eol=lf` rule so the system
`core.autocrlf=true` setting cannot produce a different raw byte stream.

The preapproval gate creates a new detached D:-based checkout of the frozen
harness commit with `core.autocrlf=true`. It verifies all approval-bound file
sizes and SHA-256 values against the proposed manifest. A normalized Git blob,
matching semantic text, or worktree-clean status is insufficient: raw bytes
must match exactly. Any mismatch invalidates the draft before approval.

## 4. Isolated fixture preparation

Fixture creation uses the installed frozen distribution as its only Python
import root. The child process uses safe-path and no-user-site isolation and
must resolve KokoroArc beneath the installed target both before and after
asset generation. The harness process may orchestrate the child but may not
import KokoroArc to create fixture assets.

Any exception before the first provider launch seals a bounded preparation
failure with zero started and zero completed runs. The seal binds the complete
pre-seal raw inventory, exposes only a safe failure type/code, and can be
imported and replayed without fabricated run directories.

## 5. Distribution and dependency inputs

Campaign 5 reuses only the six third-party wheels from the immutable proposed4
wheelhouse. Each dependency wheel must retain its exact filename, size,
SHA-256, and distribution identity. Reuse is offline and does not authorize a
download, network client, or mutation of the predecessor wheelhouse.

The proposed4 KokoroArc wheel remains immutable predecessor evidence but is
not a campaign 5 input. Its archive used mixed CRLF/LF source bytes and its ZIP
timestamps did not equal the recorded fixed release epoch. Preserving those
bytes merely to retain the predecessor hash would violate the canonical
checkout contract.

KokoroArc is rebuilt twice from the canonical-LF harness commit at
`SOURCE_DATE_EPOCH=1787151982`. Both builds must produce the same wheel:

```text
filename: kokoroarc-0.0.0.dev0-py3-none-any.whl
size: 345607
sha256: 76ebb700b7bb9c4eb88fd74a2268c077eeff741245cb7d7f6402673e2f02174f
```

The new wheel is combined with the six byte-identical dependency wheels in a
unique proposed5 seven-wheel wheelhouse. That new closed manifest is captured
and bound only after assembly. Offline installation, module-origin checks, CLI
version/help, real Rin validation, and isolated fixture-generation smokes run
against this exact wheelhouse before the campaign is frozen.

## 6. Draft and approval lifecycle

The proposed campaign identity is `2026-08-20-proposed5`. Its initial state is
`draft_not_approved`, its `user_approval` is null, and all execution counters
are zero. The draft binds:

- the frozen harness commit, tree, and parent;
- the exact approval-bound file manifest and digest;
- the newly assembled dependency wheelhouse manifest and canonical-LF
  KokoroArc wheel;
- the 24-run policy and evaluator configuration;
- the unique raw and retained roots; and
- the resulting campaign and approval-envelope SHA-256 values.

No raw campaign, retained campaign, or results root is created while freezing
or presenting the envelope. After the complete preapproval gate passes on one
clean committed tree, the exact envelope is shown to the user. Only a new
explicit approval of that envelope permits an `approved_not_started` commit
and one-shot execution.

## 7. Verification

The same committed tree must pass:

- structure, preparation, runner, sanitizer, importer, adjudicator, and result
  validation tests;
- the isolated fixture-builder and zero-run preparation-failure regressions;
- two byte-identical fixed-epoch canonical-LF builds, new wheelhouse capture,
  offline install, and real CLI smokes;
- exact raw-to-retained replay and unchanged inventories for approved1 through
  approved4;
- the fresh-checkout 141-file raw-byte audit;
- package inventory, Skill/plugin validators, secret scanning, compile, line
  length, and exact-range whitespace checks; and
- absence of proposed5 raw, retained, and results roots and provider sessions.

Any failed gate returns the campaign to draft preparation. It never consumes
approval and never launches a provider process.

## 8. Rejected alternatives

Preserving the mixed approved4 newline state, including solely to retain its
KokoroArc wheel hash, was rejected because a clean checkout could not
reproduce it. Adding a separate approval snapshot archive was rejected because
it would create a second source of truth beside Git and the raw file manifest.
Deriving approval only from normalized Git blobs was rejected because the
harness executes checked-out raw bytes, not abstract blob content. Reusing the
entire proposed4 wheelhouse was rejected because its KokoroArc member is not a
truthful fixed-epoch build of the canonical-LF source.
