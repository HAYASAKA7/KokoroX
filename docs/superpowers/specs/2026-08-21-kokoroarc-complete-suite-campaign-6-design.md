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

The correction has seven isolated components:

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
6. **CLI evidence binder** pairs each accepted operational CLI invocation with
   its exact ordered JSON document, exit status, captures, and artifacts.
7. **Behavioral adjudicator** consumes only integrity-approved facts and then
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

Each run receives a unique case root under the unique Campaign 6 raw root. All
approved write targets, temporary directories, data directories, and tool homes
resolve beneath that case root. Approved read-only roots are enumerated in the
envelope. The preflight verifies path ancestry and identities without following
redirecting links and refuses junctions, symlinks, hard-linked writable inputs,
or pre-existing campaign outputs.

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

## 7. Closed static command policy

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

### 7.4 Rejected operations

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

For every command event, the importer first proves the retained event is the
declared sanitized copy of an approved raw event. Started and completed events
must share the same event ID and exact command bytes before sanitization. The
completed event must have a terminal status and an integer exit code.

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

For a command record containing `N` operational `--json` CLI invocations, the
completed output must contain exactly `N` complete JSON documents in invocation
order, separated only by JSON whitespace. Streaming decoding is bounded by the
existing 64 MiB session limit, 4 MiB per document, and at most 128 documents per
record. Profile output, banners, inspection text, duplicate documents, trailing
bytes, truncation, reordered documents, or a count mismatch rejects the record.
Each document is bound to its CLI operation ordinal and then passed to the
existing action-specific evidence checks.

Operational evidence requires exit code zero and consistent success fields.
Generated artifacts, captures, before/after inventories, and final response
bindings retain their existing byte, hash, identity, visibility, and confinement
checks. A syntactically valid command cannot substitute for a missing capture or
artifact.

## 9. Failure model

Integrity is fail-monotonic. Any launch, lifecycle, parser, limit, policy,
raw/retained, output, artifact, confinement, or final-binding failure makes every
declared case assertion false before `must` or `must_not` interpretation. A
`must_not` assertion can never become true merely because its evidence was
missing or untrusted.

Stable non-echoing failure codes distinguish at least:

- shell or decoder identity failure;
- profile or environment boundary failure;
- command lifecycle failure;
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
directory preparation, raw/retained path normalization, and exact JSON binding.

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
  and
- parser errors, decoder drift, PowerShell version drift, and profile execution.

Every mutant must fail all assertions monotonically. Determinism tests run the
decoder and canonicalizer twice on the same bytes and compare exact output.
Resource tests exercise every boundary at the limit and at limit plus one.
Mutation tests prove caller inputs, fixture bytes, parser output, and evidence
records remain unchanged.

The pre-freeze gate includes the complete focused campaign suite, all relevant
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
- all twenty-four raw/retained lifecycles and command plans are integrity-valid
  and evaluable;
- all twelve suite-enabled cases pass every declared behavioral assertion;
- the existing campaign summary reports no suite deviation and
  `suite_closure_passed=true`;
- baseline results and all twelve paired comparisons are complete,
  deterministic, and honestly retained; and
- import and adjudication replay reproduce the exact inventories, plans,
  results, summaries, and hashes.

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
