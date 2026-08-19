# KokoroArc Skill Suite Installation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the four KokoroArc Skills as one valid skills-only Codex
plugin and provide a deterministic, dry-runnable, atomic installer for explicit
repository or user Skill roots.

**Architecture:** The repository root is the plugin root and keeps the four
authoritative Skills under `skills/`. A new `distribution.suite` module takes a
bounded immutable snapshot of exactly those twelve Skill files, validates the
Skill frontmatter and closed layout from captured bytes, plans an install into
one explicit scope, and publishes missing Skill directories with atomic
no-replace renames. Existing identical installations are unchanged; conflicts,
redirects, mutation, and incomplete transactions fail closed and roll back only
nodes whose identities were retained by this transaction.

**Tech Stack:** Python 3.11+, PyYAML safe duplicate-key parsing, standard-library
filesystem/hash/fsync/locking primitives, pytest, Codex `SKILL.md` directories,
and `.codex-plugin/plugin.json`.

---

## Contract frozen for this task

The authoritative suite contains exactly these Skill directories, in this
order:

1. `using-kokoroarc`
2. `authoring-character-packs`
3. `researching-characters`
4. `testing-character-packs`

Each directory contains exactly:

- `SKILL.md`
- `agents/openai.yaml`
- its named contract beneath `references/`

The public Python surface is:

```python
SKILL_SUITE_NAMES: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class SkillSuiteLimits:
    max_files: int = 12
    max_file_bytes: int = 512 * 1024
    max_total_bytes: int = 2 * 1024 * 1024

def resolve_skill_suite_source(source_root: Path | None = None) -> Path: ...

def preview_skill_suite_install(
    *,
    source_root: Path | None = None,
    scope: Literal["user", "repo"] = "user",
    repo_root: Path | None = None,
    skills_root: Path | None = None,
    limits: SkillSuiteLimits = SkillSuiteLimits(),
) -> dict[str, Any]: ...

def install_skill_suite(
    *,
    source_root: Path | None = None,
    scope: Literal["user", "repo"] = "user",
    repo_root: Path | None = None,
    skills_root: Path | None = None,
    dry_run: bool = False,
    limits: SkillSuiteLimits = SkillSuiteLimits(),
) -> dict[str, Any]: ...
```

The plan/result document is canonical JSON-compatible data with these closed
top-level fields: `artifact_id`, `version`, `scope`, `skills_root`,
`source_tree_sha256`, `skills`, `dry_run`, and `will_write`. Each `skills`
entry records `name`, `source_sha256`, `target`, and `action`, where action is
`install` or `unchanged`. `preview_skill_suite_install` is equivalent to
`install_skill_suite(..., dry_run=True)`.

Scope rules:

- `repo` requires an explicit safe `repo_root`, rejects `skills_root`, and
  targets `<repo_root>/.agents/skills`.
- `user` rejects `repo_root` and targets an explicit `skills_root` when given;
  otherwise it uses `$HOME/.agents/skills` without assuming a drive letter.
- Tests and build probes always supply D:-based roots. No Task 16 test writes
  beneath the real user home.

Stable failure codes are:

- `SKILL_SUITE_SOURCE_INVALID`
- `SKILL_SUITE_LIMIT_EXCEEDED`
- `SKILL_SUITE_SOURCE_CHANGED`
- `SKILL_SUITE_PATH_INVALID`
- `SKILL_SUITE_DESTINATION_CHANGED`
- `SKILL_SUITE_CONFLICT`
- `SKILL_SUITE_INSTALL_FAILED`
- `SKILL_SUITE_CLEANUP_FAILED`
- `SKILL_SUITE_ROLLBACK_FAILED`

## Task 1: Freeze the plugin and source-inventory contract

**Files:**

- Create: `.codex-plugin/plugin.json`
- Create: `tests/unit/test_skill_suite.py`
- Create: `src/kokoroarc/distribution/suite.py`

- [ ] Add a unit test that requires `.codex-plugin/plugin.json` to contain
  `name=kokoroarc`, strict semver `0.1.0`, nonempty description and author,
  `skills=./skills/`, all required interface fields, and no `apps`,
  `mcpServers`, `hooks`, or unknown top-level capability declarations.
- [ ] Add a unit test that enumerates the plugin through its `skills` path and
  requires exactly the four directories and twelve frozen relative files.
- [ ] Add unit tests for `resolve_skill_suite_source`: explicit source root,
  repository checkout discovery, installed `share/kokoroarc/skills`
  discovery, absent source, and ambiguous/incomplete source candidates.
- [ ] Add unit tests for a valid source snapshot and exact deterministic
  `source_tree_sha256`/per-Skill hashes.
- [ ] Run the new tests and record RED because the manifest and module do not
  exist:

```powershell
$env:TEMP='D:\tmp\kokoroarc-task16-red-manifest-01'
$env:TMP=$env:TEMP
python -m pytest tests/unit/test_skill_suite.py -q -p no:cacheprovider
```

