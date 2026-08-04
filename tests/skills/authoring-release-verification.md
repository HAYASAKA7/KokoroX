# Milestone 6 authoring release verification

## Scope and source identity

This evidence verifies only Milestone 6, `authoring-character-packs`. It does not approve Milestones 7-9 or the complete standalone suite.

- Verification date: 2026-08-04 (Asia/Hong_Kong)
- Platform: Windows, Python 3.14.0
- Verified pre-release HEAD: `598ad0bc1b9d3ed78524d0b58a896b7012d36e73`
- Milestone implementation/evidence range: `5b68452^..598ad0b` (22 commits), based on plan commit `5bb48e38a0ebc2c7ea5db065c0230d9c99d3e4fc`
- Release-evidence commit: the commit containing this file, with message `docs: verify character pack authoring milestone`
- Final temporary root: `D:\tmp\kokoroarc-m6-release-20260804-final`

All commands ran from the repository root with `PYTHONPATH=src`. `TEMP`, `TMP`, pytest `--basetemp`, build output, CLI working storage, and compiled draft output were confined to the final temporary root.

## Complete verification

### Runtime and authoring suite

```powershell
$env:PYTHONPATH='src'
$env:TEMP='D:\tmp\kokoroarc-m6-release-20260804-final\temp'
$env:TMP=$env:TEMP
python -m pytest -q --basetemp 'D:\tmp\kokoroarc-m6-release-20260804-final\pytest'
```

Exit code: `0`. Result: `1348 passed, 19 skipped in 95.84s`.

The 19 expected capability/platform skips comprise 15 symlink or POSIX-symlink-semantics cases, three FIFO cases, and one safe Windows-junction-creation case. They cover the existing vertical-slice, authoring-storage, pack-security, manifest, and session-store capability branches. There were no failed or errored tests.

### Distribution build

```powershell
$env:TEMP='D:\tmp\kokoroarc-m6-release-20260804-final\build-temp'
$env:TMP=$env:TEMP
python -m build --outdir 'D:\tmp\kokoroarc-m6-release-20260804-final\dist'
```

Exit code: `0`. The build log ended with `Successfully built kokoroarc-0.0.0.dev0.tar.gz and kokoroarc-0.0.0.dev0-py3-none-any.whl`.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `kokoroarc-0.0.0.dev0-py3-none-any.whl` | 76,296 | `50407EE62DFE89409CCDA98FA519777548E98171B36A798BAA88AF3335532AAC` |
| `kokoroarc-0.0.0.dev0.tar.gz` | 57,329 | `9B9FE6DB9295A981D6BFDB96356EF6E48151EB2DB05A04928506FE996B498628` |

The build log shows the three Milestone 6 schemas and the `kokoroarc.authoring` package in both built distributions.

### Skill validation

```powershell
python C:/Users/cyanl/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/using-kokoroarc
python C:/Users/cyanl/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/authoring-character-packs
```

Both commands exited `0` and printed `Skill is valid!`.

| Skill artifact | SHA-256 |
| --- | --- |
| `skills/using-kokoroarc/SKILL.md` | `C643503C3CAB5FFA1D7EDDFBF64A1F3650E52AA179F49D47E62EC9400C629AC0` |
| `skills/authoring-character-packs/SKILL.md` | `2C1F141F71A4F7FC2FADC3FF3ACA8870392DD3F8FCFC65C92359DC412C139156` |
| `skills/authoring-character-packs/references/authoring-contract.md` | `93566B8CB353F426B01EC990C5D7F891F7C84A81ADEC5A1E051F10C370F1D705` |
| `skills/authoring-character-packs/agents/openai.yaml` | `A181AF32F27F35BA41A21A4CCF124DF8691178E89FCD71AEE1E1DC0400B8DF47` |

The behavioral campaign recorded in `authoring-character-packs-results.md` is baseline RED `5/6` and Skill-enabled PASS `6/6`. Its evidence test is included in the 1,348-test full-suite result. Structural validation and the campaign do not establish factual truth, canon accuracy, provenance authenticity, or approval for installation or publication.

## Auditable CLI smoke

The final smoke root began empty:

