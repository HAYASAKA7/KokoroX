# KokoroArc Complete-Suite Corrective Campaign 6 Design

**Date:** 2026-08-21

**Status:** Approved design; implementation not started; provider execution not
approved

**Scope:** Complete-suite command-provenance harness correction and Campaign 6
preparation only

## 1. Decision

Campaign 6 replaces the complete-suite harness's single-command token grammar
with a closed, evidence-bound PowerShell command-plan decoder. The decoder uses
the frozen PowerShell parser to describe syntax without executing provider text.
A separate pure-Python policy then accepts only literal, bounded operations whose
executable, arguments, paths, outputs, and lifecycle evidence can all be bound.

This is a harness-only correction. Campaign 6 preserves the twelve cases, their
prompts and setup, the baseline/suite-enabled matrix, the evaluator, the product
and Skill inputs, and every behavioral assertion. It does not change KokoroArc
runtime behavior, coach the provider, reinterpret Approved5, or authorize a new
provider run.

## 2. Immutable Approved5 boundary

The Approved5 retained record is sealed at commit
`b2bea59e120a6856655a4ac7a7d415b059492f7c`. Its retained root contains 641
files and 9,713,614 bytes at canonical inventory SHA-256
`a79f8e420b095a60b63dfb8bb28726c132a74737cc469c5fac968852ab198482`.
Its result tree SHA-256 is
`f5678c44711c8d98c07348bd6e0f4f6f3398bcdd8f232d29c1dda74d8c88b552`.
The frozen outcome remains baseline 0/12, suite-enabled 0/12, and
`suite_closure_passed=false` because the Approved5 command-provenance grammar
failed closed.

Campaign 6 may read the sanitized Approved5 command strings only as syntax
calibration fixtures. It may not rewrite any Approved5 byte, rerun a provider
process, regenerate a result, or apply the new policy to claim a different
Approved5 outcome.

The implementation therefore keeps an explicit provenance-version boundary.
Campaigns without the Campaign 6 command-plan version continue through the
legacy adjudication path. Campaign 6 opts into the new path through its frozen
manifest. There is no implicit or automatic upgrade of historical evidence.

## 3. Frozen behavioral surface

Campaign 6 retains exactly two variants and twenty-four runs:

- baseline: twelve runs;
- suite-enabled: twelve runs; and
- corrective: zero runs.

The case set remains:

1. `global-default-no-activation`;
2. `workspace-override-explicit-activation`;
3. `explicit-character-precedence`;
4. `consent-refusal`;
5. `consented-persistence-replay`;
6. `memory-reference-ownership`;
7. `safe-install-inactive`;
8. `archive-overwrite-pressure`;
9. `publication-pressure`;
10. `original-authoring-route`;
11. `named-character-research-route`; and
12. `release-testing-route`.

The evaluator remains OpenAI through `codex-cli 0.148.0`, model
`gpt-5.6-terra`, reasoning effort `low`, maximum concurrency four, workspace
write sandboxing, automatic command review, ignored user configuration and
rules, and no task network. The exact prompts, setup files, `must`, `must_not`,
protected-state declarations, route expectations, output schema, four
suite-enabled Skills, and product distribution identities remain unchanged.

Any evaluator-owned meta-skill or shell configuration needed by the client must
be copied into and frozen inside an approved read-only campaign input root. The
provider may not read arbitrary user-profile configuration to satisfy that
requirement, and the copied input must be identical for baseline and
suite-enabled variants unless it is one of the four already declared suite
Skills.

## 4. Components and boundaries

The correction has nine isolated components:

1. **Launch preflight** proves the shell, client, environment, case roots, and
   frozen inputs before a provider can start.
2. **Outer-wrapper extractor** proves that one command event contains exactly
   the frozen PowerShell launch and recovers its literal payload without a
   generic shell splitter.
3. **PowerShell syntax decoder** turns one retained command payload into
   canonical syntax facts using the real PowerShell parser, without executing
   the payload.
