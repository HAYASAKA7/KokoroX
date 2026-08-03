# Task 19 release verification

Verified on Windows on 2026-08-03. Temporary test, build, CLI, and evaluator data were placed on `D:`.

## Automated checks

- `python -m pytest tests\skills\test_using_kokoroarc_evidence.py -v`: 11 passed.
- `python -m pytest -v`: 975 passed, 13 skipped in 61.87 seconds; Python reported `tempdir=D:\tmp\kokoroarc-pytest-postreview-20260803`.
- `quick_validate.py skills\using-kokoroarc`: `Skill is valid!`.
- `git diff --check`: passed.

The 13 full-suite skips are the accepted Windows capability exceptions: this account cannot create the required symlinks, the Python standard library has no safe junction-creation API, and the platform has no portable FIFO-creation API. They are capability skips, not failing product assertions.

## Distribution build

`python -m build --outdir D:\tmp\kokoroarc-dist-task19-final-d-20260803` succeeded.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `kokoroarc-0.0.0.dev0-py3-none-any.whl` | 55,692 | `C4CCC2786669298E4E326D24C81CE8F9A0415D19D30F43F56FAD53175DE12950` |
| `kokoroarc-0.0.0.dev0.tar.gz` | 41,537 | `AA68788783985DF88BCF3A1B1D3D47AB50A4D597BA94E64AA54AC768F004A152` |

## CLI smoke test

With `KOKOROARC_DATA_DIR=D:\tmp\kokoroarc-cli-task19-final-d-20260803`:

- compiled `characters\original\rin-aster` successfully;
- source hash was `049c8a4dcec7cd71163b3b4585367ea3644bd3d65cdb9a6aba75ff93849ab463`;
- started active session `verification-s1` successfully;
- loaded `zh-CN` runtime context for the `debugging` scenario successfully.

Fresh concise transcript using `D:\tmp\kokoroarc-cli-transcript-final-20260803`:

```powershell
$compiled = python -m kokoroarc.cli pack compile .\characters\original\rin-aster --json | ConvertFrom-Json
$session = python -m kokoroarc.cli session start --character $compiled.path --session transcript-s1 --json | ConvertFrom-Json
$context = python -m kokoroarc.cli runtime context --session transcript-s1 --locale zh-CN --scenario debugging --json | ConvertFrom-Json
# Project the three success envelopes into one auditable line.
```

```json
{"compile_ok":true,"source_hash":"049c8a4dcec7cd71163b3b4585367ea3644bd3d65cdb9a6aba75ff93849ab463","compiled_path":"D:\\tmp\\kokoroarc-cli-transcript-final-20260803\\compiled\\rin-aster-049c8a4dcec7cd71.json","session_ok":true,"session_id":"transcript-s1","active":true,"context_ok":true,"character_id":"rin-aster","locale":"zh-CN","scenario":"debugging"}
```

## Behavioral result

- No-Skill baseline: 3/6.
- Final Skill campaign: 6/6.
- Twelve unique completed evaluator threads are retained.
- Protected source bytes are host-bound through a value-free byte-range manifest, validated through the runtime, delivered verbatim, and never executed.

## Git handoff

- Branch: `feat/vertical-slice`.
- Full Tasks 1–19 implementation range: `475f75e186a87ffab46564336ac39c9d1723912f..HEAD` (Task 1 begins at `428a97d`).
- Task 19-only range: `e5f2672cbe42..HEAD`.
- The final handoff captures `git status --short --branch` after the commits so the status evidence itself does not dirty the branch.
