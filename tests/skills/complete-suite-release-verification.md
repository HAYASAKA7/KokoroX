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

## Approved campaign 2: immutable response-schema failure

Status: **sealed with deviations; suite closure failed**.

The user approved envelope
`4938b9de462b5f81a20fb1c79022290dd6675cfe06facb91e36da35418e4b5f5`
for exactly 24 fresh runs. The approval was recorded in campaign SHA-256
`dc981d45019700eaad4def6ab036f4cdcd045e8675f1a587d8ef416a5fde241e`.
It bound Git commit `44032b3f897393b7eae04a0bf171e8a94c61636e`, tree
`303e067d2c8f4ea80ceb6ecb7bc0b9f914e15956`, parent
`c536ee82d33bba14a9124485789f2f4562fa3f8d`, 141 approval files,
manifest `ebffd439ecdd71b7cc90634b897464beab941e34ee84c43a5f5b7565ab9f4744`,
and wheel
`e5e069cb5a219f0b6c59b4b2a94bbad7507a3add1ede0e544d2d304bfee6c5b4`.
The approved-not-started record was committed as
`52876ea8783718566947d5b5cfaf869416d8cb3e` before execution.

The one-shot runner started and completed all 24 authorized processes, used no
retry or resume path, and sealed the raw campaign at
`2026-08-20T03:26:53.529Z`. The raw campaign ledger SHA-256 is
`27e1f0c65edea2db058968df2b0424a53b8c0a7c01b8a53c44fa7e5f7ef76446`.

Every process created a unique provider thread, then exited with code 1. All
24 session streams contain exactly `thread.started`, `turn.started`, `error`,
and `turn.failed`. The provider returned HTTP 400 `invalid_json_schema` because
the frozen response schema's `$defs.relative_path.not` subschema contains a
`pattern` without an explicit `type`. No command or final-agent event was
created. Every run therefore retains exactly `PROCESS_NONZERO` plus
`FINAL_BINDING_INVALID`. This is a frozen response-schema compatibility
failure, not character behavior.

Sanitized import retained 515 files and 24 run ledgers under
`tests/skills/evidence/complete-suite/approved2`. The import ledger SHA-256 is
`530ffed0e3e62a950148c4dcf27f2f18abb10b403ec321ea2d2cd5a165079664`;
the retained inventory SHA-256 is
`c04fc14fa99acfefd3e06c0f003da793630714e39c0c540b37f2e0412e1cdf88`.
The importer recorded 408 deterministic `user_profile` redactions across 384
run-ledger file entries. Retained-output self-scanning and exact raw-to-retained
replay passed.

Adjudication produced 24 result documents, with baseline 0/12 and
suite-enabled 0/12. No run was evaluable. The adjudication ledger SHA-256 is
`21c60fb1b0d18726c8a2edd71b200a822c671818d944ec9143541d889d7543d6`;
the campaign-summary SHA-256 is
`c01171cf0459bf1d2a04f1cc92c44f21c914eec63f605138fe22e88ddd38325e`.
Exact replay reports 24 runs, 24 ledgers, 0 evaluable runs, 25 suite-relevant
deviations, and `suite_closure_passed=false`.

No approved2 process may be retried. Correcting the frozen response schema
requires a new campaign, a new D:-based raw and retained root, and fresh exact
user approval. Until a corrective campaign passes, Task 18 and the standalone
suite remain incomplete.

## Approved campaign 3: immutable installed-runtime harness failure

Status: **sealed without raw deviations; adjudication failed closed; suite
closure failed**.

The user approved envelope
`6e02744b1523e8455652cfd1999a2c400398b1d46e3991b7640fb1acb4e85aa3`
for exactly 24 fresh runs. The approval was recorded in campaign SHA-256
`2c86e70cc07266b5ffb97e46cb6e998bcffcfa01496e435170c60df4d3dde53d`.
It bound Git commit `8623f555641b1b8596f559f14923e773c1c5a471`, tree
`84451c7befca6aa1ce87839580cff73498dea995`, parent
`c474ff2b32dd414c2a50f3898be13fd2b0d98c5e`, 141 approval files,
manifest `28b43b685c5298b2c374bc41ba12ff2e5972a4e1105efc3b41ee65233a2e88fa`,
and wheel
`e5e069cb5a219f0b6c59b4b2a94bbad7507a3add1ede0e544d2d304bfee6c5b4`.
The approved-not-started record was committed as
`f48b05e2380da9de628e6b9865d8cea7c890dd84` before execution.

The one-shot runner started and completed all 24 authorized processes, used no
retry or resume path, and sealed the raw campaign at
`2026-08-20T06:07:37.772Z`. Every process created a unique provider thread and
exited with code 0; no process timed out and the campaign recorded zero raw
deviations. The raw campaign ledger SHA-256 is
`81797df9d23dd0068b8d0c818689a4a30abc96e29f76b46127fcb5f065edb479`.

