from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import errno
from pathlib import Path
from threading import Barrier, Lock
from typing import Any

import pytest

from kokoroarc.errors import KokoroError
from kokoroarc.packs import compiler
from kokoroarc.packs.compiler import canonical_bytes, write_compiled_pack


def temp_files(directory: Path) -> list[Path]:
    return list(directory.glob("*.tmp"))


def test_compiled_pack_is_written_as_canonical_json_with_one_lf(tmp_path: Path) -> None:
    target = tmp_path / "compiled" / "rin.json"

    write_compiled_pack({"z": "日本語😀", "a": [2, 1]}, target)

    assert target.read_bytes() == canonical_bytes(
        {"z": "日本語😀", "a": [2, 1]}
    ) + b"\n"
    assert temp_files(target.parent) == []


def test_writer_creates_nested_parents_and_replaces_an_existing_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "nested" / "compiled" / "rin.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old-complete-document\n")

    write_compiled_pack({"new": True}, target)

    assert target.read_bytes() == b'{"new":true}\n'
    assert temp_files(target.parent) == []


def test_writer_flushes_and_fsyncs_a_closed_staging_file_before_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "compiled.json"
    events: list[str] = []
    real_named_temporary_file = compiler.tempfile.NamedTemporaryFile
    real_fsync = compiler.os.fsync
    real_replace = compiler.os.replace

    class ObservedFile:
        def __init__(self, handle: Any) -> None:
            self._handle = handle
            self.name = handle.name

        @property
        def closed(self) -> bool:
            return bool(self._handle.closed)

        def write(self, payload: bytes) -> int:
            events.append("write")
            return int(self._handle.write(payload))

        def flush(self) -> None:
            events.append("flush")
            self._handle.flush()

        def fileno(self) -> int:
            return int(self._handle.fileno())

        def close(self) -> None:
            events.append("close")
            self._handle.close()

    def observed_tempfile(*args: Any, **kwargs: Any) -> ObservedFile:
        return ObservedFile(real_named_temporary_file(*args, **kwargs))

    def observed_fsync(fd: int) -> None:
        events.append("fsync")
        real_fsync(fd)

    def observed_replace(source: str | Path, destination: str | Path) -> None:
        assert Path(source).parent == target.parent
        assert Path(source).suffix == ".tmp"
        events.append("replace")
        real_replace(source, destination)

    monkeypatch.setattr(compiler.tempfile, "NamedTemporaryFile", observed_tempfile)
    monkeypatch.setattr(compiler.os, "fsync", observed_fsync)
    monkeypatch.setattr(compiler.os, "replace", observed_replace)

    write_compiled_pack({"value": 1}, target)

    assert events == ["write", "flush", "fsync", "close", "replace"]


def test_each_call_uses_a_unique_same_directory_staging_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "compiled.json"
    staging_paths: list[Path] = []
    real_replace = compiler.os.replace

    def capture_replace(source: str | Path, destination: str | Path) -> None:
        staging_paths.append(Path(source))
        real_replace(source, destination)

    monkeypatch.setattr(compiler.os, "replace", capture_replace)

    write_compiled_pack({"value": 1}, target)
    write_compiled_pack({"value": 2}, target)

    assert len(set(staging_paths)) == 2
    assert all(path.parent == target.parent for path in staging_paths)
    assert all(path.suffix == ".tmp" for path in staging_paths)
    assert temp_files(target.parent) == []


def test_canonical_failure_does_not_create_parent_target_or_staging(
    tmp_path: Path,
) -> None:
    target = tmp_path / "not-created" / "compiled.json"

    with pytest.raises(KokoroError) as raised:
        write_compiled_pack({"invalid": object()}, target)

    assert raised.value.code == "INVALID_PACK_DATA"
    assert not target.parent.exists()


class FailingFile:
    def __init__(
        self,
        handle: Any,
        expected: OSError,
        operation: str,
    ) -> None:
        self._handle = handle
        self._expected = expected
        self._operation = operation
        self.name = handle.name

    @property
    def closed(self) -> bool:
        return bool(self._handle.closed)

    def write(self, payload: bytes) -> int:
        if self._operation == "write":
            raise self._expected
        return int(self._handle.write(payload))

    def flush(self) -> None:
        if self._operation == "flush":
            raise self._expected
        self._handle.flush()

    def fileno(self) -> int:
        return int(self._handle.fileno())

    def close(self) -> None:
        self._handle.close()
        if self._operation == "close":
            raise self._expected


