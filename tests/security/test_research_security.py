from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import traceback
from types import SimpleNamespace

import pytest

import kokoroarc.research.workspace as research_workspace
from kokoroarc.errors import KokoroError
from kokoroarc.research.workspace import ResearchLimits, load_research_workspace
from kokoroarc.schemas import SchemaRegistry


FIXTURE_ROOT = Path("tests/fixtures/research/complete")


def copied_workspace(tmp_path: Path) -> Path:
    target = tmp_path / "workspace"
    shutil.copytree(FIXTURE_ROOT, target)
    return target


def registry() -> SchemaRegistry:
    return SchemaRegistry(Path("schemas/v1"))


def manifest(path: Path) -> dict[str, object]:
    return json.loads((path / "workspace.json").read_text(encoding="utf-8"))


def write_manifest(path: Path, value: dict[str, object]) -> None:
    (path / "workspace.json").write_text(json.dumps(value), encoding="utf-8")


def assert_safe_error(error: KokoroError, secret: str) -> None:
    rendered = (
        str(error)
        + json.dumps(error.details)
        + json.dumps(error.envelope())
        + "".join(traceback.format_exception(error))
    )
    assert secret not in rendered
    assert not Path(secret).is_absolute() or str(Path(secret)) not in rendered
    assert error.__cause__ is None


def test_manifest_is_validated_before_following_missing_reference(tmp_path: Path) -> None:
    root = copied_workspace(tmp_path)
    value = manifest(root)
    value["unknown_secret_field"] = "SENSITIVE_SOURCE_TEXT"
    write_manifest(root, value)
    (root / "request.json").unlink()

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_INVALID"
    assert_safe_error(raised.value, "SENSITIVE_SOURCE_TEXT")


@pytest.mark.parametrize(
    "contents",
    [b'{"value":NaN}', b'{"value":1,"value":2}', b"\xff"],
)
def test_rejects_non_strict_manifest_json(tmp_path: Path, contents: bytes) -> None:
    root = copied_workspace(tmp_path)
    (root / "workspace.json").write_bytes(contents)

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_INVALID"


def test_rejects_unreferenced_files_without_leaking_name(tmp_path: Path) -> None:
    root = copied_workspace(tmp_path)
    secret = "SENSITIVE_UNREFERENCED_SOURCE.json"
    (root / secret).write_text("{}", encoding="utf-8")

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_UNSAFE"
    assert_safe_error(raised.value, secret)


