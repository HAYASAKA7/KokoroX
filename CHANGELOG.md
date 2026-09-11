# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- A turn can now be genuinely bilingual: the character speaks its authored
  line in the language it was written in, while everything the model formed
  this turn follows the reader. A render plan gained a second segment kind --
  a *fixed segment*, carrying `fixed_line` with the pack author's own text,
  copied verbatim rather than generated. `runtime plan --context <file>` takes
  the saved output of `runtime context`, and when the pack authors a line for
  the named `--expression-intent`, that line leads the response on
  `character_dialogue`. The planner adds it to `protected_spans`, so a
  translated or dropped catchphrase now fails validation instead of passing
  as characterization.
- `runtime context` reports `requested_locale` alongside `persona_locale`.
  A host that saw only the locale it was given could not tell material
  authored for this reader from material borrowed from another; the pair says
  plainly when the persona is improvising.
- `pack validate` now speaks every authored line. The hard gate walks each
  locale the pack authors through the production path -- runtime context,
  plan, render, validate -- and reports, per locale, a line the plan failed
  to carry (`PACK_FIXED_LINE_NOT_SPOKEN`), failed to protect
  (`PACK_FIXED_LINE_UNPROTECTED`), or that validation rejected
  (`PACK_FIXED_LINE_VALIDATION_FAILED`). Before this the gate passed no
  runtime context at all, so no fixed segment was ever planned during
  validation, and a pack could pass while its character stayed silent.

### Changed

- `conclusion` is now its own language channel. It had been sharing
  `character_dialogue`, which made the channel's name a lie and put the
  answer on a channel that is supposed to follow the pack rather than the
  reader. `character_dialogue` now carries fixed segments only, and semantic
  segments may no longer use it; the schema enforces both directions.
- The compiled default for `character_dialogue` is `preserve` rather than
  `en-US`. No policy compiled without sight of the pack can name the locale
  its lines were written in, so a language tag there was a guess that would
  silence every pack not authored in it. `preserve` means "as written", and
  the planner resolves it to the locale the runtime context actually served.

### Added

- `kokorox pack recover` finishes or rolls back an interrupted install or
  removal. `recover_karc_installations` already existed, was exported, and was
  covered by three test files -- and had no call site anywhere in `src/`. A
  scope killed mid-install therefore deadlocked: install refused with
  `KARC_INSTALL_RECOVERY_REQUIRED` because a journal was present, removal
  reported `KARC_REMOVE_NOT_FOUND` because the registry never recorded the
  installation, and the bytes stayed in the target. The only way out was
  deleting the journal and staging tree by hand, which no document described.
  The suite stayed green throughout, because the recovery function itself was
  well tested; nothing tested that anything called it.

### Added

- `suite install --source <path>` names the Skill suite source explicitly.
  Discovery searches the checkout and every install scheme's data root, so a
  checkout whose package is also installed offers two complete suites and the
  command could only refuse. There was no way to say which one you meant.

### Fixed

- The README promised that recovery from an interrupted transaction "is
  automatic on the next matching install or removal operation". It never was,
  and a test asserted the README contained that sentence, so the claim was held
  in place by the suite. Both now describe the refusal and name
  `kokorox pack recover`.
- Fifty-one `KARC_*` error codes reached callers as "Command could not be
  completed"; only the `KARC_DEFAULT_*` family had public messages. That
  included both halves of the deadlock above, so the situation was unreadable
  from the CLI. Every code now carries its own message, and the one that
  strands a scope names the command that clears it.
- `runtime plan` accepted a policy routing the conclusion off
  `primary_language`, leaving `runtime validate` to reject the result. No
  fallback rung can repair that: every rung operates on the rendered candidate
  and the plan is fixed input, so an agent renders once, descends all four
  rungs and is still invalid. Planning now raises
  `PLAN_CONCLUSION_LANGUAGE_MISMATCH` where the policy can still be corrected.
  The planning fixture had encoded the defect -- `character_dialogue: ja-JP`
  under a `zh-CN` primary -- exactly as the contract example once did.
- The runtime contract described `runtime context` as returning a
  `persona_locale`. It is a local variable; the authored locale is the single
  key of the returned `locales` map.

- Skill suite errors reached callers with the generic "Command could not be
  completed", because no `SKILL_SUITE_*` code had a public message. Every
  remedy they carried was discarded before anyone could read it. All eleven now
  say what happened and what to do.
