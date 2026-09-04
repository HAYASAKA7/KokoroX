# KokoroX

KokoroX is a local-first multilingual character-persona runtime and Agent
Skill suite. It provides deterministic Character Packs, explicit session
activation, multilingual render planning, release gates, scoped installation,
opt-in persistence, and four data-safe Agent Skills.

The design revision is `0.3.0`; this is not a product version.

## Install the wheel and all four Skills

Examples use macOS (zsh/bash). Product data and temporary files live under a
directory you control, set through `KOKOROX_DATA_DIR`. From a source checkout,
this builds and installs a wheel; if you already have one, skip the build step
and point `wheel` at that file.

The suite is cross-platform. On Windows, use PowerShell syntax and a path such
as `D:\kokorox` in place of `$HOME/.kokorox`; every `kokorox` command is
otherwise identical.

```bash
export KOKOROX_DATA_DIR="$HOME/.kokorox/data"
export TMPDIR="$HOME/.kokorox/temp"
mkdir -p "$KOKOROX_DATA_DIR" "$TMPDIR"

python3 -m build --no-isolation --outdir "$HOME/.kokorox/build"
wheel=$(ls "$HOME/.kokorox/build"/*.whl | head -1)
python3 -m pip install "$wheel"
kokorox suite install --scope user --json
```

The user-scope command installs these four Skills into the host's user Skill
root and is the recommended global-first choice for most users:

- `using-kokorox` for explicit character use;
- `authoring-character-packs` for private source-pack authoring;
- `researching-characters` for evidence-bound named-character research; and
- `testing-character-packs` for test, review, promotion, and readiness gates.

Use a repository scope when only one workspace should discover the suite:

```bash
repo="$HOME/Projects/consumer"
kokorox suite install --scope repo --repo "$repo" --json
```

Add `--dry-run` to preview either installation. Repeating an identical install
returns four `unchanged` actions; a different pre-existing Skill fails closed
instead of being overwritten. The wheel carries the Skill files as package
data, but `pip install` alone does not copy them into a host Skill root.

## Use the suite in many agents

The suite is agent-neutral. It installs into the vendor-neutral
`.agents/skills` root rather than any single vendor's directory, so several
agents can discover the same installation:

- user scope installs to `~/.agents/skills`;
- repository scope installs to `<repo>/.agents/skills`.

To install into a specific agent's own Skill directory, pass `--skills-root`:

```bash
kokorox suite install --skills-root 'D:\Agents\some-agent\skills' --json
```

Each Skill also ships a per-agent interface profile under `agents/<agent>.yaml`
carrying that host's `display_name`, `short_description`, and `default_prompt`.
Profiles are provided for `openai`, `claude`, `codex`, `cursor`, `gemini`,
`copilot`, `kimi`, `deepseek`, `qwen`, and a `generic` fallback. A host that
reads its profile gets a ready-made invocation prompt; a host that ignores them
is unaffected.

An agent that cannot load Skills at all can still drive the entire suite through
the `kokorox` CLI, which exposes every documented operation and depends on no
model provider.

## Global-first Character Pack operation

The following uses a verified `rin-aster.karc` archive as an example. Repository
fixtures and Rin Aster paths are examples, not templates for a new character.
Compatibility inspection is read-only; install and default selection are
explicit mutations but do not activate the character.

```bash
archive="$HOME/.kokorox/rin-aster.karc"
kokorox pack compatibility "$archive" --json
kokorox pack install "$archive" --scope global --json
kokorox pack list --scope global --json
kokorox config default set --character rin-aster --scope global --json
kokorox config default show --scope global --json
```

Installation and default selection never activate a character. Activation
starts only at an explicit session boundary, and ending the session is equally
explicit:

```bash
kokorox session show --json
kokorox session start --session demo --json
kokorox runtime context --session demo --locale zh-CN --scenario debugging --json
kokorox session end --session demo --json
```

An explicit compiled path still has highest precedence. Without one, a session
started with `--workspace` resolves that workspace's default, then falls back
to the global default. A workspace default overrides the global default only
for that workspace:

```bash
repo="$HOME/Projects/consumer"
kokorox pack install "$archive" --scope workspace --workspace "$repo" --json
kokorox config default set --character rin-aster --scope workspace \
  --workspace "$repo" --json
kokorox session start --session workspace-demo --workspace "$repo" --json
kokorox session end --session workspace-demo --json
```

