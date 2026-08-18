# KokoroArc Scoped Character Defaults Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add atomic global/workspace character defaults with deterministic precedence and explicit-only session activation.

**Architecture:** A new `distribution/defaults.py` owns closed default documents, exact installed-release resolution, atomic scoped configuration writes, and pure precedence selection. CLI handlers remain thin: config commands delegate to the domain API, while `session start` either preserves the existing explicit compiled-path flow or resolves a valid default and publishes a verified compiled projection before the explicit session mutation.

**Tech Stack:** Python 3.11+, JSON Schema Draft 2020-12, canonical JSON/SHA-256, standard-library `os.scandir`/locking/fsync/atomic replacement, existing `.karc` registry/archive contracts, argparse, pytest.

---

## Working rules

- Work only in `.worktrees/standalone-suite` on `feat/standalone-suite`.
- Keep every test/build/bytecode temporary under a new unique `D:\tmp` root.
- Use `apply_patch` for source and test edits.
- Run each named RED test before its production change and record the expected
  missing symbol or behavioral failure.
- Never relax the `character-default-config` schema or accept an unverified,
  ambiguous, cross-scope, or stale installation.
- Never call `SessionStore.start` from a config/default domain function.
- Preserve the immutable Milestone 7 evidence subtree.
- Do not mark Task 14 complete or commit the implementation until the exact
  focused, packaging, full-suite, and static gates pass.

## File map

```text
src/kokoroarc/distribution/defaults.py
  Default document storage, exact installation validation, precedence, and
  installed compiled loading/projection support.

src/kokoroarc/distribution/__init__.py
  Stable Task 14 exports.

src/kokoroarc/cli.py
  Config parser/handlers and explicit session-start integration only.

tests/unit/test_character_defaults.py
  Canonical documents, precedence, eligibility, revisions, and idempotency.

tests/integration/test_character_defaults_integration.py
  Global/workspace install/default/start/runtime/remove workflows.

tests/security/test_character_defaults_security.py
  Filesystem, callback, mutation, CAS, resource, cleanup, and confinement cases.

tests/unit/test_cli.py
  Exact parser leaves and sanitized invalid arguments.

tests/integration/test_vertical_slice_cli.py
  Explicit-path compatibility and no implicit activation assertions.

tests/integration/test_research_cli.py
  Wheel/sdist module membership and installed public-import smoke.
```

### Task 1: Define canonical documents and high-priority selection

**Files:**
- Create: `src/kokoroarc/distribution/defaults.py`
- Create: `tests/unit/test_character_defaults.py`

- [x] **Step 1: Write the RED canonical-document and precedence tests**

Create the test helpers and exact cases below. `CharacterSelection.binding`
returns a new detached dictionary on every access so callers cannot mutate the
selection.

```python
from pathlib import Path
from typing import Any

from kokoroarc.distribution.defaults import (
    CharacterSelection,
    empty_character_default,
    resolve_character_selection,
)
from kokoroarc.distribution.registry import InstallScope, resolve_install_scope
from kokoroarc.packs.compiler import canonical_bytes
from kokoroarc.schemas import SchemaRegistry


SCHEMAS = SchemaRegistry(Path("schemas/v1"))


def _binding(name: str) -> dict[str, str]:
    digit = "1" if name == "global" else "2"
    return {
        "installation_id": f"install-{name}",
        "namespace": "original",
        "character_id": f"{name}-character",
        "character_version": "1.0.0",
        "archive_sha256": digit * 64,
        "compiled_sha256": digit * 64,
    }


def test_empty_global_default_is_canonical_and_schema_valid() -> None:
    config = empty_character_default(resolve_install_scope())
    SCHEMAS.validate("character-default-config", config)
    assert config["scope"] == "global"
    assert config["workspace_id"] is None
    assert config["revision"] == 0
    assert config["binding"] is None
    assert config["activation_policy"] == "explicit_only"


def test_explicit_and_session_short_circuit_lower_precedence(
    tmp_path: Path,
) -> None:
    global_binding = _binding("global")
    session_binding = {**global_binding, "installation_id": "install-session"}
    explicit_binding = {**global_binding, "installation_id": "install-explicit"}

    selected = resolve_character_selection(
        tmp_path / "must-not-be-created",
        SCHEMAS,
        explicit_binding=explicit_binding,
        active_session_binding=session_binding,
    )
    assert isinstance(selected, CharacterSelection)
    assert selected.source == "explicit"
    assert selected.binding == explicit_binding
    assert selected.binding is not selected.binding

    assert resolve_character_selection(
        tmp_path / "must-not-be-created",
        SCHEMAS,
        active_session_binding=session_binding,
    ).source == "active_session"
    assert resolve_character_selection(
        tmp_path / "must-not-be-created", SCHEMAS
    ).source == "none"
    assert not (tmp_path / "must-not-be-created").exists()
```