- `SKILL_SUITE_SOURCE_INVALID` covered both "two sources were found" and "none
  was found", whose remedies are opposites, with `details: {}` either way.
  Discovery failures are now `SKILL_SUITE_SOURCE_MISSING`, an ambiguous
  discovery is `SKILL_SUITE_SOURCE_AMBIGUOUS` and reports how many were found,
  and `SKILL_SUITE_SOURCE_INVALID` keeps its literal meaning: the source you
  named is unusable.


- The answer arrived in the character's language instead of the reader's. The
  planner routed `conclusion` to `character_dialogue`, and the contract defined
  exactly that channel as the one that falls back to a locale the pack actually
  authors. So a pack authoring only `ja-JP`, asked a question in `zh-CN`,
  returned the explanation, recommendations and warnings in `zh-CN` and the
  conclusion -- the answer, the one load-bearing sentence -- in `ja-JP`, and
  every gate passed.

  Nothing caught it because `PRIMARY_LANGUAGE_ABSENT` fires only when *no*
  segment carries the primary language, and three of four did. `runtime
  validate` now rejects any plan whose conclusion renders in another language:
  the conclusion is the answer, so its language is not a routing choice. The
  fallback itself was never wrong, only misapplied -- a pack's authored locales
  decide which expression material `runtime context` offers, which is what
  `persona_locale` already selects, not what language the answer is written in.
  The contract said the opposite, and its own render-plan example demonstrated
  the defect.


- A pack's relationship pacing was never read. `growth.stages` -- the
  familiarity and trust thresholds at which a character moves between
  `unknown`, `acquainted`, `familiar` and `trusted` -- validated, compiled into
  the artifact byte for byte, and cleared every gate, while `transitions.py`
  held the reference character's numbers as literals and never mentioned
  `stages` at all. Every authored pack silently ran rin-aster's curve: one
  declaring `acquainted` at 6 reached it only at her 10, and one declaring
  `familiar` at 22 familiarity and 16 trust sat at `acquainted` with 24 and 24,
  because her gate wants 30.

  The derivation rule is unchanged -- strongest stage first, hold on a relaxed
  floor before testing the entry bar -- and is now applied to the pack's own
  numbers. The former literals became `FROZEN_STAGES_V1`, the fallback for a
  pack that declares no stages, and a test pins that block to the reference
  pack's `growth.yaml` so the two cannot drift. Equivalence was checked over
  69,360 combinations of previous stage, familiarity, trust and tension: the
  reference curve is bit-identical.

  The schema had no exit form for tension, yet the hold value (40) was five
  above the declared ceiling (35) while every other exit was declared. That is
  now the documented default, with an optional `exit_max_tension` for packs
  that prefer to state it. Session, persistence and migration journals each
  record the thresholds so replay never needs the pack; the field is optional,
  and its absence correctly means an event was applied under the frozen curve,
  so no existing journal is invalidated.


## [0.2.0] - 2026-09-08

Findings from the second external QA pass, on the research chain.

### Changed

- `timeline_cutoff` and every claim `timeline` are ordered points
  (`{"unit": "volume", "index": 26}`) instead of strings compared by prefix.
  The old test was `value == cutoff or value.startswith(cutoff + "-")`, which
  ordered nothing: under a `volume-26` cutoff a claim at `volume-1` was
  rejected although it precedes the cutoff, while `volume-26-epilogue` was
  accepted whatever it described. The field could not bound spoilers or express
  where a fact came from, and the message -- "Claim timeline exceeds the
  requested cutoff" -- named a comparison that never ran.

  A claim now passes at or before the cutoff's index, within one unit. Units
  are never mapped onto one another, so a claim in a different unit is a
  mismatch rather than a guess. A claim may be unplaced (`"index": null`) when
  no source places it: inventing a number where the evidence gives none is
  worse than admitting the gap, so it is not a violation, but a coverage topic
  supported by an unplaced claim cannot be `covered` -- and `covered` forbids
  limitations, so the gap has to be recorded.

  An authoring request keeps a prose `timeline`, because original and dossier
  packs have no canonical axis; a research-backed request names the bundle
  cutoff in its rendered form, `<unit>:<index>`.

  The repository fixtures had hidden all of this by using `episode-01` for both
  the cutoff and every claim, so equality alone satisfied them.
