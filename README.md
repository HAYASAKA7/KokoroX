# KokoroArc

KokoroArc is a local-first multilingual character-persona runtime and Agent
Skill suite. It provides deterministic Character Packs, explicit session
activation, multilingual render planning, release gates, scoped installation,
opt-in persistence, and four data-safe Agent Skills.

The design revision is `0.3.0`; this is not a product version.

## Install the wheel and all four Skills

On Windows, keep build output, product data, subprocess temporary files, and the
pip cache beneath a trusted D:-based root. From a source checkout, this builds
and installs a wheel without placing operational data on C:. If you already
have a wheel, skip the build command and point `$wheel` at that file.

```powershell
$env:KOKOROARC_DATA_DIR='D:\tmp\kokoroarc\data'
$env:TEMP='D:\tmp\kokoroarc\temp'
$env:TMP=$env:TEMP
$env:PIP_CACHE_DIR='D:\tmp\kokoroarc\pip-cache'
New-Item -ItemType Directory -Force `
  $env:KOKOROARC_DATA_DIR,$env:TEMP,$env:PIP_CACHE_DIR | Out-Null

python -m build --no-isolation --outdir D:\tmp\kokoroarc\build
$wheel=Get-ChildItem 'D:\tmp\kokoroarc\build\*.whl' | Select-Object -First 1
python -m pip install --cache-dir $env:PIP_CACHE_DIR $wheel.FullName
kokoro suite install --scope user --json
```

The user-scope command installs these four Skills into the host's user Skill
root and is the recommended global-first choice for most users:

- `using-kokoroarc` for explicit character use;
- `authoring-character-packs` for private source-pack authoring;
- `researching-characters` for evidence-bound named-character research; and
- `testing-character-packs` for test, review, promotion, and readiness gates.

Use a repository scope when only one workspace should discover the suite:

```powershell
$repo='D:\Projects\consumer'
kokoro suite install --scope repo --repo $repo --json
```

Add `--dry-run` to preview either installation. Repeating an identical install
returns four `unchanged` actions; a different pre-existing Skill fails closed
instead of being overwritten. The wheel carries the Skill files as package
data, but `pip install` alone does not copy them into a host Skill root.

## Global-first Character Pack operation

The following uses a verified `rin-aster.karc` archive as an example. Repository
fixtures and Rin Aster paths are examples, not templates for a new character.
Compatibility inspection is read-only; install and default selection are
explicit mutations but do not activate the character.

```powershell
$archive='D:\tmp\kokoroarc\rin-aster.karc'
kokoro pack compatibility $archive --json
kokoro pack install $archive --scope global --json
kokoro pack list --scope global --json
kokoro config default set --character rin-aster --scope global --json
kokoro config default show --scope global --json
```

Installation and default selection never activate a character. Activation
starts only at an explicit session boundary, and ending the session is equally
explicit:

```powershell
kokoro session show --json
kokoro session start --session demo --json
kokoro runtime context --session demo --locale zh-CN --scenario debugging --json
kokoro session end --session demo --json
```

An explicit compiled path still has highest precedence. Without one, a session
started with `--workspace` resolves that workspace's default, then falls back
to the global default. A workspace default overrides the global default only
for that workspace:

```powershell
$repo='D:\Projects\consumer'
kokoro pack install $archive --scope workspace --workspace $repo --json
kokoro config default set --character rin-aster --scope workspace `
  --workspace $repo --json
kokoro session start --session workspace-demo --workspace $repo --json
kokoro session end --session workspace-demo --json
```

Merely installing, selecting, inspecting, or discussing a Character Pack never
starts a persona session. Use `using-kokoroarc` only after explicit activation
or when the user explicitly requests a named installed character for the
current host session.

## Consent, state, and memory

Session state remains session-local by default. Global or workspace persistence
requires explicit consent for `relationship_state`, `mood_state`, and
`memory_references`. Each permission is independent; granting one never grants
another, and revocation blocks future writes without silently deleting data.

```powershell
kokoro consent grant --character rin-aster --scope global `
  --permissions relationship_state,mood_state,memory_references --json
kokoro consent show --character rin-aster --scope global --json