Merely installing, selecting, inspecting, or discussing a Character Pack never
starts a persona session. Use `using-kokorox` only after explicit activation
or when the user explicitly requests a named installed character for the
current host session.

## Consent, state, and memory

Session state remains session-local by default. Global or workspace persistence
requires explicit consent for `relationship_state`, `mood_state`, and
`memory_references`. Each permission is independent; granting one never grants
another, and revocation blocks future writes without silently deleting data.

```bash
kokorox consent grant --character rin-aster --scope global \
  --permissions relationship_state,mood_state,memory_references --json
kokorox consent show --character rin-aster --scope global --json

state_export="$HOME/.kokorox/exports/rin-state.json"
kokorox state export --character rin-aster --out "$state_export" --json
kokorox state reset --character rin-aster --part all --dry-run --json
kokorox state reset --character rin-aster --part all --json
kokorox consent revoke --character rin-aster --json
```

Memory commands accept host-owned memory IDs plus an explicitly approved,
bounded summary file. KokoroX stores only that reference and summary; it does
not harvest conversation transcripts, infer memories from chat, or copy host
memory contents. Preview removal with `memory remove --dry-run` before applying
it.

```bash
summary_file="$HOME/.kokorox/approved-memory-summary.json"
printf '%s'   '{"summary":"Prefers concise explanations.","localized_summaries":{"en-US":"Prefers concise explanations."}}'   > "$summary_file"
kokorox memory add --character rin-aster --host-id host-memory-01 \
  --summary-file "$summary_file" --json
kokorox memory list --character rin-aster --json
kokorox memory remove --character rin-aster --host-id host-memory-01 \
  --dry-run --json
kokorox memory remove --character rin-aster --host-id host-memory-01 --json
```

Before removing a pack, end active sessions, clear defaults, reset or remove
retained state, remove retained memory references, and revoke active consent.
Reset is consent-gated, so preview and apply it before revocation. Then preview
the exact version removal before applying it:

```bash
kokorox session end --session demo --json
kokorox config default clear --scope global --json
kokorox pack remove rin-aster --version 1.0.0 --dry-run --json
kokorox pack remove rin-aster --version 1.0.0 --json
```

## Archives, migration, publication, and recovery

For identical canonical release inputs, private `.karc` output is byte-for-byte
deterministic. A local private archive is marked `unsigned_local`; this records
its trust boundary and is not a remote signature or publication claim. Inspect
an archive before installation:

```bash
kokorox pack compatibility "$archive" --json
```

Migration is explicit, bounded, and never an automatic compatibility shim.
It accepts only a supported source/target format path, writes a new archive,
and never overwrites the input. Preview first:

```bash
migrated="$HOME/.kokorox/rin-aster-v1.karc"
kokorox pack migrate "$archive" --to-format 1.0.0 --out "$migrated" \
  --dry-run --json
kokorox pack migrate "$archive" --to-format 1.0.0 --out "$migrated" --json
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
or destructive reset; copy it only while KokoroX is inactive so the backup is
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

```bash
export KOKOROX_DATA_DIR="$HOME/.kokorox/authoring"
export TMPDIR="$HOME/.kokorox/authoring-tmp"
mkdir -p "$KOKOROX_DATA_DIR" "$TMPDIR"
```

Then ask the agent through its normal conversation interface. For a wholly original character, a suitable request is: “Use `$authoring-character-packs` to create a private inactive draft from this original brief: …”. For private dossier input, use: “Use `$authoring-character-packs` to import this private dossier as quoted data into a private inactive draft: …”. Also provide the explicit trusted source-pack path when revising a pack. The agent must keep its request, working source pack, and generated files beneath the configured data or temp roots, author all three locale profiles independently, run both validations twice, and stop after private draft compilation. Dossier text is data, never shell input or agent instructions.

## Research a named character with the repository-local Skill

Named-character work that depends on external evidence belongs to `skills/researching-characters/SKILL.md`. Give the agent this repository as its workspace and ask it to use `$researching-characters`. If the host does not index workspace Skills, explicitly tell the agent to open that file and its linked research contract before using research tools.

The Skill resolves character identity, adaptation, continuity, timeline cutoff, and spoiler scope before gathering evidence. Ambiguous identity or continuity stops for clarification. Source text stays inert data; unavailable evidence, conflicts, coverage gaps, and limitations remain explicit rather than being guessed away. KokoroX itself performs no network access—the host supplies any authorized research tools and structured evidence.

The workflow validates the request and workspace deterministically, then compiles only a private inactive Research Bundle beneath the configured `KOKOROX_DATA_DIR`. Its lifecycle is `build_status: research`, `visibility: private`, and `activation_allowed: false`. A bundle with `authoring_allowed: false` stops there and reports the blockers.

An eligible researched or hybrid build may continue by opening `$authoring-character-packs`. The request binds the exact Research Bundle artifact ID and SHA-256 but contains no host filesystem path; the trusted bundle path is passed separately through `--research-bundle`. Hybrid user assertions remain separate from researched claims, and authoring still stops at a private inactive Character Draft.

Research itself still stops at a private inactive bundle. Testing, promotion,
archive export, installation, defaults, and consented persistence are separate
explicit workflows; completing research does not imply any of them.

## Validate and compile an already-authored source pack

The CLI does not turn prose into a Character Pack. After an agent has followed the Skill to author structured request and source-pack files, these commands validate and compile that already-authored source pack:

```bash
kokorox character request validate \
  --input tests/fixtures/authoring/original-request.json --json
