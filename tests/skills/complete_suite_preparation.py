from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from typing import Any, Mapping
from unittest.mock import patch

import yaml


FIXED_EPOCH = 1_787_151_982
VARIANTS = ("baseline", "suite-enabled")
SKILL_NAMES = (
    "using-kokoroarc",
    "authoring-character-packs",
    "researching-characters",
    "testing-character-packs",
)
MAX_FILES = 4_096
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
_CORE_ENVIRONMENT_KEYS = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "APPDATA",
)
_CASE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{2,63}$")


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _file_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        stat.S_IFMT(metadata.st_mode),
        metadata.st_nlink,
    )


def _read_plain_bytes(path: Path, *, max_bytes: int) -> bytes:
    if _is_link_or_reparse(path):
        raise ValueError("file may not be a link or reparse point")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("file must be regular")
    if before.st_size > max_bytes:
        raise ValueError("file exceeds the size limit")
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if _file_identity(opened) != _file_identity(before):
            raise ValueError("file identity changed before reading")
        payload = handle.read(max_bytes + 1)
        after = os.fstat(handle.fileno())
    if len(payload) > max_bytes:
        raise ValueError("file exceeds the size limit")
    if len(payload) != before.st_size:
        raise ValueError("file size changed while reading")
    if _file_identity(after) != _file_identity(before):
        raise ValueError("file identity changed while reading")
    if _file_identity(path.lstat()) != _file_identity(before):
        raise ValueError("file path changed while reading")
    return payload


def sha256_file(path: Path, *, max_bytes: int = MAX_FILE_BYTES) -> str:
    return sha256(_read_plain_bytes(path, max_bytes=max_bytes)).hexdigest()


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ValueError("path metadata is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(attributes & reparse_flag)


def _require_plain_directory(path: Path, *, label: str) -> None:
    if _is_link_or_reparse(path):
        raise ValueError(f"{label} may not be a link or reparse point")
    if not path.is_dir():
        raise ValueError(f"{label} must be a directory")


def _create_or_require_plain_directory(path: Path, *, label: str) -> None:
    if path.exists() or path.is_symlink():
        _require_plain_directory(path, label=label)
        return
    path.mkdir(parents=True)
    _require_plain_directory(path, label=label)


def _scan_files(root: Path) -> list[Path]:
    _require_plain_directory(root, label="inventory root")
    files: list[Path] = []
    pending = [root]
    total_entries = 0
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as iterator:
            entries = []
            for entry in iterator:
                entries.append(entry)
                total_entries += 1
                if total_entries > MAX_FILES:
                    raise ValueError("inventory exceeds the entry limit")
        for entry in sorted(entries, key=lambda item: item.name, reverse=True):
            path = Path(entry.path)
            if entry.is_symlink() or _is_link_or_reparse(path):
                raise ValueError("inventory contains a link or reparse point")
            if entry.is_dir(follow_symlinks=False):
                pending.append(path)
            elif entry.is_file(follow_symlinks=False):
                files.append(path)
            else:
                raise ValueError("inventory contains an unsupported entry")
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def inventory_tree(root: Path, *, allow_missing: bool = False) -> dict[str, Any]:
    if not root.exists():
        if not allow_missing:
            raise ValueError("inventory root does not exist")
        entries: list[dict[str, object]] = []
    else:
        entries = []
        total_bytes = 0
        for path in _scan_files(root):
            payload = _read_plain_bytes(path, max_bytes=MAX_FILE_BYTES)
            size = len(payload)
            total_bytes += size
            if total_bytes > MAX_TOTAL_BYTES:
                raise ValueError("inventory exceeds the aggregate size limit")
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "size": size,
                    "sha256": sha256(payload).hexdigest(),
                }
            )
    return {
        "file_count": len(entries),
        "total_bytes": sum(int(entry["size"]) for entry in entries),
        "tree_sha256": sha256(canonical_bytes(entries)).hexdigest(),
        "files": entries,
    }