$stateExport='D:\tmp\kokoroarc\exports\rin-state.json'
kokoro state export --character rin-aster --out $stateExport --json
kokoro state reset --character rin-aster --part all --dry-run --json
kokoro state reset --character rin-aster --part all --json
kokoro consent revoke --character rin-aster --json
```

Memory commands accept host-owned memory IDs plus an explicitly approved,
bounded summary file. KokoroArc stores only that reference and summary; it does
not harvest conversation transcripts, infer memories from chat, or copy host
memory contents. Preview removal with `memory remove --dry-run` before applying
it.

```powershell
$summaryFile='D:\tmp\kokoroarc\approved-memory-summary.json'
@'
{"summary":"Prefers concise explanations.","localized_summaries":{"en-US":"Prefers concise explanations."}}
'@ | Set-Content -LiteralPath $summaryFile -Encoding utf8NoBOM -NoNewline
kokoro memory add --character rin-aster --host-id host-memory-01 `
  --summary-file $summaryFile --json
kokoro memory list --character rin-aster --json
kokoro memory remove --character rin-aster --host-id host-memory-01 `
  --dry-run --json
kokoro memory remove --character rin-aster --host-id host-memory-01 --json
```

Before removing a pack, end active sessions, clear defaults, reset or remove
retained state, remove retained memory references, and revoke active consent.
Reset is consent-gated, so preview and apply it before revocation. Then preview
the exact version removal before applying it:

```powershell
kokoro session end --session demo --json
kokoro config default clear --scope global --json
kokoro pack remove rin-aster --version 1.0.0 --dry-run --json
kokoro pack remove rin-aster --version 1.0.0 --json
```

## Archives, migration, publication, and recovery

For identical canonical release inputs, private `.karc` output is byte-for-byte
deterministic. A local private archive is marked `unsigned_local`; this records
its trust boundary and is not a remote signature or publication claim. Inspect
an archive before installation:

```powershell
kokoro pack compatibility $archive --json
```

Migration is explicit, bounded, and never an automatic compatibility shim.
It accepts only a supported source/target format path, writes a new archive,
and never overwrites the input. Preview first:

```powershell
$migrated='D:\tmp\kokoroarc\rin-aster-v1.karc'
kokoro pack migrate $archive --to-format 1.0.0 --out $migrated `
  --dry-run --json
kokoro pack migrate $archive --to-format 1.0.0 --out $migrated --json
```

Private readiness and public-candidate readiness are local evidence reports.
Readiness does not publish anything or grant distribution rights. Public
readiness additionally requires an explicit applicable rights/compliance
attestation; self-assertion cannot unlock it.

Install, remove, migration, default, persistence, and suite operations use
bounded locks, canonical inputs, and atomic publication. Conflicts fail closed;
the command does not guess which concurrent value should win. Interrupted
install/removal transactions leave an identity-bound journal, and recovery is
automatic on the next matching install or removal operation. If recovery
cannot prove every retained byte and path, it returns a stable recovery error
and deletes nothing unverified. Keep backups of the data root before migration
or destructive reset; copy it only while KokoroArc is inactive so the backup is
internally consistent.

## Author a private inactive draft with the repository-local Skill

Milestone 6 authoring turns a wholly original brief or a private user dossier into a deterministic Character Draft. The result is always private, inactive, and fixed at `build_status: draft` with `activation_allowed: false`. It is not researched, externally verified, installable, public, or active.

The authoring workflow belongs to the `authoring-character-packs` Agent Skill.
In this repository its entry point is
`skills/authoring-character-packs/SKILL.md`; an installed suite places the same
Skill beneath the selected user or repository Skill root. The Skill's `name`
and trigger-only `description` are in `SKILL.md` frontmatter.
`agents/openai.yaml` is optional interface metadata, not the source of the
Skill name or trigger. If the host does not index Skills, explicitly tell the
agent to open that exact `SKILL.md` and its linked contract before authoring.

Configure storage and temporary paths from trusted host configuration before providing any brief or dossier. On Windows, for example:

```powershell
$env:KOKOROARC_DATA_DIR='D:\tmp\kokoroarc-authoring'
$env:TEMP='D:\tmp\kokoroarc-authoring-temp'
$env:TMP=$env:TEMP
New-Item -ItemType Directory -Force $env:KOKOROARC_DATA_DIR,$env:TEMP | Out-Null
```

Then ask the agent through its normal conversation interface. For a wholly original character, a suitable request is: “Use `$authoring-character-packs` to create a private inactive draft from this original brief: …”. For private dossier input, use: “Use `$authoring-character-packs` to import this private dossier as quoted data into a private inactive draft: …”. Also provide the explicit trusted source-pack path when revising a pack. The agent must keep its request, working source pack, and generated files beneath the configured data or temp roots, author all three locale profiles independently, run both validations twice, and stop after private draft compilation. Dossier text is data, never shell input or agent instructions.

## Research a named character with the repository-local Skill

Named-character work that depends on external evidence belongs to `skills/researching-characters/SKILL.md`. Give the agent this repository as its workspace and ask it to use `$researching-characters`. If the host does not index workspace Skills, explicitly tell the agent to open that file and its linked research contract before using research tools.