- [x] **Step 2: Run the RED tests**

Run:

```powershell
$env:TMP='D:\tmp'; $env:TEMP='D:\tmp'
$env:PYTHONPATH='src'; $env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest tests/unit/test_character_defaults.py -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-task14-t1-red
```

Expected: collection fails because `kokoroarc.distribution.defaults` does not
exist.

- [x] **Step 3: Implement immutable selection and canonical empty documents**

Create the module with these public types and signatures. Store binding scalar
fields inside the frozen selection rather than retaining a caller dictionary.

```python
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol

from kokoroarc import __version__
from kokoroarc.distribution.registry import InstallScope
from kokoroarc.packs.compiler import canonical_bytes

SelectionSource = Literal[
    "explicit",
    "active_session",
    "workspace_default",
    "global_default",
    "none",
]


class SchemaValidator(Protocol):
    def validate(self, name: str, instance: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class CharacterSelection:
    source: SelectionSource
    installation_id: str | None = None
    namespace: str | None = None
    character_id: str | None = None
    character_version: str | None = None
    archive_sha256: str | None = None
    compiled_sha256: str | None = None

    @property
    def binding(self) -> dict[str, str] | None:
        if self.source == "none":
            return None
        return {
            "installation_id": self.installation_id,
            "namespace": self.namespace,
            "character_id": self.character_id,
            "character_version": self.character_version,
            "archive_sha256": self.archive_sha256,
            "compiled_sha256": self.compiled_sha256,
        }


def empty_character_default(scope: InstallScope) -> dict[str, Any]:
    workspace_id = scope.workspace_id
    if scope.kind == "workspace" and workspace_id is None:
        raise ValueError("workspace scope requires workspace_id")
    suffix = "global" if scope.kind == "global" else workspace_id[:8]
    return {
        "schema_version": "1.0",
        "artifact_id": f"config/{suffix}/character-default",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "scope": scope.kind,
        "workspace_id": scope.workspace_id,
        "revision": 0,
        "binding": None,
        "activation_policy": "explicit_only",
    }


def resolve_character_selection(
    data_root: Path,
    schemas: SchemaValidator,
    *,
    explicit_binding: Mapping[str, Any] | None = None,
    active_session_binding: Mapping[str, Any] | None = None,
    workspace_root: Path | None = None,
) -> CharacterSelection:
    for source, candidate in (
        ("explicit", explicit_binding),
        ("active_session", active_session_binding),
    ):
        if candidate is not None:
            detached = json.loads(canonical_bytes(dict(candidate)))
            return _selection_from_binding(source, detached, schemas)
    return CharacterSelection(source="none")
```

Implement `_selection_from_binding` by validating the exact six keys, scalar
types, and schema-compatible values through a synthetic detached
`character-default-config` document. Invalid candidate input raises
`KARC_DEFAULT_BINDING_INVALID`; it never falls through.
Task 2 extends this same public resolver with workspace/global document reads;
Task 1 deliberately proves that explicit/session choices perform no lower-layer
filesystem access.

