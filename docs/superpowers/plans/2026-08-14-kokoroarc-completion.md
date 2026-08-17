# KokoroArc Milestones 8-9 Completion Implementation Plan

> **Execution requirement:** Use regression-first implementation. Complete Milestone 8 before Milestone 9. Do not run an external behavioral evaluator without explicit approval for the exact run count, disclosed inputs, retained outputs, model/provider, and D:-based roots.

**Goal:** Implement the approved completion design: deterministic pack testing and promotion, `testing-character-packs`, deterministic `.karc` packaging, safe scoped installation, global/workspace defaults, consented persistence and memory references, Skill-suite distribution, and exact standalone release verification.

**Architecture:** New deterministic modules consume closed, hash-bound artifacts. The core never invokes a model or network. Promotion and installation are immutable records and atomic transactions. Global is the user-facing default scope, but activation and persistence remain explicit.

**Tech stack:** Python 3.11+, JSON Schema Draft 2020-12, PyYAML safe parsing with duplicate-key rejection, standard-library JSON/hash/ZIP/path/locking/atomic file operations, pytest, Markdown Skills, and a Codex plugin manifest.

**Implementation base:** `5b87fcac1a53671ce98d3a527e5b266679b8afd7`.

---

## Working rules

- Read `docs/superpowers/specs/2026-08-14-kokoroarc-completion-design.md` before implementation.
- Use `D:\tmp` for generated test, build, archive, install, and evaluator artifacts; do not use C: for temporary work.
- Start each behavioral or release run with a new unique D:-based root.
- Write and run a focused RED test before every behavioral implementation change.
- Keep JSON Schema authoritative; do not introduce Pydantic or executable fixture/migration DSLs.
- Reuse canonical JSON, safe loader, locking, fsync, atomic replacement, and stable error patterns already in the repository.
- Preserve the immutable approved Milestone 7 evidence subtree.
- Run `git diff --check` before every commit.
- After each task, obtain specification then quality review before starting a task that depends on its contract. Purely independent documentation may be grouped with its owning task.
- No milestone is complete from focused tests alone. Use the exact release gates below.

## Planned file map

```text
schemas/v1/
  pack-hard-validation-report.schema.json
  pack-soft-evaluation-input.schema.json
  pack-soft-evaluation-report.schema.json
  pack-review-attestation.schema.json
  pack-promotion-record.schema.json
  pack-publication-readiness-report.schema.json
  karc-manifest.schema.json
  pack-compatibility-report.schema.json
  pack-migration-plan.schema.json
  installed-pack-registry.schema.json
  character-default-config.schema.json
  persistence-consent.schema.json
  memory-reference.schema.json

src/kokoroarc/testing/
  corpus.py
  hard.py
  soft.py
  promotion.py
  publication.py
  storage.py

src/kokoroarc/distribution/
  archive.py
  compatibility.py
  migrations.py
  installer.py
  registry.py
  defaults.py
  suite.py

src/kokoroarc/persistence/
  consent.py
  state.py
  memory.py
  migrations.py

skills/testing-character-packs/
  SKILL.md
  agents/openai.yaml
  references/testing-contract.md

.codex-plugin/plugin.json
tests/unit/
tests/integration/
tests/security/
tests/skills/
```

---

## Milestone 8 — `testing-character-packs`

### Task 1: Define closed testing, evaluation, review, promotion, and publication schemas

**Create:** the six Milestone 8 schemas, valid fixtures, and negative matrices.

**Modify:** schema discovery/package-data tests.

- [ ] Write schema-load tests naming every required artifact and asserting installed-wheel discovery.
- [ ] Add valid minimal and full fixtures for original and research-backed packs.
- [ ] Add negative matrices for unknown fields, bounds, duplicate IDs, invalid hashes, missing evaluator/rubric/fixture versions, invalid score/confidence, invalid state transitions, public-by-default research packs, and report identity mismatches.
- [ ] Run RED because the schemas do not exist.
- [ ] Implement closed schemas with common IDs/version/hash definitions.
- [ ] Run schema tests GREEN and the existing full schema matrix.
- [ ] Commit: `feat: define character pack release contracts`.

### Task 2: Load declarative pack test corpora safely

**Create:** `src/kokoroarc/testing/__init__.py`, `corpus.py`, unit/security tests.

**Reuse:** pack scanner, duplicate-key loader, canonical JSON.