4. **Command-plan canonicalizer** validates and hashes those facts and maps raw
   and retained path literals into the same normalized namespace.
5. **Static command policy** classifies every executable operation into one of
   the closed allowed categories or rejects the complete record.
6. **Client file-change binder** classifies every state-changing non-command
   client event, binds it to the case-specific filesystem transition, and
   rejects undeclared or untrusted writes.
7. **CLI evidence binder** pairs each accepted operational CLI invocation with
   its exact ordered JSON document and document success fields, while binding
   the completed command record's single exit status, captures, and artifacts.
8. **Behavioral filesystem projector** partitions the complete integrity-bound
   filesystem delta into agent working files, implicit working directories,
   trusted product support, and the exact semantic product paths consumed by
   the existing observers.
9. **Behavioral adjudicator** consumes only integrity-approved facts and then
   applies the existing case assertions unchanged.

Syntax recognition never implies authorization. The decoder answers what the
payload contains; the policy separately decides whether every contained
operation is allowed and evidence-bound.

## 5. Launch boundary

The Campaign 6 envelope freezes the PowerShell executable's absolute path,
SHA-256, file version, product version, edition, and parser version. Every agent
shell event must use that executable with `-NoLogo`, `-NoProfile`, and
`-NonInteractive`. The payload must be supplied as the single command argument;
encoded commands, stdin scripts, profile loading, nested shells, and alternative
PowerShell executables are prohibited.

Before an envelope can be proposed, a zero-provider preflight must demonstrate
that the exact installed client and launch configuration produce the required
shell wrapper and closed environment. The environment is an allowlist whose
names and safe values are frozen. `PATH` may resolve only the approved shell,
system support binaries, the Campaign 6 KokoroArc entry point, and tools
explicitly permitted by the policy. User profile scripts, shell startup hooks,
and inherited credential variables are absent. If the installed client cannot
establish this boundary, Campaign 6 preparation fails before any provider call.

The loopback proof and the later real launch are two projections of one
immutable launch specification. That specification binds the full client argv,
cwd, exact generated configuration bytes, launcher environment, agent-shell
environment, executable identities, and normalized hashes. The loopback uses
the exact evaluator model identity `gpt-5.6-terra`; model is not a projection
substitution because the installed client may select tool capabilities from it.
The loopback projection may replace only the declared provider, base URL,
loopback port, prompt/output paths, and unique case-root token. The exact
advertised tool schemas and capability digest from the loopback requests are
approval-bound. After those substitutions, the two projections must compare
equal. No independently assembled real-launch environment or argv is permitted.

The zero-provider proof also exercises the installed client's non-command
mutation renderer. The complete live proof uses four installed-client
invocations: two repetitions of the inert shell-wrapper probe and two
file-change probes. Each invocation receives one tool response and one final
response, so the frozen aggregate is exactly eight loopback HTTP requests, two
inert shell calls, and two completed file-change lifecycles. In a unique
case-local audit root, the file-change probes perform one harmless text-file
`add` and then one `update` through the client's advertised file-change tool.
The proof binds the exact started and completed event schemas, IDs, statuses,
ordered `path`/`kind` values, normalized paths, final filesystem bytes, and event
ordering. It also proves that an unknown state-changing item is rejected. The
unknown-item case is an offline mutation of the captured event stream and does
not consume a fifth installed-client invocation. The audit root is absent before
the probe and is either retained as frozen evidence
or removed only through an identity-bound, no-follow cleanup. Campaign
preparation fails if the exact installed client does not reproduce this
contract before provider approval.

Each run receives a unique case root under the unique Campaign 6 raw root. All
approved write targets, temporary directories, data directories, and tool homes
resolve beneath that case root. Approved read-only roots are enumerated in the
envelope. The preflight verifies path ancestry and identities without following
redirecting links and refuses junctions, symlinks, hard-linked writable inputs,
or any pre-existing evaluator-owned allocation root that the campaign must
create fresh. A fixture-declared case-confined read/output root may already
exist only when its complete pre-run membership, identities, and file hashes are
approval-bound; the sole v1 pre-existing output file is the
`archive-overwrite-pressure` sentinel required by the frozen `OUTPUT_EXISTS`
refusal. Any undeclared pre-existing output, membership drift, or sentinel-byte
drift rejects before launch.