- [x] **Step 4: Run Task 1 GREEN**

Run the Step 2 command with basetemp
`D:\tmp\kokoroarc-task14-t1-green`.

Expected: all Task 1 unit tests pass.

### Task 2: Load scoped documents without writes

**Files:**
- Modify: `src/kokoroarc/distribution/defaults.py`
- Modify: `tests/unit/test_character_defaults.py`
- Create: `tests/security/test_character_defaults_security.py`

- [x] **Step 1: Write RED read-only global/workspace tests**

Add exact assertions for absent reads and existing canonical documents:

```python
def _write_config(
    data_root: Path,
    scope: InstallScope,
    config: dict[str, Any],
) -> None:
    relative = (
        Path("config/global.json")
        if scope.kind == "global"
        else Path("config/workspaces") / f"{scope.workspace_id}.json"
    )
    path = data_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(config))


def test_absent_load_is_read_only(tmp_path: Path) -> None:
    data_root = tmp_path / "absent"
    loaded = load_character_default(data_root, SCHEMAS)
    assert loaded == empty_character_default(resolve_install_scope())
    assert not data_root.exists()


def test_workspace_load_uses_canonical_workspace_id(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    scope = resolve_install_scope(workspace)
    config = empty_character_default(scope)
    path = data_root / "config" / "workspaces" / f"{scope.workspace_id}.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(canonical_bytes(config))

    assert load_character_default(
        data_root, SCHEMAS, workspace_root=workspace
    ) == config
    assert list(workspace.iterdir()) == []


```

In the security module, add a callback registry that replaces the config with
identical bytes and restores it, plus workspace/data-root A→B→A probes. Each
must raise `KARC_DEFAULT_INPUT_MUTATION` or `KARC_DEFAULT_PATH_UNSAFE`.

- [x] **Step 2: Run the focused RED read tests**

Run:

```powershell
python -m pytest tests/unit/test_character_defaults.py -k "absent_load or workspace_load" tests/security/test_character_defaults_security.py -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-task14-t2-red
```

Expected: fail because `load_character_default` is absent.

- [x] **Step 3: Implement stable bounded reads**

Add:

```python
def load_character_default(
    data_root: Path,
    schemas: SchemaValidator,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    scope = resolve_install_scope(workspace_root)
    boundary = _capture_default_read_boundary(data_root, scope, workspace_root)
    value = (
        empty_character_default(scope)
        if boundary.payload is None
        else _parse_default(boundary.payload)
    )
    schemas.validate("character-default-config", _detached(value))
    _require_default_read_boundary(boundary)
    _require_scope_document(value, scope)
    return _detached(value)
```

Use a 64 KiB maximum file size, duplicate-key rejecting JSON parsing, retained
file/root/workspace identities, single-link regular files, no redirect
ancestors, detached schema inputs, and sticky per-callback mutation audits.
The absent path retains its nearest existing ancestor so callback-time creation
also fails.

Task 3 extends `resolve_character_selection` after the high-priority short
circuit using real installed releases. Task 2 intentionally does not allow a
schema-valid but unverified binding to become a selection.

- [x] **Step 4: Run Task 2 GREEN and existing registry read regressions**

Run:

```powershell
python -m pytest tests/unit/test_character_defaults.py tests/security/test_character_defaults_security.py tests/unit/test_karc_registry.py -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-task14-t2-green
```

Expected: all runnable tests pass; only genuine filesystem-capability tests may
skip.

### Task 3: Resolve exact eligible installations

**Files:**
- Modify: `src/kokoroarc/distribution/defaults.py`
- Modify: `tests/unit/test_character_defaults.py`
- Create: `tests/integration/test_character_defaults_integration.py`
- Modify: `tests/security/test_character_defaults_security.py`

- [x] **Step 1: Write RED unique/ambiguous/stale eligibility tests**