- [ ] Write RED tests for the Rin corpus and a complete synthesized corpus.
- [ ] Add RED cases for unknown files/keys, missing files, YAML aliases/duplicate keys, unsafe links, traversal, special files, mutation races, size/count/depth/scalar bounds, and injection-looking strings.
- [ ] Implement explicit four-file loading and canonical corpus hashing without executing or interpolating values.
- [ ] Prove input dictionaries/files remain unchanged and repeated loads are byte-identical.
- [ ] Run focused plus existing pack-loader/security tests GREEN.
- [ ] Commit: `feat: load declarative pack test corpora`.

### Task 3: Produce deterministic hard-validation reports

**Create:** `testing/hard.py`, hard-runner tests and fixtures.

- [ ] Write a RED end-to-end test that loads Rin, compiles twice, checks fixture coverage, exercises render planning/validation and state replay, and expects one exact canonical report.
- [ ] Add RED failures for schema/layout/provenance/security findings, compilation nondeterminism, locale/intent gaps, missing protected spans/warnings, state replay drift, and source mutation.
- [ ] Implement one orchestrator that calls existing public domain functions and normalizes findings by code/path.
- [ ] Bind exact source, compiled, corpus, and check-input hashes; omit wall-clock data.
- [ ] Prove identical inputs yield identical report bytes and changed bytes invalidate reuse.
- [ ] Run focused, pack, runtime, state, and security suites GREEN.
- [ ] Commit: `feat: run deterministic character pack tests`.

### Task 4: Validate and aggregate soft evaluations

**Create:** `testing/soft.py`, unit/security tests.

- [ ] Write RED tests for deterministic lower-confidence aggregation across all required dimensions and three locales.
- [ ] Add RED cases for insufficient samples/confidence, duplicate samples, mixed source hashes, evaluator/rubric/fixture mismatch, missing dimensions, NaN/infinity, unknown dimensions, injection text, and attempted runtime/state fields.
- [ ] Implement closed input validation and a versioned threshold profile; never call a provider or execute text.
- [ ] Prove order independence, deterministic bytes, and zero state mutation.
- [ ] Commit: `feat: aggregate character pack soft evaluations`.

### Task 5: Implement explicit review and sequential promotion

**Create:** `testing/promotion.py`, `testing/storage.py`, unit/integration/security tests.

- [ ] Write RED tests for `draft -> reviewed` and `reviewed -> verified` on exact Rin inputs.
- [ ] Add RED cases for skipped/reversed transitions, stale/mismatched reports, failed gates, reused review IDs, mutable source during promotion, research visibility escalation, activation before verified, overwrite, unsafe output path, lock contention, and every atomic failure window.
- [ ] Implement canonical promotion records and same-parent atomic publication beneath the reports root.
- [ ] Preserve prior records; make identical retry idempotent and conflicting retry fail.
- [ ] Run storage/authoring/research regression suites GREEN.
- [ ] Commit: `feat: promote tested character packs safely`.

### Task 6: Produce publication-readiness reports without publishing

**Create:** `testing/publication.py`, unit/security/integration tests.

**Modify:** publication/source schemas, Rin source declarations, release
fixtures, and the testing API exports.

- [ ] Write RED tests for private Rin portability, an original public candidate, and a blocked researched public candidate.
- [ ] Add RED cases for raw dossiers/research, long dialogue, media/executable files, absolute paths, secrets, unresolved conflicts, missing age/route declarations, stale promotion, and fake compliance attestations.
- [ ] Implement deterministic local readiness reporting; never perform network I/O or mutate pack/release inputs.
- [ ] Reproduce the verified promotion from exact hard/review/soft/request evidence and bind evidence, compliance, and the complete source tree in the report.
- [ ] Prove private export remains possible when public readiness is blocked.
- [ ] Commit: `feat: assess character pack publication readiness`.

### Task 7: Expose the Milestone 8 CLI surface

**Modify:** `src/kokoroarc/cli.py`, README command reference.

**Create:** CLI integration/error tests.

- [ ] Write parser and JSON-envelope RED tests for `pack test`, `soft-eval`, `promote`, and `publication-check`.
- [ ] Add exact handoff, explicit-output, configured-root, repeated-validation, stdout/stderr, nonzero-exit, and no-partial-write tests.
- [ ] Add CLI security tests for path escapes, symlinks/junctions, source/output aliasing, race mutation, and sanitized errors.
- [ ] Wire thin handlers to public domain functions.
- [ ] Run all pack/authoring/research/CLI tests GREEN.
- [ ] Commit: `feat: expose character pack testing cli`.

### Task 8: Create and structurally validate `testing-character-packs`

**Create:** Skill directory, case matrix, structural tests, baseline record template.