Sanitized import retained 542 files and 24 evaluable run ledgers under
`tests/skills/evidence/complete-suite/approved3`. The import ledger SHA-256 is
`d8611bc380a7033ccff2928f5e12f5596e779bdf8d55999efc2b831ca24903ab`;
the retained inventory SHA-256 is
`811c92b0c6e141d511bb67fdffdffbec2e0765f6cb9a5cf520527e8aae40f6d7`.
Retained-output self-scanning, final-event binding, and exact raw-to-retained
replay passed for all 24 runs.

Approved3 does not establish character behavior. The isolated runtime was
created by installing the KokoroArc wheel with `--no-deps`, while the package
requires PyYAML and jsonschema. KokoroArc CLI invocations therefore failed at
module import with `ModuleNotFoundError: No module named 'jsonschema'`. In
addition, the frozen adjudicator does not recognize the actual escaped Windows
PowerShell executable form (or the optional `-NoProfile` wrapper flag), and
its result validator omits the `not_applicable` status allowed by the approved
provider schema. The first and only local adjudication attempt consequently
raised `RuntimeError: campaign adjudication result is invalid` and atomically
removed its scratch tree; no results directory was published.

No approved3 process may be retried, and its retained evidence may not be
rewritten. Repairing the installed runtime, wrapper parser, and output/result
contract requires a new frozen campaign with unique D:-based raw and retained
roots and fresh exact user approval. Until a corrective campaign passes, Task
18 and the standalone suite remain incomplete.

## Approved campaign 4: immutable preparation failure

Status: **sealed before provider launch; suite closure failed**.

The user approved envelope
`0e6b3e3146b4d3cf6539b14412e0f127c39d60d41048d96ddcad26987100ae64`
for exactly 24 fresh runs. The approval was recorded in campaign SHA-256
`3f283f7cec6bb147f819616883c28cd1281f1478e63d869f33cceb457eb1789b`.
It bound Git commit `778c77dc93a1bfa13537f5d96c31e5ad779b602e`, tree
`1c5c67d8b7ba29d4ff36a9534440afcead354849`, parent
`788e86a08af8c94a36bed8d4b33021091201b4a6`, 141 approval files,
manifest `047a372cabe1f5ec2de84c434bff86fde45e98c257e227625e1c43b62073d9bc`,
dependency-wheelhouse manifest
`0753050ecf612684fec5102e993253c74842ec618bfcc086a025f5dee69bbba2`,
and KokoroArc wheel
`61ef3a5ff7201eebbcc6d6fb1c88016ce6de8cf74ab38592c0206ed72db4e1e5`.
The approved-not-started record was committed as
`4bcd1e4785bad9c73d2e2f0b8b7b972880c048de` before execution.

Preparation installed and validated the frozen runtime, then stopped while
building the trusted fixture assets. Fixture generation imported
`kokoroarc.packs.loader` in the harness process instead of the isolated
installed-runtime subprocess. The normal test environment had masked this
undeclared `PYTHONPATH` dependency; the clean launch raised
`ModuleNotFoundError` before any provider process or session was created.

The failure was sealed at `2026-08-20T09:45:43.314Z` with 24 runs authorized,
zero started, and zero completed. There is no raw `runs` directory. The
pre-seal snapshot contains 389 files and 6,398,678 bytes at tree SHA-256
`a82b3a59c9208c49fb6c298785051f2bba9df81bb9b5479b5f08500738b7933f`.
The bounded failure artifact SHA-256 is
`86ade7a07e7890b5a34e897acbc3e08035194d37d3a9240d11a5a8c129868558`;
the raw campaign ledger SHA-256 is
`a737cfeb13e877bcc6d0da24a7c19a4064b9c9dc12d32eab0ac77ba3728a0202`.
Its 49 deviations are the campaign preparation failure plus deterministic
`RUN_NOT_STARTED` and `RUN_STATUS_MISSING` entries for all 24 authorized runs.

Sanitized import retained only the five campaign artifacts and import ledger
under `tests/skills/evidence/complete-suite/approved4`. The import ledger
SHA-256 is
`4a7675f203fb3365a9dc743e4426fb5217da49e27817fea8f5c6a2a7aa9df90e`;
the six-file retained inventory is 84,056 bytes at tree SHA-256
`ceac9432c278c9fb74a787745ac34c28411b8ec3c4616c45728bca4ec2cf1292`.
Exact raw-to-retained replay passed with `run_count=0` and
`runs_authorized=24`.

The frozen file manifest also exposed a separate checkout-reproducibility
defect: 37 approval-bound files reflected a mixed legacy working-tree newline
state rather than the byte form produced by a fresh checkout. Every retained
claim above was validated against the exact 141 approved hashes; no hash was
relaxed or replaced. A successor campaign must freeze a fresh-checkout-stable
manifest in addition to fixing fixture-generation isolation.

No approved4 process may be started or retried, and its raw or retained
evidence may not be rewritten. Corrective campaign 5 requires a new frozen
campaign, new raw and retained roots, a fresh exact approval envelope, and a
new explicit user approval. Until that campaign passes, Task 18 and the
standalone suite remain incomplete.
