# Milestone 6 authoring release verification

## Scope

This evidence verifies only Milestone 6, `authoring-character-packs`. It does not approve Milestones 7-9 or the complete standalone suite.

- Verification date: 2026-08-04 (Asia/Hong_Kong)
- Platform: Windows, PowerShell 7.6.4, Python 3.14.0
- Build base HEAD: `5324281d2ace5fe1306c1cdca195fcd766d3a764`
- Milestone implementation/evidence range before this correction: `5b68452^..5324281`, based on plan commit `5bb48e38a0ebc2c7ea5db065c0230d9c99d3e4fc`
- Correction commit: the commit containing this file, with message `fix: verify authoring release evidence claims`
- Final temporary root: `D:\tmp\kokoroarc-m6-release-20260804-quality2-lf-final`

## Prepared-host prerequisites and isolated directories

These commands assume a prepared host; directory creation alone does not install the toolchain. Prerequisites are Git, PowerShell 7, a supported Python 3.11+ interpreter, and this project with its dev/build/test dependencies installed. From an activated environment, prepare the project dependencies with:

```powershell
python -m pip install -e ".[dev]"
python -c "import build, pytest"
```

Skill metadata verification additionally requires the Skill Creator's `quick_validate.py`. It is an external prerequisite, not repository content and not a canonical user-specific path. The operator supplies its installed path through trusted host configuration:

```powershell
$skillCreatorValidator=$env:KOKOROARC_SKILL_VALIDATOR
if ([string]::IsNullOrWhiteSpace($skillCreatorValidator) -or
    -not (Test-Path -LiteralPath $skillCreatorValidator -PathType Leaf)) {
    throw 'Set KOKOROARC_SKILL_VALIDATOR to the installed Skill Creator quick_validate.py.'
}
```

Run the remaining commands from the repository root. The shell must be allowed to create and read the selected `D:\tmp` root. In a managed sandbox, that may require a user-approved, narrowly scoped escalation for `D:\tmp`; this is a harness permission prerequisite, not a KokoroArc administrator requirement.

The recorded run began by rejecting a reused root and creating every final operational directory explicitly:

```powershell
$releaseRoot='D:\tmp\kokoroarc-m6-release-20260804-quality2-lf-final'
if (Test-Path -LiteralPath $releaseRoot) {
    throw "Release root already exists: $releaseRoot"
}
New-Item -ItemType Directory -Force -Path `
    $releaseRoot, `
    "$releaseRoot\temp", `
    "$releaseRoot\pytest", `
    "$releaseRoot\build-temp", `
    "$releaseRoot\smoke", `
    "$releaseRoot\smoke-data" | Out-Null
```

Use a new unused root name to reproduce the procedure from fresh state. All test, build, CLI, and capture output stays under that root.

## Exact distribution build input

The distribution was not described as a build from an unmodified checkout. Under the current `pyproject.toml`, its repository inputs are `README.md`, `pyproject.toml`, `src/`, and `schemas/`. It was built from base HEAD `5324281d2ace5fe1306c1cdca195fcd766d3a764` plus exactly the final README-only patch. An independent base-to-current-HEAD check over `pyproject.toml`, `src/`, and `schemas/` returned no changed paths, so every non-README distribution input equals the base commit. Skills, Character Packs, tests, plans, and release evidence are not inputs to these wheel/sdist definitions.

At the build boundary, `git diff --name-only` printed exactly:

```text
README.md
```

The build-input identities were:

| Identity | Value |
| --- | --- |
| Base HEAD | `5324281d2ace5fe1306c1cdca195fcd766d3a764` |
| README SHA-256 (`Get-FileHash`) | `EA295EE36843E01074D7D30024AB04CFA3F6948375F09A13D9313BCA0A52132C` |
| README Git blob (`git hash-object`) | `15a3e8285ab7f16c044ff871e1f40be3ab5d3983` |
| README normalized patch SHA-256 | `1FCE8488CDD80D308EDBA0450A1AA89D27A56052CEBAA6465A6A2092F511912B` |

