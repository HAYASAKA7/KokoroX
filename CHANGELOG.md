# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Consented relationship state now reaches sessions. A session started from
  an installed default whose consent grants `relationship_state` returns
  `relationship_state: durable`; `runtime context` shows the retained
  relationship and `state preview` and `state apply` work against it, so the
  next such session continues from it. Revoking consent stops a running
  session's writes. Other sessions report `relationship_state: session` and
  are unchanged. The library wrote and migrated retained state, but no
  command called it: a user who granted consent and applied an event met the
  character at trust 0 in the next session.
- `kokorox state migrate --character <id> --mood-strategy <strategy>` moves
  retained state to the installation the current consent names, with
  `--dry-run` to preview the plan. After an upgrade, writes refused with
  `PERSISTENCE_STATE_MIGRATION_REQUIRED` and nothing could perform one.
  `consent grant` now advises that `relationship_state` reaches new sessions,
  and still that `mood_state` is not connected.
- A hard report now lists every authored line the gate spoke, in
  `fixed_lines_spoken`: intent, locale, and whether it opens or closes the
  turn. The gate walked every line but recorded only failures, so a clean
  report gave a reviewer no way to see what had been exercised. The field is
  optional in the schema, so reports made before it still validate.
- A turn can speak more than one authored line, and a line can close the
  response. `runtime plan` accepts `--expression-intent` once per manner the
  turn calls for, and a pack lists intents that belong after the answer
  under `closing_expressions` in `behavior.yaml`. A persona that says one
  line on taking an order and another on finishing could say only the first,
  and always before the answer, so a completion line announced work that had
  not been shown yet. Opening lines now lead in the order asked, closing lines
  follow the answer, authoring refuses a closing intent the pack does not
  author (`AUTHORING_CLOSING_EXPRESSION_UNKNOWN`), and the hard gate reports
  a line planned at the wrong end (`PACK_FIXED_LINE_MISPLACED`).
- `kokorox suite install --replace` upgrades an installed Skill suite in
  place. Install now writes a receipt, `.kokorox-skill-suite.json`, recording
  each Skill's digest and file list. After an upgrade the installed Skills
  match only that receipt, not the new source, so a plain install refuses
  with `SKILL_SUITE_REPLACE_REQUIRED`. `--replace` moves the proven earlier
  Skills aside, publishes the new ones, verifies them, rewrites the receipt,
  and only then deletes what it replaced; a failure before that puts every
  earlier Skill and the old receipt back. An edited Skill matches neither and
  still refuses. Removal uses the same receipt, so the previous suite can be
  removed after an upgrade. A malformed, oversized, or redirected receipt
  proves nothing, and ownership falls back to the current source alone.
  Suites installed by 0.1.0 or 0.2.0, which wrote no receipt, are recognised
  by the exact per-Skill digests those releases shipped, so their first
  upgrade needs no manual step. A Skill nothing vouches for refuses with
  `SKILL_SUITE_RECEIPT_MISSING`, told apart from the `SKILL_SUITE_CONFLICT`
  of a Skill edited after install.
- The build validation report now names each locale a request asked for
  that the pack does not author, as the advisory
  `AUTHORING_REQUESTED_LOCALE_UNAUTHORED`. `requested_locales` was
  required of every build request and read by nothing, so a build could
  deliver fewer locales than were asked for without saying so. A pack may
  still author fewer -- the runtime borrows material for an unauthored
  locale and discloses it -- but the gap is now stated.
- A pack authored in one locale can clear the soft gate honestly.
  `pack soft-eval --profile single-locale-release` judges the five dimensions
  that apply and drops `cross_language_persona_equivalence`, which a
  one-language pack cannot have -- the release profile demanded three samples
  of it anyway. The profile is earned rather than chosen: the hard report now
  records the pack's declared `locales`, and promotion refuses the profile
  unless that is exactly one locale and every sample was taken in it.