def test_missing_root_error_suppresses_absolute_os_error_path(tmp_path: Path) -> None:
    secret_root = tmp_path / "SENSITIVE_ABSOLUTE_WORKSPACE_PATH"

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(secret_root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_NOT_FOUND"
    assert_safe_error(raised.value, str(secret_root.resolve()))


def test_rejects_non_directory_workspace_root(tmp_path: Path) -> None:
    root = tmp_path / "workspace.json"
    root.write_text("{}", encoding="utf-8")

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_UNSAFE"


def test_root_disappearance_after_initial_stat_is_changed_and_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = copied_workspace(tmp_path)
    secret = str((tmp_path / "SENSITIVE_DISAPPEARED_ROOT").resolve())

    def disappeared(_path: Path) -> tuple[research_workspace._PathIdentity, ...]:
        raise FileNotFoundError(secret)

    monkeypatch.setattr(research_workspace, "_path_chain_identities", disappeared)

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_CHANGED"
    assert_safe_error(raised.value, secret)


def test_rejects_casefold_duplicate_reference_defensively() -> None:
    value = manifest(FIXTURE_ROOT)
    sources = value["sources"]
    assert isinstance(sources, list)
    duplicate = deepcopy(sources[0])
    assert isinstance(duplicate, dict)
    duplicate["path"] = str(duplicate["path"]).upper()
    sources.append(duplicate)

    with pytest.raises(KokoroError) as raised:
        research_workspace._references(value)

    assert raised.value.code == "RESEARCH_WORKSPACE_UNSAFE"


def test_rejects_symlink_workspace_root_or_skips_with_exact_reason(
    tmp_path: Path,
) -> None:
    target = copied_workspace(tmp_path)
    root = tmp_path / "workspace-link"
    try:
        root.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Symbolic links are unavailable on this platform")

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_UNSAFE"


def test_rejects_symlinked_workspace_parent_or_skips_with_exact_reason(
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    target = copied_workspace(real_parent)
    linked_parent = tmp_path / "linked-parent"
    try:
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except OSError:
        pytest.skip("Symbolic links are unavailable on this platform")

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(linked_parent / target.name, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_UNSAFE"


def test_rejects_manifest_digest_mismatch_without_source_leak(tmp_path: Path) -> None:
    root = copied_workspace(tmp_path)
    (root / "request.json").write_text('{"SENSITIVE_REQUEST_TEXT": true}', encoding="utf-8")

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_DIGEST_MISMATCH"
    assert_safe_error(raised.value, "SENSITIVE_REQUEST_TEXT")


def test_schema_failure_does_not_leak_source_text_in_traceback(tmp_path: Path) -> None:
    root = copied_workspace(tmp_path)
    secret = "SENSITIVE_SCHEMA_SOURCE_TEXT_91C4"
    target = root / "sources" / "source-official-profile.json"
    document = json.loads(target.read_text(encoding="utf-8"))
    document["unknown_source_field"] = secret
    contents = json.dumps(document).encode("utf-8")
    target.write_bytes(contents)
    value = manifest(root)
    sources = value["sources"]
    assert isinstance(sources, list)
    for entry in sources:
        assert isinstance(entry, dict)
        if entry["path"] == "sources/source-official-profile.json":
            entry["sha256"] = sha256(contents).hexdigest()
    write_manifest(root, value)

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_INVALID"
    assert_safe_error(raised.value, secret)


@pytest.mark.parametrize("contents", [b'{"value":NaN}', b'{"value":1,"value":2}', b'\xff'])
def test_rejects_strict_json_after_matching_manifest_digest(
    tmp_path: Path, contents: bytes
) -> None:
    root = copied_workspace(tmp_path)
    target = root / "request.json"
    target.write_bytes(contents)
    value = manifest(root)
    request = value["request"]
    assert isinstance(request, dict)
    request["sha256"] = sha256(contents).hexdigest()
    write_manifest(root, value)

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_INVALID"


def test_rejects_hardlinked_referenced_file(tmp_path: Path) -> None:
    root = copied_workspace(tmp_path)
    target = root / "request.json"
    link = root / "linked-request.json"
    try:
        link.hardlink_to(target)
    except OSError:
        pytest.skip("Hard links are unavailable on this platform")

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_UNSAFE"


def test_rejects_referenced_file_hardlinked_outside_workspace(tmp_path: Path) -> None:
    root = copied_workspace(tmp_path)
    outside = tmp_path / "outside-request.json"
    try:
        outside.hardlink_to(root / "request.json")
    except OSError:
        pytest.skip("Hard links are unavailable on this platform")

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_UNSAFE"


def test_rejects_fifo_or_skips_with_exact_capability_reason(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFOs are unavailable on this platform")
    root = copied_workspace(tmp_path)
    fifo = root / "sources" / "unexpected-fifo.json"
    try:
        os.mkfifo(fifo)
    except (NotImplementedError, OSError):
        pytest.skip("FIFOs are unavailable on this platform")

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_UNSAFE"


def test_rejects_symlinked_referenced_file(tmp_path: Path) -> None:
    root = copied_workspace(tmp_path)
    target = root / "request.json"
    replacement = root / "request-target.json"
    target.replace(replacement)
    try:
        target.symlink_to(replacement.name)
    except OSError:
        pytest.skip("Symbolic links are unavailable on this platform")

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_UNSAFE"


@pytest.mark.parametrize(
    "limits,code,details",
    [
        (
            ResearchLimits(
                max_files=1,
                max_file_bytes=4 * 1024 * 1024,
                max_total_bytes=32 * 1024 * 1024,
            ),
            "RESEARCH_WORKSPACE_LIMIT_EXCEEDED",
            {"limit": "max_files"},
        ),
        (
            ResearchLimits(
                max_files=1024,
                max_file_bytes=1,
                max_total_bytes=32 * 1024 * 1024,
            ),
            "RESEARCH_WORKSPACE_LIMIT_EXCEEDED",
            {"limit": "max_file_bytes"},
        ),
        (
            ResearchLimits(
                max_files=1024,
                max_file_bytes=4 * 1024 * 1024,
                max_total_bytes=1,
            ),
            "RESEARCH_WORKSPACE_LIMIT_EXCEEDED",
            {"limit": "max_total_bytes"},
        ),
    ],
)
def test_enforces_filesystem_limits(
    tmp_path: Path,
    limits: ResearchLimits,
    code: str,
    details: dict[str, str],
) -> None:
    with pytest.raises(KokoroError) as raised:
        load_research_workspace(copied_workspace(tmp_path), registry(), limits)
    assert raised.value.code == code
    assert raised.value.details == details


def test_injection_fixture_is_inert_and_does_not_expand_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = Path("tests/fixtures/research/injection")
    root = tmp_path / "injection"
    shutil.copytree(source, root)
    marker = tmp_path / "must-not-exist"
    outside = tmp_path / "SENSITIVE_OUTSIDE_EVIDENCE"
    outside.write_text("must not be read", encoding="utf-8")
    monkeypatch.setenv("PRIVATE_VALUE", "SENSITIVE_ENVIRONMENT_VALUE")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("inert source invoked subprocess.run"),
    )
    monkeypatch.setattr(
        os,
        "system",
        lambda *_args, **_kwargs: pytest.fail("inert source invoked os.system"),
    )
    real_open = research_workspace.os.open
    opened: list[Path] = []

    def recording_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes], flags: int
    ) -> int:
        opened.append(Path(path).resolve())
        return real_open(path, flags)

    monkeypatch.setattr(research_workspace.os, "open", recording_open)

    loaded = load_research_workspace(root, registry())

    assert not marker.exists()
    serialized = json.dumps(
        {
            "request": loaded.request,
            "sources": loaded.sources,
            "claims": loaded.claims,
        },
        ensure_ascii=False,
    )
    assert "${env:PRIVATE_VALUE}" in serialized
    assert "SENSITIVE_ENVIRONMENT_VALUE" not in serialized
    assert opened
    assert all(path.is_relative_to(root.resolve()) for path in opened)
    assert outside.resolve() not in opened


@pytest.mark.parametrize(
    "candidate",
    [
        "../request.json", "./request.json", "/request.json", "C:request.json",
        "C:/request.json", "//host/request.json", "\\host\\request.json",
        "sources\\source.json", "sources//source.json", "sources/../request.json",
        "sources/con.json", "sources/PRN.txt.json", "sources/aux .json",
        "sources/nul..json", "sources/com1.json", "sources/lpt9.any.json",
        "sources/name:.json", "sources/name .json", "sources/name..json",
        "sources/CONIN$.json", "sources/conout$.json", "sources/name\t.json",
        "sources/name\n.json", "sources/\x00name.json", "",
    ],
)
def test_reference_path_gate_rejects_cross_platform_escape_forms(candidate: str) -> None:
    assert research_workspace._safe_relative_path(candidate) is False


@pytest.mark.parametrize(
    "candidate",
    [
        "request.json",
        "sources/source-01.json",
        "claims/prnish.json",
        "conflicts/com10.json",
        "nested/v1.2/item-name.json",
    ],
)
def test_reference_path_gate_accepts_normalized_benign_paths(candidate: str) -> None:
    assert research_workspace._safe_relative_path(candidate) is True


def test_rejects_duplicate_reference_path_even_when_entries_differ(tmp_path: Path) -> None:
    root = copied_workspace(tmp_path)
    value = manifest(root)
    sources = value["sources"]
    assert isinstance(sources, list)
    duplicate = deepcopy(sources[0])
    assert isinstance(duplicate, dict)
    duplicate["sha256"] = "0" * 64
    sources.append(duplicate)
    write_manifest(root, value)

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_UNSAFE"
    assert raised.value.details == {"reason": "duplicate_reference"}


def test_rejects_directory_reported_as_junction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = copied_workspace(tmp_path)
    marked = root / "sources"
    real_is_junction = getattr(Path, "is_junction", lambda _path: False)

    def injected_junction(path: Path) -> bool:
        return path == marked or bool(real_is_junction(path))

    monkeypatch.setattr(Path, "is_junction", injected_junction, raising=False)

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_UNSAFE"


def test_rejects_real_windows_junction_or_skips_with_exact_reason(
    tmp_path: Path,
) -> None:
    if os.name != "nt" or not hasattr(Path, "is_junction"):
        pytest.skip("Windows junctions are unavailable on this platform")
    root = copied_workspace(tmp_path)
    outside = tmp_path / "outside-sources"
    shutil.move(str(root / "sources"), outside)
    junction = root / "sources"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip("The current account cannot create directory junctions")

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_UNSAFE"


def test_junction_probe_failure_is_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = copied_workspace(tmp_path)
    secret = str((tmp_path / "SENSITIVE_JUNCTION_PROBE_PATH").resolve())

    def denied_probe(_path: Path) -> bool:
        raise OSError(secret)

    monkeypatch.setattr(Path, "is_junction", denied_probe, raising=False)

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_UNSAFE"
    assert_safe_error(raised.value, secret)


def test_file_hash_mapping_is_read_only() -> None:
    loaded = load_research_workspace(FIXTURE_ROOT, registry())
    with pytest.raises(TypeError):
        loaded.file_hashes["request.json"] = "0" * 64  # type: ignore[index]


def test_detects_manifest_change_after_initial_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = copied_workspace(tmp_path)
    real_read = research_workspace._read_regular
    calls = 0

    def mutate_after_manifest(
        read_root: Path, path: Path, limits: ResearchLimits
    ) -> research_workspace._ReadResult:
        nonlocal calls
        result = real_read(read_root, path, limits)
        calls += 1
        if calls == 2:
            (root / "workspace.json").write_text('{"mutated":true}', encoding="utf-8")
        return result

    monkeypatch.setattr(research_workspace, "_read_regular", mutate_after_manifest)
    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())
    assert raised.value.code == "RESEARCH_WORKSPACE_CHANGED"