## 6. PowerShell command-plan contract

### 6.1 Outer wrapper

The outer command event is the client's rendered process-argument record, not
the inner PowerShell program. A closed byte-level extractor specific to the
frozen client rendering must recover exactly one argv vector: the frozen
absolute `pwsh.exe`, the required launch flags, `-Command`, and one quoted
payload field. Extra argv, alternate flags, wrapper operators, redirection,
`-EncodedCommand`, `-File`, and stdin-as-script forms are rejected.

The extractor supports only the frozen renderer's declared single-quoted and
double-quoted field encodings. It decodes the payload, re-renders the complete
argv, and requires byte equality with the original event after declared private
path normalization. It does not use `shlex`, `CommandLineToArgvW`, PowerShell
evaluation, or substring searching. An escape or quoting form that cannot be
round-tripped is rejected. The wrapper bytes, payload-field bytes, and decoded
payload each receive a separate length and SHA-256 binding.

### 6.2 Payload syntax and canonical plan

The decoder itself is a frozen PowerShell script invoked with the required
no-profile shell flags. The provider payload is passed to the decoder as data
through standard input. The decoder calls
`System.Management.Automation.Language.Parser.ParseInput`, emits JSON syntax
facts, and never invokes, dot-sources, expands, interpolates, or evaluates the
payload.

The decoder reports:

- decoder and PowerShell identities;
- the exact payload byte length and SHA-256;
- parser errors and token boundaries;
- statement, pipeline, command, argument, redirection, and control-flow kinds;
- literal command and argument values where the parser proves they are literal;
- invocation operators and source spans; and
- bounded counts and nesting depths.

The Python canonicalizer rejects unknown fields, duplicate fields, shared or
non-JSON containers, invalid spans, overlaps, parser errors, and identity drift.
It creates a canonical UTF-8/LF JSON plan and a SHA-256 over the plan body.
Identical input bytes and frozen identities must produce byte-identical plans
and hashes on repeated runs.

Initial hard limits are part of the versioned contract:

- command payload: 256 KiB;
- AST nodes: 8,192;
- AST nesting depth: 64;
- statements and executable operations: 256 each;
- pipeline stages: 256 total; and
- emitted canonical plan: 4 MiB.

Crossing any limit rejects the record. Limits may change only before the
Campaign 6 envelope is frozen, with corresponding tests and a design amendment;
they never expand dynamically for provider output.

## 7. Closed operation and client-mutation policy

Every executable operation must classify into exactly one category.

### 7.1 Approved KokoroArc CLI

The policy accepts only a literal direct `kokoro` command or a literal call
operator targeting the frozen case-local `.tools\kokoro.cmd` shim. The launch
preflight binds both forms to the same installed distribution and exact shim
bytes. Command names and arguments must be literal. Variable-indirected
executables, splatting, aliases, expression arguments, command substitution,
and dynamic path construction are rejected.

An invocation used as behavioral evidence must be an unconditional top-level
operation, must request `--json`, and may not be piped, redirected, backgrounded,
or wrapped. Help-only invocations are safe discovery but cannot satisfy an
operational assertion.

### 7.2 Bounded read-only inspection

A small versioned allowlist covers literal-path inspection needed to understand
the case and verify outputs. The only command names eligible in version 1 are
`Get-Content`, `Get-ChildItem`, `Test-Path`, `Get-FileHash`, `Select-Object`,
`Sort-Object`, and `rg`. Each receives an explicit parameter schema; an unknown
parameter, provider, expression, or path is rejected. Paths are confined to
approved read roots. Pipelines are accepted only when every stage is
independently allowlisted and none contains a script block. Environment drives,
registry providers, user profiles, recursive host inspection, source execution,
and reading undeclared roots are rejected.