- `kokorox suite remove` uninstalls the Skill suite. There was no way to take
  it out again short of deleting directories by hand. A Skill goes only when
  it is byte-identical to the suite source or to the earlier version its
  install receipt records, and any other difference refuses the whole removal
  with `SKILL_SUITE_REMOVE_CONFLICT`. Every Skill is moved aside before any is
  deleted, so a failure while moving puts them all back. The Skill root and
  anything else in it are left alone.
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
- The hard gate (`pack test`) now speaks every authored line. It walks each
  intent the pack authors, in each locale that intent is written in, through
  the production path -- runtime context, plan, render, validate -- and
  reports, by intent and locale, a line the plan failed to carry
  (`PACK_FIXED_LINE_NOT_SPOKEN`), failed to protect
  (`PACK_FIXED_LINE_UNPROTECTED`), or that validation rejected
  (`PACK_FIXED_LINE_VALIDATION_FAILED`). Before this the gate passed no
  runtime context at all, so no fixed segment was ever planned during
  validation, and a pack could pass while its character stayed silent.

### Changed

- A session that applied events while degraded no longer loses them when
  consent returns. It jumped back to retained state without a word and the
  events were gone; it now stays on session state with the advisory cause
  `SESSION_EVENTS_KEPT`, and a new session continues the retained
  relationship. A degraded session that wrote nothing still reconnects.
  `session start` reports the state a session actually gets: one started
  after an upgrade but before migration answered `durable` while every
  context came back degraded.
- Two commands creating the same data directory at once no longer fail. Two
  installs into a fresh data root both found the registry directory missing,
  both created it, and the second reported `KARC_REGISTRY_PATH_INVALID`;
  concurrent default changes could do the same. A directory another command
  just created is accepted once it is confirmed to be a plain directory.
- Concurrent installs now actually both succeed. The previous fix re-read
  the registry after a failed preview but still before taking the scope
  lock, so when the other install had not yet published, the locked path
  audited against a stale capture and refused with `KARC_INSTALL_CONFLICT`.
  The baseline is now taken once the lock is held, verified with real
  concurrent processes, and the lock wait is about six seconds so several
  queued installs do not give up.
- A removal on a long-lived data root is fast again. Its audits skipped
  re-reading unchanged listings, but the removal's own scope lock and
  registry sit in the workspace-registries directory, so every audit took
  the slow path; the installed tree was also re-read after each validation.
  Both now use metadata when nothing changed.
- A reference another command changes during a removal -- an install into
  another workspace, a session starting -- is still refused, but as a
  retryable `KARC_REMOVE_REFERENCE_SCAN_INVALID` with reason
  `concurrent_change`, since the same removal run again answers correctly.
- Every session now records what it started from, in a session binding:
  the installation and scope a default resolved, or a compiled path. Removal
  reads it, so removing one workspace's installation is no longer blocked by
  another workspace's session or a compiled-path session that only share its
  character hash. Sessions started before this change still block, as before.
- A neutral plan now lists the pack's authored lines under the optional
  `forbidden_spans`, and `runtime validate` refuses a render that speaks one
  with `FORBIDDEN_SPAN_PRESENT`; a render keeping both catchphrases against a
  `--fallback-level 3` plan used to validate. A line the Semantic Result
  itself protects is not forbidden.
- Smaller fixes from the eleventh QA pass. `runtime plan --policy` accepts what
  `policy compile` printed, as `--context` already did. Persistence refusals
  keep their fixed reason in `details`, so a second `state migrate` says
  `same_installation`. `state export` with no consent answers
  `PERSISTENCE_CONSENT_NOT_FOUND` instead of a corrupt journal. `consent grant`
  takes workspace scope from `--workspace`, and still refuses to default to
  global. `session start` reports `source_hash`, which a session's
  `compiled_pack_hash` is. `session show` reports `relationship_state` and the
  `relationship_revision` a durable session's next event must name. A user
  claim's quote folded across YAML lines binds, since whitespace is ignored
  entirely when matching.
- Packs authored before `closing_expressions` no longer open with their
  completion line unannounced. Agents now pass both the acknowledgement and
  the completion, and such a pack places both at the top. `runtime plan`
  advises `EXPRESSION_CLOSING_UNDECLARED` when two or more authored lines all
  open because the pack declares no closing intent, and authoring validation
  advises `AUTHORING_COMPLETION_LINE_OPENS` for an intent named like a
  completion line that `closing_expressions` does not list.