- `PRIMARY_LANGUAGE_ABSENT` reports only what was counted -- the language
  expected and the zero segments carrying it -- and omits the floor, which
  gates the check but is never compared against a measured share.

### Fixed

- Both spoiler-scope messages said "exceeds the requested scope" for what is a
  plain equality test, so a claim whose scope was *narrower* than requested was
  told it had exceeded it.

### Added

- A host adapter section in the research contract, covering evidence a
  retrieval tool has reprocessed. `content_sha256` must digest the bytes a
  Source Record describes, but a fetch tool commonly returns text its own model
  produced from the page, and a digest over that attests the rendering rather
  than the source -- silently, since the digest computes and the schema
  validates. The section says to digest what was retained, record it in
  `limitations`, and keep citing claims out of `direct_fact`.

## [0.1.1] - 2026-09-07

Findings from the first external QA pass against 0.1.0.

### Fixed

- A policy that named only its primary language still rendered in English. The
  four prose channels (`character_dialogue`, `technical_explanation`,
  `recommendations`, `warnings`) were hard-coded to `en-US` in the default
  template, and merging only replaced keys a caller passed explicitly. The
  documented minimal input `{"mode": "single", "primary_language": "zh-CN"}`
  therefore produced a plan whose `primary_language` was `zh-CN` and whose every
  segment was routed to `en-US` -- and validation called it valid. Those four
  channels now follow `primary_language` unless a caller names one.
- The Semantic Result example put a digest in `immutable_spans`
  (`"sha256:0123456789abcdef"`). The validator checks that each span occurs
  verbatim in the rendered text, so following the example produced
  `MISSING_PROTECTED_SPAN`, and the natural repair -- printing the digest --
  satisfied the check while leaving the command it was meant to protect
  unconstrained. The example is now a literal string, and the contract states
  that digests belong to the host's binding record, not to `immutable_spans`.
- `authoring-contract.md` still required reporting "three-locale coverage"
  after locales became an open set, contradicting the Skill's own statement
  that a pack may author a single locale. It now reads "declared-locale
  coverage".
- Every error but `STATE_REVISION_CONFLICT` reached callers with `details: {}`,
  including schema failures, which left no way to tell which argument was
  rejected. The schema name now survives sanitization; it names the violated
  contract without echoing any input.

### Added

- A host adapter section in the runtime contract covering raw user-turn
  binding. Hosts store several kinds of record under one "user" label -- in one
  measured Claude Code session, only 119 of 914 `type: "user"` entries were real
  turns -- so a naive "last user message" silently binds injected Skill text or
  a tool result. The section gives the discriminator and the checks that catch a
  bad binding.
- `PRIMARY_LANGUAGE_ABSENT`: a plan that declares a primary-language floor above
  zero and routes no segment to that language is rejected. `min_primary_ratio`
  was previously declared, shape-checked, and never used for anything.

### Changed

- Render plans carry `min_primary_ratio`, and it is required. The share of
  primary-language content cannot be measured -- rendered segments carry no
  per-segment text -- so only the exact zero case is enforced: no segment in the
  primary language means a zero share whatever the segment lengths are. A
  count-based ratio was deliberately rejected; with two segments a 0.7 floor
  would mean "both", flagging legitimate mixed plans.


ment was
  rejected. The schema name now survives sanitization; it names the violated
  contract without echoing any input.

### Added

- A host adapter section in the runtime contract covering raw user-turn
  binding. Hosts store several kinds of record under one "user" label -- in one
  measured Claude Code session, only 119 of 914 `type: "user"` entries were real
  turns -- so a naive "last user message" silently binds injected Skill text or
  a tool result. The section gives the discriminator and the checks that catch a
  bad binding.
- A host adapter section in the research contract, covering evidence a
  retrieval tool has reprocessed. `content_sha256` must digest the bytes a
  Source Record describes, but a fetch tool commonly returns text its own model
  produced from the page, and a digest over that attests the rendering rather
  than the source -- silently, since the digest computes and the schema
  validates. The section says to digest what was retained, record it in
  `limitations`, and keep citing claims out of `direct_fact`.

- `PRIMARY_LANGUAGE_ABSENT`: a plan that declares a primary-language floor above
  zero and routes no segment to that language is rejected. `min_primary_ratio`
  was previously declared, shape-checked, and never used for anything. The
  violation reports only what was counted -- the language expected and the zero
  segments carrying it -- and deliberately omits the floor, which gates the
  check but is never compared against a measured share.