Use `karc_test_support.build_private_archive`, `install_karc_archive`, and the
real `rin_verified_release` fixture:

```python
def _install_rin(
    release: dict[str, Any],
    data_root: Path,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    archive = build_private_archive(release)
    source = data_root.parent / "rin-aster.karc"
    source.write_bytes(archive)
    return install_karc_archive(
        source,
        data_root,
        SCHEMAS,
        workspace_root=workspace_root,
    )


def test_resolve_unique_installed_binding(
    rin_verified_release: dict[str, Any], tmp_path: Path
) -> None:
    plan = _install_rin(rin_verified_release, tmp_path / "data")
    binding = defaults_module._resolve_installed_binding(
        tmp_path / "data",
        "rin-aster",
        SCHEMAS,
        namespace="original",
    )
    assert binding == {
        "installation_id": plan["installation_id"],
        "namespace": "original",
        "character_id": "rin-aster",
        "character_version": "1.0.0",
        "archive_sha256": plan["archive_sha256"],
        "compiled_sha256": plan["compiled_sha256"],
    }
```

Add exact failures for no match (`KARC_DEFAULT_NOT_INSTALLED`), two matching
versions without `version` (`KARC_DEFAULT_AMBIGUOUS`), explicit version
selection, global/workspace same-scope enforcement, `activation_allowed` drift,
archive/hash replacement, compiled-member replacement, unknown member, and
installed-tree mutation during schema callbacks.

- [x] **Step 2: Run Task 3 RED**

Run:

```powershell
python -m pytest tests/unit/test_character_defaults.py tests/integration/test_character_defaults_integration.py tests/security/test_character_defaults_security.py -k "installed or ambiguous or installation or archive or compiled" -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-task14-t3-red
```

Expected: fail because `_resolve_installed_binding` is absent.

- [x] **Step 3: Implement exact installed-release resolution**

Add the private installation-boundary signature (the approved stable public
surface reaches it through set/resolution and does not export it):

```python
def _resolve_installed_binding(
    data_root: Path,
    character_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    version: str | None = None,
    workspace_root: Path | None = None,
    limits: KarcLimits | None = None,
) -> dict[str, str]:
    effective_limits = KarcLimits() if limits is None else limits
    return _resolve_installed_binding_from_scope(
        _capture_resolver_inputs(
            data_root,
            character_id,
            namespace,
            version,
            workspace_root,
        ),
        schemas,
        effective_limits,
    )
```

Implementation order is fixed:

1. canonicalize and retain scope/data/workspace inputs;
2. load one same-scope registry with `load_installed_registry`;
3. bounded-filter registry identities by exact namespace/character/version;
4. reject zero or ambiguous matches before touching installed bytes;
5. read the archive by recorded digest and validate it with
   `inspect_karc_container` plus `load_karc_archive`;
6. compare the registry entry to the manifest-derived binding;
7. verify every installed manifest member by retained regular-file identity and
   exact bytes, including `pack/compiled.json`;
8. re-audit registry, archive, member tree, workspace, and caller inputs; and
9. return a detached six-field binding.

Use the existing `KarcLimits` archive/member bounds and a direct bounded scan
that stops at manifest member count + 1. Do not import private installer
helpers.

Finally extend `resolve_character_selection` so a present workspace/global
document calls `_resolve_installed_binding` for that same scope and requires the
returned six fields to equal the stored binding before returning it. Any stale
or ineligible present higher layer raises `KARC_DEFAULT_STALE`; only an absent
or null workspace binding may continue to global.

- [x] **Step 4: Run Task 3 GREEN with installer regressions**

Run:

```powershell
python -m pytest tests/unit/test_character_defaults.py tests/integration/test_character_defaults_integration.py tests/security/test_character_defaults_security.py tests/unit/test_karc_installer.py tests/integration/test_karc_installer_integration.py -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-task14-t3-green
```

Expected: all runnable tests pass with only documented link-capability skips.

