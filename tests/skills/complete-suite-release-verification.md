# KokoroArc complete-suite release verification

This record is append-only across approved complete-suite campaigns. A failed
campaign is retained as evidence and is never rewritten into a behavioral
pass.

## Approved campaign 1: immutable harness failure

Status: **sealed with deviations; suite closure failed**.

The user approved envelope
`dd85e3e629aeaec0db889332c72fe32fc4f9c235167e169c321fb1df34b37b4e`
for exactly 24 fresh runs. The approval was recorded in campaign SHA-256
`1283de0ae407f20b8befdcb1b8b892a3add9bc3457b7d02a3c568e39ab3f087a`.
It bound Git commit `a4b1e96aad44dd586417413b7df860255f4ff2dd`, tree
`48d40b7d67bf3620b46d54d08b0b9502a1a3cc26`, parent
`e868643a011042ff71a84d72a67f9340ddf89d4c`, 141 approval files,
manifest `1eda78dc1e49e0a28024542968f67d1915fdcd7652ed4e9651ee40e7cbe022b2`,
and wheel
`e5e069cb5a219f0b6c59b4b2a94bbad7507a3add1ede0e544d2d304bfee6c5b4`.

The one-shot runner started and completed all 24 authorized processes, used no
retry or resume path, and sealed the raw campaign at
`2026-08-20T02:26:24.767Z`. The raw campaign ledger SHA-256 is
`36119df750256d497d3c4b7074983e7f743038c17b8202d56e5e1e28ac3243a0`.

Every process exited with code 2 before an evaluator session was created. All
24 runs have the same 206-byte stderr hash
`42d4eeb1d04c7232c5075ef6d4cf2674c374a37b96c9d2c4499cfcc19ef166ae`,
an empty session stream, and exactly `PROCESS_NONZERO` plus
`FINAL_BINDING_INVALID`. The installed `codex-cli 0.148.0` rejected the
simultaneous `--approve-for-me` and `--sandbox workspace-write` arguments.
Its local help states that `--approve-for-me` itself routes approval review
through the workspace-write sandbox. This is a campaign-harness deviation, not
character behavior.

Sanitized import retained 515 files and 24 run ledgers under
`tests/skills/evidence/complete-suite/approved1`. The import ledger SHA-256 is
`c7ad268f5a3202449056791871130f88f4f4325038c5e9e0f2490f514d4e6881`;
the retained inventory SHA-256 is
`8eae25e7b6a0bee1929c3405280ff4d900403a34a52d423cfd0390a0aa7bb862`.
The importer recorded 408 deterministic `user_profile` redactions across 384
run-ledger file entries. Retained-output self-scanning and exact raw-to-retained
replay passed.

Adjudication produced 24 result documents, with baseline 0/12 and
suite-enabled 0/12. No run was evaluable. The adjudication ledger SHA-256 is
`cad553428510597c2416d312be61b83ba83ecf403895488a9aedf965ace7765b`;
the campaign-summary SHA-256 is
`9ef44dbf5877dff07f381aa5f199df487cb451f37472226e427baf46415c64a5`.
Exact replay reports 24 runs, 24 ledgers, 0 evaluable runs, 25 suite-relevant
deviations, and `suite_closure_passed=false`.

No approved1 process may be retried. Correcting the launch arguments requires
a new frozen campaign, a new D:-based raw and retained root, and fresh explicit
user approval. Until a corrective campaign passes, Task 18 and the standalone
suite remain incomplete.