- Concurrent administration gives the right answer instead of a false one.
  The second of two concurrent installs of one archive, or of two versions
  into one workspace, failed with `KARC_INSTALL_CONFLICT`: its preview ran
  before the scope lock and read the other install's publication as a
  conflict. That preview now defers to the locked path, which plans again, so
  an identical archive is idempotent. A default set while a removal ran made
  the removal fail as `KARC_REMOVE_REFERENCE_SCAN_INVALID`; default changes
  now take the scope's registry lock, and a removal captures its references
  again once it holds that lock, so it answers `KARC_REMOVE_REFERENCED`. A
  removal's audits no longer re-read every session manifest and workspace
  registry after each document: a listing whose entries are old and unchanged
  in size, times, and file id is not read again. One removal in a long-lived
  data root had taken 67 seconds with the lock held.
- A live session no longer stops answering when its consent changes. The
  changelog said revoking consent stops a running session's writes, but it
  stopped `runtime context` too, so the character could not reply; granting
  consent to a newer version did the same. `runtime context`, `state
  preview`, and `state apply` now continue with session state and return the
  advisory `PERSISTENCE_SESSION_DEGRADED` naming the `cause`; nothing is
  written durably and retained data is not read.
- Adding a permission no longer locks a character out of its retained
  relationship. Retained state was bound to the exact grant revision that
  created it, so any later grant on the same installation -- the README's way
  to add a permission, or granting again after a revoke -- made every
  durable session fail with `PERSISTENCE_STATE_MIGRATION_REQUIRED`, while
  `state migrate` refused an unchanged installation and reset did not help.
  The same consent at a later grant revision now continues the retained
  state, and the next write binds it to the new grant. Granting again after
  a revoke reattaches what revocation kept. A new version still requires
  `state migrate`. Existing journals replay unchanged.
- Canonical JSON checks are faster on valid documents. Every canonical
  write and comparison checks the document is plain JSON, thousands of times
  per install, migration, or gate run, and that check built a path tuple and
  sorted the keys of every object even when nothing was wrong -- a fifth to a
  quarter of some operations. A quick pass now proves validity without
  paths; only a document it cannot vouch for takes the exact walk, so every
  refusal and the path it names are unchanged.
- Bounded file reads no longer reserve their whole bound. Installing,
  recovering, migrating, and removing packs, reading registries, defaults,
  sessions, Skill files, and JSON inputs each called `read(limit + 1)`,
  which on a buffered file allocates the full bound before reading: with the
  64 MiB archive bound, about 17 ms and 64 MiB per call for a file of a few
  hundred kilobytes. They now read in 1 MiB chunks up to the same bound, so
  the limits and their refusals are unchanged.
- **Breaking:** every `user_dossier` or `user_override` evidence claim now
  carries a `quote` copied from the content of a typed request input of the
  same type. Authoring validation checked a user claim's label and never its
  content, so a dossier claim the dossier never made, or an override that
  differed from the request's, validated. A missing or too-short quote is
  `AUTHORING_USER_CLAIM_QUOTE_REQUIRED`; one no such input contains is
  `AUTHORING_USER_CLAIM_QUOTE_UNBOUND`. Quotes match after NFC and whitespace
  folding. More `user_override` claims than override inputs returns the
  advisory `AUTHORING_USER_OVERRIDE_CLAIMS_EXCEED_INPUTS`. Packs with user
  claims need a `quote` added to each before they validate again.
- `runtime plan` now honours a `neutral` scenario intensity cap and the
  neutral fallback rung. A scenario capped at `neutral` still planned the
  pack's lines, so an agent that honoured the cap failed validation and one
  that ignored it passed; and the plan a turn already had protected those
  lines, so the contract's last rung, the neutral renderer, could never
  validate. With `--context` naming a neutral scenario, or with the new
  `--fallback-level 3`, the plan carries no authored lines and no intent,
  routes every segment that is not `preserve` to the primary language, and
  allows no switches; the command returns the advisory `PLAN_NEUTRAL` with
  the reasons. The hard gate speaks authored lines through a scenario that
  is not capped at neutral.
- Starting an installed character is documented and reports what it
  started. `using-kokorox` said a compiled path was the only valid input to
  `session start`, so an agent told to use the installed pack tried a file
  inside the installation and was refused; the skill and runtime contract
  now give `session start --workspace <repo-root>`. The start result adds
  `resolved_from` (`compiled_path`, `workspace_default`, `global_default`)
  and `installation_id`, and a global start without `--workspace` returns
  the advisory `SESSION_WORKSPACE_NOT_CONSULTED`. `--workspace` alone now
  selects workspace scope for scoped commands such as `config default show`,
  which refused it without `--scope workspace`.
