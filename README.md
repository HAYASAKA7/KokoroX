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