- [ ] Use the required plugin scaffolder only in D:-based temporary space to
  obtain a validation-current manifest shape; do not create a marketplace:

```powershell
python C:\Users\cyanl\.codex\skills\.system\plugin-creator\scripts\create_basic_plugin.py kokoroarc --path D:\tmp\kokoroarc-task16-plugin-scaffold-01 --with-skills
```

- [ ] Create the repository manifest with real KokoroArc descriptions,
  skills-only capabilities, and one concise default prompt. Do not add a
  marketplace, connector, MCP server, app, hook, asset, or config mutation.
- [ ] Implement the constants, limits, immutable captured-file/snapshot
  records, installed/source checkout discovery, and canonical result builders
  in `suite.py`.
- [ ] Scan with a bounded iterator before sorting. Require the closed twelve
  file layout, regular no-follow files, no executable bits, no hardlink reuse,
  strict UTF-8, stable lstat/open/fstat/read/lstat identity, and aggregate
  byte/count limits.
- [ ] Parse `SKILL.md` frontmatter from captured bytes with the repository's
  alias-disabled, duplicate-key-rejecting YAML parser. Require exactly one
  opening and closing frontmatter delimiter, matching directory/name,
  nonblank description, and an allowed Skill metadata mapping.
- [ ] Rerun the unit file GREEN.

## Task 2: Plan repo and user installs without mutation

**Files:**

- Modify: `tests/unit/test_skill_suite.py`
- Modify: `src/kokoroarc/distribution/suite.py`

- [ ] Add RED tests for exact repo target resolution, explicit user target,
  mocked user-home default, invalid scope/argument combinations, relative or
  missing repo roots, source/destination overlap, source nested under target,
  and target nested under source.
- [ ] Add RED tests proving preview and `dry_run=True` return byte-equivalent
  documents and create no directory, lock, staging, config, or Skill file.
- [ ] Add RED tests for four missing targets, four identical targets, a mixed
  install/unchanged plan, and one non-identical conflict.
- [ ] Add a guard test that patches `Path.home()` to a D:-based fake home and
  proves only `<fake-home>/.agents/skills` is inspected; also snapshot the real
  home path and assert it is not created, read, or written by test helpers.
- [ ] Run the new planning tests RED.
- [ ] Implement strict scope argument validation and lexical/canonical
  containment without hard-coded profile paths.
- [ ] Validate every existing ancestor no-follow, reject redirects and special
  nodes, capture identities for every existing ancestor, and require the
  destination to be disjoint from the source snapshot.
- [ ] Classify existing Skill targets only after a bounded, byte-exact,
  no-follow scan. Exact captured bytes are `unchanged`; any missing/extra or
  different byte is `SKILL_SUITE_CONFLICT`.
- [ ] Ensure preview never creates the destination hierarchy or a lock and
  never reads host configuration.
- [ ] Rerun planning tests GREEN.

## Task 3: Publish the four Skills atomically and idempotently

**Files:**

- Create: `tests/integration/test_skill_suite_install.py`
- Modify: `src/kokoroarc/distribution/suite.py`
- Modify: `src/kokoroarc/distribution/__init__.py`

- [ ] Add RED integration tests that install all four Skills beneath an
  explicit D:-based user `skills_root` and an explicit repository root.
- [ ] Assert every installed byte equals the source snapshot, results are
  deterministic, staging/lock debris is absent, and no unrelated file changes.
- [ ] Add a RED exact reinstall test that returns four `unchanged` actions and
  performs no replacement or metadata rewrite.
- [ ] Add a RED mixed test where two identical Skills pre-exist and two are
  installed in one transaction.
- [ ] Add a RED conflict test proving no missing Skill is installed when any
  target has non-identical bytes.
- [ ] Run the integration file RED.
- [ ] Add a same-root transaction lock with retained identity and bounded
  acquisition semantics. Create missing `.agents`/`skills` ancestors one level
  at a time, retaining identities and refusing redirects/replacements.
- [ ] Stage every missing Skill as a unique hidden sibling. Write only captured
  source bytes with exclusive create, restrictive regular-file modes, file
  fsync, directory fsync, and a complete byte/identity revalidation.
- [ ] Re-audit source bytes, all captured destination ancestors, all target
  states, and every staging identity before the first publication.
- [ ] Publish each directory with the existing hardened platform-specific
  atomic no-replace rename primitive, translating installer-specific errors to
  the suite error contract.
- [ ] Revalidate each published directory from disk and fsync its parent.
- [ ] Export `SkillSuiteLimits`, `SKILL_SUITE_NAMES`, source resolution,
  preview, and install from `kokoroarc.distribution`.
- [ ] Rerun the integration file GREEN.

## Task 4: Close mutation, path, and rollback failure windows

**Files:**

- Create: `tests/security/test_skill_suite_security.py`
- Modify: `src/kokoroarc/distribution/suite.py`