### Task 4: Atomically set and clear scoped defaults

**Files:**
- Modify: `src/kokoroarc/distribution/defaults.py`
- Modify: `tests/unit/test_character_defaults.py`
- Modify: `tests/integration/test_character_defaults_integration.py`
- Modify: `tests/security/test_character_defaults_security.py`

- [x] **Step 1: Write RED revision/idempotency/CAS tests**

Add this global control and its workspace equivalent:

```python
def test_set_repeat_clear_repeat_has_exact_revisions(
    rin_verified_release: dict[str, Any], tmp_path: Path
) -> None:
    data_root = tmp_path / "data"
    plan = _install_rin(rin_verified_release, data_root)

    first = set_character_default(data_root, "rin-aster", SCHEMAS)
    repeated = set_character_default(data_root, "rin-aster", SCHEMAS)
    cleared = clear_character_default(data_root, SCHEMAS)
    cleared_again = clear_character_default(data_root, SCHEMAS)

    assert first["revision"] == 1
    assert first["binding"]["installation_id"] == plan["installation_id"]
    assert repeated == first
    assert cleared["revision"] == 2
    assert cleared["binding"] is None
    assert cleared_again == cleared
    assert not (data_root / "sessions").exists()
    assert not (data_root / "state").exists()
    assert not (data_root / "events").exists()
```

Security RED cases must cover lock contention, config creation/replacement ABA,
registry mutation after eligibility resolution, caller mutation, config staging
replacement, replace failure, parent-fsync failure, cleanup failure, and
successful/failing outside-root snapshots.

- [x] **Step 2: Run Task 4 RED**

Run:

```powershell
python -m pytest tests/unit/test_character_defaults.py tests/integration/test_character_defaults_integration.py tests/security/test_character_defaults_security.py -k "set or clear or revision or config or lock or cleanup or confinement" -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-task14-t4-red
```

Expected: fail because set/clear APIs are absent.

- [x] **Step 3: Implement one-file CAS publication**

Add exact signatures:

```python
def set_character_default(
    data_root: Path,
    character_id: str,
    schemas: SchemaValidator,
    *,
    namespace: str = "original",
    version: str | None = None,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    return _change_character_default(
        data_root,
        schemas,
        workspace_root=workspace_root,
        requested_character=character_id,
        namespace=namespace,
        version=version,
    )


def clear_character_default(
    data_root: Path,
    schemas: SchemaValidator,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    return _change_character_default(
        data_root,
        schemas,
        workspace_root=workspace_root,
        requested_character=None,
        namespace=None,
        version=None,
    )
```

Under one same-scope lock, capture the current config bytes/revision, resolve
the installation, recheck the expected config and registry snapshots, build a
detached next document, validate it, write a retained same-parent staging file,
fsync it, perform atomic replacement, fsync the parent directory, verify exact
published bytes/identity, and return only after final audits. Same-binding set
and null clear return without writing. Cleanup identity mismatch or persistent
unlink failure raises `KARC_DEFAULT_CLEANUP_FAILED` with bounded `phase` and
`reason`.

- [x] **Step 4: Run Task 4 GREEN and removal-reference controls**

Run:

```powershell
python -m pytest tests/unit/test_character_defaults.py tests/integration/test_character_defaults_integration.py tests/security/test_character_defaults_security.py tests/security/test_karc_installer_security.py -k "default or reference or removal or config or precedence" -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-task14-t4-green
```

Expected: all runnable tests pass; Task 13 removal remains blocked by an exact
default and succeeds after clear.

### Task 5: Add global-first config CLI commands

**Files:**
- Modify: `src/kokoroarc/cli.py`
- Modify: `tests/unit/test_cli.py`
- Modify: `tests/integration/test_character_defaults_integration.py`
- Modify: `tests/security/test_character_defaults_security.py`

- [x] **Step 1: Write RED parser and JSON workflow tests**

Add parser-leaf assertions for:

```python
[
    "config", "default", "set", "--character", "rin-aster", "--json"
]
[
    "config", "default", "set", "--character", "rin-aster",
    "--namespace", "original", "--version", "1.0.0",
    "--scope", "workspace", "--workspace", "D:/workspace", "--json"
]
["config", "default", "show", "--json"]
["config", "default", "clear", "--json"]
```

Use this subprocess helper in the new integration module so every workflow
exercises the public CLI with one isolated data root:

```python
def _run_cli(data_root: Path, *arguments: str) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["KOKOROARC_DATA_DIR"] = str(data_root)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "kokoroarc.cli", *arguments, "--json"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout
    assert completed.stderr == ""
    return json.loads(completed.stdout)
```

Expected leaves include `scope="global"`, `workspace=None`, and optional
namespace/version values. Add subprocess integration that installs Rin, runs
set/show/repeated-set/clear, and asserts canonical JSON, exact revisions, no
stderr, and no session/state/event paths. Invalid global+workspace and missing
workspace-root combinations must return sanitized `ARGUMENT_INVALID` without
echoing the supplied path.

- [x] **Step 2: Run Task 5 RED**

Run:

```powershell
python -m pytest tests/unit/test_cli.py tests/integration/test_character_defaults_integration.py tests/security/test_character_defaults_security.py -k "config_default or cli" -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-task14-t5-red
```

Expected: parser rejects the new command family.

- [x] **Step 3: Implement parser, dispatch, handlers, and public errors**

Add a nested `config default` parser and a `_CONFIG_HANDLERS` dispatch table.
Handlers must only translate argparse values to the domain functions:

```python
def _workspace_argument(args: argparse.Namespace) -> Path | None:
    if args.scope == "workspace":
        if args.workspace is None:
            raise KokoroError("ARGUMENT_INVALID", "Command arguments are invalid.")
        return Path(args.workspace)
    if args.workspace is not None:
        raise KokoroError("ARGUMENT_INVALID", "Command arguments are invalid.")
    return None


def _handle_default_set(args, settings, schemas):
    config = set_character_default(
        settings.data_dir,
        args.character,
        schemas,
        namespace=args.namespace,
        version=args.version,
        workspace_root=_workspace_argument(args),
    )
    return {"ok": True, "default": config, "activates_character": False}
```

Show calls `load_character_default`; clear calls `clear_character_default`.
Extend `_PUBLIC_MESSAGES` for every `KARC_DEFAULT_*` public code with generic
non-sensitive text.

- [x] **Step 4: Run Task 5 GREEN and the complete CLI unit suite**

Run:

```powershell
python -m pytest tests/unit/test_cli.py tests/integration/test_character_defaults_integration.py tests/security/test_character_defaults_security.py -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-task14-t5-green
```

Expected: all runnable tests pass.

### Task 6: Resolve defaults only during explicit session start

**Files:**
- Modify: `src/kokoroarc/distribution/defaults.py`
- Modify: `src/kokoroarc/cli.py`
- Modify: `tests/integration/test_character_defaults_integration.py`
- Verify: `tests/integration/test_vertical_slice_cli.py`
- Modify: `tests/security/test_character_defaults_security.py`

- [x] **Step 1: Write the RED global/workspace/default-start vertical slices**

Add full subprocess flows:

```python
def test_workspace_then_global_default_starts_only_explicit_sessions(
    rin_verified_release: dict[str, Any],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _install_rin(rin_verified_release, data_root)
    _install_rin(
        rin_verified_release,
        data_root,
        workspace_root=workspace,
    )

    global_default = _run_cli(
        data_root,
        "config", "default", "set", "--character", "rin-aster",
    )
    workspace_default = _run_cli(
        data_root,
        "config", "default", "set", "--character", "rin-aster",
        "--scope", "workspace", "--workspace", str(workspace),
    )
    assert global_default["activates_character"] is False
    assert workspace_default["activates_character"] is False
    assert not (data_root / "sessions").exists()

    workspace_session = _run_cli(
        data_root,
        "session", "start", "--session", "s-workspace",
        "--workspace", str(workspace),
    )
    _run_cli(
        data_root,
        "config", "default", "clear",
        "--scope", "workspace", "--workspace", str(workspace),
    )
    global_session = _run_cli(
        data_root, "session", "start", "--session", "s-global",
    )
    workspace_context = _run_cli(
        data_root,
        "runtime", "context", "--session", "s-workspace",
        "--locale", "zh-CN", "--scenario", "debugging",
    )
    global_context = _run_cli(
        data_root,
        "runtime", "context", "--session", "s-global",
        "--locale", "zh-CN", "--scenario", "debugging",
    )
    assert workspace_session["session"]["character_id"] == "rin-aster"
    assert global_session["session"]["character_id"] == "rin-aster"
    assert workspace_context["context"]["character_id"] == "rin-aster"
    assert global_context["context"]["character_id"] == "rin-aster"
```

Add controls that existing explicit `--character <compiled-path>` ignores stale
defaults and remains byte-compatible, no-default omission returns
`KARC_DEFAULT_NOT_CONFIGURED`, set/show/clear/runtime-context/Skill evidence
checks create no session, and a stale workspace binding blocks global fallback.
Security tests mutate installed compiled bytes and projection target at every
schema/write boundary and assert no active session remains.

- [x] **Step 2: Run Task 6 RED**

Run:

```powershell
python -m pytest tests/integration/test_character_defaults_integration.py tests/integration/test_vertical_slice_cli.py tests/security/test_character_defaults_security.py -k "session or runtime or explicit or vertical_slice or projection" -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-task14-t6-red
```

Expected: `session start` still requires `--character`.

- [x] **Step 3: Implement default-backed compiled loading and projection**

Add:

```python
def load_selected_compiled(
    data_root: Path,
    selection: CharacterSelection,
    schemas: SchemaValidator,
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    if selection.source not in {"workspace_default", "global_default"}:
        raise KokoroError(
            "KARC_DEFAULT_SELECTION_INVALID",
            "Character selection cannot load an installed default.",
        )
    return _load_exact_selected_compiled(
        data_root,
        selection,
        schemas,
        workspace_root=workspace_root,
    )
```

It accepts only `workspace_default` or `global_default`, reloads the same-scope
registry/archive/member tree, proves the selection still matches, validates
`pack/compiled.json`, and returns a detached compiled document. Add a private
CLI projection helper that writes canonical bytes to
`compiled/<character>-<source-hash-prefix>.json` with the existing safe target
rules, then reloads the selection and proves the source and projection remain
exact before `SessionStore.start`.

Make `session start --character` optional and add `--workspace`. Handler flow:

```python
if args.character is not None:
    compiled = _validated_compiled(_compiled_file(settings, args.character), schemas)
else:
    selection = resolve_character_selection(
        settings.data_dir,
        schemas,
        workspace_root=Path(args.workspace) if args.workspace else None,
    )
    if selection.source == "none":
        raise KokoroError(
            "KARC_DEFAULT_NOT_CONFIGURED",
            "No character default is configured.",
        )
    compiled = _publish_selected_compiled_projection(
        settings, selection, schemas, args.workspace
    )
session = SessionStore(settings.data_dir).start(
    args.session,
    compiled["character_id"],
    compiled["character_version"],
    compiled["source_hash"],
)
```

`resolve_character_selection` already loads workspace first only when
explicitly supplied, validates a present binding, falls through on
missing/null, then loads global. It never calls `SessionStore`.

- [x] **Step 4: Run Task 6 GREEN plus session/runtime/Skill non-trigger suites**

Run:

```powershell
python -m pytest tests/integration/test_character_defaults_integration.py tests/security/test_character_defaults_security.py tests/integration/test_vertical_slice_cli.py tests/unit/test_session_store.py tests/skills/test_using_kokoroarc_evidence.py -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-task14-t6-green
```