def test_detects_file_added_after_initial_closed_tree_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = copied_workspace(tmp_path)
    real_canonical_bytes = research_workspace.canonical_bytes
    added = False

    def add_during_final_assembly(value: object) -> bytes:
        nonlocal added
        if not added:
            (root / "late-unreferenced.json").write_text("{}", encoding="utf-8")
            added = True
        return real_canonical_bytes(value)

    monkeypatch.setattr(research_workspace, "canonical_bytes", add_during_final_assembly)

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_CHANGED"


def test_detects_same_content_file_replacement_between_validation_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = copied_workspace(tmp_path)
    real_read = research_workspace._read_regular
    replaced = False

    def replace_after_first_read(
        read_root: Path, path: Path, limits: ResearchLimits
    ) -> research_workspace._ReadResult:
        nonlocal replaced
        result = real_read(read_root, path, limits)
        if path.name == "request.json" and not replaced:
            replacement = root / "replacement-request.json"
            replacement.write_bytes(result.contents)
            os.replace(replacement, root / "request.json")
            replaced = True
        return result

    monkeypatch.setattr(research_workspace, "_read_regular", replace_after_first_read)

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_CHANGED"


def test_detects_file_removal_between_validation_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = copied_workspace(tmp_path)
    real_read = research_workspace._read_regular
    removed = False

    def remove_after_first_read(
        read_root: Path, path: Path, limits: ResearchLimits
    ) -> research_workspace._ReadResult:
        nonlocal removed
        result = real_read(read_root, path, limits)
        if path.name == "request.json" and not removed:
            (root / "request.json").unlink()
            removed = True
        return result

    monkeypatch.setattr(research_workspace, "_read_regular", remove_after_first_read)

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_CHANGED"