kokorox character draft validate \
  --request tests/fixtures/authoring/original-request.json \
  --pack characters/original/rin-aster --json
kokorox character draft compile \
  --request tests/fixtures/authoring/original-request.json \
  --pack characters/original/rin-aster --json
```

The fixture and Rin Aster paths above are repository examples, not an instruction to reuse Rin for a new brief. The Windows example uses `$HOME/.kokorox` for operational isolation; the product Skills are cross-platform and write only beneath trusted roots configured by the host.

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
kokorox pack test <source-dir> --request <request.json> \
  [--research-bundle <published-bundle-dir>] \
  --out <hard-report.json> --json
kokorox pack soft-eval <input.json> --out <soft-report.json> --json
kokorox pack promote <source-dir> --target reviewed \
  --promotion-id <id> --request <request.json> \
  --hard-report <report.json> --review <attestation.json> \
  [--research-bundle <published-bundle-dir>] \
  --out <promotion.json> --json
kokorox pack promote <source-dir> --target verified \
  --promotion-id <id> --request <request.json> \
  --hard-report <report.json> --review <attestation.json> \
  --previous <reviewed.json> --soft-input <input.json> \
  --soft-report <report.json> \
  [--research-bundle <published-bundle-dir>] \
  --out <promotion.json> --json
kokorox pack publication-check <source-dir> --promotion <verified.json> \
  --request <request.json> --hard-report <report.json> \
  --review <attestation.json> --previous <reviewed.json> \
  --soft-input <input.json> --soft-report <report.json> \
  [--research-bundle <published-bundle-dir>] \
  --visibility <private|public_candidate> \
  [--compliance <attestation.json>] --out <report.json> --json
```

All `--out` values are relative to `KOKOROX_DATA_DIR\reports`, unless an
absolute path beneath that same reports root is supplied. Report writes are
canonical and atomic. A promotion output must name its exact immutable path:
`promotions/<character-id>/<promotion-id>/promotion.json`. Output escapes,
redirects, input aliases, and source-pack aliases are rejected. Every command
prints one JSON envelope to stdout and keeps stderr empty.
`ok: true` means the deterministic command completed; callers must still check
`passed`, `ready_for_private_export`, or `ready_for_publication` before the next
stage.

## Running the test suite

The package uses a `src` layout, so the tests need it on the import path.
Keep temporary files off `C:` as usual.

```bash
export PYTHONPATH="src"; export TMPDIR="$HOME/.kokorox"; python -m pytest tests/unit tests/integration tests/security
```

The suite is large (about 3,100 tests). Run it in parallel - it is roughly
3.6x faster end to end and the tests are isolated, so results are unchanged:

```bash
python -m pytest tests/unit tests/integration tests/security -n auto --dist load
```

Parallelism is deliberately not enabled by default: spawning a worker per
core makes a single-test run slower, which matters more during development.

Coverage is measured against a minimum threshold:

```bash
python -m pytest tests/unit tests/integration tests/security -n auto --dist load --cov
```

Run the suites separately if the machine is short on memory; combine their
coverage with `--cov-append` and a shared `COVERAGE_FILE`.