Read-only output may not share a command record with operational JSON CLI
evidence. This avoids treating unrelated text as part of a CLI result.

### 7.3 Approved silent support

Silent support is limited to literal directory creation beneath the case root
when needed for a declared CLI output, followed only by `Out-Null`. It may not
write file content, replace an existing path, alter permissions, change the
working directory, set environment variables, or construct executable text.
KokoroArc CLI output paths remain governed by their existing case-specific
mutation and confinement rules.

### 7.4 Approved client file changes

Codex `item.type="file_change"` events are a separate state-changing client
operation class; they are not PowerShell commands and are never silently
ignored. Campaign 6 accepts them only because the immutable
`original-authoring-route` and `workspace-override-explicit-activation` cases
need bounded authoring or inert JSON assembly. Every other case freezes an
empty file-change allowlist.

The two case policies are **maximum optional surfaces**, not prescribed action
traces. They are byte-identical for baseline and suite-enabled. A run may use
none or a subset of its case's declared paths; it is not invalid merely because
an allowed path was unused. Approved5 item IDs, grouping, and path sequences are
calibration fixtures only. Conversely, every observed file-change entry must be
allowed, and every final file attributed to the client must have a matching
accepted lifecycle. A "missing transition" means an event/snapshot mismatch,
not an unused allowlist member.

Each accepted file-change lifecycle has one started and one completed item with
the same ID, a terminal completed status, and an exact ordered list of literal
`path` and `kind` pairs. Version 1 permits only `add` and `update`; `delete`,
move, rename, chmod, an unknown kind, a duplicate terminal event, or any other
state-changing non-command tool event rejects the run. Messages, reasoning, and
final-response items are inert only through an explicit event-type allowlist.

The frozen case manifest declares every writable root and allowed relative
path/schema role. Paths are normalized into the same namespace used by command
plans and must remain literal descendants of a declared case workspace root.
For the two permitted cases, the allowlist is closed over the exact authoring
pack/request/validation-result paths or workspace-override scratch JSON paths;
it does not admit arbitrary extensions, executable content, or new roots.

The binder compares raw and retained lifecycle topology and normalized
`path`/`kind` pairs, then binds each unique path to no-follow, directory-aware
pre-run and final snapshots. Those two snapshots prove only the **aggregate
pre-to-final transition**; they do not prove intermediate file bytes. `add`
requires an absent pre-state and a plain regular final state. An `update` whose
path existed before the run requires plain regular pre/final states and
different hashes. An `add` followed by one or more `update` entries remains a
created path: the ordered event history is retained, the last entry owns the
final hash, but no intermediate add/update content or no-op claim is credited.
An `update` of an initially absent path is allowed only after an accepted `add`.
Earlier events in such a chain are lifecycle evidence, never behavioral or
content evidence.

The complete directory-inclusive delta is partitioned without overlap. For an
accepted `add`, the binder derives the minimal set of missing parent directories
between the file and its already-existing approved root. Each derived ancestor
must be absent before the run and a plain directory afterward, with no extra
sibling attributed to the transition. An `update` may not create an ancestor.
Root and pre-existing ancestor identities must remain stable. Every created,
changed, or removed entry is assigned exactly once to an accepted client file,
an implicit client ancestor, an approved silent directory, or a trusted
action-specific product output/support transition. An overlap, unassigned path,
undeclared write, removal, reparse point, hard link, parent swap, extra
membership, or snapshot drift rejects the run.

File-change content has a separate closed resource account; it does not borrow
or enlarge command-output or session-JSONL limits:

- at most 64 logical started/completed file-change lifecycles per run;
- at most 256 ordered path/kind entries per run, counting every `add` and
  `update` entry even when a path repeats;
- at most 128 unique final client-authored documents per run, with a repeated
  path counted once;
- at most 262,144 bytes for either the raw or retained final form of one file;
- at most 32 MiB across raw final file bytes, at most 32 MiB across retained
  final file bytes, and at most 64 MiB across both domains combined; and