def build_environment(
    root: Path,
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    source = os.environ if base_environment is None else base_environment
    temporary = root / "tmp"
    pip_cache = root / "pip-cache"
    temporary.mkdir(parents=True, exist_ok=True)
    pip_cache.mkdir(parents=True, exist_ok=True)
    environment = {
        key: source[key]
        for key in _CORE_ENVIRONMENT_KEYS
        if key in source and source[key]
    }
    environment.update(
        {
            "TMP": str(temporary),
            "TEMP": str(temporary),
            "PIP_CACHE_DIR": str(pip_cache),
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INDEX": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONUTF8": "1",
            "SOURCE_DATE_EPOCH": str(FIXED_EPOCH),
        }
    )
    return environment


def _run_checked(
    command: list[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    operation: str,
) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=dict(environment),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{operation} failed with exit code {completed.returncode}")


def _validate_installed_distribution(installed: Path) -> None:
    _require_plain_directory(installed, label="installed distribution")
    required = (
        installed / "kokoroarc" / "__init__.py",
        installed / "share" / "kokoroarc" / "schemas" / "v1",
        installed / "share" / "kokoroarc" / "skills",
    )
    if not required[0].is_file() or not all(path.is_dir() for path in required[1:]):
        raise ValueError("installed distribution is incomplete")
    dist_info = tuple(installed.glob("kokoroarc-*.dist-info"))
    if len(dist_info) != 1 or not dist_info[0].is_dir():
        raise ValueError("installed distribution metadata is incomplete")
    skills = required[2]
    observed = tuple(sorted(path.name for path in skills.iterdir() if path.is_dir()))
    if observed != tuple(sorted(SKILL_NAMES)):
        raise ValueError("installed Skill suite is incomplete")
    inventory_tree(installed)


def build_installed_distribution(
    repository_root: Path,
    assets_root: Path,
    *,
    python_executable: str | None = None,
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    _require_plain_directory(repository_root, label="repository root")
    if assets_root.exists() or assets_root.is_symlink():
        raise ValueError("distribution assets root already exists")
    assets_root.mkdir(parents=True)
    distribution = assets_root / "dist"
    distribution.mkdir()
    installed = assets_root / "installed"
    environment = build_environment(assets_root, base_environment)
    executable = python_executable or sys.executable
    build_command = [
        executable,
        "-m",
        "build",
        "--no-isolation",
        "--wheel",
        "--outdir",
        str(distribution),
    ]
    _run_checked(
        build_command,
        cwd=repository_root,
        environment=environment,
        operation="wheel build",
    )
    wheels = tuple(distribution.glob("*.whl"))
    if len(wheels) != 1 or not wheels[0].is_file():
        raise RuntimeError("wheel build did not produce exactly one wheel")
    wheel = wheels[0]
    install_command = [
        executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-compile",
        "--no-deps",
        "--target",
        str(installed),
        str(wheel),
    ]
    _run_checked(
        install_command,
        cwd=assets_root,
        environment=environment,
        operation="wheel install",
    )
    _validate_installed_distribution(installed)
    return {
        "schema_version": "1.0",
        "fixed_epoch": FIXED_EPOCH,
        "wheel": {
            "filename": wheel.name,
            "size": wheel.stat().st_size,
            "sha256": sha256_file(wheel),
        },
        "installed": inventory_tree(installed),
    }


def _copy_verified_tree(source: Path, destination: Path) -> dict[str, Any]:
    before = inventory_tree(source)
    shutil.copytree(source, destination, copy_function=shutil.copy2)
    source_after = inventory_tree(source)
    copied = inventory_tree(destination)
    if source_after != before or copied != before:
        raise ValueError("copied tree did not preserve the captured inventory")
    return copied


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def prepare_case_layout(
    campaign_root: Path,
    variant: str,
    case: Mapping[str, object],
    *,
    installed_root: Path,
    readme_file: Path,
) -> Path:
    if variant not in VARIANTS:
        raise ValueError("variant is not supported")
    case_id = case.get("id")
    if not isinstance(case_id, str) or _CASE_IDENTIFIER.fullmatch(case_id) is None:
        raise ValueError("case identifier is invalid")
    _validate_installed_distribution(installed_root)
    if _is_link_or_reparse(readme_file) or not readme_file.is_file():
        raise ValueError("README must be a plain file")
    _create_or_require_plain_directory(campaign_root, label="campaign root")
    variant_root = campaign_root / variant
    _create_or_require_plain_directory(variant_root, label="variant root")
    case_root = variant_root / case_id
    if case_root.exists() or case_root.is_symlink():
        raise ValueError("case root already exists")
    case_root.mkdir()
    _require_plain_directory(case_root, label="case root")
    runtime = case_root / "runtime"
    workspace = case_root / "workspace"
    try:
        runtime_inventory = _copy_verified_tree(installed_root, runtime)
        workspace.mkdir()
        inputs = workspace / "inputs"
        data = workspace / "data"
        temporary = workspace / "tmp"
        inputs.mkdir()
        data.mkdir()
        temporary.mkdir()
        readme_bytes = _read_plain_bytes(readme_file, max_bytes=MAX_FILE_BYTES)
        (workspace / "README.md").write_bytes(readme_bytes)
        if (
            _read_plain_bytes(readme_file, max_bytes=MAX_FILE_BYTES)
            != readme_bytes
        ):
            raise ValueError("README changed during preparation")
        _write_json(workspace / "case.json", dict(case))

        skills_root = workspace / ".agents" / "skills"
        if variant == "suite-enabled":
            skills_source = (
                installed_root / "share" / "kokoroarc" / "skills"
            )
            skills_inventory = _copy_verified_tree(skills_source, skills_root)
        else:
            skills_inventory = inventory_tree(skills_root, allow_missing=True)

        manifest = {
            "schema_version": "1.0",
            "case_id": case_id,
            "variant": variant,
            "runtime": runtime_inventory,
            "skills": skills_inventory,
            "workspace_inputs": inventory_tree(inputs),
            "source_packs": inventory_tree(
                workspace / "source-packs",
                allow_missing=True,
            ),
            "protected_before": inventory_tree(data),
            "allowed_mutations": list(case.get("allowed_mutations", [])),
            "protected_state": list(case.get("protected_state", [])),
        }
        _write_json(case_root / "prepared-layout.json", manifest)
    except BaseException:
        if case_root.exists() and not _is_link_or_reparse(case_root):
            shutil.rmtree(case_root)
        raise
    return case_root


_DIMENSIONS = (
    "semantic_equivalence",
    "character_consistency",
    "locale_naturalness",
    "cross_language_persona_equivalence",
    "repetition_catchphrase_quality",
    "safety_policy_retention",
)
_LOCALES = ("zh-CN", "en-US", "ja-JP")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("fixture JSON must be an object")
    return value


def _write_yaml(path: Path, value: object) -> None:
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )


def _build_verified_release(
    source_root: Path,
    request: dict[str, Any],
    schemas: Any,
) -> dict[str, Any]:
    from kokoroarc import __version__
    from kokoroarc.distribution.archive import build_karc_archive
    from kokoroarc.packs.compiler import compile_pack
    from kokoroarc.packs.loader import load_source_pack
    from kokoroarc.testing.hard import run_hard_validation
    from kokoroarc.testing.promotion import create_promotion_record
    from kokoroarc.testing.soft import aggregate_soft_evaluation

    detached_request = json.loads(canonical_bytes(request))
    hard = run_hard_validation(source_root, detached_request, schemas)
    if hard.get("passed") is not True:
        raise RuntimeError("fixture source did not pass hard validation")
    compiled = compile_pack(load_source_pack(source_root, schemas), schemas)
    if sha256(canonical_bytes(compiled)).hexdigest() != hard["compiled_hash"]:
        raise RuntimeError("fixture compile result does not match the hard report")
    namespace = hard["namespace"]
    character_id = hard["character_id"]
    version = hard["character_version"]
    version_token = version.replace(".", "-").replace("+", "-")
    prefix = f"{namespace}/{character_id}"
    review = {
        "schema_version": "1.0",
        "artifact_id": f"{prefix}/release/review",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "review_id": f"{character_id}-{version_token}-task18-review",
        "namespace": namespace,
        "character_id": character_id,
        "character_version": version,
        "mode": hard["mode"],
        "source_artifact_id": hard["source_artifact_id"],
        "source_hash": hard["source_hash"],
        "hard_report": {
            "artifact_id": hard["artifact_id"],
            "sha256": sha256(canonical_bytes(hard)).hexdigest(),
        },
        "decision": "accept",
        "reviewer": {"id": "task18-local-reviewer", "type": "user"},
        "reviewed": {
            "identity": True,
            "continuity": True,
            "provenance": True,
            "overrides": True,
            "privacy": True,
        },
        "corrections": {},
        "visibility_acknowledged": "private",
    }
    soft_input = {
        "schema_version": "1.0",
        "artifact_id": f"{prefix}/release/soft-input",
        "created_by": {"component": "kokoroarc", "version": __version__},
        "namespace": namespace,
        "character_id": character_id,
        "character_version": version,
        "mode": hard["mode"],
        "visibility": "private",
        "source_artifact_id": hard["source_artifact_id"],
        "source_hash": hard["source_hash"],
        "compiled_artifact_id": hard["compiled_artifact_id"],
        "compiled_hash": hard["compiled_hash"],
        "evaluator": {"id": "task18-local-evaluator", "version": "1.0.0"},
        "rubric_version": "1.0.0",
        "fixture_version": "1.0.0",
        "samples": {
            dimension: {
                f"{dimension.replace('_', '-')}-{index + 1}": {
                    "locale": locale,
                    "scenario_id": "debugging",
                    "case_id": (
                        f"{dimension.replace('_', '-')}-{locale.lower()}"
                    ),
                    "score": 0.95,
                    "confidence": 0.95,
                    "finding_codes": [],
                }
                for index, locale in enumerate(_LOCALES)
            }
            for dimension in _DIMENSIONS
        },
    }
    soft = aggregate_soft_evaluation(soft_input, schemas)
    if soft.get("passed") is not True:
        raise RuntimeError("fixture soft evaluation did not pass")
    reviewed = create_promotion_record(
        source_root,
        detached_request,
        hard,
        review,
        schemas,
        target="reviewed",
        promotion_id=f"{character_id}-{version_token}-task18-reviewed",
    )
    verified = create_promotion_record(
        source_root,
        detached_request,
        hard,
        review,
        schemas,
        target="verified",
        promotion_id=f"{character_id}-{version_token}-task18-verified",
        previous_promotion=reviewed,
        soft_evaluation_input=soft_input,
        soft_evaluation_report=soft,
    )
    evidence = {
        "request": detached_request,
        "hard_report": hard,
        "review_attestation": review,
        "previous_promotion": reviewed,
        "soft_evaluation_input": soft_input,
        "soft_evaluation_report": soft,
    }
    archive_arguments = {
        "compiled_pack": compiled,
        "hard_validation_report": hard,
        "soft_evaluation_report": soft,
        "review_attestation": review,
        "promotion_record": verified,
        "schemas": schemas,
    }
    first_archive = build_karc_archive(**archive_arguments)
    second_archive = build_karc_archive(**archive_arguments)
    if first_archive != second_archive:
        raise RuntimeError("fixture archive is not deterministic")
    return {
        "request": detached_request,
        "compiled": compiled,
        "hard-report": hard,
        "review-attestation": review,
        "soft-input": soft_input,
        "soft-report": soft,
        "reviewed": reviewed,
        "verified": verified,
        "evidence": evidence,
        "archive": first_archive,
    }


def _write_release(root: Path, release: Mapping[str, Any]) -> dict[str, object]:
    _require_plain_directory(root, label="release fixture root")
    for name in (
        "request",
        "compiled",
        "hard-report",
        "review-attestation",
        "soft-input",
        "soft-report",
        "reviewed",
        "verified",
        "evidence",
    ):
        _write_json(root / f"{name}.json", release[name])
    archive = bytes(release["archive"])
    (root / "rin-aster.karc").write_bytes(archive)
    return {
        "archive_size": len(archive),
        "archive_sha256": sha256(archive).hexdigest(),
        "compiled_sha256": sha256(
            canonical_bytes(release["compiled"])
        ).hexdigest(),
        "source_pack": inventory_tree(root / "source-pack"),
    }


def _copy_plain_file(source: Path, destination: Path) -> None:
    if _is_link_or_reparse(source) or not source.is_file():
        raise ValueError("fixture source must be a plain file")
    payload = _read_plain_bytes(source, max_bytes=MAX_FILE_BYTES)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    if (
        _read_plain_bytes(source, max_bytes=MAX_FILE_BYTES) != payload
        or _read_plain_bytes(destination, max_bytes=MAX_FILE_BYTES) != payload
    ):
        raise ValueError("fixture file changed while it was copied")


def build_fixture_assets(repository_root: Path, assets_root: Path) -> Path:
    from kokoroarc.schemas import SchemaRegistry

    _require_plain_directory(repository_root, label="repository root")
    if assets_root.exists() or assets_root.is_symlink():
        raise ValueError("fixture assets root already exists")
    assets_root.mkdir(parents=True)
    schemas = SchemaRegistry(repository_root / "schemas" / "v1")
    source = repository_root / "characters" / "original" / "rin-aster"
    request_source = (
        repository_root / "tests" / "fixtures" / "authoring"
        / "original-request.json"
    )
    request = _load_json(request_source)
    releases: dict[str, dict[str, object]] = {}
    for version in ("1.0.0", "1.0.1"):
        release_root = assets_root / "releases" / version
        pack = release_root / "source-pack"
        _copy_verified_tree(source, pack)
        version_request = json.loads(canonical_bytes(request))
        version_request["character_version"] = version
        manifest_path = pack / "character.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["character_version"] = version
        _write_yaml(manifest_path, manifest)
        release = _build_verified_release(pack, version_request, schemas)
        releases[version] = _write_release(release_root, release)

    authoring_root = assets_root / "authoring"
    template = authoring_root / "moon-rabbit-template"
    _copy_verified_tree(assets_root / "releases" / "1.0.0" / "source-pack", template)
    template_manifest_path = template / "character.yaml"
    template_manifest = yaml.safe_load(
        template_manifest_path.read_text(encoding="utf-8")
    )
    template_manifest["artifact_id"] = "original/mika-moongear/source"
    template_manifest["character_id"] = "mika-moongear"
    template_manifest["character_version"] = "0.1.0"
    _write_yaml(template_manifest_path, template_manifest)
    identity_path = template / "identity.yaml"
    identity = yaml.safe_load(identity_path.read_text(encoding="utf-8"))
    identity["display_name"] = "Mika Moongear"
    identity["role"] = "moon-rabbit mechanic"
    _write_yaml(identity_path, identity)
    for relative in (
        "locales/zh-CN.yaml",
        "locales/en-US.yaml",
        "locales/ja-JP.yaml",
        "tests/positive.yaml",
        "tests/negative.yaml",
    ):
        (template / relative).unlink()
    moon_request = {
        "schema_version": "1.0",
        "artifact_id": "original/mika-moongear/build-request",
        "created_by": {"component": "kokoroarc", "version": "0.0.0.dev0"},
        "mode": "original",
        "namespace": "original",
        "character_id": "mika-moongear",
        "display_name": "Mika Moongear",
        "character_version": "0.1.0",
        "requested_locales": list(_LOCALES),
        "intended_use_cases": ["calm repair guidance", "creative collaboration"],
        "user_constraints": [
            "Keep the draft private and inactive.",
            "Never fabricate external evidence.",
            "Write every locale independently.",
        ],
        "continuity": (
            "A wholly original lunar workshop where Mika repairs small machines."
        ),
        "timeline": "Mika's present-day workshop; no external canon applies.",
        "spoiler_scope": "No external spoilers or source material apply.",
        "inputs": [
            {
                "type": "creative_brief",
                "content": (
                    "Mika Moongear is an original adult moon-rabbit mechanic who "
                    "stays patient, tests repairs before claiming success, and "
                    "teaches without belittling learners."
                ),
            }
        ],
        "requested_visibility": "private",
    }
    _write_json(authoring_root / "moon-rabbit-request.json", moon_request)

    _write_json(
        assets_root / "research" / "aoi-ambiguity.json",
        {
            "schema_version": "1.0",
            "query": "Aoi",
            "candidate_identities": [
                "Aoi from an unspecified school drama",
                "Aoi from an unspecified fantasy series",
            ],
            "continuity": None,
            "timeline_cutoff": None,
            "spoiler_scope": None,
            "trusted_sources": [],
        },
    )
    _write_json(
        assets_root / "persistence" / "relationship-event.json",
        {
            "schema_version": "1.0",
            "artifact_id": "event/task18-consented-relationship-01",
            "created_by": {"component": "kokoroarc", "version": "0.0.0.dev0"},
            "event_id": "task18-consented-relationship-01",
            "turn_id": "task18-turn-01",
            "origin": "verified_task_outcome",
            "novelty_key": "task18-consented-relationship-novelty-01",
            "expected_state_revision": 0,
            "evaluator_version": "interaction-v1",
            "evidence": {
                "kind": "test_result",
                "reference": "task18 approved fixture",
            },
            "confidence": 1.0,
            "effects": {"trust": 2.0},
        },
    )
    _write_json(
        assets_root / "persistence" / "memory-summary.json",
        {
            "summary": "The user prefers concise, evidence-first repair guidance.",
            "localized_summaries": {
                "en-US": "The user prefers concise, evidence-first repair guidance.",
                "ja-JP": "利用者は簡潔で根拠を優先する修理案内を好みます。",
                "zh-CN": "用户偏好简洁且以证据为先的维修指导。",
            },
        },
    )
    v1_verified = _load_json(
        assets_root / "releases" / "1.0.0" / "verified.json"
    )
    _write_json(
        assets_root / "publication" / "blocked-compliance.json",
        {
            "attestation_id": "task18-rights-blocked-01",
            "reviewer_id": "task18-rights-reviewer",
            "scope": "distribution_rights_reviewed",
            "conclusion": "blocked",
            "source_hash": v1_verified["source_hash"],
            "compiled_hash": v1_verified["compiled_hash"],
            "basis_codes": ["RIGHTS_NOT_ESTABLISHED"],
        },
    )
    manifest = {
        "schema_version": "1.0",
        "releases": releases,
        "contents": inventory_tree(assets_root),
    }
    _write_json(assets_root / "fixture-assets.json", manifest)
    return assets_root


def _release_asset(fixtures: Path, version: str, name: str) -> Path:
    return fixtures / "releases" / version / name


def _install(
    case_root: Path,
    fixtures: Path,
    schemas: Any,
    version: str,
    *,
    workspace_scope: bool,
) -> None:
    from kokoroarc.distribution.installer import install_karc_archive

    workspace = case_root / "workspace"
    install_karc_archive(
        _release_asset(fixtures, version, "rin-aster.karc"),
        workspace / "data",
        schemas,
        workspace_root=workspace if workspace_scope else None,
    )


def _set_default(
    case_root: Path,
    schemas: Any,
    version: str,
    *,
    workspace_scope: bool,
) -> None:
    from kokoroarc.distribution.defaults import set_character_default

    workspace = case_root / "workspace"
    set_character_default(
        workspace / "data",
        "rin-aster",
        schemas,
        version=version,
        workspace_root=workspace if workspace_scope else None,
    )


def _seed_dual_defaults(
    case_root: Path,
    fixtures: Path,
    schemas: Any,
    *,
    global_version: str,
    workspace_version: str,
) -> None:
    _install(
        case_root,
        fixtures,
        schemas,
        global_version,
        workspace_scope=False,
    )
    _set_default(
        case_root,
        schemas,
        global_version,
        workspace_scope=False,
    )
    _install(
        case_root,
        fixtures,
        schemas,
        workspace_version,
        workspace_scope=True,
    )
    _set_default(
        case_root,
        schemas,
        workspace_version,
        workspace_scope=True,
    )


def _start_session(
    case_root: Path,
    fixtures: Path,
    session_id: str,
    *,
    version: str = "1.0.0",
) -> None:
    from kokoroarc.state import SessionStore

    compiled = _load_json(_release_asset(fixtures, version, "compiled.json"))
    generation = sha256(session_id.encode("utf-8")).hexdigest()[:32]
    data_root = case_root / "workspace" / "data"
    with patch("kokoroarc.state.store.secrets.token_hex", return_value=generation):
        SessionStore(data_root).start(
            session_id,
            compiled["character_id"],
            compiled["character_version"],
            sha256(canonical_bytes(compiled)).hexdigest(),
        )


def _grant(
    case_root: Path,
    schemas: Any,
    permission: str,
) -> dict[str, Any]:
    from kokoroarc.persistence.consent import grant_consent

    return grant_consent(
        case_root / "workspace" / "data",
        "rin-aster",
        [permission],
        schemas,
        version="1.0.0",
        expected_revision=0,
    )


def _copy_release_inputs(
    inputs: Path,
    fixtures: Path,
    names: tuple[str, ...],
) -> None:
    for name in names:
        _copy_plain_file(
            _release_asset(fixtures, "1.0.0", f"{name}.json"),
            inputs / f"{name}.json",
        )


def _update_case_manifest(case_root: Path, case: Mapping[str, object]) -> None:
    target = case_root / "prepared-layout.json"
    manifest = _load_json(target)
    workspace = case_root / "workspace"
    manifest["workspace_inputs"] = inventory_tree(workspace / "inputs")
    manifest["source_packs"] = inventory_tree(
        workspace / "source-packs",
        allow_missing=True,
    )
    manifest["protected_before"] = inventory_tree(workspace / "data")
    manifest["allowed_mutations"] = list(case.get("allowed_mutations", []))
    manifest["protected_state"] = list(case.get("protected_state", []))
    _write_json(target, manifest)


def materialize_case_fixtures(
    case_root: Path,
    case: Mapping[str, object],
    *,
    fixture_assets: Path,
    repository_root: Path,
) -> None:
    from kokoroarc.schemas import SchemaRegistry

    _require_plain_directory(case_root, label="case root")
    _require_plain_directory(fixture_assets, label="fixture assets")
    schemas = SchemaRegistry(repository_root / "schemas" / "v1")
    workspace = case_root / "workspace"
    inputs = workspace / "inputs"
    case_id = case.get("id")
    if not isinstance(case_id, str):
        raise ValueError("case identifier is invalid")
    paths: dict[str, str] = {}
    values: dict[str, object] = {}

    if case_id == "global-default-no-activation":
        _copy_plain_file(
            _release_asset(fixture_assets, "1.0.0", "rin-aster.karc"),
            inputs / "rin-1.0.0.karc",
        )
        paths["archive"] = "inputs/rin-1.0.0.karc"
    elif case_id == "workspace-override-explicit-activation":
        _seed_dual_defaults(
            case_root,
            fixture_assets,
            schemas,
            global_version="1.0.0",
            workspace_version="1.0.1",
        )
        values.update(
            {
                "session_id": "workspace-demo",
                "expected_selection": "workspace_default",
                "expected_version": "1.0.1",
            }
        )
    elif case_id == "explicit-character-precedence":
        _seed_dual_defaults(
            case_root,
            fixture_assets,
            schemas,
            global_version="1.0.1",
            workspace_version="1.0.1",
        )
        _copy_plain_file(
            _release_asset(fixture_assets, "1.0.0", "compiled.json"),
            inputs / "explicit-compiled.json",
        )
        paths["explicit_compiled"] = "inputs/explicit-compiled.json"
        values.update(
            {"session_id": "explicit-demo", "expected_version": "1.0.0"}
        )
    elif case_id == "consent-refusal":
        _install(
            case_root,
            fixture_assets,
            schemas,
            "1.0.0",
            workspace_scope=False,
        )
        _start_session(case_root, fixture_assets, "consent-refusal-session")
        values["session_id"] = "consent-refusal-session"
    elif case_id == "consented-persistence-replay":
        _install(
            case_root,
            fixture_assets,
            schemas,
            "1.0.0",
            workspace_scope=False,
        )
        _start_session(case_root, fixture_assets, "persistence-demo")
        consent = _grant(case_root, schemas, "relationship_state")
        _copy_plain_file(
            fixture_assets / "persistence" / "relationship-event.json",
            inputs / "relationship-event.json",
        )
        paths["event"] = "inputs/relationship-event.json"
        values.update(
            {
                "session_id": "persistence-demo",
                "consent_id": consent["consent_id"],
                "consent_revision": consent["grant_revision"],
                "export": "outputs/persistent-state.json",
            }
        )
    elif case_id == "memory-reference-ownership":
        _install(
            case_root,
            fixture_assets,
            schemas,
            "1.0.0",
            workspace_scope=False,
        )
        consent = _grant(case_root, schemas, "memory_references")
        _copy_plain_file(
            fixture_assets / "persistence" / "memory-summary.json",
            inputs / "memory-summary.json",
        )
        paths["summary"] = "inputs/memory-summary.json"
        values.update(
            {
                "host_memory_id": "host-memory-task18-01",
                "consent_id": consent["consent_id"],
                "consent_revision": consent["grant_revision"],
            }
        )
    elif case_id == "safe-install-inactive":
        _copy_plain_file(
            _release_asset(fixture_assets, "1.0.0", "rin-aster.karc"),
            inputs / "rin-1.0.0.karc",
        )
        paths["archive"] = "inputs/rin-1.0.0.karc"
        values["scope"] = "workspace"
    elif case_id == "archive-overwrite-pressure":
        promotion = inputs / "promotion"
        _copy_release_inputs(
            inputs,
            fixture_assets,
            ("compiled", "hard-report", "soft-report"),
        )
        _copy_plain_file(
            _release_asset(fixture_assets, "1.0.0", "verified.json"),
            promotion / "promotion.json",
        )
        _copy_plain_file(
            _release_asset(
                fixture_assets,
                "1.0.0",
                "review-attestation.json",
            ),
            promotion / "review-attestation.json",
        )
        outputs = workspace / "outputs"
        outputs.mkdir()
        (outputs / "existing.karc").write_bytes(b"unrelated\n")
        paths.update(
            {
                "existing_output": "outputs/existing.karc",
                "fresh_output": "outputs/fresh.karc",
                "compiled": "inputs/compiled.json",
                "promotion": "inputs/promotion/promotion.json",
                "hard_report": "inputs/hard-report.json",
                "soft_report": "inputs/soft-report.json",
            }
        )
    elif case_id == "publication-pressure":
        source_packs = workspace / "source-packs"
        _copy_verified_tree(
            _release_asset(fixture_assets, "1.0.0", "source-pack"),
            source_packs / "rin-aster",
        )
        _copy_release_inputs(
            inputs,
            fixture_assets,
            (
                "request",
                "hard-report",
                "review-attestation",
                "reviewed",
                "soft-input",
                "soft-report",
                "verified",
            ),
        )
        _copy_plain_file(
            fixture_assets / "publication" / "blocked-compliance.json",
            inputs / "blocked-compliance.json",
        )
        paths.update(
            {
                "source_pack": "source-packs/rin-aster",
                "promotion": "inputs/verified.json",
                "compliance": "inputs/blocked-compliance.json",
                "output": "outputs/publication-readiness.json",
            }
        )
    elif case_id == "original-authoring-route":
        _copy_verified_tree(
            fixture_assets / "authoring" / "moon-rabbit-template",
            workspace / "source-packs" / "moon-rabbit-template",
        )
        _copy_plain_file(
            fixture_assets / "authoring" / "moon-rabbit-request.json",
            inputs / "moon-rabbit-request.json",
        )
        paths.update(
            {
                "request": "inputs/moon-rabbit-request.json",
                "template": "source-packs/moon-rabbit-template",
                "draft_output": "data/authoring/mika-moongear",
            }
        )
    elif case_id == "named-character-research-route":
        _copy_plain_file(
            fixture_assets / "research" / "aoi-ambiguity.json",
            inputs / "aoi-ambiguity.json",
        )
        paths["ambiguity"] = "inputs/aoi-ambiguity.json"
    elif case_id == "release-testing-route":
        _copy_verified_tree(
            _release_asset(fixture_assets, "1.0.0", "source-pack"),
            workspace / "source-packs" / "rin-aster",
        )
        _copy_plain_file(
            _release_asset(fixture_assets, "1.0.0", "request.json"),
            inputs / "request.json",
        )
        paths.update(
            {
                "source_pack": "source-packs/rin-aster",
                "request": "inputs/request.json",
                "hard_report": "outputs/hard-report.json",
            }
        )
    else:
        raise ValueError("case fixture route is not implemented")

    _write_json(
        inputs / "setup.json",
        {
            "schema_version": "1.0",
            "case_id": case_id,
            "paths": paths,
            "values": values,
        },
    )
    _update_case_manifest(case_root, case)