- [ ] Add RED source cases for unknown file/directory, missing file, wrong
  reference name, malformed/duplicate/aliased frontmatter, name mismatch,
  invalid UTF-8, oversized file/tree, too many entries, executable file,
  symlink, junction, hardlink alias, FIFO/device where supported, and
  scan/read/recheck mutation.
- [ ] Add RED destination cases for traversal/relative ambiguity, unsafe repo
  root, redirect in any existing ancestor, redirected target, hardlinked target
  file, target replacement after planning, and target appearance before
  no-replace rename.
- [ ] Add RED transaction cases for write failure, file/directory fsync failure,
  staged validation failure, first/second/third/fourth publish failure, source
  mutation before cutover, and destination mutation during verification.
- [ ] For every pre-cutover failure assert no Skill was published. For partial
  cutover failure assert all directories created by this transaction are
  removed and every pre-existing identical Skill remains untouched.
- [ ] Add replacement-race cleanup tests. Cleanup must delete only staging or
  published directory identities retained by this transaction; identity loss
  or residual cleanup becomes `SKILL_SUITE_CLEANUP_FAILED` or
  `SKILL_SUITE_ROLLBACK_FAILED`, never recursive deletion of a replacement.
- [ ] Add a lock-contention test and capability-gated Windows junction/POSIX
  symlink and special-file tests with documented skips only.
- [ ] Run the security file RED, implement the smallest identity-bound cleanup
  and rollback logic, then rerun GREEN.

## Task 5: Prove plugin, wheel, sdist, and installed-Skill integrity

**Files:**

- Modify: `tests/integration/test_research_cli.py`
- Modify: `pyproject.toml` only if a RED archive test proves new package-data
  declarations are required
- Test: `.codex-plugin/plugin.json`
- Test: all four `skills/*`

- [ ] Add `suite` to `REQUIRED_DISTRIBUTION_MODULES` and retain the existing
  exact twelve-file wheel/sdist Skill inventory assertions.
- [ ] Add an archive assertion that the sdist carries the plugin manifest at
  `.codex-plugin/plugin.json`; only change package metadata after observing the
  RED result.
- [ ] Extend the installed-wheel probe so repository source is unavailable,
  `resolve_skill_suite_source()` selects installed data, dry-run writes
  nothing, and direct installation into an explicit D:-based root produces all
  twelve exact files.
- [ ] Validate the plugin with the installed official validator:

```powershell
python C:\Users\cyanl\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py .
```

- [ ] Validate each source Skill with the installed official validator:

```powershell
python C:\Users\cyanl\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills/using-kokoroarc
python C:\Users\cyanl\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills/authoring-character-packs
python C:\Users\cyanl\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills/researching-characters
python C:\Users\cyanl\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills/testing-character-packs
```

- [ ] Run the same four validations against an explicit D:-based installed
  Skill root.
- [ ] Build wheel and sdist at a fixed base epoch beneath a fresh D:-based
  output root. Inspect exact module, plugin-manifest, and twelve Skill members;
  install the wheel into a fresh D:-based target and rerun its direct-install
  smoke with repository source unavailable.

## Task 6: Verify, review, record, and commit Task 16

**Files:**

- Modify: `docs/superpowers/plans/2026-08-14-kokoroarc-completion.md`
- Test: all Task 16 files and adjacent distribution/package suites

- [ ] Run the focused Task 16 gate with a unique D:-based temp root:

```powershell
$env:TEMP='D:\tmp\kokoroarc-task16-focused-final-01'
$env:TMP=$env:TEMP
python -m pytest tests/unit/test_skill_suite.py tests/integration/test_skill_suite_install.py tests/security/test_skill_suite_security.py tests/integration/test_research_cli.py -q -p no:cacheprovider
```

- [ ] Run adjacent distribution, packaging, Skill structure, and security
  suites, then the complete repository suite. Record exact counts, durations,
  and capability skips.
- [ ] Run `compileall`, enforce the repository's 88-column bound for changed
  Python files, run `git diff --check`, and confirm no test wrote outside its
  D:-based roots.
- [ ] Obtain a specification review against completion-design section 10 and
  Task 16, followed by a quality/security review of the same frozen tree. Fix
  every Critical or Important finding with a focused RED regression and repeat
  the affected review.
- [ ] Only after exact gates and both reviews pass, mark all Task 16 checkboxes
  in `2026-08-14-kokoroarc-completion.md`. Leave Tasks 17 and 18 unchecked and
  state explicitly that the CLI/docs and complete-suite release remain open.
- [ ] Stage only the Task 16 slice, re-run `git diff --cached --check`, inspect
  the staged name/status inventory, and commit:

```powershell
git commit -m "feat: package the kokoroarc skill suite"
```

- [ ] Verify exact commit/tree/parent, clean status, exact base-to-HEAD diff,
  focused tests, plugin validator, four Skill validators, and installed-wheel
  smoke on the committed tree before reporting Task 16 complete.