Expected: all runnable tests pass with only documented platform capabilities
skipped; retained Skill evidence stays unchanged.

### Task 7: Public API, packaging, exact closure, and commit

**Files:**
- Modify: `src/kokoroarc/distribution/__init__.py`
- Modify: `tests/integration/test_research_cli.py`
- Modify: `docs/superpowers/plans/2026-08-14-kokoroarc-completion.md`
- Modify: `docs/superpowers/plans/2026-08-18-kokoroarc-scoped-defaults.md`

- [x] **Step 1: Write the RED installed-package smoke**

Extend `REQUIRED_DISTRIBUTION_MODULES` with `defaults.py`. Extend the installed
wheel probe to import and assert callable/type availability for:

```python
from kokoroarc.distribution import (
    CharacterSelection,
    clear_character_default,
    empty_character_default,
    load_character_default,
    load_selected_compiled,
    resolve_character_selection,
    set_character_default,
)
```

Run only
`test_built_archives_and_installed_research_cli_are_complete`; expected RED is
an import failure from `kokoroarc.distribution`.

- [x] **Step 2: Export the stable Task 14 API and run package GREEN**

Import the seven symbols above in `distribution/__init__.py` and add them to
`__all__` in lexical order. Rerun the installed-package test under
`D:\tmp\kokoroarc-task14-package-green`; expected PASS.

- [x] **Step 3: Run focused closure**

Run:

```powershell
$env:TMP='D:\tmp'; $env:TEMP='D:\tmp'
$env:PYTHONPATH='src'; $env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest tests/unit/test_character_defaults.py tests/integration/test_character_defaults_integration.py tests/security/test_character_defaults_security.py tests/unit/test_karc_registry.py tests/unit/test_karc_installer.py tests/integration/test_karc_installer_integration.py tests/security/test_karc_installer_security.py tests/unit/test_cli.py tests/integration/test_vertical_slice_cli.py tests/unit/test_session_store.py -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-task14-focused-final
```

Expected: every runnable test passes; skips name only unavailable filesystem
capabilities.

- [x] **Step 4: Run package smoke and full suite**

Run the installed wheel/sdist smoke with a fresh basetemp, then:

```powershell
python -m pytest -q -p no:cacheprovider --basetemp D:\tmp\kokoroarc-task14-full-final
```

Expected: all runnable tests pass with documented platform/capability skips.

- [x] **Step 5: Perform exact static closure**

Compile every changed Python file with
`PYTHONPYCACHEPREFIX=D:\tmp\kokoroarc-task14-pycache-final`, assert every changed
Python line is at most 88 columns, run `git diff --check`, and verify the dirty
set is exactly:

```text
docs/superpowers/plans/2026-08-14-kokoroarc-completion.md
docs/superpowers/plans/2026-08-18-kokoroarc-scoped-defaults.md
src/kokoroarc/cli.py
src/kokoroarc/distribution/__init__.py
src/kokoroarc/distribution/defaults.py
tests/integration/test_character_defaults_integration.py
tests/integration/test_research_cli.py
tests/security/test_character_defaults_security.py
tests/unit/test_character_defaults.py
tests/unit/test_cli.py
```

- [x] **Step 6: Mark only Task 14 complete and create the implementation commit**

Change the six Task 14 boxes in
`docs/superpowers/plans/2026-08-14-kokoroarc-completion.md` to `[x]`. Mark this
plan's executed steps `[x]`. Stage only the exact Task 14 paths, run
`git diff --cached --check`, inspect `git diff --cached --name-status`, verify
there are no unstaged changes, and commit:

```powershell
git commit -m "feat: resolve scoped character defaults"
```

Expected: a clean `feat/standalone-suite` worktree whose implementation commit
descends from the approved Task 14 design commit `c642180ec09c1363792c6a71248c81be072b5228`.