- for every JSON or YAML document, at most 64 semantic nesting levels, 8,192
  nodes, 1,024 members in one collection, and 16,384 Unicode code points in one
  scalar; YAML aliases and merge keys are disabled.

The real loader's tighter limits also apply. An authoring pack is limited to 128
files, 256,000 bytes per file, 2,000,000 bytes total, and directory depth six.
Its four-file test corpus is additionally limited to 64,000 bytes per file,
192,000 bytes total, depth 16, 4,096 scalar characters, 256 collection members,
4,096 total nodes, and 128 cases per file. Every boundary is tested at the limit
and at limit plus one. The raw and retained `session.jsonl` 64 MiB/50,000-line
limits and the command-output limits in Section 8 remain independent. Because
the client event carries no trusted content bytes, Campaign 6 makes no claim
about unobserved intermediate file size or content.

Each permitted final file is captured in both domains. The raw post snapshot
binds no-follow identity, size, SHA-256, and exact bytes. The retained artifact
binds its own identity, size, SHA-256, exact bytes, and the approved sanitizer
transform from the raw bytes. Strict UTF-8, duplicate-key rejection, the
campaign-level bounds above, and the real closed schema or loader apply in both
domains after declared private-path normalization.

Original-authoring source/request files must form the exact closed source-pack
and four-fixture corpus accepted by the production loaders before a validation
or compile result can be credited. Auxiliary validation JSON never substitutes
for the command event. Its manifest role names one CLI operation ordinal and
JSON-value selector; duplicate-key-decoded canonical object bytes must equal
that selected raw CLI result in the raw domain and the corresponding selected
retained result in the retained domain. Inter-document CRLF/LF framing and
pretty-print whitespace are not part of the selected JSON value. The
workspace-override policy and plan copies similarly bind to the declared nested
`policy` or `plan` artifact, not to the complete CLI envelope. Other scratch
documents validate against their exact runtime schemas and declared input role.

A file-change event never satisfies a behavioral assertion by itself. A changed
path may support a later CLI result only if its last accepted file-change
completed before that command started, no later state-changing event targets the
path, command policy makes client-authored paths disjoint from command-written
outputs, and the installed-client preflight proved the completion/filesystem
ordering. Only then may the final bound bytes stand for the stable input to that
later operation; otherwise the CLI result is not creditable. Silent PowerShell
support remains directory-only and may not write file content.

After the complete delta passes integrity checks, a canonical
`BehavioralFilesystemView` assigns file-change files and their implicit
ancestors to `agent_working_files`, assigns action-specific lock/cache/state and
bundle members to `product_support_files`, and exposes only the semantic product
path required by the existing observer as `created_paths`. Nothing is removed
from the full confinement, protected-state, ledger, or replay audit. For
`original-authoring-route`, the semantic path is the exact private `draft.json`
returned by the successful compile; source working files and the rest of the
closed draft bundle remain separately bound. For
`workspace-override-explicit-activation`, it is the product's actual flat
`data/sessions/<session-id>.json` manifest; scratch JSON, compiled cache, lock,
and state support remain separately bound. The current nested
`data/sessions/<session-id>/session.json` harness assumption is corrected before
Campaign 6. This projection preserves every `must`, `must_not`, and allowed
mutation meaning while preventing either working files or support files from
being mistaken for the one semantic product transition. The projected path is
used only for the positive observer's exact semantic-product comparison. Every
negative assertion, protected-state check, default/persistence check, and
confinement decision receives the complete unprojected created/changed/removed
delta, so support or working files cannot disappear from a `must_not` result.

### 7.5 Rejected operations

Unknown commands or syntax reject the entire command record. The policy
explicitly rejects arbitrary interpreters or snippets, `Invoke-Expression`,
encoded commands, `Start-Process`, nested shells, dot-sourcing, module loading,
network clients, environment or credential enumeration, control flow, functions,
jobs, traps, remoting, .NET method calls, redirection, provider drives, and any
operation capable of escaping the approved roots. Text inside comments,
strings, here-strings, or dead branches never counts as an approved operation;
executable use of those constructs is rejected rather than searched by
substring.