@pytest.mark.parametrize("operation", ["write", "flush", "close"])
def test_file_operation_failure_cleans_staging_and_preserves_existing_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    target = tmp_path / "compiled.json"
    target.write_bytes(b"existing\n")
    expected = OSError(f"{operation} failed")
    real_named_temporary_file = compiler.tempfile.NamedTemporaryFile

    def failing_tempfile(*args: Any, **kwargs: Any) -> FailingFile:
        return FailingFile(
            real_named_temporary_file(*args, **kwargs), expected, operation
        )

    monkeypatch.setattr(compiler.tempfile, "NamedTemporaryFile", failing_tempfile)

    with pytest.raises(OSError) as raised:
        write_compiled_pack({"new": True}, target)

    assert raised.value is expected
    assert target.read_bytes() == b"existing\n"
    assert temp_files(tmp_path) == []


@pytest.mark.parametrize("operation", ["fsync", "replace"])
def test_os_failure_cleans_staging_and_preserves_existing_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    target = tmp_path / "compiled.json"
    target.write_bytes(b"existing\n")
    expected = OSError(f"{operation} failed")

    if operation == "fsync":
        monkeypatch.setattr(compiler.os, "fsync", lambda _fd: (_ for _ in ()).throw(expected))
    else:
        monkeypatch.setattr(
            compiler.os,
            "replace",
            lambda _source, _target: (_ for _ in ()).throw(expected),
        )

    with pytest.raises(OSError) as raised:
        write_compiled_pack({"new": True}, target)

    assert raised.value is expected
    assert target.read_bytes() == b"existing\n"
    assert temp_files(tmp_path) == []


@pytest.mark.parametrize("winerror", [5, 32])
def test_transient_permission_error_is_retried_until_replace_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, winerror: int
) -> None:
    target = tmp_path / "compiled.json"
    attempts = 0
    sleeps: list[float] = []
    expected = PermissionError(f"transient WinError {winerror}")
    expected.winerror = winerror  # type: ignore[attr-defined]
    real_replace = compiler.os.replace

    def transient_replace(source: str | Path, destination: str | Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise expected
        real_replace(source, destination)

    monkeypatch.setattr(compiler, "_REPLACE_OS_NAME", "nt", raising=False)
    monkeypatch.setattr(compiler.os, "replace", transient_replace)
    monkeypatch.setattr(compiler.time, "sleep", sleeps.append)

    write_compiled_pack({"complete": True}, target)

    assert attempts == 3
    assert sleeps == [0.0, 0.001]
    assert target.read_bytes() == b'{"complete":true}\n'
    assert temp_files(tmp_path) == []


def test_permanent_permission_error_exhausts_retries_and_reraises_latest_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "compiled.json"
    target.write_bytes(b"existing\n")
    errors: list[PermissionError] = []
    sleeps: list[float] = []

    def permanent_replace(_source: str | Path, _destination: str | Path) -> None:
        error = PermissionError(f"attempt {len(errors) + 1}")
        error.winerror = 5  # type: ignore[attr-defined]
        errors.append(error)
        raise error

    monkeypatch.setattr(compiler, "_REPLACE_OS_NAME", "nt", raising=False)
    monkeypatch.setattr(compiler.os, "replace", permanent_replace)
    monkeypatch.setattr(compiler.time, "sleep", sleeps.append)

    with pytest.raises(PermissionError) as raised:
        write_compiled_pack({"new": True}, target)

    assert len(errors) == 5
    assert sleeps == [0.0, 0.001, 0.002, 0.004]
    assert raised.value is errors[-1]
    assert target.read_bytes() == b"existing\n"
    assert temp_files(tmp_path) == []


def test_non_permission_replace_error_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "compiled.json"
    expected = OSError("replace failed")
    attempts = 0
    sleeps: list[float] = []

    def fail_replace(_source: str | Path, _destination: str | Path) -> None:
        nonlocal attempts
        attempts += 1
        raise expected

    monkeypatch.setattr(compiler.os, "replace", fail_replace)
    monkeypatch.setattr(compiler.time, "sleep", sleeps.append)

    with pytest.raises(OSError) as raised:
        write_compiled_pack({"new": True}, target)

    assert attempts == 1
    assert sleeps == []
    assert raised.value is expected
    assert temp_files(tmp_path) == []


@pytest.mark.parametrize("winerror", [5, 32])
def test_transient_replace_classifier_accepts_allowed_windows_codes(
    monkeypatch: pytest.MonkeyPatch, winerror: int
) -> None:
    error = PermissionError(f"WinError {winerror}")
    error.winerror = winerror  # type: ignore[attr-defined]
    monkeypatch.setattr(compiler, "_REPLACE_OS_NAME", "nt", raising=False)

    assert compiler._is_transient_replace_error(error) is True


@pytest.mark.parametrize(
    ("platform", "winerror", "posix_errno"),
    [
        ("nt", None, None),
        ("nt", 1, None),
        ("nt", 33, None),
        ("posix", 5, None),
        ("posix", 32, None),
        ("posix", None, errno.EACCES),
        ("posix", None, errno.EPERM),
    ],
)
def test_non_transient_permission_error_is_not_retried_or_slept(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    winerror: int | None,
    posix_errno: int | None,
) -> None:
    expected = (
        PermissionError(posix_errno, "permission denied")
        if posix_errno is not None
        else PermissionError("permission denied")
    )
    if winerror is not None:
        expected.winerror = winerror  # type: ignore[attr-defined]
    attempts = 0
    sleeps: list[float] = []

    def fail_replace(_source: str | Path, _destination: str | Path) -> None:
        nonlocal attempts
        attempts += 1
        raise expected

    monkeypatch.setattr(compiler, "_REPLACE_OS_NAME", platform, raising=False)
    monkeypatch.setattr(compiler.os, "replace", fail_replace)
    monkeypatch.setattr(compiler.time, "sleep", sleeps.append)

    with pytest.raises(PermissionError) as raised:
        compiler._replace_atomically(Path("staging.tmp"), Path("target.json"))

    assert attempts == 1
    assert sleeps == []
    assert raised.value is expected


class CleanupAbort(BaseException):
    pass


@pytest.mark.parametrize(
    "cleanup_error",
    [
        OSError("cleanup failed"),
        RuntimeError("cleanup failed"),
        CleanupAbort("cleanup failed"),
    ],
    ids=["os-error", "runtime-error", "base-exception"],
)
@pytest.mark.parametrize("original_operation", ["write", "replace"])
def test_cleanup_failure_does_not_mask_the_original_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cleanup_error: BaseException,
    original_operation: str,
) -> None:
    target = tmp_path / "compiled.json"
    expected = OSError(f"{original_operation} failed")
    if original_operation == "write":
        real_named_temporary_file = compiler.tempfile.NamedTemporaryFile

        def failing_tempfile(*args: Any, **kwargs: Any) -> FailingFile:
            return FailingFile(
                real_named_temporary_file(*args, **kwargs), expected, "write"
            )

        monkeypatch.setattr(
            compiler.tempfile, "NamedTemporaryFile", failing_tempfile
        )
    else:
        monkeypatch.setattr(
            compiler.os,
            "replace",
            lambda _source, _target: (_ for _ in ()).throw(expected),
        )
    monkeypatch.setattr(
        compiler.os,
        "unlink",
        lambda _path: (_ for _ in ()).throw(cleanup_error),
    )

    with pytest.raises(OSError) as raised:
        write_compiled_pack({"new": True}, target)

    assert raised.value is expected