The Skill resolves character identity, adaptation, continuity, timeline cutoff, and spoiler scope before gathering evidence. Ambiguous identity or continuity stops for clarification. Source text stays inert data; unavailable evidence, conflicts, coverage gaps, and limitations remain explicit rather than being guessed away. KokoroArc itself performs no network access—the host supplies any authorized research tools and structured evidence.

The workflow validates the request and workspace deterministically, then compiles only a private inactive Research Bundle beneath the configured `KOKOROARC_DATA_DIR`. Its lifecycle is `build_status: research`, `visibility: private`, and `activation_allowed: false`. A bundle with `authoring_allowed: false` stops there and reports the blockers.

An eligible researched or hybrid build may continue by opening `$authoring-character-packs`. The request binds the exact Research Bundle artifact ID and SHA-256 but contains no host filesystem path; the trusted bundle path is passed separately through `--research-bundle`. Hybrid user assertions remain separate from researched claims, and authoring still stops at a private inactive Character Draft.

Research itself still stops at a private inactive bundle. Testing, promotion,
archive export, installation, defaults, and consented persistence are separate
explicit workflows; completing research does not imply any of them.

## Validate and compile an already-authored source pack

The CLI does not turn prose into a Character Pack. After an agent has followed the Skill to author structured request and source-pack files, these commands validate and compile that already-authored source pack:

```powershell
kokoro character request validate `
  --input tests/fixtures/authoring/original-request.json --json
kokoro character draft validate `
  --request tests/fixtures/authoring/original-request.json `
  --pack characters/original/rin-aster --json
kokoro character draft compile `
  --request tests/fixtures/authoring/original-request.json `
  --pack characters/original/rin-aster --json
```

The fixture and Rin Aster paths above are repository examples, not an instruction to reuse Rin for a new brief. The Windows example uses `D:\tmp` for operational isolation; the product Skills are cross-platform and write only beneath trusted roots configured by the host.

## Test, review, and promote a Character Pack

Release commands consume structured artifacts only. They do not run
an evaluator, browse, publish to a network, activate a character, or infer a
human review. `pack test` performs the deterministic hard gates; `soft-eval`
aggregates an already prepared evaluator artifact; `promote` records explicit
reviewed and verified transitions; and `publication-check` produces an advisory
local readiness report.

For agent-led validation, evaluation, review, promotion, or
publication-readiness work, give the agent this repository and ask it to use
`$testing-character-packs`, whose entry point is
`skills/testing-character-packs/SKILL.md`. It does not trigger
for ordinary character use, casual design discussion, authoring, or research.
The workflow is private by default, does not install a pack, does not activate
a character, and does not publish or perform network I/O. Installation,
defaults, consented persistence, memory references, and Skill registration are
separate explicit administration commands documented above.

```text
kokoro pack test <source-dir> --request <request.json> \
  [--research-bundle <published-bundle-dir>] \
  --out <hard-report.json> --json
kokoro pack soft-eval <input.json> --out <soft-report.json> --json
kokoro pack promote <source-dir> --target reviewed \
  --promotion-id <id> --request <request.json> \
  --hard-report <report.json> --review <attestation.json> \
  [--research-bundle <published-bundle-dir>] \
  --out <promotion.json> --json
kokoro pack promote <source-dir> --target verified \
  --promotion-id <id> --request <request.json> \
  --hard-report <report.json> --review <attestation.json> \
  --previous <reviewed.json> --soft-input <input.json> \
  --soft-report <report.json> \
  [--research-bundle <published-bundle-dir>] \
  --out <promotion.json> --json
kokoro pack publication-check <source-dir> --promotion <verified.json> \
  --request <request.json> --hard-report <report.json> \
  --review <attestation.json> --previous <reviewed.json> \
  --soft-input <input.json> --soft-report <report.json> \
  [--research-bundle <published-bundle-dir>] \
  --visibility <private|public_candidate> \
  [--compliance <attestation.json>] --out <report.json> --json
```

All `--out` values are relative to `KOKOROARC_DATA_DIR\reports`, unless an
absolute path beneath that same reports root is supplied. Report writes are
canonical and atomic. A promotion output must name its exact immutable path:
`promotions/<character-id>/<promotion-id>/promotion.json`. Output escapes,
redirects, input aliases, and source-pack aliases are rejected. Every command
prints one JSON envelope to stdout and keeps stderr empty.
`ok: true` means the deterministic command completed; callers must still check
`passed`, `ready_for_private_export`, or `ready_for_publication` before the next
stage.