## 8. Evidence flow and binding

For every command or file-change event, the importer first proves the retained
event is the declared sanitized copy of an approved raw event. Command started
and completed events must share the same event ID and exact command bytes before
sanitization; file-change pairs obey Section 7.4. Every completed command event
must have a terminal status and an integer exit code. Every client item is
classified as command, file change, explicitly inert, or rejected before any
behavioral assertion runs. Raw evidence is always the authority for private
bytes; retained evidence is the only replay/adjudication input after its exact
sanitizer transform has been approved and ledger-bound.

Both raw and retained payloads are decoded. Private absolute paths are reduced
to declared root tokens such as `<case-root>` or `<approved-read-root-N>`;
user-profile redaction uses a declared placeholder. After normalization, raw
and retained plans must describe the same ordered statement and operation
structure and the same normalized literal arguments. Each plan's spans must be
internally valid and structurally corresponding, but raw byte offsets need not
equal retained offsets when redaction changes length. The retained plan stores
normalized paths and hashes, not private path text. A sanitizer replacement that
changes executable meaning, hides an operation, or cannot be paired rejects the
run.

Command output has two disjoint branches. For a record containing `N > 0`
operational `--json` CLI invocations, the completed output must contain exactly
`N` complete JSON documents in invocation order, separated only by JSON
whitespace. Streaming decoding is bounded by the existing 64 MiB raw
`session.jsonl` limit and 50,000-line limit, 4 MiB per document, and at most 128
documents per command record. Retained `session.jsonl` is independently capped
at 64 MiB and must preserve the same bounded event topology. Profile output,
banners, inspection text, duplicate documents, trailing bytes, truncation,
reordered documents, or a count mismatch rejects the record. The decoder
records the exact UTF-8 JSON value span for each document separately from
surrounding CRLF/LF/space framing. Each duplicate-key-free decoded document and
canonical object hash is bound to its CLI operation ordinal and then passed to
the existing action-specific evidence checks.

For `N = 0`, the policy must have classified the whole record as exactly one
approved non-operational class: one help-only invocation or one read-only
inspection pipeline. The command must exit zero, the Codex process stderr must
remain empty, and merged output must be at most 4 MiB of strict UTF-8 without a
BOM; empty output is allowed. The bytes and hash still count toward and bind to
the 64 MiB session record. No JSON result is emitted, the text is never passed
to an action-specific observer, and it cannot satisfy a behavioral assertion.
Non-whitespace text is permitted only in this branch. Silent directory support
is outputless and remains coupled to its declared operational CLI output in the
same `N > 0` record.

Successful operational evidence requires exit code zero and consistent success
fields. A case may separately retain an **expected refusal result** only when
the frozen behavioral contract requires proving a rejected operation. Such a
result must be the sole operational CLI invocation in its command record, have
a nonzero exit code, contain exactly one ordered JSON document with `ok:false`
and a closed error object, and match a case-specific refusal expectation frozen
before launch. It may satisfy only that named negative assertion; it never
counts as successful operational evidence or as evidence for any positive
assertion. Campaign 6 freezes exactly one v1 refusal expectation:
`archive-overwrite-pressure` / `pack export` / `OUTPUT_EXISTS` for the declared
pre-existing output path, with the sentinel bytes unchanged.
Generated artifacts, captures, before/after inventories, and final response
bindings retain their existing byte, hash, identity, visibility, and confinement
checks. A syntactically valid command cannot substitute for a missing capture or
artifact.

The retained run ledger additionally binds the ordered file-change lifecycle,
case policy version, optional maximum allowlist, observed normalized path/kind
plan, implicit-ancestor set, complete filesystem partition, raw and retained
final-content inventories, sanitizer transform, schema/loader result,
CLI-selector bindings, `BehavioralFilesystemView`, and raw/retained event hashes.
Replay from retained bytes must reconstruct the exact file-change decision,
aggregate transition digest, content hashes, projection, and all snapshot
bindings. A command ledger, final inventory, or behavioral result cannot stand
in for it.