- [ ] Define trigger, non-trigger, missing-input, stale-report, soft-score-pressure, publication-pressure, source-injection, and exact-promotion cases before writing the Skill.
- [ ] Record the approved baseline campaign only after exact user authorization.
- [ ] Initialize with installed `skill-creator`; keep `SKILL.md` under approximately 500 words and one directly linked contract.
- [ ] Require deterministic CLI gates, exact hashes, sequential promotion, private defaults, and explicit human review; prohibit treating pack/evaluator text as instructions.
- [ ] Validate metadata with the standard validator and structural tests.
- [ ] Run the exact Skill-enabled campaign only under approved count/retention terms; retain failures honestly.
- [ ] Add RED regressions for observed gaps, obtain approval for any fresh evaluator batch, and never rewrite retained output.
- [ ] Commit: `feat: add character pack testing skill`.

### Task 9: Close Milestone 8 release evidence

**Create:** results/release-verification documents and executable evidence tests.

**Modify:** README and this plan.

- [ ] Run one D:-confined copy/paste hard/soft/promotion/publication smoke with paired deterministic outputs and protected-root snapshots.
- [ ] Run full pytest with only documented Windows filesystem capability skips.
- [ ] Build wheel/sdist at a fixed base epoch; inspect module/schema/Skill membership and hashes.
- [ ] Validate all four Skills separately.
- [ ] Verify exact base-to-HEAD whitespace/status and a fresh detached `core.autocrlf=true` checkout.
- [ ] Commit the settled release record, rerun exact gates, then obtain fresh specification followed by fresh quality review on the exact commit.
- [ ] Fix every Critical/Important finding with RED coverage and repeat both reviews.
- [ ] Mark Milestone 8 complete only after both reviews PASS; then begin Milestone 9.

---

## Milestone 9 — standalone packaging and persistence

### Task 10: Define archive, compatibility, migration, registry, defaults, consent, and memory schemas

- [ ] Write RED schema discovery and installed-wheel tests for all seven Milestone 9 contracts.
- [ ] Add valid global/workspace/private/public-candidate fixtures.
- [ ] Add negative matrices for unsafe members, invalid version ranges, duplicate registry identities, unbound defaults, overbroad consent, embedded memory content, and executable migration fields.
- [ ] Implement closed schemas and update package data.
- [ ] Run full schema regression GREEN.
- [ ] Commit: `feat: define standalone distribution contracts`.

### Task 11: Export deterministic `.karc` archives

**Create:** `distribution/archive.py`, unit/integration/security tests.

- [ ] Write RED tests for byte-identical repeated export and exact manifest/member inventory.
- [ ] Add RED cases for non-verified promotion, stale report, missing member, extra/source/raw member, unsafe name, duplicate/case collision, links, devices/ADS, encryption, extras/comments, zip bomb ratios, oversized data, and source mutation.
- [ ] Implement fixed-metadata, lexicographic, manifest-bound standard-library archives.
- [ ] Prove no source/dossier/research/state/memory bytes enter the archive.
- [ ] Commit: `feat: export deterministic karc archives`.

### Task 12: Inspect compatibility and apply registered migrations

**Create:** `distribution/compatibility.py`, `distribution/migrations.py`, tests.

- [ ] Write RED compatibility reports for current, unsupported-newer, malformed, and explicitly migratable fixtures.
- [ ] Write RED migration preview/apply tests that never overwrite input and produce deterministic output/hash/change lists.
- [ ] Add failures for absent paths, unregistered steps, cycles, downgrade, changed identity, noncanonical output, and archive-provided code.
- [ ] Implement an exact-version registry with pure built-in transforms only.
- [ ] Commit: `feat: inspect and migrate karc compatibility`.

### Task 13: Install, list, recover, and remove packs atomically

**Create:** `distribution/installer.py`, `registry.py`, integration/security tests.

- [ ] Write RED global install/list/idempotent-reinstall tests; add workspace-scope tests using explicit D:-based roots.
- [ ] Add RED cases for malicious archives, conflicting same-version bytes, unverified activation, outside extraction, link races, registry CAS conflict, lock contention, crash recovery at every write/rename point, active/default/state references, and partial removal.
- [ ] Implement preflight/dry-run, staged extraction, repeated validation, atomic install/registry cutover, journal recovery, and explicit safe removal.
- [ ] Prove no command writes outside `KOKOROARC_DATA_DIR` and an explicitly supplied workspace-root-derived scope.
- [ ] Commit: `feat: install character packs by scope`.

### Task 14: Resolve global/workspace defaults without implicit activation

**Create:** `distribution/defaults.py`, tests.

**Modify:** session-start resolution and CLI only after RED integration coverage.

