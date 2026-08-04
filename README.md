# KokoroArc

KokoroArc is a multilingual character-persona runtime for AI agents. The initial vertical slice provides a Python CLI, a data-only original Character Pack, deterministic session state, multilingual render planning, structural and protected-output validation, and the `using-kokoroarc` Agent Skill.

The design revision is `0.3.0`; this is not a product version.

## Quick start

KokoroArc activates characters explicitly; installing or discussing a Character Pack does not start a persona session. All compiled packs, sessions, state, and journals follow `KOKOROARC_DATA_DIR`.

```powershell
$env:KOKOROARC_DATA_DIR='D:\tmp\kokoroarc'
python -m pip install --cache-dir D:\tmp\kokoroarc-pip-cache -e ".[dev]"
$compiled = kokoro pack compile characters/original/rin-aster --json | ConvertFrom-Json
kokoro session start --character $compiled.path --session demo --json
kokoro runtime context --session demo --locale zh-CN --scenario debugging --json
```

Use the repository-local `using-kokoroarc` Agent Skill after explicit activation or when the user explicitly asks for a response through a named installed Character Pack. The latter request authorizes activation for the current host session; merely installing or discussing a pack does not.

## Author a private inactive draft

Milestone 6 authoring turns a wholly original brief or a private user dossier into a deterministic Character Draft. The result is always private, inactive, and fixed at `build_status: draft` with `activation_allowed: false`. It is not researched, externally verified, installable, public, or active.

```powershell
$env:KOKOROARC_DATA_DIR='D:\tmp\kokoroarc-authoring'
kokoro character request validate `
  --input tests/fixtures/authoring/original-request.json --json
kokoro character draft validate `
  --request tests/fixtures/authoring/original-request.json `
  --pack characters/original/rin-aster --json
kokoro character draft compile `
  --request tests/fixtures/authoring/original-request.json `
  --pack characters/original/rin-aster --json
```

The Windows example uses `D:\tmp` for operational isolation; the product Skill is cross-platform and writes only beneath the trusted `KOKOROARC_DATA_DIR` configured by the host.

Named-character work that depends on external evidence must route through the planned `researching-characters` Skill. Until Milestone 7 supplies that prerequisite and an evidence bundle, authoring stops and reports the missing prerequisite. Draft testing and promotion, installation, archive creation, and publication remain unavailable until their later milestones.