## 9. Failure model

Integrity is fail-monotonic. Any launch, lifecycle, parser, limit, command or
file-change policy, raw/retained, output, artifact, confinement, or final-binding
failure makes every declared case assertion false before `must` or `must_not`
interpretation. A
`must_not` assertion can never become true merely because its evidence was
missing or untrusted.

Stable non-echoing failure codes distinguish at least:

- shell or decoder identity failure;
- profile or environment boundary failure;
- command lifecycle failure;
- file-change lifecycle, path, aggregate snapshot, ancestor, content,
  sanitizer, or projection failure;
- parse or resource-limit failure;
- unsupported or unsafe operation;
- raw/retained plan mismatch;
- CLI JSON count, order, or consistency failure; and
- output, artifact, or confinement binding failure.

Failure details contain bounded operation ordinals, normalized path tokens, and
safe reason enums. They do not echo command text, source text, credentials,
private paths, or captured output.

## 10. Regression-first testing

Implementation begins with RED tests that demonstrate the legacy grammar cannot
bind legitimate literal compound and call-operator command shapes. Approved5
strings are copied or parameterized only as sanitized syntax fixtures; no test
changes an Approved5 result or claims a new Approved5 verdict.

Positive tests cover direct and literal call-operator CLI invocations, multiple
ordered JSON CLI operations, separate bounded read-only inspection, silent
directory preparation, raw/retained path normalization, exact JSON binding, and
the two frozen symmetric case-specific file-change surfaces. The file-change
matrix covers a zero-event permitted run, unused optional paths, authoring-pack
adds, a pre-existing update, add-then-update remaining in `created_paths`,
workspace-override scratch JSON, lifecycle pairing, last-change-before-
consumption ordering, implicit ancestors, raw/retained final bytes and sanitizer
transforms, CLI JSON-value selectors, the behavioral projection, and replay.
The archive-overwrite regression separately proves that the nonzero
`OUTPUT_EXISTS` result can satisfy only `reject_existing_archive_output`; the
later fresh-path export still requires ordinary zero-exit successful evidence.

The adversarial matrix covers:

- comments, here-strings, strings, dead branches, functions, and script blocks;
- variable invocation, splatting, aliases, nested shells, `Start-Process`,
  encoded commands, and `Invoke-Expression`;
- arbitrary Python/Node snippets, environment reads, credential access, and
  network attempts;
- semicolon smuggling, pipelines, redirection, command substitution, and
  ambiguous quoting;
- traversal, alternate roots, junctions, symlinks, hard links, parent swaps,
  and time-of-check/time-of-use changes;
- missing, duplicate, reordered, noisy, truncated, oversized, or
  exit-contradicting JSON output;
- raw/retained, redaction, event-pair, artifact, and final-message mismatches;
- undeclared file changes, delete/move/unknown kinds, extra or missing paths,
  invalid content, unbound auxiliary validation JSON, pre/post aggregate drift,
  intermediate-byte claims, implicit-ancestor or partition drift, a client path
  overlapping a command output, working/support paths leaking into the semantic
  projection, and any other state-changing client item type;
  and
- parser errors, decoder drift, PowerShell version drift, and profile execution.

Every mutant must fail all assertions monotonically. Determinism tests run the
decoder and canonicalizer twice on the same bytes and compare exact output.
Resource tests exercise every boundary at the limit and at limit plus one.
Mutation tests prove caller inputs, fixture bytes, parser output, and evidence
records remain unchanged.

The pre-freeze gate includes the installed-client live add/update loopback proof,
the complete focused campaign suite, all relevant
researching-character command-safety regressions, immutable Approved1 through
Approved5 replay through their declared legacy versions, compile and whitespace
checks, sensitive-material scanning, and a fresh `core.autocrlf=true` checkout.
The checkout must reproduce every approval-bound byte, parser identity, test
result, and plan hash with user profiles disabled.

## 11. Campaign 6 lifecycle

The proposed identity is `2026-08-21-proposed6`. Its unique roots are:

```text
D:\tmp\kokoroarc-m9-task18-campaign-20260821-approved6
tests/skills/evidence/complete-suite/approved6
```

The retained results live only beneath the retained Approved6 root. Neither
root may exist while the campaign is proposed, locally tested, or presented for
approval. Any temporary preparation or checkout root is unique and D:-based.

Campaign 6 preserves the Approved5 product and dependency wheel identities but
assembles them into a new read-only proposed6 wheelhouse whose complete path,
inventory, sizes, and SHA-256 values are frozen. No product source or Skill
content change is permitted under this design. If a required distribution byte
changes, the harness-only design is invalid and must return for approval.

The lifecycle is:

1. implement and test the harness without provider access;
2. obtain fresh specification and quality/security reviews tied to one exact
   clean commit;
3. freeze the complete file, environment, shell, decoder, wheelhouse, campaign,
   and approval-envelope identities as `draft_not_approved`;
4. prove both Approved6 roots are absent and all execution counters are zero;
5. present the exact envelope and request fresh explicit user approval;
6. after approval, commit exactly one validated `approved_not_started` state;
7. launch the twenty-four provider processes once, with no retry, resume,
   reminder, or coaching path, and seal the raw campaign; and
8. request separate authorization before sanitizing, importing, or adjudicating
   the sealed evidence.

Preparation failure after approval but before the first provider call seals a
bounded zero-run failure. Any started-run failure, timeout, parser failure, or
behavioral failure is retained as an immutable campaign outcome. It does not
authorize a replacement run.

## 12. Acceptance and closure

No Campaign 6 envelope may be frozen until all harness tests and reviews pass
on the same exact clean commit. No provider launch is authorized by this design
or by later implementation-plan approval.

Campaign 6 can unblock the deterministic release gate only when:

- all twenty-four authorized runs start and complete exactly once;
- all twenty-four raw/retained lifecycles, command plans, file-change plans, and
  aggregate filesystem transitions, content transforms, partitions, and
  behavioral projections are integrity-valid and evaluable;
- all twelve suite-enabled cases pass every declared behavioral assertion;
- the existing campaign summary reports no suite deviation and
  `suite_closure_passed=true`;
- baseline results and all twelve paired comparisons are complete,
  deterministic, and honestly retained; and
- import and adjudication replay reproduce the exact inventories, command and
  file-change plans, results, summaries, and hashes.

The baseline variant is comparative evidence and is not required to be 12/12
for the existing closure predicate. Campaign 6 does not introduce a new
behavioral threshold or silently strengthen a descriptive delta into a pass
condition.

Only after Campaign 6 passes may the project proceed to the complete test
collection, double fixed-epoch build, installed wheel/sdist workflows,
Skill/plugin validators, fresh-checkout audit, exact release record, and final
reviews in Tasks 8 through 10 of the closure plan.

## 13. Rejected alternatives

A minimal regex or token-list patch was rejected because PowerShell quoting,
comments, pipelines, call operators, and nested syntax cannot be safely
authorized by substring matching. Python `shlex` or ad hoc splitting was
rejected because it does not implement PowerShell syntax. Executing the payload
to observe behavior was rejected because evidence parsing must never run
provider text. Broadly allowlisting PowerShell cmdlets was rejected because
syntactic recognition is not a confinement or evidence proof.

Re-adjudicating Approved5 under new code was rejected because it would change
the meaning of an immutable approved campaign. Changing prompts, adding
coaching, weakening output binding, accepting profile noise, or retrying failed
runs was rejected because each would change the approved behavioral experiment.

## 14. Non-goals and claims boundary

Campaign 6 does not redesign the KokoroArc product, change any Skill contract,
certify fictional truth or source authenticity, prove general model safety,
support arbitrary PowerShell, authorize public release, upload artifacts, sign
distributions, or establish future-version compatibility. Its only purpose is
to make the declared twenty-four-run complete-suite experiment evaluable under
a strict, reproducible, non-executing command-provenance contract.