- Refusals now say what would work. `UNKNOWN_SCENARIO` lists the pack's
  scenario ids in `details.available` -- three of five agents guessed a
  scenario on their first call and read the pack's files to recover.
  `INVALID_RENDER_PLAN_INPUT` for an intent list gives a fixed `reason` and,
  for too many, the `limit` and `observed` count. `MIGRATION_INPUT_INVALID`
  keeps the failed `checks` and the finding codes `pack install` would give.
  `runtime plan` also returns `advisories`: `EXPRESSION_INTENT_NOT_AUTHORED`
  when a named intent planned no line, with the intents the pack does author,
  so a misspelt `task_complete` no longer looks like a quiet pack; and
  `EXPRESSION_CONTEXT_MISSING` when intents were named without `--context`.
- `runtime plan --help` now says `--expression-intent` is repeatable, and the
  runtime contract and `using-kokorox` say to pass both the acknowledgement
  and the completion when a task finishes inside the reply. The flag carried
  no help text and the contract's "the first styles the conclusion" read as
  singular, so across four finishable conversations no agent passed two
  intents, and three said the CLI took only one.
- `runtime validate` now checks where an authored line is rendered. The
  contract says to render every segment in plan order, but a completion line
  moved before the answer, or both lines swapped, still validated. The lines
  must now appear in plan order, a plan that opens with one must have the
  text open with it, and one that closes with one must have the text close
  with it; otherwise `FIXED_LINE_OUT_OF_ORDER`.
- `runtime validate` no longer takes a render's `switch_count` on trust. A
  render whose segments went `ja-JP`, `zh-CN`, `ja-JP` could declare no
  switches and pass. The language changes between consecutive segments are
  now a floor: a lower declared count is `SWITCH_COUNT_UNDERSTATED`, and the
  switch limit is checked against whichever of the two is higher.
- Concurrent installs and removals now wait long enough and say when to
  retry. The registry scope lock gave up after 150 ms while an install holds
  it for about half a second, so the second of two concurrent installs always
  failed; it now backs off for about two seconds, and
  `KARC_REGISTRY_LOCKED` is marked retryable. A removal whose reference scan
  landed on a concurrent atomic replace -- a default being set -- failed as
  if the file were corrupt; it now rereads briefly and returns the right
  answer, such as `KARC_REMOVE_REFERENCED`.
- The README and `consent grant` now say plainly that relationship and mood
  persistence is not connected yet. A user could grant `relationship_state`
  and `mood_state` and expect the character to remember, but no command
  writes session events to durable storage, reads them into a new session,
  or performs the migration an upgrade requires. Granting either now returns
  the advisory `PERSISTENCE_STATE_NOT_CONNECTED`; memory references, export,
  and reset are unaffected.
- A refused removal now says what still refers to the installation.
  `KARC_REMOVE_REFERENCED` was raised with its blocker list and reached the
  caller with an empty `details`, and its message named only sessions and
  memory while the scan also covers defaults, consent, state, and
  migrations. `details.references` now carries the blocking kinds, and
  `details.sessions` the ids of any active sessions to end first.
- `pack list` now explains an unusable release with the failure `pack
  install` reports for the same archive, such as
  `KARC_RELEASE_BINDING_INVALID`. It used to pass along the default
  resolver's generic `KARC_DEFAULT_STALE`, which named a subsystem that was
  not involved; that code now appears only when the installed metadata
  itself is stale.
- Verbatim delivery now leaves room for host metadata. Step 6 of
  `using-kokorox` and the runtime contract still require `rendered.text`
  unchanged and complete; a host that must attach a declared deviation,
  provenance, or a diagnostic now has a legitimate place for it -- a separate
  host field, or after the whole response behind a separator, labelled as
  host metadata, never before or inside it. The old wording left none, so
  every delivery that needed metadata had to declare a deviation.
- `policy compile` now says that subtitles are not rendered. A policy could
  enable `subtitles` and pass validation, but no render plan carried it and
  nothing read it, so the setting changed nothing without a word. Compiling
  such a policy returns the advisory `POLICY_SUBTITLES_NOT_RENDERED` in a new
  `advisories` list, and the runtime contract states the limitation.
- `pack list` now says whether each installed release can still be used.
  A release installed under an earlier KokoroX stayed listed after an upgrade
  even when its evidence no longer validated, while consent, state, and
  memory refused it with `PERSISTENCE_INSTALLATION_STALE`. Each entry now
  carries `usable`, and an `unusable_reason` code when it is false, from the
  same revalidation those commands run. The README says what to do: rebuild
  the release from its source pack and install the new archive.