def test_detects_ancestor_identity_change_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = copied_workspace(tmp_path)
    real_identities = research_workspace._ancestor_identities
    calls = 0

    def changed_identities(
        read_root: Path, path: Path
    ) -> tuple[research_workspace._StatSnapshot, ...]:
        nonlocal calls
        identities = real_identities(read_root, path)
        if path.name == "workspace.json":
            calls += 1
            if calls == 2:
                return identities + ((-1, -1, -1, -1, -1),)
        return identities

    monkeypatch.setattr(research_workspace, "_ancestor_identities", changed_identities)

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_CHANGED"


def test_detects_open_file_identity_change_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = copied_workspace(tmp_path).resolve()
    real_fstat = research_workspace.os.fstat
    calls = 0

    def changed_fstat(descriptor: int) -> SimpleNamespace | os.stat_result:
        nonlocal calls
        path_stat = real_fstat(descriptor)
        calls += 1
        if calls != 2:
            return path_stat
        return SimpleNamespace(
            st_dev=path_stat.st_dev,
            st_ino=path_stat.st_ino + 1,
            st_mode=path_stat.st_mode,
            st_nlink=path_stat.st_nlink,
            st_size=path_stat.st_size,
            st_mtime_ns=path_stat.st_mtime_ns,
        )

    monkeypatch.setattr(research_workspace.os, "fstat", changed_fstat)

    with pytest.raises(KokoroError) as raised:
        research_workspace._read_regular(
            root, root / "request.json", ResearchLimits()
        )

    assert raised.value.code == "RESEARCH_WORKSPACE_CHANGED"