```powershell
$env:KOKOROARC_DATA_DIR='D:\tmp\kokoroarc-m6-release-20260804-final\smoke-data'
python -m kokoroarc.cli character request validate --input tests/fixtures/authoring/original-request.json --json
python -m kokoroarc.cli character request validate --input tests/fixtures/authoring/original-request.json --json
python -m kokoroarc.cli character draft validate --request tests/fixtures/authoring/original-request.json --pack characters/original/rin-aster --json
python -m kokoroarc.cli character draft validate --request tests/fixtures/authoring/original-request.json --pack characters/original/rin-aster --json
python -m kokoroarc.cli character draft compile --request tests/fixtures/authoring/original-request.json --pack characters/original/rin-aster --json
```

All five invocations exited `0` with empty stderr.

| Output | Determinism | UTF-8 stdout SHA-256 |
| --- | --- | --- |
| Request validation | two byte-identical complete JSON outputs | `A9DB730C84EF2238D2FDC79D1DDB658B878CAA67922D5082C19E7E005A84EE82` |
| Draft/source-pack validation | two byte-identical complete JSON outputs | `16921F792156A28CA20445A76A91A884AD5F6F48CE0DB37EB89444CB77A84DED` |
| Draft compilation | one successful output | `DD711A28C2841929BBC99E8AC5580775B613A75ABFC7B010AAB163B59872CA5E` |

The canonical transcript SHA-256 is `DE2DFC090488D401BDEEE071EEBBF4DDE309D4981B16B7B7755385F7382F4CAE`. It hashes five UTF-8 records in invocation order, joined by one LF; each record is `<command>|<exit-code>|<complete stdout>`, and each stdout retains its terminal LF.

Observed compilation fields:

```text
artifact_id=original/rin-aster/draft/049c8a4dcec7cd71
path=D:\tmp\kokoroarc-m6-release-20260804-final\smoke-data\drafts\original\rin-aster\draft\049c8a4dcec7cd71
build_status=draft
visibility=private
activation_allowed=false
validation_report.valid=true
locale_coverage=en-US:true,ja-JP:true,zh-CN:true
```

The resolved output path was beneath the configured data root and existed as a directory. Before compilation the data root was empty; afterward its only top-level entry was `drafts`. Assertions confirmed that `compiled`, `installed`, `public`, `sessions`, `state`, and `events` did not exist.

## Acceptance review

| Milestone 6 acceptance criterion | Evidence |
| --- | --- |
| Three authoring schemas validate positive and negative fixtures | Full suite passed; built artifacts contain all three schemas. |
| Original and dossier requests normalize deterministically | Full suite passed; request smoke outputs are byte-identical; dossier fixture tests are included. |
| Valid input creates a byte-stable private draft bundle | Storage/integration tests passed; smoke compiled the canonical draft identifier. |
| Locale, identity, provenance, unsafe-path, and activation failures close safely | Unit, integration, and security suites passed, subject to the recorded Windows capability skips. |
| Output is confined and lifecycle constants are fixed | Smoke path and lifecycle assertions passed; no protected state was created. |
| Skill metadata validates | Both current Skills validated with exit code 0. |
| Baseline exposes intended gaps | Campaign evidence records baseline RED 5/6 with each claimed gap class bound to a failed assertion. |
| Skill-enabled cases satisfy declared assertions | Campaign evidence records PASS 6/6 with unique fresh threads. |
| Existing runtime remains green | Full suite: 1,348 passed, zero failures/errors. |
| Documentation states the draft boundary | README states private/inactive/draft and not researched, verified, installed, public, or active. |

## Excluded attempts and limitations

An initial full-suite attempt used an unprivileged shell that could not create its requested `D:\tmp` parent. It produced 458 `tmp_path` setup errors and was excluded as an environment-path failure. The fresh elevated rerun and the final from-current-tree run both passed with the counts above.

An earlier smoke harness compared the locale-coverage object as though it were an array. All product commands and lifecycle assertions in that attempt succeeded, but the harness exited `1`; it was excluded and replaced in a fresh data root by the schema-correct object-key assertion recorded above.

The product Skill is cross-platform and resolves a trusted configured data root. `D:\tmp` appears only in this Windows operational evidence. Named external-evidence research remains a missing prerequisite until Milestone 7. Testing/promotion, installation, archive creation, and publication remain outside Milestone 6 and unavailable until later milestones.