def test_cleanup_unlinks_only_the_generated_staging_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "compiled.json"
    unrelated = tmp_path / "unrelated.tmp"
    unrelated.write_bytes(b"keep")
    expected = OSError("replace failed")
    replacement_sources: list[Path] = []
    unlinked: list[Path] = []
    real_unlink = compiler.os.unlink

    def fail_replace(source: str | Path, _target: str | Path) -> None:
        replacement_sources.append(Path(source))
        raise expected

    def capture_unlink(path: str | Path) -> None:
        unlinked.append(Path(path))
        real_unlink(path)

    monkeypatch.setattr(compiler.os, "replace", fail_replace)
    monkeypatch.setattr(compiler.os, "unlink", capture_unlink)

    with pytest.raises(OSError) as raised:
        write_compiled_pack({"new": True}, target)

    assert raised.value is expected
    assert len(replacement_sources) == 1
    assert unlinked == replacement_sources
    assert unrelated.read_bytes() == b"keep"
    assert temp_files(tmp_path) == [unrelated]


def test_concurrent_writers_publish_one_complete_document_without_temp_leaks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "compiled.json"
    values = [
        {"writer": "first", "payload": "a" * 4096},
        {"writer": "second", "payload": "b" * 4096},
    ]
    barrier = Barrier(2)
    lock = Lock()
    first_attempts: set[Path] = set()
    simultaneous_live_staging: list[bool] = []
    real_replace = compiler.os.replace

    def overlapping_replace(source: str | Path, destination: str | Path) -> None:
        staging = Path(source)
        wait_for_peer = False
        with lock:
            if staging not in first_attempts:
                assert staging.exists()
                first_attempts.add(staging)
                simultaneous_live_staging.append(
                    len(first_attempts) == 2
                    and all(path.exists() for path in first_attempts)
                )
                wait_for_peer = True
        if wait_for_peer:
            barrier.wait(timeout=5)
        real_replace(source, destination)

    monkeypatch.setattr(compiler.os, "replace", overlapping_replace)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda value: write_compiled_pack(value, target), values))

    assert len(first_attempts) == 2
    assert all(path.parent == target.parent for path in first_attempts)
    assert all(path.suffix == ".tmp" for path in first_attempts)
    assert any(simultaneous_live_staging)
    assert target.read_bytes() in {canonical_bytes(value) + b"\n" for value in values}
    assert temp_files(tmp_path) == []