### Changed

- Render plans carry `min_primary_ratio`, and it is required. The share of
  primary-language content cannot be measured -- rendered segments carry no
  per-segment text -- so only the exact zero case is enforced: no segment in the
  primary language means a zero share whatever the segment lengths are. A
  count-based ratio was deliberately rejected; with two segments a 0.7 floor
  would mean "both", flagging legitimate mixed plans.


## [0.1.0] - 2026-09-04

First versioned release of the standalone Agent Skill Suite.

### Added

- Four installable Agent Skills: `using-kokorox`, `authoring-character-packs`,
  `researching-characters`, and `testing-character-packs`.
- The `kokorox` CLI covering the pack lifecycle (compile, validate, test,
  soft-eval, promote, publication-check, export, compatibility, migrate,
  install, list, remove), research, sessions, runtime render planning, scoped
  configuration, consent, state, and memory references.
- Per-agent interface profiles for ten hosts (`openai`, `claude`, `codex`,
  `cursor`, `gemini`, `copilot`, `kimi`, `deepseek`, `qwen`, `generic`), shipped
  with every Skill so a host can present the suite in its own idiom.
- Suite installation into the vendor-neutral `.agents/skills` root, a
  repository scope, or any explicit `--skills-root`.
- Open, shape-validated locales: any well-formed BCP-47 language tag is
  accepted. Task content follows the user's language; character expression
  falls back to a locale the pack actually authors; protected channels
  (commands, file paths, exact errors, code identifiers) are always preserved.
- Coverage measurement with a minimum threshold, and a `py.typed` marker so
  consumers receive the package's type information.
- MIT license.

### Changed

- The product is named KokoroX everywhere it is visible: the distribution is
  `kokorox` (`pip install kokorox`), so is the import package (`import
  kokorox`) and the command; installed data files live under `share/kokorox/`;
  and every artifact the runtime writes records
  `created_by.component: "kokorox"`, which the schemas require. It is delivered
  as a standalone Agent Skill Suite; Lumora integration is not pursued.
- Locales are no longer restricted to `zh-CN`, `en-US`, and `ja-JP`. Those
  remain the repository's reference profiles, not a required set.

### Removed

- The frozen Campaign 6 harness and its approved run evidence (`tests/skills/`,
  4842 files and 74 MB - 93% of the repository's files). It sat outside the CI
  gate, so it guarded nothing, and its 250-character evidence paths were the
  sole reason every Windows checkout needed `core.longpaths`. After the rename
  it also attested to a product name that no longer exists, and its harness
  runners are byte-compared against approved copies, so it could not be renamed
  without falsifying what it certifies. The record is preserved at the
  `campaign-6-evidence` tag.

### Fixed

- Atomic installation never worked on macOS. `renameatx_np(2)` takes
  `(fromfd, from, tofd, to, flags)`, but it was declared and called with three
  arguments, so every publish failed with
  `Installation directory could not be published atomically`. It now passes
  `AT_FDCWD` for both descriptors, matching the working Linux `renameat2` path.
- Every command writes UTF-8 whatever the console's codepage is. `--json`
  output uses `ensure_ascii=False`, so on a console using a legacy codepage
  (cp1252, for example) any command whose result contained non-ASCII text died
  with `UnicodeEncodeError` after doing its work -- which, for a multilingual
  runtime, was most of them.
- Reading a registry file nested too deeply for the JSON decoder raised a bare
  `RecursionError` instead of `KARC_REGISTRY_INVALID`. The depth at which this
  happened varied by interpreter and platform.
- Building the package needs setuptools 77 or newer. The declared minimum was
  75, which predates PEP 639 support and rejected `license = "MIT"` with
  ``configuration error: `project.license` must be valid exactly by one
  definition``.

- An installed `kokorox` could not find its Skill sources: the resolver only
  searched beside the package in `site-packages`, while a wheel places the
  Skill data files in the install scheme's data directory. `pip install`
  followed by `kokorox suite install` previously failed with
  `SKILL_SUITE_SOURCE_INVALID`. Resolution now asks `sysconfig` for every
  scheme's data path and also covers per-user installs, so environment,
  `--user`, and framework layouts all work.

[Unreleased]: https://github.com/HAYASAKA7/KokoroX/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/HAYASAKA7/KokoroX/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/HAYASAKA7/KokoroX/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/HAYASAKA7/KokoroX/releases/tag/v0.1.0