def test_os_open_failure_is_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = copied_workspace(tmp_path)
    secret = str((tmp_path / "SENSITIVE_OPEN_PATH").resolve())

    def denied_open(*_args: object, **_kwargs: object) -> int:
        raise OSError(secret)

    monkeypatch.setattr(research_workspace.os, "open", denied_open)

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_UNSAFE"
    assert_safe_error(raised.value, secret)


def test_os_close_failure_is_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = copied_workspace(tmp_path)
    secret = str((tmp_path / "SENSITIVE_CLOSE_PATH").resolve())
    real_close = research_workspace.os.close

    def close_then_fail(descriptor: int) -> None:
        real_close(descriptor)
        raise OSError(secret)

    monkeypatch.setattr(research_workspace.os, "close", close_then_fail)

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_CHANGED"
    assert_safe_error(raised.value, secret)


def test_final_tree_scan_failure_is_changed_and_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = copied_workspace(tmp_path)
    real_scan = research_workspace._scan_closed_tree
    secret = str((tmp_path / "SENSITIVE_FINAL_SCAN_PATH").resolve())
    calls = 0

    def fail_final_scan(
        read_root: Path, limits: ResearchLimits
    ) -> dict[str, research_workspace._StatSnapshot]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KokoroError(
                "RESEARCH_WORKSPACE_UNSAFE",
                secret,
                details={"path": secret},
            )
        return real_scan(read_root, limits)

    monkeypatch.setattr(research_workspace, "_scan_closed_tree", fail_final_scan)

    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())

    assert raised.value.code == "RESEARCH_WORKSPACE_CHANGED"
    assert_safe_error(raised.value, secret)


def test_reparse_attribute_is_treated_as_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    reparse_flag = 0x400
    fake_stat = SimpleNamespace(
        st_mode=stat.S_IFREG,
        st_file_attributes=reparse_flag,
    )
    monkeypatch.setattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", reparse_flag)

    assert research_workspace._redirect(Path("logical.json"), fake_stat) is True


def test_rejects_short_read_even_when_stat_size_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = copied_workspace(tmp_path)
    real_read = research_workspace.os.read
    called = False

    def short_read(descriptor: int, size: int) -> bytes:
        nonlocal called
        value = real_read(descriptor, size)
        if not called and value:
            called = True
            return value[:-1]
        return b""

    monkeypatch.setattr(research_workspace.os, "read", short_read)
    with pytest.raises(KokoroError) as raised:
        load_research_workspace(root, registry())
    assert raised.value.code == "RESEARCH_WORKSPACE_CHANGED"