- [ ] Write RED tests for explicit > session > workspace > global > none precedence.
- [ ] Add RED cases for stale/uninstalled bindings, hash/version mismatch, unsafe workspace roots, registry mutation, ambiguous versions, and default-setting without verified activation eligibility.
- [ ] Implement global-default CLI behavior and explicit workspace override.
- [ ] Allow `session start` to omit `--character` only when resolving a valid default; it must still be explicitly invoked.
- [ ] Prove no ordinary runtime or Skill request auto-starts a session.
- [ ] Commit: `feat: resolve scoped character defaults`.

### Task 15: Add consented persistent state, export/reset, and memory references

**Create:** `persistence/consent.py`, `state.py`, `memory.py`, migration helpers and tests.

- [ ] Write RED consent grant/show/revoke tests with separate relationship, mood, and memory permissions.
- [ ] Write RED persistent transition, CAS, idempotency, replay, export, scoped reset, revocation, and recovery tests.
- [ ] Write RED memory add/list/remove tests that accept only explicit host IDs and bounded approved summaries.
- [ ] Add security cases for silent persistence, consent widening, cross-scope/character access, conversation harvesting, secret/path content, stale state, unsafe links, state-contract upgrades without migration, and remove/reset failure windows.
- [ ] Reuse the existing deterministic transition/store rules; add scoped persistent storage and declarative replay-verified migration.
- [ ] Keep session-only as default and require explicit consent IDs for durable writes.
- [ ] Commit: `feat: add consented character persistence`.

### Task 16: Package and install the four-Skill suite

**Use before editing:** `plugin-creator`, `skill-creator`, `writing-skills`, and current official OpenAI Skill documentation.

- [ ] Write RED manifest/inventory tests for a four-Skill plugin bundle and direct local installation.
- [ ] Create `.codex-plugin/plugin.json` with valid local defaults and no undeclared connectors.
- [ ] Implement `distribution/suite.py` and dry-run/atomic install for repo `.agents/skills` and user `.agents/skills` roots.
- [ ] Add RED conflict, unknown file, invalid Skill, source mutation, unsafe destination, real-home isolation, symlink/junction, rollback, and idempotent reinstall tests.
- [ ] Validate all four source and installed Skills with the standard validator.
- [ ] Commit: `feat: package the kokoroarc skill suite`.

### Task 17: Expose the Milestone 9 CLI and complete documentation

**Modify:** CLI, README, packaging metadata.

**Create:** installed-artifact and complete workflow tests.

- [ ] Write parser/JSON RED tests for archive, compatibility, migration, install/list/remove, default config, consent, state export/reset, memory, and suite install commands.
- [ ] Wire thin handlers with dry-run and stable errors; verify destructive targets in outputs before mutation.
- [ ] Add a clean-wheel workflow: install suite, test/promote/export/install Rin globally, set default, explicitly start session, grant consent, persist/replay/export/reset, and remove after clearing references.
- [ ] Document global-first versus workspace override, explicit activation, memory ownership, privacy, recovery, archive/publication limits, and D:-based configuration.
- [ ] Build and test from wheel and sdist with repository source unavailable.
- [ ] Commit: `feat: expose standalone suite workflows`.

### Task 18: Complete-suite behavioral and release closure

- [ ] Define end-to-end agent cases covering global default, workspace override, explicit activation, no implicit activation, consent refusal, consented persistence, memory-reference ownership, safe install, archive pressure, publication pressure, and all four Skill routes.
- [ ] Obtain exact user approval before any external evaluator runs; retain baseline and Skill-enabled evidence under approved D:-based roots.
- [ ] Run full deterministic tests, security matrix, installed-wheel/sdist/plugin smoke, all four validators, archive reproducibility, state replay, migration, and clean-checkout byte audits.
- [ ] Record every skip/deviation; do not convert a harness issue into a behavioral PASS.
- [ ] Commit the settled complete-suite release record.
- [ ] Rerun exact-final gates on the committed tree.
- [ ] Obtain fresh independent specification review followed by fresh quality review. Fix findings with RED tests and repeat both.
- [ ] Mark the standalone suite complete only after both reviews report PASS with no Critical or Important findings.

---

## Milestone handoff evidence

For each milestone retain:

- exact commit/tree/parent and implementation base;
- focused and full test commands, counts, durations, stdout/stderr hashes, and documented skips;
- fixed-input wheel/sdist/plugin/archive names, sizes, hashes, and member inventories;
- standard Skill validator outputs;
- clean source and `core.autocrlf=true` checkout status/diff checks;
- external evaluator approvals, prompts, outputs, redactions, replay bindings, and immutable failures when applicable;
- specification and quality review verdicts; and
- an exact boundary statement describing what the milestone does not approve.