“Normalized patch SHA-256” means SHA-256 over the raw output of `git diff --binary <base> -- README.md` after replacing each CRLF byte pair with LF; no other normalization is applied. Equivalently: replace each CRLF byte pair with LF; no other normalization. These copy/paste commands reconstruct and verify that build source in an isolated local clone:

```powershell
$repoRoot=(Resolve-Path '.').Path
$buildSource="$releaseRoot\build-source"
git clone --quiet --no-hardlinks --no-checkout $repoRoot $buildSource
git -C $buildSource checkout --quiet --detach 5324281d2ace5fe1306c1cdca195fcd766d3a764
Copy-Item -LiteralPath "$repoRoot\README.md" -Destination "$buildSource\README.md"

git -C $buildSource rev-parse HEAD
git -C $buildSource diff --name-only
git -C $buildSource status --short
Get-FileHash -LiteralPath "$buildSource\README.md" -Algorithm SHA256
git -C $buildSource hash-object -- README.md
git -C $buildSource diff --binary 5324281d2ace5fe1306c1cdca195fcd766d3a764 -- README.md
python -c "import hashlib,subprocess; d=subprocess.run(['git','-C',r'$buildSource','diff','--binary','5324281d2ace5fe1306c1cdca195fcd766d3a764','--','README.md'],check=True,stdout=subprocess.PIPE).stdout.replace(b'\r\n',b'\n'); print(hashlib.sha256(d).hexdigest().upper())"
git -C $buildSource diff --exit-code 5324281d2ace5fe1306c1cdca195fcd766d3a764 -- pyproject.toml src schemas
```

The HEAD and hashes matched the table, the name-only output contained only `README.md`, status contained only ` M README.md`, and the explicit non-README distribution-input command exited `0`. This evidence file, the implementation-plan evidence references, and `tests/skills/test_authoring_release_evidence.py` were updated after the build; they are not packaged inputs and were absent from the isolated build-source changes.

## Complete verification

### Runtime, authoring, and evidence suite

```powershell
$env:PYTHONPATH=(Join-Path $repoRoot 'src')
$env:TEMP="$releaseRoot\temp"
$env:TMP=$env:TEMP
python -m pytest -q --basetemp "$releaseRoot\pytest"
```

Exit code: `0`. Result: `1353 passed, 19 skipped`. The 19 expected capability/platform skips comprise 15 symlink or POSIX-symlink-semantics cases, three FIFO cases, and one safe Windows-junction-creation case. There were no failed or errored tests.

### Distribution build and contents

```powershell
$env:TEMP="$releaseRoot\build-temp"
$env:TMP=$env:TEMP
Push-Location $buildSource
try {
    python -m build --outdir "$releaseRoot\dist"
} finally {
    Pop-Location
}
Get-FileHash -LiteralPath "$releaseRoot\dist\kokoroarc-0.0.0.dev0-py3-none-any.whl" -Algorithm SHA256
Get-FileHash -LiteralPath "$releaseRoot\dist\kokoroarc-0.0.0.dev0.tar.gz" -Algorithm SHA256
```

Exit code: `0`. The build ended with `Successfully built kokoroarc-0.0.0.dev0.tar.gz and kokoroarc-0.0.0.dev0-py3-none-any.whl`.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `kokoroarc-0.0.0.dev0-py3-none-any.whl` | 77,148 | `A969E84566EF711463DD76070DE101759F109D7618902FC995691466B03C43A6` |
| `kokoroarc-0.0.0.dev0.tar.gz` | 58,688 | `D67DF8F4AD7EDF5E54CC203BE366B9838A969FEB6488AD3B5763C447447ED207` |

Archive inspection found 44 wheel entries and 60 sdist entries. Both contained all four authoring modules and all three Milestone 6 schemas. The sdist README SHA-256 was `EA295EE36843E01074D7D30024AB04CFA3F6948375F09A13D9313BCA0A52132C`, equal to the identified LF build-input README. `git ls-files --eol README.md` reported `i/lf w/lf`, so a fresh checkout reproduces the same file bytes.