- The host-adapter check in the runtime contract now ties the selected
  transcript record to the request being answered. Its four conditions find
  a real user turn, but a message sent while a turn is running reaches the
  transcript too late, so the newest real turn could be the previous request
  and pass every check. The record must now match the request by content or
  timestamp; when neither ties it to this request, there is no lossless
  source.
- `pack install` now says why an archive is invalid. `KARC_INSTALL_ARCHIVE_INVALID`
  carries the failing compatibility codes in `details.reasons` -- for an
  archive released before the `file_safety` rename, the binding failure
  that `pack compatibility` reports -- and its message names
  `kokorox pack compatibility` for the full report. It used to state the
  fact with an empty `details`, one command away from the reason.
- A research workspace that fails to load now says where.
  `RESEARCH_WORKSPACE_INVALID` carries the rejected record's position in the
  manifest (`record`, such as `["conflicts", 0]`), the contract it broke
  (`schema`), the field `path`, and any `missing` required properties. An
  unresolved conflict filed without its `incompatibility_rationale` used to
  fail with an empty `details` object; it now names the conflict and the
  absent field. Only structure is reported, never the rejected values.
- Schema validation no longer repeats work that depends only on a schema
  file's bytes. Loading still reads and parses the file every time, so a
  schema that changes on disk is honoured immediately, but Draft 2020-12
  meta-validation and validator construction are now remembered per file
  and digest. The hard gate loads eleven distinct schemas twenty-seven
  times per run and spent most of that time re-checking the schemas
  themselves.
- **Breaking:** the hard gate's `security` check is now `file_safety`. It
  flags executable-shaped files, executable permissions, and pack files that
  keep changing while the gate runs. It never read pack text, and a check
  named `security` reporting `passed: true` invited the reading that
  pack-borne injection had been examined. The testing contract now says
  content trust has no gate behind it. Hard reports made before this change
  no longer validate; re-run the gate.
- **Breaking:** an unresolved research conflict now needs an
  `incompatibility_rationale` saying why its claims cannot both be true. Both
  resolved states always had to be argued for, while `unresolved` -- the
  state that blocks authoring -- needed nothing, and the schema forbade a
  reason outright. Existing workspaces with an unresolved conflict fail
  validation until one is added. The research contract now also says to
  classify the attribute and re-read the cited excerpts first: two sources
  giving different values for something that changes over time usually record
  a progression, not a contradiction.
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

- The build validation report counted evidence as one number, so a reviewer
  could not tell unverified private assertions from externally sourced facts --
  the distinction the construction modes exist to keep apart, in the report a
  review is made from. `provenance_counts.evidence_by_source` now breaks the
  count out by claim source; a label outside the four known sources is counted
  as `unrecognized` rather than named.
- `consent grant` replaces the permission set, and the README said "granting
  one never grants another" -- true, but it read as "granting one leaves the
  others alone", which is the opposite of what happens. Adding one permission
  silently dropped the rest. The README now states the semantics, and the
  command returns `revoked_by_replacement`, naming every permission a grant
  withdrew from the consent it replaced.
- `PUBLICATION_PROMOTION_STALE` blamed "the Character Pack" whenever any
  promotion binding moved -- including after a KokoroX upgrade, when the
  source was byte-identical and only the compiled artifact had changed, which
  sent authors to audit files that had not moved. The finding now names what
  did: the source, the compiled artifact and the versions that built it, or
  the specific field. The testing Skill says an upgrade voids release
  evidence.
- 133 of the 248 error codes the runtime raises reached callers as
  "Command could not be completed", with empty `details` -- session, runtime,
  policy, promotion, publication, persistence, and migration errors alike.
  Messages had been added one family at a time, only after a report named
  that family. Every code now carries its own message, a test fails on any
  raised code without one, and four codes return what a caller needs to act
  on: the languages behind `PLAN_CONCLUSION_LANGUAGE_MISMATCH`, the
  hard-failure codes behind `AUTHORING_VALIDATION_FAILED`, the registered
  paths behind `MIGRATION_UNAVAILABLE`, and which of three situations
  `PERSISTENCE_INSTALLATION_STALE` is -- whose message no longer calls a
  pack that was never installed "stale".
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