### Skill validation and diff hygiene

```powershell
python $skillCreatorValidator skills/using-kokoroarc
python $skillCreatorValidator skills/authoring-character-packs
git diff --check
```

Both Skill validators exited `0` and printed `Skill is valid!`. The exact `git diff --check` command above exited `0` and reported no bad-whitespace lines. Git also emitted these working-copy conversion warnings on stderr; `git ls-files --eol` reported `i/lf` for all four tracked blobs:

```text
warning: in the working copy of 'README.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'docs/superpowers/plans/2026-08-03-kokoroarc-authoring.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'tests/skills/authoring-release-verification.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'tests/skills/test_authoring_release_evidence.py', LF will be replaced by CRLF the next time Git touches it
```

| Skill artifact | SHA-256 |
| --- | --- |
| `skills/using-kokoroarc/SKILL.md` | `C643503C3CAB5FFA1D7EDDFBF64A1F3650E52AA179F49D47E62EC9400C629AC0` |
| `skills/authoring-character-packs/SKILL.md` | `2C1F141F71A4F7FC2FADC3FF3ACA8870392DD3F8FCFC65C92359DC412C139156` |
| `skills/authoring-character-packs/references/authoring-contract.md` | `93566B8CB353F426B01EC990C5D7F891F7C84A81ADEC5A1E051F10C370F1D705` |
| `skills/authoring-character-packs/agents/openai.yaml` | `A181AF32F27F35BA41A21A4CCF124DF8691178E89FCD71AEE1E1DC0400B8DF47` |

The behavioral campaign recorded in `authoring-character-packs-results.md` is baseline RED `5/6` and Skill-enabled PASS `6/6`. Its evidence test is included in the full-suite result. Structural validation and the campaign do not establish factual truth, canon accuracy, provenance authenticity, or approval for installation or publication.

## Copy/paste auditable CLI smoke

The isolated-directory setup above creates empty `smoke` and `smoke-data` directories. The following complete sequence records two request validations, two draft validations, and one compilation while preserving stdout and stderr separately:

```powershell
$smoke="$releaseRoot\smoke"
$dataRoot="$releaseRoot\smoke-data"
$env:PYTHONPATH=(Join-Path $repoRoot 'src')
$env:KOKOROARC_DATA_DIR=$dataRoot

if ((Get-ChildItem -Force -LiteralPath $smoke).Count -ne 0) { throw 'Smoke capture root is not empty.' }
if ((Get-ChildItem -Force -LiteralPath $dataRoot).Count -ne 0) { throw 'Smoke data root is not empty.' }

python -m kokoroarc.cli character request validate --input tests/fixtures/authoring/original-request.json --json 1> "$smoke\request-1.json" 2> "$smoke\request-1.stderr.txt"
if ($LASTEXITCODE -ne 0) { throw 'request-1 failed' }
python -m kokoroarc.cli character request validate --input tests/fixtures/authoring/original-request.json --json 1> "$smoke\request-2.json" 2> "$smoke\request-2.stderr.txt"
if ($LASTEXITCODE -ne 0) { throw 'request-2 failed' }
python -m kokoroarc.cli character draft validate --request tests/fixtures/authoring/original-request.json --pack characters/original/rin-aster --json 1> "$smoke\draft-1.json" 2> "$smoke\draft-1.stderr.txt"
if ($LASTEXITCODE -ne 0) { throw 'draft-1 failed' }
python -m kokoroarc.cli character draft validate --request tests/fixtures/authoring/original-request.json --pack characters/original/rin-aster --json 1> "$smoke\draft-2.json" 2> "$smoke\draft-2.stderr.txt"
if ($LASTEXITCODE -ne 0) { throw 'draft-2 failed' }
python -m kokoroarc.cli character draft compile --request tests/fixtures/authoring/original-request.json --pack characters/original/rin-aster --json 1> "$smoke\compile.json" 2> "$smoke\compile.stderr.txt"
if ($LASTEXITCODE -ne 0) { throw 'compile failed' }
```

These assertions prove exact output equality, empty stderr, lifecycle constants, three-locale coverage, path confinement, and absence of protected runtime/publication roots:

```powershell
$request1=[IO.File]::ReadAllBytes("$smoke\request-1.json")
$request2=[IO.File]::ReadAllBytes("$smoke\request-2.json")
if (-not [Linq.Enumerable]::SequenceEqual[byte]($request1,$request2)) { throw 'Request outputs differ.' }
$draft1=[IO.File]::ReadAllBytes("$smoke\draft-1.json")
$draft2=[IO.File]::ReadAllBytes("$smoke\draft-2.json")
if (-not [Linq.Enumerable]::SequenceEqual[byte]($draft1,$draft2)) { throw 'Draft outputs differ.' }
Get-ChildItem -LiteralPath $smoke -Filter '*.stderr.txt' | ForEach-Object {
    if ($_.Length -ne 0) { throw "Non-empty stderr: $($_.Name)" }
}

$compiled=Get-Content -LiteralPath "$smoke\compile.json" -Raw | ConvertFrom-Json
if ($compiled.ok -ne $true -or
    $compiled.build_status -ne 'draft' -or
    $compiled.visibility -ne 'private' -or
    $compiled.activation_allowed -ne $false -or
    $compiled.validation_report.valid -ne $true) { throw 'Lifecycle or validation assertion failed.' }
foreach ($locale in 'zh-CN','en-US','ja-JP') {
    if ($compiled.validation_report.locale_coverage.$locale -ne $true) { throw "Missing locale: $locale" }
}

$resolvedData=[IO.Path]::GetFullPath($dataRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
$resolvedDrafts=[IO.Path]::GetFullPath("$resolvedData\drafts").TrimEnd([IO.Path]::DirectorySeparatorChar)+[IO.Path]::DirectorySeparatorChar
$resolvedOutput=[IO.Path]::GetFullPath($compiled.path)
if (-not $resolvedOutput.StartsWith($resolvedDrafts,[StringComparison]::OrdinalIgnoreCase) -or
    -not (Test-Path -LiteralPath $resolvedOutput -PathType Container)) { throw 'Draft path is missing or outside data root/drafts.' }
$top=@(Get-ChildItem -Force -LiteralPath $resolvedData | Select-Object -ExpandProperty Name)
if ($top.Count -ne 1 -or $top[0] -ne 'drafts') { throw "Unexpected data-root entries: $($top -join ',')" }
foreach ($name in 'compiled','installed','public','sessions','state','events') {
    if (Test-Path -LiteralPath (Join-Path $resolvedData $name)) { throw "Forbidden root exists: $name" }
}
```

The three complete representative stdout captures can be hashed directly:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath `
    "$smoke\request-1.json", `
    "$smoke\draft-1.json", `
    "$smoke\compile.json"
```

| Output | Determinism | UTF-8 stdout SHA-256 |
| --- | --- | --- |
| Request validation | two byte-identical complete JSON outputs | `A9DB730C84EF2238D2FDC79D1DDB658B878CAA67922D5082C19E7E005A84EE82` |
| Draft/source-pack validation | two byte-identical complete JSON outputs | `16921F792156A28CA20445A76A91A884AD5F6F48CE0DB37EB89444CB77A84DED` |
| Draft compilation | one successful complete JSON output | `6BE138D815D6B4D97C4104030F848A4AF174F47205F96211EAE335E3C891EEAF` |

The canonical transcript is five UTF-8 records in invocation order joined by one LF. Each record is `<command>|<exit-code>|<complete stdout>`, and each complete stdout retains its terminal LF. This constructs its hash from the captured files rather than from selected fields:

```powershell
$commandLines=@(
    'python -m kokoroarc.cli character request validate --input tests/fixtures/authoring/original-request.json --json',
    'python -m kokoroarc.cli character request validate --input tests/fixtures/authoring/original-request.json --json',
    'python -m kokoroarc.cli character draft validate --request tests/fixtures/authoring/original-request.json --pack characters/original/rin-aster --json',
    'python -m kokoroarc.cli character draft validate --request tests/fixtures/authoring/original-request.json --pack characters/original/rin-aster --json',
    'python -m kokoroarc.cli character draft compile --request tests/fixtures/authoring/original-request.json --pack characters/original/rin-aster --json'
)
$outputFiles=@('request-1.json','request-2.json','draft-1.json','draft-2.json','compile.json')
$utf8=[Text.UTF8Encoding]::new($false)
$records=for($i=0;$i -lt $outputFiles.Count;$i++) {
    $stdout=[IO.File]::ReadAllText((Join-Path $smoke $outputFiles[$i]),$utf8)
    "$($commandLines[$i])|0|$stdout"
}
$canonicalTranscriptBytes=[Text.Encoding]::UTF8.GetBytes([string]::Join("`n",$records))
$canonicalTranscriptHash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($canonicalTranscriptBytes))
$canonicalTranscriptHash
```

Result: `F4307BFD9B42C7B9DA5E78FB284F5E0748AC1BB21EA637A9AB1CBDEBE486AF9C`.

Observed compilation fields:

```text
artifact_id=original/rin-aster/draft/049c8a4dcec7cd71
path=D:\tmp\kokoroarc-m6-release-20260804-quality2-lf-final\smoke-data\drafts\original\rin-aster\draft\049c8a4dcec7cd71
build_status=draft
visibility=private
activation_allowed=false
validation_report.valid=true
locale_coverage=en-US:true,ja-JP:true,zh-CN:true
```

## Acceptance review

| Milestone 6 acceptance criterion | Evidence |
| --- | --- |
| Three authoring schemas validate positive and negative fixtures | Full suite passed; both archives contain all three schemas. |
| Original and dossier requests normalize deterministically | Full suite passed; request smoke outputs are byte-identical; dossier fixture tests are included. |
| Valid input creates a byte-stable private draft bundle | Storage/integration tests passed; smoke compiled the canonical draft identifier. |
| Locale, identity, provenance, unsafe-path, and activation failures close safely | Unit, integration, and security suites passed, subject to the recorded Windows capability skips. |
| Output is confined and lifecycle constants are fixed | Smoke path and lifecycle assertions passed; no protected state was created. |
| Skill metadata validates | Both current Skills validated with exit code 0. |
| Baseline exposes intended gaps | Campaign evidence records baseline RED 5/6 with each claimed gap class bound to a failed assertion. |
| Skill-enabled cases satisfy declared assertions | Campaign evidence records PASS 6/6 with unique fresh threads. |
| Existing runtime remains green | Full suite: 1,353 passed, zero failures/errors. |
| Documentation describes actual authoring entry point | README routes original briefs and private dossiers through the repository-local Skill, then labels the CLI example as validation/compilation of already-authored files. |

## Excluded attempts and limitations

No build or smoke attempt was excluded from the retained `quality2-lf-final` run. The superseded `quality2-final` build used the same Git patch but a mixed-EOL README working file, so it was rejected before commit because a fresh checkout could not reproduce its raw file SHA-256. The earlier `quality-final` evidence recorded one managed-sandbox permission failure and one incorrect smoke-harness assertion. None of those attempts produced or altered the retained artifacts listed here; every iteration used a new root without overwriting or deleting prior material.

The product Skill is cross-platform and resolves a trusted configured data root. `D:\tmp` appears only in this Windows operational evidence. Named external-evidence research remains a missing prerequisite until Milestone 7. Testing/promotion, installation, archive creation, and publication remain outside Milestone 6 and unavailable until later milestones.
