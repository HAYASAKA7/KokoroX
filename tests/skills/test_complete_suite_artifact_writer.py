from __future__ import annotations

import ast
import base64
from hashlib import sha256
import importlib
import itertools
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pytest


SKILLS_ROOT = Path(__file__).resolve().parent
WRITER_PATH = SKILLS_ROOT / "complete_suite_artifact_writer.py"
LAUNCHER_PATH = SKILLS_ROOT / "complete_suite_artifact_launcher.ps1"
SHELL_PATH = r"C:\Program Files\PowerShell\7\pwsh.exe"
REQUEST_KEYS = (
    "schema_version",
    "mode",
    "root",
    "leaf",
    "content_base64",
    "expected_content_sha256",
)
MODES = (
    "operator-prompt",
    "operator-attestation",
    "host-review-envelope",
    "host-review-result",
)
ALLOWED_IMPORTS = (
    "base64",
    "ctypes",
    "encodings",
    "hashlib",
    "json",
    "os",
    "re",
    "sys",
)
NATIVE_API_NAMES = (
    "CloseHandle",
    "CommandLineToArgvW",
    "CreateFileW",
    "FindClose",
    "FindFirstFileW",
    "FindNextFileW",
    "FlushFileBuffers",
    "GetCommandLineW",
    "GetFileInformationByHandle",
    "GetFileInformationByHandleEx",
    "GetFinalPathNameByHandleW",
    "GetModuleFileNameW",
    "LocalFree",
    "NtCreateFile",
    "ReadFile",
    "SetFilePointerEx",
    "WriteFile",
)
NATIVE_CALL_ARITIES = (
    ("GetModuleFileNameW", 3),
    ("GetCommandLineW", 0),
    ("CommandLineToArgvW", 2),
    ("LocalFree", 1),
    ("CreateFileW", 7),
    ("NtCreateFile", 11),
    ("GetFileInformationByHandle", 2),
    ("GetFileInformationByHandleEx", 4),
    ("GetFinalPathNameByHandleW", 4),
    ("WriteFile", 5),
    ("FlushFileBuffers", 1),
    ("ReadFile", 5),
    ("SetFilePointerEx", 4),
    ("FindFirstFileW", 2),
    ("FindNextFileW", 2),
    ("FindClose", 1),
    ("CloseHandle", 1),
    ("ctypes._cast", 3),
)
NATIVE_CONSTANTS = {
    "FILE_ATTRIBUTE_DIRECTORY": 0x00000010,
    "FILE_ATTRIBUTE_REPARSE_POINT": 0x00000400,
    "FILE_ATTRIBUTE_TAG_INFO": 9,
    "FILE_CREATE": 2,
    "FILE_DIRECTORY_FILE": 0x00000001,
    "FILE_FLAG_BACKUP_SEMANTICS": 0x02000000,
    "FILE_FLAG_OPEN_REPARSE_POINT": 0x00200000,
    "FILE_LIST_DIRECTORY": 0x00000001,
    "FILE_NON_DIRECTORY_FILE": 0x00000040,
    "FILE_OPEN": 1,
    "FILE_OPEN_FOR_BACKUP_INTENT": 0x00004000,
    "FILE_OPEN_REPARSE_POINT": 0x00200000,
    "FILE_READ_ATTRIBUTES": 0x00000080,
    "FILE_READ_DATA": 0x00000001,
    "FILE_SHARE_READ": 0x00000001,
    "FILE_SYNCHRONOUS_IO_NONALERT": 0x00000020,
    "FILE_TRAVERSE": 0x00000020,
    "FILE_WRITE_DATA": 0x00000002,
    "OBJ_DONT_REPARSE": 0x00001000,
    "OPEN_EXISTING": 3,
    "SYNCHRONIZE": 0x00100000,
}
OUTER_ENVIRONMENT_MARKER = (
    b'{"policy_revision":"complete-suite-artifact-outer-environment-name-drift-v1",'
    b'"present_name_count":0}'
)
CHILD_ENVIRONMENT_ITEMS = (
    ("SYSTEMROOT", r"C:\Windows"),
    ("WINDIR", r"C:\Windows"),
)
POWERSHELL_AST_NODE_AUDIT = r"""
$source=[Console]::In.ReadToEnd()
$tokens=$null
$errors=$null
$root=[System.Management.Automation.Language.Parser]::ParseInput(
    $source,
    [ref]$tokens,
    [ref]$errors
)
if ($errors.Count -ne 0) {
    [Console]::Error.Write([string]::Join("`n",$errors.ErrorId))
    [Environment]::Exit(2)
}
foreach ($node in $root.FindAll({ param($candidate) $true },$true)) {
    [Console]::Out.WriteLine($node.GetType().Name)
}
"""
FRAME_HEADER_BEGIN = "# C6_ARTIFACT_FRAME_HEADER_VALIDATION_BEGIN"
FRAME_HEADER_END = "# C6_ARTIFACT_FRAME_HEADER_VALIDATION_END"
FRAME_ALLOCATION_BEGIN = "# C6_ARTIFACT_FRAME_PAYLOAD_ALLOCATION_BEGIN"
FRAME_ALLOCATION_END = "# C6_ARTIFACT_FRAME_PAYLOAD_ALLOCATION_END"
FRAME_PAYLOAD_BEGIN = "# C6_ARTIFACT_FRAME_PAYLOAD_VALIDATION_BEGIN"
FRAME_PAYLOAD_END = "# C6_ARTIFACT_FRAME_PAYLOAD_VALIDATION_END"
NATIVE_VECTOR_BEGIN = "# C6_ARTIFACT_NATIVE_VECTOR_VALIDATION_BEGIN"
NATIVE_VECTOR_END = "# C6_ARTIFACT_NATIVE_VECTOR_VALIDATION_END"
CHILD_LIFECYCLE_BEGIN = "# C6_ARTIFACT_CHILD_LIFECYCLE_BEGIN"
CHILD_LIFECYCLE_END = "# C6_ARTIFACT_CHILD_LIFECYCLE_END"
PROCESS_INFO_BEGIN = "# C6_ARTIFACT_PROCESS_START_INFO_ALLOCATION_BEGIN"
PROCESS_INFO_END = "# C6_ARTIFACT_PROCESS_START_INFO_ALLOCATION_END"


def _writer():
    sys.modules.pop("complete_suite_artifact_writer", None)
    return importlib.import_module("complete_suite_artifact_writer")


def _canonical_request(
    *,
    mode: str,
    root: str,
    leaf: str,
    content: bytes,
) -> bytes:
    document = {
        "schema_version": "complete-suite-artifact-writer-request-v1",
        "mode": mode,
        "root": root,
        "leaf": leaf,
        "content_base64": base64.b64encode(content).decode("ascii"),
        "expected_content_sha256": sha256(content).hexdigest(),
    }
    assert tuple(document) == REQUEST_KEYS
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _canonical_artifact_frame(request: bytes) -> str:
    payload = base64.b64encode(request).decode("ascii")
    header = (
        "C6ARF1:"
        f"{94 + len(payload):07d}:"
        f"{len(request):06d}:"
        f"{len(payload):06d}:"
        f"{sha256(request).hexdigest()}:"
    )
    assert len(header) == 94
    return header + payload


def _replace_artifact_frame_field(frame: str, index: int, value: str) -> str:
    fields = frame.split(":", 5)
    assert len(fields) == 6
    fields[index] = value
    return ":".join(fields)


def _launcher_region(source: str, begin: str, end: str) -> str:
    assert source.count(begin) == 1
    assert source.count(end) == 1
    begin_index = source.index(begin)
    content_index = source.index("\n", begin_index) + 1
    end_index = source.index(end, content_index)
    return source[content_index:end_index]


def _assert_launcher_frame_dominance(source: str) -> None:
    header_begin = source.index(FRAME_HEADER_BEGIN)
    header_end = source.index(FRAME_HEADER_END)
    allocation_begin = source.index(FRAME_ALLOCATION_BEGIN)
    allocation_end = source.index(FRAME_ALLOCATION_END)
    payload_begin = source.index(FRAME_PAYLOAD_BEGIN)
    payload_end = source.index(FRAME_PAYLOAD_END)

    assert (
        header_begin
        < header_end
        < allocation_begin
        < allocation_end
        < payload_begin
        < payload_end
    )
    assert (
        "$script:C6ArtifactPayloadCharacters="
        "[char[]]::new($script:C6ArtifactFramePayloadCharacters)"
    ) in _launcher_region(
        source,
        FRAME_ALLOCATION_BEGIN,
        FRAME_ALLOCATION_END,
    )
    for child_constructor in (
        "[System.Diagnostics.ProcessStartInfo]::new",
        "[System.Diagnostics.Process]::Start",
    ):
        child_index = source.find(child_constructor)
        assert child_index == -1 or payload_end < child_index


def _run_launcher_frame_validation(
    tmp_path: Path,
    frame: str,
) -> subprocess.CompletedProcess[str]:
    source = LAUNCHER_PATH.read_text(encoding="utf-8")
    header_region = _launcher_region(source, FRAME_HEADER_BEGIN, FRAME_HEADER_END)
    allocation_region = _launcher_region(
        source,
        FRAME_ALLOCATION_BEGIN,
        FRAME_ALLOCATION_END,
    )
    payload_region = _launcher_region(
        source,
        FRAME_PAYLOAD_BEGIN,
        FRAME_PAYLOAD_END,
    )
    header_path = tmp_path / "frame-header.txt"
    payload_path = tmp_path / "frame-payload.txt"
    harness_path = tmp_path / "frame-harness.ps1"
    header_path.write_text(frame[:94], encoding="utf-8", newline="")
    payload_path.write_text(frame[94:], encoding="utf-8", newline="")
    harness = (
        "$ErrorActionPreference='Stop'\n"
        "$script:C6ArtifactRequestCapBytes=524288\n"
        "$script:C6ArtifactFrameHeaderCharacters=94\n"
        "$script:C6ArtifactFramePayloadCapCharacters=699052\n"
        "$script:C6ArtifactFrameTotalCapCharacters=699146\n"
        "$strictUtf8=[System.Text.UTF8Encoding]::new($false,$true)\n"
        "$script:C6ArtifactFrameHeaderText="
        "[System.IO.File]::ReadAllText($args[0],$strictUtf8)\n"
        + header_region
        + allocation_region
        + "$script:C6ArtifactFramePayloadText="
        "[System.IO.File]::ReadAllText($args[1],$strictUtf8)\n"
        + payload_region
        + "[Console]::Out.Write("
        "$script:C6ArtifactValidatedRequestBytes.Length.ToString(" 
        "[Globalization.CultureInfo]::InvariantCulture)+':' +"
        "$script:C6ArtifactValidatedRequestSha256)\n"
    )
    harness_path.write_text(harness, encoding="utf-8", newline="")
    return subprocess.run(
        (
            SHELL_PATH,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(harness_path),
            str(header_path),
            str(payload_path),
        ),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
        check=False,
    )


def _independent_windows_native_argument(value: str) -> str:
    assert "\0" not in value
    value.encode("utf-16-le", errors="strict")
    if value and not any(character in '" \t' for character in value):
        return value
    output = '"'
    cursor = 0
    while cursor < len(value):
        slash_start = cursor
        while cursor < len(value) and value[cursor] == "\\":
            cursor += 1
        slash_count = cursor - slash_start
        if cursor == len(value):
            output += "\\" * (2 * slash_count)
            break
        if value[cursor] == '"':
            output += "\\" * (2 * slash_count + 1) + '"'
        else:
            output += "\\" * slash_count + value[cursor]
        cursor += 1
    return output + '"'


def _independent_windows_native_vector(
    executable: str,
    arguments: tuple[str, ...],
) -> tuple[int, str]:
    command_line = " ".join(
        _independent_windows_native_argument(value)
        for value in (executable, *arguments)
    )
    encoded = (command_line + "\0").encode("utf-16-le", errors="strict")
    return len(encoded) // 2, sha256(encoded).hexdigest()


def _powershell_native_value_expression(value: object) -> str:
    if value is None:
        return "$null"
    if isinstance(value, int):
        return f"[int]{value}"
    assert isinstance(value, str)
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        characters = ",".join(
            f"[char]{ord(character)}" for character in value
        )
        return f"[string]::new([char[]]@({characters}))"
    encoded = base64.b64encode(value.encode("utf-8", errors="strict")).decode(
        "ascii"
    )
    return (
        "[System.Text.UTF8Encoding]::new($false,$true).GetString("
        f"[Convert]::FromBase64String('{encoded}'))"
    )


def _powershell_native_arguments_expression(arguments: object) -> str:
    if isinstance(arguments, tuple):
        return "[object[]]@(" + ",".join(
            _powershell_native_value_expression(value) for value in arguments
        ) + ")"
    return _powershell_native_value_expression(arguments)


def _run_launcher_native_vector_validation(
    tmp_path: Path,
    *,
    executable: object,
    arguments: object,
) -> subprocess.CompletedProcess[str]:
    source = LAUNCHER_PATH.read_text(encoding="utf-8")
    region = _launcher_region(source, NATIVE_VECTOR_BEGIN, NATIVE_VECTOR_END)
    harness_path = tmp_path / "native-vector-harness.ps1"
    harness = (
        "$ErrorActionPreference='Stop'\n"
        "$script:C6ArtifactNativeVectorCapUtf16Units=30000\n"
        "$script:C6ArtifactNativeExecutable="
        + _powershell_native_value_expression(executable)
        + "\n$script:C6ArtifactNativeArguments="
        + _powershell_native_arguments_expression(arguments)
        + "\n"
        + region
        + "[Console]::Out.Write("
        "$script:C6ArtifactNativeVectorContract+':' +"
        "$script:C6ArtifactNativeVectorUtf16Units.ToString("
        "[Globalization.CultureInfo]::InvariantCulture)+':' +"
        "$script:C6ArtifactNativeVectorUtf16LeSha256)\n"
    )
    harness_path.write_text(harness, encoding="utf-8", newline="")
    return subprocess.run(
        (
            SHELL_PATH,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(harness_path),
        ),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
        check=False,
    )


def _assert_launcher_native_vector_dominance(source: str) -> None:
    native_begin = source.index(NATIVE_VECTOR_BEGIN)
    native_end = source.index(NATIVE_VECTOR_END)
    assert native_begin < native_end
    for child_constructor in (
        "[System.Diagnostics.ProcessStartInfo]::new",
        "[System.Diagnostics.Process]::Start",
    ):
        start = 0
        while True:
            child_index = source.find(child_constructor, start)
            if child_index == -1:
                break
            assert native_end < child_index
            start = child_index + len(child_constructor)


def _powershell_string_array_expression(values: tuple[str, ...]) -> str:
    return "[string[]]@(" + ",".join(
        _powershell_native_value_expression(value) for value in values
    ) + ")"


def _run_launcher_child_lifecycle(
    tmp_path: Path,
    *,
    request: bytes,
    expected_output_path: str,
    helper_path: Path,
    working_directory: Path,
    deadline_ms: int = 5_000,
) -> subprocess.CompletedProcess[str]:
    source = LAUNCHER_PATH.read_text(encoding="utf-8")
    region = _launcher_region(source, CHILD_LIFECYCLE_BEGIN, CHILD_LIFECYCLE_END)
    request_hash = sha256(request).hexdigest()
    arguments = (
        "-I",
        "-S",
        "-B",
        "-X",
        "utf8",
        str(helper_path),
        "--expected-request-sha256",
        request_hash,
    )
    request_base64 = base64.b64encode(request).decode("ascii")
    harness_path = tmp_path / "child-lifecycle-harness.ps1"
    harness = (
        "$ErrorActionPreference='Stop'\n"
        "$script:C6ArtifactFrameValidated=$true\n"
        "$script:C6ArtifactNativeVectorValidated=$true\n"
        "$script:C6ArtifactPythonPath='C:\\Python314\\python.exe'\n"
        "$script:C6ArtifactAuthenticatedWriterPath="
        + _powershell_native_value_expression(str(helper_path))
        + "\n$script:C6ArtifactValidatedRequestSha256="
        + _powershell_native_value_expression(request_hash)
        + "\n"
        "$script:C6ArtifactValidatedNativeExecutable='C:\\Python314\\python.exe'\n"
        "$script:C6ArtifactValidatedNativeArguments="
        + _powershell_string_array_expression(arguments)
        + "\n$script:C6ArtifactValidatedRequestBytes="
        f"[Convert]::FromBase64String('{request_base64}')\n"
        "$script:C6ArtifactValidatedExpectedOutputPath="
        + _powershell_native_value_expression(expected_output_path)
        + "\n$script:C6ArtifactAuthenticatedCheckoutPath="
        + _powershell_native_value_expression(str(working_directory))
        + f"\n$script:C6ArtifactOutputCapBytes=65536\n"
        f"$script:C6ArtifactDeadlineMilliseconds={deadline_ms}\n"
        "$script:C6ArtifactTerminationGraceMilliseconds=5000\n"
        "$script:C6ArtifactDeadlineStopwatch="
        "[System.Diagnostics.Stopwatch]::StartNew()\n"
        + region
        + "[Console]::Out.Write('ok:' +"
        "$script:C6ArtifactChildExitCode.ToString("
        "[Globalization.CultureInfo]::InvariantCulture)+':' +"
        "$script:C6ArtifactChildStdoutBytes.Length.ToString("
        "[Globalization.CultureInfo]::InvariantCulture)+':' +"
        "$script:C6ArtifactChildStdoutSha256)\n"
    )
    harness_path.write_text(harness, encoding="utf-8", newline="")
    return subprocess.run(
        (
            SHELL_PATH,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(harness_path),
        ),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
        check=False,
    )


def _write_synthetic_launcher_child(
    tmp_path: Path,
    *,
    behavior: str,
    request: bytes,
    expected_output_path: str,
) -> Path:
    helper_path = tmp_path / f"synthetic-child-{behavior}.py"
    request_hash = sha256(request).hexdigest()
    expected_output = expected_output_path.encode("utf-8") + b"\n"
    source = (
        "import os\n"
        "import sys\n"
        f"behavior={behavior!r}\n"
        f"expected_request=bytes.fromhex({request.hex()!r})\n"
        f"expected_hash={request_hash!r}\n"
        f"expected_output=bytes.fromhex({expected_output.hex()!r})\n"
        "if sys.flags.isolated != 1 or sys.flags.no_site != 1:\n"
        "    raise SystemExit(91)\n"
        "if sys.flags.dont_write_bytecode != 1 or sys.flags.utf8_mode != 1:\n"
        "    raise SystemExit(92)\n"
        "if sys.argv[1:] != ['--expected-request-sha256', expected_hash]:\n"
        "    raise SystemExit(93)\n"
        "if set(os.environ) != {'SYSTEMROOT', 'WINDIR'}:\n"
        "    raise SystemExit(94)\n"
        "if os.environ['SYSTEMROOT'] != r'C:\\Windows':\n"
        "    raise SystemExit(95)\n"
        "if os.environ['WINDIR'] != r'C:\\Windows':\n"
        "    raise SystemExit(96)\n"
        "if sys.stdin.buffer.read() != expected_request:\n"
        "    raise SystemExit(97)\n"
        "if behavior == 'nonzero':\n"
        "    raise SystemExit(7)\n"
        "if behavior == 'timeout':\n"
        "    while True:\n"
        "        pass\n"
        "if behavior == 'closed-pipes-timeout':\n"
        "    os.close(sys.stdout.fileno())\n"
        "    os.close(sys.stderr.fileno())\n"
        "    while True:\n"
        "        pass\n"
        "if behavior == 'dual-pressure':\n"
        "    sys.stdout.buffer.write(b'o' * 61440)\n"
        "    sys.stdout.buffer.flush()\n"
        "    sys.stderr.buffer.write(b'e' * 61440)\n"
        "    sys.stderr.buffer.flush()\n"
        "    raise SystemExit(0)\n"
        "if behavior == 'stdout-cap':\n"
        "    sys.stdout.buffer.write(b'x' * 65537)\n"
        "elif behavior == 'stderr-cap':\n"
        "    sys.stderr.buffer.write(b'x' * 65537)\n"
        "elif behavior == 'malformed-stdout':\n"
        "    sys.stdout.buffer.write(b'\\xff\\n')\n"
        "elif behavior == 'malformed-stderr':\n"
        "    sys.stdout.buffer.write(expected_output)\n"
        "    sys.stderr.buffer.write(b'\\xff')\n"
        "elif behavior == 'stderr-nonempty':\n"
        "    sys.stdout.buffer.write(expected_output)\n"
        "    sys.stderr.buffer.write(b'synthetic-error')\n"
        "elif behavior == 'crlf-output':\n"
        "    sys.stdout.buffer.write(expected_output[:-1] + b'\\r\\n')\n"
        "elif behavior == 'extra-output':\n"
        "    sys.stdout.buffer.write(expected_output + b'x')\n"
        "elif behavior == 'wrong-output':\n"
        "    sys.stdout.buffer.write(b'D:\\\\tmp\\\\wrong.txt\\n')\n"
        "else:\n"
        "    sys.stdout.buffer.write(expected_output)\n"
        "sys.stdout.buffer.flush()\n"
        "sys.stderr.buffer.flush()\n"
    )
    helper_path.write_text(source, encoding="utf-8", newline="")
    return helper_path


def _assert_launcher_child_dominance(source: str) -> None:
    native_end = source.index(NATIVE_VECTOR_END)
    child_begin = source.index(CHILD_LIFECYCLE_BEGIN)
    process_info_begin = source.index(PROCESS_INFO_BEGIN)
    process_info_end = source.index(PROCESS_INFO_END)
    child_end = source.index(CHILD_LIFECYCLE_END)
    lowered = source.casefold()
    assert (
        native_end
        < child_begin
        < process_info_begin
        < process_info_end
        < child_end
    )
    assert lowered.count("processstartinfo") == 1
    assert lowered.count("process]::start(") == 1
    assert ".start()" not in lowered
    child_region = _launcher_region(
        source,
        CHILD_LIFECYCLE_BEGIN,
        CHILD_LIFECYCLE_END,
    )
    child_lowered = child_region.casefold()
    for forbidden_constructor_surface in (
        "invokemember",
        "getmethod(",
        "createdelegate",
        "[activator]",
        "activator]::",
    ):
        assert forbidden_constructor_surface not in child_lowered
    for raw_name in (
        "$script:C6ArtifactNativeExecutable",
        "$script:C6ArtifactNativeArguments",
    ):
        assert raw_name not in child_region
    required = (
        "$script:C6ArtifactNativeVectorValidated -ne $true",
        ".FileName=$script:C6ArtifactValidatedNativeExecutable",
        "$script:C6ArtifactValidatedNativeArguments",
        ".Environment.Clear()",
        ".Environment.Add('SYSTEMROOT','C:\\Windows')",
        ".Environment.Add('WINDIR','C:\\Windows')",
        ".StandardInput.BaseStream.WriteAsync(",
        ".StandardInput.Close()",
        ".StandardOutput.BaseStream.ReadAsync(",
        ".StandardError.BaseStream.ReadAsync(",
        ".Kill($true)",
        ".WaitForExit($script:C6ArtifactTerminationGraceMilliseconds)",
    )
    for literal in required:
        assert literal in child_region
    assert "ReadToEnd" not in child_region
    assert child_region.count(".Kill($true)") == 1
    assert child_region.count(".Kill(") == 1
    assert child_region.count(".WaitForExit(") == 2
    assert (
        child_region.count(
            ".WaitForExit($script:C6ArtifactTerminationGraceMilliseconds)"
        )
        == 1
    )
    assert ".WaitForExit()" not in child_region
    assert ".WaitForExitAsync(" not in child_region
    assert child_region.count("[Threading.Tasks.Task]::WaitAny(") == 1
    assert "$script:C6ArtifactDeadlineStopwatch.Restart(" not in child_region
    assert "$script:C6ArtifactDeadlineStopwatch.Reset(" not in child_region
    assert "[System.Diagnostics.Stopwatch]::StartNew(" not in child_region
    ordinary_wait = (
        ".WaitForExit(\n"
        "            [int]$c6ArtifactRemainingMilliseconds\n"
        "        )"
    )
    assert child_region.count(ordinary_wait) == 1
    kill_index = child_region.index(".Kill($true)")
    grace_index = child_region.index(
        ".WaitForExit($script:C6ArtifactTerminationGraceMilliseconds)"
    )
    assert kill_index < grace_index

    stdout_initial = child_region.index(
        ".StandardOutput.BaseStream.ReadAsync("
    )
    stderr_initial = child_region.index(
        ".StandardError.BaseStream.ReadAsync("
    )
    wait_any = child_region.index("[Threading.Tasks.Task]::WaitAny(")
    stdout_cap = child_region.find(
        "$c6ArtifactStdoutMemory.Length+$c6ArtifactStdoutRead -gt"
    )
    stderr_cap = child_region.find(
        "$c6ArtifactStderrMemory.Length+$c6ArtifactStderrRead -gt"
    )
    stdout_write = child_region.index("$c6ArtifactStdoutMemory.Write(")
    stderr_write = child_region.index("$c6ArtifactStderrMemory.Write(")
    stdout_reschedule = child_region.find(
        "$c6ArtifactStdoutTask=$c6ArtifactStdoutStream.ReadAsync("
    )
    stderr_reschedule = child_region.find(
        "$c6ArtifactStderrTask=$c6ArtifactStderrStream.ReadAsync("
    )
    assert child_region.count(".StandardOutput.BaseStream.ReadAsync(") == 1
    assert child_region.count(".StandardError.BaseStream.ReadAsync(") == 1
    assert (
        child_region.count(
            "$c6ArtifactStdoutTask=$c6ArtifactStdoutStream.ReadAsync("
        )
        == 1
    )
    assert (
        child_region.count(
            "$c6ArtifactStderrTask=$c6ArtifactStderrStream.ReadAsync("
        )
        == 1
    )
    assert child_region.count("$c6ArtifactStdoutEof=$false") == 1
    assert child_region.count("$c6ArtifactStderrEof=$false") == 1
    assert child_region.count("$c6ArtifactStdoutEof=$true") == 1
    assert child_region.count("$c6ArtifactStderrEof=$true") == 1
    assert (
        child_region.count(
            "$c6ArtifactStdoutMemory.Length+$c6ArtifactStdoutRead -gt"
        )
        == 1
    )
    assert (
        child_region.count(
            "$c6ArtifactStderrMemory.Length+$c6ArtifactStderrRead -gt"
        )
        == 1
    )
    assert stdout_cap >= 0
    assert stderr_cap >= 0
    assert stdout_reschedule >= 0
    assert stderr_reschedule >= 0
    assert stdout_initial < wait_any
    assert stderr_initial < wait_any
    assert stdout_cap < stdout_write < stdout_reschedule
    assert stderr_cap < stderr_write < stderr_reschedule
    clear_index = child_region.index(".Environment.Clear()")
    systemroot_index = child_region.index(
        ".Environment.Add('SYSTEMROOT','C:\\Windows')"
    )
    windir_index = child_region.index(
        ".Environment.Add('WINDIR','C:\\Windows')"
    )
    start_index = child_region.index("[System.Diagnostics.Process]::Start(")
    assert clear_index < systemroot_index < windir_index < start_index


def _decode(raw: bytes, *, writer=None):
    active_writer = _writer() if writer is None else writer
    return active_writer.decode_artifact_writer_request(
        raw,
        expected_request_sha256=sha256(raw).hexdigest(),
    )


def _root_and_leaf(mode: str, discriminator: str) -> tuple[str, str]:
    nonce = uuid.uuid4().hex
    if mode.startswith("operator-"):
        root = rf"D:\tmp\kokoroarc-c6-{discriminator}-{nonce}"
        if mode == "operator-prompt":
            leaf = f"{discriminator}-prompt.txt"
        else:
            leaf = f"{discriminator}.json"
        return root, leaf
    phase, review_type = discriminator.split("/", 1)
    root = rf"D:\tmp\kokoroarc-c6-host-review-{phase}-{review_type}-{nonce}"
    leaf = (
        "review-evaluation-envelope.json"
        if mode == "host-review-envelope"
        else "review-result.json"
    )
    return root, leaf


HOST_REVIEW_ENVELOPE_KEYS = (
    "schema_version",
    "envelope_id",
    "phase",
    "review_type",
    "reviewer_task_name",
    "purpose",
    "target_head",
    "target_tree",
    "target_parent",
    "target_base",
    "design_sha256",
    "plan_sha256",
    "campaign_sha256",
    "subject_records",
    "subject_equivalence_sha256",
    "authorized_input_projection_entry_count",
    "authorized_input_projection_sha256",
    "host_review_input_bundle_entry_count",
    "host_review_input_bundle_decoded_bytes",
    "host_review_input_bundle_aggregate_sha256",
    "predecessor_review_result_sha256s",
    "phase_model_call_ordinal",
    "host_collaboration_model_call",
    "host_model_transport",
    "local_windows_processes_allowed",
    "local_windows_codex_client_processes_allowed",
    "local_provider_processes_allowed",
    "local_socket_network_calls_allowed",
    "network_access_allowed",
    "credential_access_allowed",
    "filesystem_read_authority",
    "unlisted_filesystem_access_allowed",
    "filesystem_writes_allowed",
    "git_mutations_allowed",
    "test_execution_allowed",
    "tool_execution_allowed",
    "child_agent_spawns_allowed",
    "result_transport",
    "deadline_ms",
    "deadline_clock",
    "deadline_expiry_action",
    "result_cap_bytes",
    "cybersecurity_checks_may_be_bypassed",
)
HOST_REVIEW_RESULT_KEYS = (
    "schema_version",
    "capture_method",
    "evaluation_envelope_sha256",
    "phase",
    "review_type",
    "reviewer_task_name",
    "verdict",
    "target_head",
    "target_tree",
    "target_parent",
    "target_base",
    "design_sha256",
    "plan_sha256",
    "campaign_sha256",
    "subject_records",
    "subject_equivalence_sha256",
    "authorized_input_projection_entry_count",
    "authorized_input_projection_sha256",
    "host_review_input_bundle_entry_count",
    "host_review_input_bundle_decoded_bytes",
    "host_review_input_bundle_aggregate_sha256",
    "predecessor_review_result_sha256s",
    "phase_model_call_ordinal",
    "deadline_ms",
    "deadline_clock",
    "deadline_expiry_action",
    "critical_findings",
    "important_findings",
)
HOST_REVIEW_SUBJECT_KEYS = ("role", "path", "identity", "size", "sha256")
HOST_REVIEW_IDENTITY_KEYS = (
    "device",
    "inode",
    "file_type",
    "reparse_tag",
    "link_count",
)


def _canonical_document(document: dict[str, object]) -> bytes:
    return (
        json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        + b"\n"
    )


def _host_subjects(phase: str) -> list[dict[str, object]]:
    nonce = "1" * 32
    paths = {
        "candidate": (
            ("pre-freeze-gate", rf"D:\tmp\kokoroarc-c6-task12-prefreeze-{nonce}.json"),
            ("candidate-input-aggregate", rf"D:\tmp\kokoroarc-c6-task12-inputs-{nonce}.json"),
            ("candidate-review-input-bundle", rf"D:\tmp\kokoroarc-c6-task12-prefreeze-{nonce}\host-review-input-bundle.json"),
        ),
        "closure": (
            ("closure-committed-release", rf"D:\tmp\kokoroarc-c6-task16-committed-{nonce}.json"),
            ("closure-review-input-bundle", rf"D:\tmp\kokoroarc-c6-task16-committed-{nonce}\host-review-input-bundle.json"),
        ),
        "final-docs": (
            ("final-docs-release", rf"D:\tmp\kokoroarc-c6-task16-final-docs-{nonce}.json"),
            ("final-cumulative-manifest", rf"D:\tmp\kokoroarc-c6-task16-final-docs-worktree-{nonce}\cumulative-release-scope.json"),
            ("closure-reviewed-release", rf"D:\tmp\kokoroarc-c6-task16-reviewed-{nonce}.json"),
            ("final-docs-review-input-bundle", rf"D:\tmp\kokoroarc-c6-task16-final-docs-{nonce}\host-review-input-bundle.json"),
        ),
    }[phase]
    subjects: list[dict[str, object]] = []
    for ordinal, (role, path) in enumerate(paths, start=1):
        subjects.append(
            {
                "role": role,
                "path": path,
                "identity": {
                    "device": 10,
                    "inode": ordinal,
                    "file_type": 1,
                    "reparse_tag": 0,
                    "link_count": 1,
                },
                "size": 200 + ordinal,
                "sha256": f"{ordinal:x}" * 64,
            }
        )
    return subjects


def _host_common(phase: str, review_type: str) -> dict[str, object]:
    subjects = _host_subjects(phase)
    projection = {
        "schema_version": "complete-suite-host-review-authorized-input-projection-v1",
        "phase": phase,
        "entries": subjects,
    }
    return {
        "phase": phase,
        "review_type": review_type,
        "reviewer_task_name": f"c6_{phase.replace('-', '_')}_{review_type}_review",
        "target_head": "1" * 40,
        "target_tree": "2" * 40,
        "target_parent": "3" * 40,
        "target_base": "30beb3832d18f6d0011bb4f8af96b7cdda9222f6",
        "design_sha256": "4" * 64,
        "plan_sha256": "5" * 64,
        "campaign_sha256": "6" * 64,
        "subject_records": subjects,
        "subject_equivalence_sha256": "7" * 64,
        "authorized_input_projection_entry_count": len(subjects),
        "authorized_input_projection_sha256": sha256(
            _canonical_document(projection)
        ).hexdigest(),
        "host_review_input_bundle_entry_count": 12,
        "host_review_input_bundle_decoded_bytes": 4096,
        "host_review_input_bundle_aggregate_sha256": "8" * 64,
        "predecessor_review_result_sha256s": (
            [] if review_type == "specification" else ["9" * 64]
        ),
        "phase_model_call_ordinal": 1 if review_type == "specification" else 2,
        "deadline_ms": 900000,
        "deadline_clock": "monotonic",
        "deadline_expiry_action": "interrupt_agent-exactly-once",
    }


def _host_review_content(mode: str, discriminator: str) -> bytes:
    phase, root_review_type = discriminator.split("/", 1)
    review_type = root_review_type.replace("-", "_")
    common = _host_common(phase, review_type)
    if mode == "host-review-envelope":
        document = {
            "schema_version": "complete-suite-host-review-evaluation-envelope-v1",
            "envelope_id": f"{phase}-{review_type}-evaluation",
            "phase": common["phase"],
            "review_type": common["review_type"],
            "reviewer_task_name": common["reviewer_task_name"],
            "purpose": "campaign-6-independent-read-only-review",
            "target_head": common["target_head"],
            "target_tree": common["target_tree"],
            "target_parent": common["target_parent"],
            "target_base": common["target_base"],
            "design_sha256": common["design_sha256"],
            "plan_sha256": common["plan_sha256"],
            "campaign_sha256": common["campaign_sha256"],
            "subject_records": common["subject_records"],
            "subject_equivalence_sha256": common["subject_equivalence_sha256"],
            "authorized_input_projection_entry_count": common["authorized_input_projection_entry_count"],
            "authorized_input_projection_sha256": common["authorized_input_projection_sha256"],
            "host_review_input_bundle_entry_count": common["host_review_input_bundle_entry_count"],
            "host_review_input_bundle_decoded_bytes": common["host_review_input_bundle_decoded_bytes"],
            "host_review_input_bundle_aggregate_sha256": common["host_review_input_bundle_aggregate_sha256"],
            "predecessor_review_result_sha256s": common["predecessor_review_result_sha256s"],
            "phase_model_call_ordinal": common["phase_model_call_ordinal"],
            "host_collaboration_model_call": True,
            "host_model_transport": "platform-managed-outside-campaign6-windows-process-boundary",
            "local_windows_processes_allowed": 0,
            "local_windows_codex_client_processes_allowed": 0,
            "local_provider_processes_allowed": 0,
            "local_socket_network_calls_allowed": 0,
            "network_access_allowed": False,
            "credential_access_allowed": False,
            "filesystem_read_authority": "retained-envelope-phase-fixed-subjects-and-bundle-bounded-no-follow",
            "unlisted_filesystem_access_allowed": False,
            "filesystem_writes_allowed": False,
            "git_mutations_allowed": False,
            "test_execution_allowed": False,
            "tool_execution_allowed": False,
            "child_agent_spawns_allowed": False,
            "result_transport": "collaboration-final-message-only",
            "deadline_ms": common["deadline_ms"],
            "deadline_clock": common["deadline_clock"],
            "deadline_expiry_action": common["deadline_expiry_action"],
            "result_cap_bytes": 262144,
            "cybersecurity_checks_may_be_bypassed": False,
        }
        assert tuple(document) == HOST_REVIEW_ENVELOPE_KEYS
        return _canonical_document(document)
    document = {
        "schema_version": {
            "candidate": "complete-suite-candidate-review-v2",
            "closure": "complete-suite-closure-review-v1",
            "final-docs": "complete-suite-final-docs-review-v1",
        }[phase],
        "capture_method": "codex-host-collaboration-final-v1",
        "evaluation_envelope_sha256": "a" * 64,
        "phase": common["phase"],
        "review_type": common["review_type"],
        "reviewer_task_name": common["reviewer_task_name"],
        "verdict": "PASS",
        "target_head": common["target_head"],
        "target_tree": common["target_tree"],
        "target_parent": common["target_parent"],
        "target_base": common["target_base"],
        "design_sha256": common["design_sha256"],
        "plan_sha256": common["plan_sha256"],
        "campaign_sha256": common["campaign_sha256"],
        "subject_records": common["subject_records"],
        "subject_equivalence_sha256": common["subject_equivalence_sha256"],
        "authorized_input_projection_entry_count": common["authorized_input_projection_entry_count"],
        "authorized_input_projection_sha256": common["authorized_input_projection_sha256"],
        "host_review_input_bundle_entry_count": common["host_review_input_bundle_entry_count"],
        "host_review_input_bundle_decoded_bytes": common["host_review_input_bundle_decoded_bytes"],
        "host_review_input_bundle_aggregate_sha256": common["host_review_input_bundle_aggregate_sha256"],
        "predecessor_review_result_sha256s": common["predecessor_review_result_sha256s"],
        "phase_model_call_ordinal": common["phase_model_call_ordinal"],
        "deadline_ms": common["deadline_ms"],
        "deadline_clock": common["deadline_clock"],
        "deadline_expiry_action": common["deadline_expiry_action"],
        "critical_findings": [],
        "important_findings": [],
    }
    assert tuple(document) == HOST_REVIEW_RESULT_KEYS
    return _canonical_document(document)


DESTINATION_ROWS = (
    *( 
        (mode, kind, *_root_and_leaf(mode, kind))
        for mode in ("operator-prompt", "operator-attestation")
        for kind in ("provider-approval", "import-authorization")
    ),
    *(
        (mode, f"{phase}/{review_type}", *_root_and_leaf(mode, f"{phase}/{review_type}"))
        for mode in ("host-review-envelope", "host-review-result")
        for phase in ("candidate", "closure", "final-docs")
        for review_type in ("specification", "quality-security")
    ),
)


def _content_for_mode(mode: str, discriminator: str) -> bytes:
    if mode == "operator-prompt":
        return b"Approve the bounded synthetic request.\n"
    if mode == "operator-attestation":
        return b"{}\n"
    return _host_review_content(mode, discriminator)


def test_artifact_writer_source_and_closed_contract_tables_exist() -> None:
    writer = _writer()

    assert WRITER_PATH.is_file()
    assert writer.ARTIFACT_WRITER_REQUEST_KEYS == REQUEST_KEYS
    assert writer.ARTIFACT_WRITER_MODES == MODES
    assert writer.ARTIFACT_WRITER_ALLOWED_IMPORTS == ALLOWED_IMPORTS
    assert writer.ARTIFACT_WRITER_NATIVE_API_NAMES == NATIVE_API_NAMES
    assert writer.ARTIFACT_WRITER_NATIVE_CALL_ARITIES == NATIVE_CALL_ARITIES
    assert writer.ARTIFACT_WRITER_NATIVE_CONSTANTS == NATIVE_CONSTANTS


def test_artifact_writer_records_are_static_frozen_and_repr_safe() -> None:
    writer = _writer()
    root, leaf = _root_and_leaf("operator-prompt", "provider-approval")
    content = b"synthetic-private-record-canary\n"
    request = _decode(
        _canonical_request(
            mode="operator-prompt",
            root=root,
            leaf=leaf,
            content=content,
        ),
        writer=writer,
    )
    identity = writer.ArtifactWriterObjectIdentity(
        volume_serial_number=1,
        file_index=2,
        link_count=1,
        attributes=3,
        reparse_tag=0,
    )
    equal_identity = writer.ArtifactWriterObjectIdentity(1, 2, 1, 3, 0)

    with pytest.raises(AttributeError):
        request.mode = "host-review-result"
    with pytest.raises(AttributeError):
        identity.file_index = 9
    assert identity == equal_identity
    assert hash(identity) == hash(equal_identity)
    assert content.decode("ascii").strip() not in repr(request)
    assert repr(request).startswith("ArtifactWriterRequest(")


@pytest.mark.parametrize(
    ("mode", "_discriminator", "root", "leaf"),
    DESTINATION_ROWS,
)
def test_artifact_writer_accepts_exact_four_mode_destination_matrix(
    mode: str,
    _discriminator: str,
    root: str,
    leaf: str,
) -> None:
    content = _content_for_mode(mode, _discriminator)
    raw = _canonical_request(
        mode=mode,
        root=root,
        leaf=leaf,
        content=content,
    )

    request = _decode(raw)

    assert request.schema_version == "complete-suite-artifact-writer-request-v1"
    assert request.mode == mode
    assert request.root == root
    assert request.leaf == leaf
    assert request.content == content
    assert request.expected_content_sha256 == sha256(content).hexdigest()
    assert request.creates_root is (mode in {"operator-prompt", "host-review-envelope"})
    if mode == "operator-attestation":
        assert request.predecessor_leaf == leaf.replace(".json", "-prompt.txt")
    elif mode == "host-review-result":
        assert request.predecessor_leaf == "review-evaluation-envelope.json"
    else:
        assert request.predecessor_leaf is None


@pytest.mark.parametrize(
    "mutation",
    (
        "missing-key",
        "extra-key",
        "reordered-key",
        "wrong-schema",
        "fifth-mode",
        "wrong-root-kind",
        "wrong-root-drive",
        "wrong-root-case",
        "wrong-root-nonce",
        "wrong-leaf",
        "noncanonical-base64",
        "wrong-content-hash",
    ),
)
def test_artifact_writer_rejects_request_or_destination_drift_without_mutation(
    mutation: str,
) -> None:
    root, leaf = _root_and_leaf("operator-prompt", "provider-approval")
    content = b"approve\n"
    document = json.loads(
        _canonical_request(
            mode="operator-prompt",
            root=root,
            leaf=leaf,
            content=content,
        )
    )
    if mutation == "missing-key":
        document.pop("leaf")
    elif mutation == "extra-key":
        document["extra"] = False
    elif mutation == "reordered-key":
        document = {"mode": document["mode"], **{k: v for k, v in document.items() if k != "mode"}}
    elif mutation == "wrong-schema":
        document["schema_version"] = "complete-suite-artifact-writer-request-v2"
    elif mutation == "fifth-mode":
        document["mode"] = "generic-write"
    elif mutation == "wrong-root-kind":
        document["root"] = root.replace("provider-approval", "host-review")
    elif mutation == "wrong-root-drive":
        document["root"] = "C:" + root[2:]
    elif mutation == "wrong-root-case":
        document["root"] = root.replace(r"D:\tmp", r"D:\TMP")
    elif mutation == "wrong-root-nonce":
        document["root"] = root[:-32] + "A" * 32
    elif mutation == "wrong-leaf":
        document["leaf"] = "alternate.txt"
    elif mutation == "noncanonical-base64":
        document["content_base64"] = document["content_base64"].rstrip("=")
    else:
        document["expected_content_sha256"] = "0" * 64
    raw = (
        json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )
    target = Path(root)
    assert not target.exists()

    with pytest.raises(RuntimeError):
        _decode(raw)

    assert not target.exists()


@pytest.mark.parametrize(
    "raw_factory",
    (
        lambda raw: raw[:-1],
        lambda raw: b"\xef\xbb\xbf" + raw,
        lambda raw: raw.replace(b"\n", b"\r\n"),
        lambda raw: raw[:-1] + b"\x00\n",
        lambda raw: b" " + raw,
        lambda raw: raw[:-2] + b" \n",
        lambda raw: raw.replace(b'"mode":', b'"mode":"operator-prompt","mode":', 1),
        lambda raw: raw.replace(b'"mode":"operator-prompt"', b'"mode":NaN', 1),
        lambda raw: raw[:-1] + b"\xff\n",
    ),
)
def test_artifact_writer_rejects_noncanonical_or_unsafe_request_bytes(
    raw_factory,
) -> None:
    root, leaf = _root_and_leaf("operator-prompt", "provider-approval")
    raw = _canonical_request(
        mode="operator-prompt",
        root=root,
        leaf=leaf,
        content=b"approve\n",
    )
    mutated = raw_factory(raw)

    with pytest.raises(RuntimeError):
        _decode(mutated)

    assert not Path(root).exists()


def test_artifact_writer_rejects_outer_request_hash_mismatch() -> None:
    root, leaf = _root_and_leaf("operator-prompt", "provider-approval")
    raw = _canonical_request(
        mode="operator-prompt",
        root=root,
        leaf=leaf,
        content=b"approve\n",
    )

    with pytest.raises(RuntimeError):
        _writer().decode_artifact_writer_request(
            raw,
            expected_request_sha256="0" * 64,
        )

    assert not Path(root).exists()


@pytest.mark.parametrize(
    ("mode", "limit"),
    (
        ("operator-prompt", 65_536),
        ("operator-attestation", 65_536),
        ("host-review-envelope", 131_072),
        ("host-review-result", 262_144),
    ),
)
def test_artifact_writer_content_limits_accept_exact_and_reject_one_over(
    mode: str,
    limit: int,
) -> None:
    writer = _writer()
    exact = b"x" * (limit - 1) + b"\n"
    encoded_exact = base64.b64encode(exact).decode("ascii")
    accepted, accepted_sha256 = writer._decode_content(
        {
            "content_base64": encoded_exact,
            "expected_content_sha256": sha256(exact).hexdigest(),
        },
        mode,
    )
    assert accepted == exact
    assert accepted_sha256 == sha256(exact).hexdigest()

    over = b"x" * limit + b"\n"
    with pytest.raises(RuntimeError):
        writer._decode_content(
            {
                "content_base64": base64.b64encode(over).decode("ascii"),
                "expected_content_sha256": sha256(over).hexdigest(),
            },
            mode,
        )


@pytest.mark.parametrize("mode", ("host-review-envelope", "host-review-result"))
def test_artifact_writer_rejects_empty_host_review_object(mode: str) -> None:
    root, leaf = _root_and_leaf(mode, "candidate/specification")

    with pytest.raises(RuntimeError, match=r"^ARTIFACT_WRITER_REQUEST_INVALID$"):
        _decode(_canonical_request(mode=mode, root=root, leaf=leaf, content=b"{}\n"))

    assert not Path(root).exists()


def _decode_host_document(
    mode: str,
    discriminator: str,
    document: dict[str, object],
) -> object:
    root, leaf = _root_and_leaf(mode, discriminator)
    return _decode(
        _canonical_request(
            mode=mode,
            root=root,
            leaf=leaf,
            content=_canonical_document(document),
        )
    )


@pytest.mark.parametrize("mode", ("host-review-envelope", "host-review-result"))
@pytest.mark.parametrize(
    "mutation",
    (
        "missing",
        "extra",
        "reordered",
        "null",
        "wrong-phase",
        "wrong-review-type",
        "wrong-task",
        "wrong-target-base",
        "wrong-target-hash",
        "wrong-document-hash",
        "wrong-subject-order",
        "wrong-subject-path",
        "wrong-subject-identity",
        "wrong-subject-size",
        "wrong-projection-count",
        "wrong-projection-hash",
        "wrong-bundle-count",
        "wrong-bundle-bytes",
        "wrong-predecessor",
        "wrong-ordinal",
        "wrong-deadline",
    ),
)
def test_artifact_writer_rejects_host_review_schema_or_binding_drift(
    mode: str,
    mutation: str,
) -> None:
    document = json.loads(_host_review_content(mode, "candidate/specification"))
    if mutation == "missing":
        document.pop("campaign_sha256")
    elif mutation == "extra":
        document["extension"] = False
    elif mutation == "reordered":
        document = {
            "phase": document["phase"],
            **{key: value for key, value in document.items() if key != "phase"},
        }
    elif mutation == "null":
        document["design_sha256"] = None
    elif mutation == "wrong-phase":
        document["phase"] = "closure"
    elif mutation == "wrong-review-type":
        document["review_type"] = "quality-security"
    elif mutation == "wrong-task":
        document["reviewer_task_name"] = "c6_candidate_quality_security_review"
    elif mutation == "wrong-target-base":
        document["target_base"] = "0" * 40
    elif mutation == "wrong-target-hash":
        document["target_head"] = "A" * 40
    elif mutation == "wrong-document-hash":
        document["plan_sha256"] = "A" * 64
    elif mutation == "wrong-subject-order":
        document["subject_records"] = list(reversed(document["subject_records"]))
    elif mutation == "wrong-subject-path":
        document["subject_records"][0]["path"] = r"D:\tmp\alternate.json"
    elif mutation == "wrong-subject-identity":
        document["subject_records"][0]["identity"]["link_count"] = 2
    elif mutation == "wrong-subject-size":
        document["subject_records"][0]["size"] = 4_194_305
    elif mutation == "wrong-projection-count":
        document["authorized_input_projection_entry_count"] += 1
    elif mutation == "wrong-projection-hash":
        document["authorized_input_projection_sha256"] = "0" * 64
    elif mutation == "wrong-bundle-count":
        document["host_review_input_bundle_entry_count"] = 0
    elif mutation == "wrong-bundle-bytes":
        document["host_review_input_bundle_decoded_bytes"] = 33_554_433
    elif mutation == "wrong-predecessor":
        document["predecessor_review_result_sha256s"] = ["9" * 64]
    elif mutation == "wrong-ordinal":
        document["phase_model_call_ordinal"] = 2
    else:
        document["deadline_ms"] = 899999

    with pytest.raises(RuntimeError, match=r"^ARTIFACT_WRITER_REQUEST_INVALID$"):
        _decode_host_document(mode, "candidate/specification", document)


@pytest.mark.parametrize(
    ("field", "mutated"),
    (
        ("purpose", "generic-review"),
        ("host_collaboration_model_call", False),
        ("host_model_transport", "local-client"),
        ("local_windows_processes_allowed", 1),
        ("local_windows_codex_client_processes_allowed", 1),
        ("local_provider_processes_allowed", 1),
        ("local_socket_network_calls_allowed", 1),
        ("network_access_allowed", True),
        ("credential_access_allowed", True),
        ("filesystem_read_authority", "repository"),
        ("unlisted_filesystem_access_allowed", True),
        ("filesystem_writes_allowed", True),
        ("git_mutations_allowed", True),
        ("test_execution_allowed", True),
        ("tool_execution_allowed", True),
        ("child_agent_spawns_allowed", True),
        ("result_transport", "filesystem"),
        ("deadline_clock", "wall"),
        ("deadline_expiry_action", "continue"),
        ("result_cap_bytes", 262143),
        ("cybersecurity_checks_may_be_bypassed", True),
    ),
)
def test_artifact_writer_rejects_host_review_envelope_authority_drift(
    field: str,
    mutated: object,
) -> None:
    document = json.loads(
        _host_review_content("host-review-envelope", "closure/quality-security")
    )
    document[field] = mutated

    with pytest.raises(RuntimeError, match=r"^ARTIFACT_WRITER_REQUEST_INVALID$"):
        _decode_host_document(
            "host-review-envelope",
            "closure/quality-security",
            document,
        )


def test_artifact_writer_rejects_duplicate_nested_host_review_key() -> None:
    mode = "host-review-envelope"
    discriminator = "candidate/specification"
    root, leaf = _root_and_leaf(mode, discriminator)
    content = _host_review_content(mode, discriminator).replace(
        b'"device":10',
        b'"device":10,"device":10',
        1,
    )

    with pytest.raises(RuntimeError, match=r"^ARTIFACT_WRITER_REQUEST_INVALID$"):
        _decode(_canonical_request(mode=mode, root=root, leaf=leaf, content=content))


def _blocked_host_result() -> dict[str, object]:
    document = json.loads(
        _host_review_content("host-review-result", "final-docs/quality-security")
    )
    document["verdict"] = "BLOCKED"
    document["critical_findings"] = [
        {
            "severity": "Critical",
            "line_start": 7,
            "line_end": 9,
            "quoted_text": "bounded excerpt",
            "why_blocking": "The invariant is not established.",
            "minimal_correction": "Add the missing exact binding.",
        }
    ]
    return document


def test_artifact_writer_accepts_bounded_blocked_host_review_result() -> None:
    request = _decode_host_document(
        "host-review-result",
        "final-docs/quality-security",
        _blocked_host_result(),
    )

    assert request.mode == "host-review-result"


@pytest.mark.parametrize(
    "mutation",
    (
        "pass-with-finding",
        "blocked-empty",
        "wrong-array-severity",
        "bad-line-start",
        "bad-line-order",
        "quoted-cap",
        "explanation-cap",
        "finding-count",
        "finding-extra-key",
    ),
)
def test_artifact_writer_rejects_host_review_result_finding_drift(
    mutation: str,
) -> None:
    document = _blocked_host_result()
    finding = document["critical_findings"][0]
    if mutation == "pass-with-finding":
        document["verdict"] = "PASS"
    elif mutation == "blocked-empty":
        document["critical_findings"] = []
    elif mutation == "wrong-array-severity":
        finding["severity"] = "Important"
    elif mutation == "bad-line-start":
        finding["line_start"] = 0
    elif mutation == "bad-line-order":
        finding["line_end"] = 6
    elif mutation == "quoted-cap":
        finding["quoted_text"] = "x" * 4097
    elif mutation == "explanation-cap":
        finding["why_blocking"] = "x" * 8193
    elif mutation == "finding-count":
        document["critical_findings"] = [finding] * 65
    else:
        finding["extension"] = False

    with pytest.raises(RuntimeError, match=r"^ARTIFACT_WRITER_REQUEST_INVALID$"):
        _decode_host_document(
            "host-review-result",
            "final-docs/quality-security",
            document,
        )


@pytest.mark.parametrize(
    "content",
    (
        b"",
        b"missing-final-lf",
        b"has\r\n",
        b"has\x00nul\n",
        b"\xef\xbb\xbfhas-bom\n",
        b"invalid-utf8-\xff\n",
    ),
)
@pytest.mark.parametrize("mode", MODES)
def test_artifact_writer_rejects_unsafe_content_before_output(
    mode: str,
    content: bytes,
) -> None:
    discriminator = (
        "provider-approval"
        if mode.startswith("operator-")
        else "candidate/specification"
    )
    root, leaf = _root_and_leaf(mode, discriminator)

    with pytest.raises(RuntimeError):
        _decode(_canonical_request(mode=mode, root=root, leaf=leaf, content=content))

    assert not Path(root).exists()


def _case_variants(value: str) -> tuple[str, ...]:
    choices = (
        (character.lower(), character.upper())
        if character.isascii() and character.isalpha()
        else (character,)
        for character in value
    )
    return tuple("".join(characters) for characters in itertools.product(*choices))


@pytest.mark.parametrize(
    "name",
    tuple(
        variant + suffix
        for prefix in ("DOTNET_", "CORECLR_", "COR_", "COMPLUS_")
        for variant in _case_variants(prefix)
        for suffix in ("", "profiler", "调试")
    ),
)
def test_artifact_writer_runtime_name_family_classifier_rejects_every_case_variant(
    name: str,
) -> None:
    writer = _writer()
    calls = {"decode": 0, "start": 0, "artifact": 0}

    with pytest.raises(
        RuntimeError,
        match=r"^artifact outer environment-family drift$",
    ) as error:
        writer.validate_artifact_writer_outer_environment_names({name: "private"})
        calls["decode"] += 1
        calls["start"] += 1
        calls["artifact"] += 1

    assert calls == {"decode": 0, "start": 0, "artifact": 0}
    assert name not in str(error.value)
    assert "private" not in str(error.value)


class _KeysOnlyEnvironment:
    def __init__(self, names: tuple[str, ...]) -> None:
        self._names = names
        self.value_access_count = 0
        self.entry_enumeration_count = 0

    def keys(self) -> tuple[str, ...]:
        return self._names

    def values(self):
        self.value_access_count += 1
        raise AssertionError("environment values must remain unread")

    def items(self):
        self.entry_enumeration_count += 1
        raise AssertionError("environment entries must remain unenumerated")

    def __getitem__(self, _key: str):
        self.value_access_count += 1
        raise AssertionError("environment values must remain unread")

    def __iter__(self):
        self.entry_enumeration_count += 1
        raise AssertionError("environment entries must remain unenumerated")


def test_artifact_writer_runtime_name_classifier_does_not_access_values() -> None:
    writer = _writer()
    environment = _KeysOnlyEnvironment(("PATH", "PSModulePath", "UNICODE_名"))

    marker = writer.validate_artifact_writer_outer_environment_names(environment)

    assert marker == OUTER_ENVIRONMENT_MARKER
    assert sha256(marker).hexdigest() == writer.ARTIFACT_WRITER_OUTER_ENVIRONMENT_MARKER_SHA256
    assert environment.value_access_count == 0
    assert environment.entry_enumeration_count == 0


def test_artifact_writer_python_early_gate_precedes_nonfrozen_imports() -> None:
    source = WRITER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    top_level = tuple(tree.body)
    gate_index = next(
        index
        for index, node in enumerate(top_level)
        if isinstance(node, ast.If)
        and any(
            isinstance(candidate, ast.Call)
            and isinstance(candidate.func, ast.Name)
            and candidate.func.id == "_run_artifact_writer_early_runtime_gate"
            for candidate in ast.walk(node)
        )
    )
    imports_before_gate: list[str] = []
    imports_after_gate: list[str] = []
    for index, node in enumerate(top_level):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        if index < gate_index:
            imports_before_gate.extend(names)
        elif index > gate_index:
            imports_after_gate.extend(names)
    assert imports_before_gate == ["sys", "os"]
    assert imports_after_gate
    assert {
        name.partition(".")[0] for name in imports_after_gate
    } <= set(ALLOWED_IMPORTS)
    assert imports_after_gate.count("encodings.utf_16_le") == 1
    assert "base64" in imports_after_gate
    assert "ctypes" in imports_after_gate
    assert "json" in imports_after_gate


def _valid_early_runtime_contract() -> dict[str, object]:
    return {
        "os_origin": "frozen",
        "executable": r"C:\Python314\python.exe",
        "isolated": 1,
        "no_site": 1,
        "dont_write_bytecode": 1,
        "utf8_mode": 1,
        "sys_path": (
            r"C:\Python314\python314.zip",
            r"C:\Python314\DLLs",
            r"C:\Python314\Lib",
            r"C:\Python314",
        ),
        "argv": (
            r"D:\task9-detached\tests\skills\complete_suite_artifact_writer.py",
            "--expected-request-sha256",
            "a" * 64,
        ),
        "environment": dict(CHILD_ENVIRONMENT_ITEMS),
    }


def test_artifact_writer_python_early_runtime_gate_accepts_exact_contract() -> None:
    writer = _writer()

    assert writer.validate_artifact_writer_early_runtime_contract(
        **_valid_early_runtime_contract()
    ) is None


@pytest.mark.parametrize(
    "mutation",
    (
        "os-origin",
        "executable",
        "isolated",
        "no-site",
        "bytecode",
        "utf8",
        "path-order",
        "path-extra",
        "argv-helper",
        "argv-option",
        "argv-hash",
        "environment-name-case",
        "environment-value",
        "environment-extra",
    ),
)
def test_artifact_writer_python_early_runtime_gate_rejects_drift(
    mutation: str,
) -> None:
    writer = _writer()
    contract = _valid_early_runtime_contract()
    if mutation == "os-origin":
        contract["os_origin"] = "source"
    elif mutation == "executable":
        contract["executable"] = r"C:\Python314\pythonw.exe"
    elif mutation == "isolated":
        contract["isolated"] = 0
    elif mutation == "no-site":
        contract["no_site"] = 0
    elif mutation == "bytecode":
        contract["dont_write_bytecode"] = 0
    elif mutation == "utf8":
        contract["utf8_mode"] = 0
    elif mutation == "path-order":
        contract["sys_path"] = tuple(reversed(contract["sys_path"]))
    elif mutation == "path-extra":
        contract["sys_path"] = (*contract["sys_path"], r"D:\hostile")
    elif mutation == "argv-helper":
        contract["argv"] = (
            r"C:\hostile\complete_suite_artifact_writer.py",
            *contract["argv"][1:],
        )
    elif mutation == "argv-option":
        contract["argv"] = (contract["argv"][0], "--request", "a" * 64)
    elif mutation == "argv-hash":
        contract["argv"] = (*contract["argv"][:2], "A" * 64)
    elif mutation == "environment-name-case":
        contract["environment"] = {
            "SystemRoot": r"C:\Windows",
            "WINDIR": r"C:\Windows",
        }
    elif mutation == "environment-value":
        contract["environment"] = {
            "SYSTEMROOT": r"C:\WINDOWS",
            "WINDIR": r"C:\Windows",
        }
    else:
        contract["environment"] = {
            **contract["environment"],
            "PATH": r"C:\hostile",
        }

    with pytest.raises(RuntimeError, match=r"^artifact inner runtime drift$"):
        writer.validate_artifact_writer_early_runtime_contract(**contract)


def test_artifact_writer_installs_audit_hook_before_any_nonfrozen_import() -> None:
    tree = ast.parse(WRITER_PATH.read_text(encoding="utf-8"))
    runtime_import_lines = tuple(
        node.lineno
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and not (
            isinstance(node, ast.Import)
            and tuple(alias.name for alias in node.names) in {("sys",), ("os",)}
        )
    )
    early_gate_line: int | None = None
    audit_hook_line: int | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == (
            "_run_artifact_writer_early_runtime_gate"
        ):
            early_gate_line = node.lineno
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "sys"
            and node.func.attr == "addaudithook"
        ):
            assert len(node.args) == 1
            assert isinstance(node.args[0], ast.Name)
            assert node.args[0].id == "_artifact_writer_audit_hook"
            audit_hook_line = node.lineno

    assert runtime_import_lines
    assert early_gate_line is not None
    assert audit_hook_line is not None
    assert early_gate_line < audit_hook_line < min(runtime_import_lines)


def test_artifact_writer_audit_hook_default_denies_unlisted_events() -> None:
    writer = _writer()

    with pytest.raises(RuntimeError, match=r"^artifact audit policy violation$"):
        writer.validate_artifact_writer_audit_event(
            event="synthetic.unlisted",
            arguments=(),
            phase="sealed",
        )


@pytest.mark.parametrize(
    "event",
    (
        "subprocess.Popen",
        "os.system",
        "os.exec",
        "os.spawn",
        "os.posix_spawn",
        "os.startfile",
        "_winapi.CreateProcess",
        "socket.connect",
        "socket.getaddrinfo",
        "http.client.connect",
        "urllib.Request",
        "os.putenv",
        "os.unsetenv",
        "os.chdir",
        "os.fchdir",
        "os.mkdir",
        "os.remove",
        "os.rename",
        "os.rmdir",
        "os.link",
        "os.symlink",
        "os.truncate",
        "os.utime",
        "os.listdir",
        "os.scandir",
        "glob.glob",
        "pathlib.Path.glob",
        "tempfile.mkstemp",
        "shutil.copyfile",
        "sys.settrace",
        "sys.setprofile",
        "sys.addaudithook",
        "builtins.breakpoint",
    ),
)
def test_artifact_writer_audit_hook_rejects_forbidden_event_families(
    event: str,
) -> None:
    writer = _writer()

    for phase in ("imports", "native", "sealed"):
        with pytest.raises(
            RuntimeError,
            match=r"^artifact audit policy violation$",
        ):
            writer.validate_artifact_writer_audit_event(
                event=event,
                arguments=("synthetic-private-value",),
                phase=phase,
            )


def test_artifact_writer_audit_rejection_does_not_disclose_arguments() -> None:
    writer = _writer()
    secret = "synthetic-private-audit-canary"

    with pytest.raises(RuntimeError) as error:
        writer.validate_artifact_writer_audit_event(
            event="synthetic.unlisted",
            arguments=(secret,),
            phase="sealed",
        )

    assert str(error.value) == "artifact audit policy violation"
    assert secret not in str(error.value)


def test_artifact_writer_audit_hook_allows_only_exact_source_import_events() -> None:
    writer = _writer()
    import_arguments = (
        "base64",
        None,
        list(writer._ARTIFACT_WRITER_EARLY_SYS_PATH),
        [],
        [],
    )

    assert writer.validate_artifact_writer_audit_event(
        event="import",
        arguments=import_arguments,
        phase="imports",
    ) is None
    assert writer.validate_artifact_writer_audit_event(
        event="open",
        arguments=(r"C:\Python314\Lib\base64.py", "r", 32896),
        phase="imports",
    ) is None
    assert writer.validate_artifact_writer_audit_event(
        event="compile",
        arguments=(b"synthetic source", r"C:\Python314\Lib\base64.py"),
        phase="imports",
    ) is None

    code = compile("value = 1", r"C:\Python314\Lib\base64.py", "exec")
    assert writer.validate_artifact_writer_audit_event(
        event="exec",
        arguments=(code,),
        phase="imports",
    ) is None
    assert writer.validate_artifact_writer_audit_event(
        event="os.listdir",
        arguments=(r"C:\Python314\Lib",),
        phase="imports",
    ) is None
    assert writer.validate_artifact_writer_audit_event(
        event="import",
        arguments=(
            "encodings.utf_16_le",
            None,
            list(writer._ARTIFACT_WRITER_EARLY_SYS_PATH),
            [],
            [],
        ),
        phase="imports",
    ) is None
    assert writer.validate_artifact_writer_audit_event(
        event="open",
        arguments=(r"C:\Python314\Lib\encodings\utf_16_le.py", "r", 32896),
        phase="imports",
    ) is None
    assert writer.validate_artifact_writer_audit_event(
        event="os.listdir",
        arguments=(r"C:\Python314\Lib\encodings",),
        phase="imports",
    ) is None

    dynamic_source = (
        b"lambda _cls, hits, misses, maxsize, currsize: "
        b"_tuple_new(_cls, (hits, misses, maxsize, currsize))"
    )
    assert writer.validate_artifact_writer_audit_event(
        event="compile",
        arguments=(dynamic_source, "<string>"),
        phase="imports",
    ) is None
    assert writer.validate_artifact_writer_audit_event(
        event="exec",
        arguments=(
            compile(
                dynamic_source,
                "<string>",
                "eval",
                dont_inherit=True,
            ),
        ),
        phase="imports",
    ) is None


@pytest.mark.parametrize(
    ("event", "arguments"),
    (
        (
            "import",
            ("socket", None, list((r"C:\Python314",)), [], []),
        ),
        (
            "import",
            (
                "base64",
                None,
                list(
                    (
                        r"C:\Python314\python314.zip",
                        r"C:\Python314\DLLs",
                        r"C:\Python314\Lib",
                        r"C:\Python314",
                        r"D:\shadow",
                    )
                ),
                [],
                [],
            ),
        ),
        (
            "open",
            (r"C:\Python314\Lib\__pycache__\base64.cpython-314.pyc", "r", 32896),
        ),
        ("open", (r"C:\Python314\Lib\base64.py", "w", 32897)),
        ("open", (r"C:\Python314\LibEvil\base64.py", "r", 32896)),
        ("compile", (b"synthetic", "<stdin>")),
        ("compile", (b"synthetic", "<string>")),
        ("exec", (compile("value = 1", "<stdin>", "exec"),)),
        ("exec", (compile("value = 1", "<string>", "exec"),)),
        ("os.listdir", (r"C:\Python314\LibEvil",)),
        ("marshal.loads", (b"x" * 6234,)),
    ),
)
def test_artifact_writer_audit_hook_rejects_import_path_or_shape_drift(
    event: str,
    arguments: tuple[object, ...],
) -> None:
    writer = _writer()

    with pytest.raises(RuntimeError, match=r"^artifact audit policy violation$"):
        writer.validate_artifact_writer_audit_event(
            event=event,
            arguments=arguments,
            phase="imports",
        )


def test_artifact_writer_audit_import_counts_are_exact_and_closed() -> None:
    writer = _writer()
    counts = dict(writer.ARTIFACT_WRITER_AUDIT_IMPORT_EVENT_COUNTS)

    assert counts == {
        "import": 42,
        "os.listdir": 6,
        "open": 27,
        "compile": 28,
        "exec": 28,
        "ctypes.dlopen": 1,
        "ctypes.dlsym": 1,
        "sys._getframemodulename": 1,
        "object.__setattr__": 1,
    }
    assert writer.validate_artifact_writer_audit_import_counts(counts) is None

    for mutation in ("missing", "extra", "lower", "higher", "bool"):
        changed: dict[str, object] = dict(counts)
        if mutation == "missing":
            changed.pop("open")
        elif mutation == "extra":
            changed["synthetic.unlisted"] = 1
        elif mutation == "lower":
            changed["open"] = counts["open"] - 1
        elif mutation == "higher":
            changed["open"] = counts["open"] + 1
        else:
            changed["open"] = True
        with pytest.raises(RuntimeError, match=r"^artifact audit policy violation$"):
            writer.validate_artifact_writer_audit_import_counts(changed)


def test_artifact_writer_source_only_loader_has_no_bytecode_lane() -> None:
    source = WRITER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    loader = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "_ArtifactWriterSourceOnlyLoader"
    )
    calls = {
        node.func.attr
        for node in ast.walk(loader)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert {"get_filename", "get_data", "source_to_code"} <= calls
    assert "SourcelessFileLoader" not in source
    assert "pycache_prefix" not in source


class _SyntheticAuditLibrary:
    def __init__(self, name: str) -> None:
        self._name = name


def test_artifact_writer_audit_hook_requires_exact_absolute_system_dlls_and_symbols() -> None:
    writer = _writer()

    for dll_path, symbols in writer.ARTIFACT_WRITER_NATIVE_SYMBOLS_BY_DLL:
        assert writer.validate_artifact_writer_audit_event(
            event="ctypes.dlopen",
            arguments=(dll_path,),
            phase="native",
        ) is None
        library = _SyntheticAuditLibrary(dll_path)
        for symbol in symbols:
            assert writer.validate_artifact_writer_audit_event(
                event="ctypes.dlsym",
                arguments=(library, symbol),
                phase="native",
            ) is None

    for bad_path in (
        "kernel32",
        "kernel32.dll",
        r"C:\Windows\kernel32.dll",
        r"C:\Windows\System32\kernel32.DLL",
        r"D:\shadow\kernel32.dll",
    ):
        with pytest.raises(RuntimeError, match=r"^artifact audit policy violation$"):
            writer.validate_artifact_writer_audit_event(
                event="ctypes.dlopen",
                arguments=(bad_path,),
                phase="native",
            )

    with pytest.raises(RuntimeError, match=r"^artifact audit policy violation$"):
        writer.validate_artifact_writer_audit_event(
            event="ctypes.dlsym",
            arguments=(
                _SyntheticAuditLibrary(r"C:\Windows\System32\kernel32.dll"),
                "CreateProcessW",
            ),
            phase="native",
        )


def test_artifact_writer_audit_native_trace_is_exact_and_ordered() -> None:
    writer = _writer()
    trace = writer.ARTIFACT_WRITER_AUDIT_NATIVE_EVENTS

    assert type(trace) is tuple
    assert len(trace) == 20
    assert writer.validate_artifact_writer_audit_native_trace(trace) is None

    for changed in (
        trace[:-1],
        (*trace, ("ctypes.dlopen", r"D:\shadow\evil.dll", None)),
        (trace[1], trace[0], *trace[2:]),
        (*trace[:-1], (trace[-1][0], trace[-1][1], "CreateProcessW")),
    ):
        with pytest.raises(RuntimeError, match=r"^artifact audit policy violation$"):
            writer.validate_artifact_writer_audit_native_trace(changed)


def test_artifact_writer_publication_audit_accepts_only_bounded_native_events() -> None:
    writer = _writer()
    call_arities = ((4096, 3), (8192, 0))
    content_buffer = (writer.ctypes.c_ubyte * 3).from_buffer_copy(b"abc")
    events = (
        ("ctypes.create_unicode_buffer", (None, 32_768)),
        ("ctypes.create_unicode_buffer", ("abc", 4)),
        ("ctypes.call_function", (4096, (None, None, None))),
        ("ctypes.call_function", (8192, ())),
        ("ctypes.get_last_error", ()),
        ("ctypes.cdata/buffer", (4096, 3, 0)),
        ("ctypes.addressof", (content_buffer,)),
    )

    for event, arguments in events:
        assert writer.validate_artifact_writer_publication_audit_event(
            event=event,
            arguments=arguments,
            authorized_call_arities=call_arities,
        ) is None

    writer._ARTIFACT_WRITER_AUDIT_PUBLICATION_CALL_ARITIES = call_arities
    assert writer.validate_artifact_writer_audit_event(
        event="ctypes.call_function",
        arguments=(4096, (None, None, None)),
        phase="publication",
    ) is None


@pytest.mark.parametrize(
    ("event", "arguments"),
    (
        ("import", ("encodings.utf_16_le",)),
        ("open", (r"C:\Python314\Lib\encodings\utf_16_le.py", "r", 32896)),
        ("ctypes.dlopen", (r"C:\Windows\System32\kernel32.dll",)),
        ("ctypes.create_unicode_buffer", (None, 0)),
        ("ctypes.create_unicode_buffer", (None, 32_769)),
        ("ctypes.create_unicode_buffer", ("abc", 3)),
        ("ctypes.create_unicode_buffer", ("a\x00b", 4)),
        ("ctypes.create_unicode_buffer", (b"abc", 4)),
        ("ctypes.create_unicode_buffer", (None, True)),
        ("ctypes.call_function", (12_288, ())),
        ("ctypes.call_function", (4096, (None, None))),
        ("ctypes.call_function", (True, (None, None, None))),
        ("ctypes.call_function", (4096, [None, None, None])),
        ("ctypes.get_last_error", (0,)),
        ("ctypes.cdata/buffer", (0, 3, 0)),
        ("ctypes.cdata/buffer", (4096, 0, 0)),
        ("ctypes.cdata/buffer", (4096, 262_145, 0)),
        ("ctypes.cdata/buffer", (4096, 3, 1)),
        ("ctypes.addressof", (object(),)),
    ),
)
def test_artifact_writer_publication_audit_rejects_event_or_shape_drift(
    event: str,
    arguments: tuple[object, ...],
) -> None:
    writer = _writer()

    with pytest.raises(RuntimeError, match=r"^artifact audit policy violation$"):
        writer.validate_artifact_writer_publication_audit_event(
            event=event,
            arguments=arguments,
            authorized_call_arities=((4096, 3), (8192, 0)),
        )


@pytest.mark.parametrize(
    "call_arities",
    (
        [(4096, 3)],
        ((4096, 3, 0),),
        ((True, 3),),
        ((0, 3),),
        ((4096, True),),
        ((4096, 12),),
        ((4096, 3), (4096, 3)),
    ),
)
def test_artifact_writer_publication_audit_rejects_call_authority_drift(
    call_arities: object,
) -> None:
    writer = _writer()

    with pytest.raises(RuntimeError, match=r"^artifact audit policy violation$"):
        writer.validate_artifact_writer_publication_audit_event(
            event="ctypes.call_function",
            arguments=(4096, (None, None, None)),
            authorized_call_arities=call_arities,
        )


def test_artifact_writer_has_no_runtime_audit_diagnostics_or_blanket_publication_allow() -> None:
    source = WRITER_PATH.read_text(encoding="utf-8")

    assert "_ARTIFACT_WRITER_PUBLICATION_DIAGNOSTIC" not in source
    assert "ARTIFACT_WRITER_AUDIT_DIAGNOSTIC" not in source
    assert "ARTIFACT_WRITER_AUDIT_COUNT_DIAGNOSTIC" not in source


def _valid_loaded_module_records() -> tuple[tuple[str, str | None, str | None], ...]:
    writer = _writer()
    helper = r"D:\task9-detached\tests\skills\complete_suite_artifact_writer.py"
    return tuple(
        (name, origin, helper if source_path == "$HELPER" else source_path)
        for name, origin, source_path in writer.ARTIFACT_WRITER_LOADED_MODULE_ORIGINS
    )


def test_artifact_writer_loaded_module_table_is_exact_closed_python314_trace() -> None:
    writer = _writer()
    table = writer.ARTIFACT_WRITER_LOADED_MODULE_ORIGINS

    assert type(table) is tuple
    assert len(table) == 73
    assert table[0] == ("sys", "built-in", None)
    assert table[21] == ("__main__", None, "$HELPER")
    assert not {"__future__", "dataclasses", "typing"} & {
        record[0] for record in table
    }
    wintypes_index = next(
        index for index, record in enumerate(table) if record[0] == "ctypes.wintypes"
    )
    assert table[wintypes_index + 1] == (
        "encodings.utf_16_le",
        r"C:\Python314\Lib\encodings\utf_16_le.py",
        r"C:\Python314\Lib\encodings\utf_16_le.py",
    )
    assert table[-1] == (
        "json",
        r"C:\Python314\Lib\json\__init__.py",
        r"C:\Python314\Lib\json\__init__.py",
    )
    assert len({record[0] for record in table}) == len(table)


def test_artifact_writer_loaded_module_origins_accept_exact_runtime_members() -> None:
    writer = _writer()
    records = _valid_loaded_module_records()
    helper = next(record[2] for record in records if record[0] == "__main__")

    assert writer.validate_artifact_writer_loaded_module_origins(
        records=records,
        helper_path=helper,
    ) is None


@pytest.mark.parametrize(
    "mutation",
    (
        "missing-main",
        "duplicate-name",
        "extra-module",
        "reordered-module",
        "missing-required",
        "main-origin",
        "main-file",
        "builtin-file",
        "frozen-origin-case",
        "frozen-outside-runtime",
        "source-outside-runtime",
        "source-origin-file-mismatch",
        "source-forward-slash",
        "source-root-case",
        "source-dot-segment",
        "source-bytecode",
        "namespace-origin",
        "record-shape",
    ),
)
def test_artifact_writer_loaded_module_origins_reject_drift(mutation: str) -> None:
    writer = _writer()
    records: list[object] = list(_valid_loaded_module_records())
    helper = next(record[2] for record in records if record[0] == "__main__")
    if mutation == "missing-main":
        records = [record for record in records if record[0] != "__main__"]
    elif mutation == "duplicate-name":
        records.append(records[-1])
    elif mutation == "extra-module":
        records.append(("synthetic_extra", "built-in", None))
    elif mutation == "reordered-module":
        records[0], records[1] = records[1], records[0]
    elif mutation == "missing-required":
        records = [record for record in records if record[0] != "json"]
    elif mutation == "main-origin":
        index = next(i for i, record in enumerate(records) if record[0] == "__main__")
        records[index] = ("__main__", helper, helper)
    elif mutation == "main-file":
        index = next(i for i, record in enumerate(records) if record[0] == "__main__")
        records[index] = ("__main__", None, r"D:\other\writer.py")
    elif mutation == "builtin-file":
        index = next(i for i, record in enumerate(records) if record[0] == "_abc")
        records[index] = ("_abc", "built-in", r"C:\Python314\Lib\abc.py")
    elif mutation == "frozen-origin-case":
        index = next(i for i, record in enumerate(records) if record[0] == "_collections_abc")
        records[index] = ("_collections_abc", "Frozen", records[index][2])
    elif mutation == "frozen-outside-runtime":
        index = next(i for i, record in enumerate(records) if record[0] == "_collections_abc")
        records[index] = ("_collections_abc", "frozen", r"D:\shadow\_collections_abc.py")
    elif mutation == "source-outside-runtime":
        index = next(i for i, record in enumerate(records) if record[0] == "base64")
        records[index] = ("base64", r"D:\shadow\base64.py", r"D:\shadow\base64.py")
    elif mutation == "source-origin-file-mismatch":
        index = next(i for i, record in enumerate(records) if record[0] == "base64")
        records[index] = ("base64", records[index][1], r"C:\Python314\Lib\base85.py")
    elif mutation == "source-forward-slash":
        index = next(i for i, record in enumerate(records) if record[0] == "base64")
        path = r"C:\Python314\Lib\base64.py".replace("\\", "/")
        records[index] = ("base64", path, path)
    elif mutation == "source-root-case":
        index = next(i for i, record in enumerate(records) if record[0] == "base64")
        path = r"C:\python314\Lib\base64.py"
        records[index] = ("base64", path, path)
    elif mutation == "source-dot-segment":
        index = next(i for i, record in enumerate(records) if record[0] == "base64")
        path = r"C:\Python314\Lib\re\..\base64.py"
        records[index] = ("base64", path, path)
    elif mutation == "source-bytecode":
        index = next(i for i, record in enumerate(records) if record[0] == "base64")
        path = r"C:\Python314\Lib\__pycache__\base64.cpython-314.pyc"
        records[index] = ("base64", path, path)
    elif mutation == "namespace-origin":
        index = next(i for i, record in enumerate(records) if record[0] == "base64")
        records[index] = ("base64", None, None)
    else:
        index = next(i for i, record in enumerate(records) if record[0] == "base64")
        records[index] = ("base64", records[index][1])

    with pytest.raises(RuntimeError, match=r"^artifact module origin drift$"):
        writer.validate_artifact_writer_loaded_module_origins(
            records=tuple(records),
            helper_path=helper,
        )


def test_artifact_writer_loaded_module_origin_gate_precedes_native_and_stdin() -> None:
    source = WRITER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    main = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_artifact_writer_main"
    )
    calls = [
        node.func.id
        for node in ast.walk(main)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]

    assert calls.index("validate_artifact_writer_loaded_module_origins") < calls.index(
        "_ArtifactWriterNativeApi"
    )
    assert calls.index("validate_artifact_writer_loaded_module_origins") < calls.index(
        "decode_artifact_writer_request"
    )


@pytest.mark.parametrize(
    "outer_name",
    (
        "PATH",
        "PSModulePath",
        "PSModuleAnalysisCachePath",
        "HTTPS_PROXY",
        "SSL_CERT_FILE",
        "AWS_SECRET_ACCESS_KEY",
        "AZURE_CLIENT_SECRET",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "NPM_CONFIG_USERCONFIG",
        "PIP_CONFIG_FILE",
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PYTHONINSPECT",
        "NODE_OPTIONS",
        "GIT_CONFIG_GLOBAL",
        "USERPROFILE",
        "HOME",
        "APPDATA",
        "LOCALAPPDATA",
        "TEMP",
        "TMP",
        "CODEX_HOME",
        "CODEX_TOKEN",
        "POWERSHELL_TELEMETRY_OPTOUT",
        "POWERSHELL_UPDATECHECK",
    ),
)
def test_artifact_writer_isolates_python_child_environment(outer_name: str) -> None:
    writer = _writer()
    outer_environment = _KeysOnlyEnvironment((outer_name,))

    marker = writer.validate_artifact_writer_outer_environment_names(outer_environment)
    child_environment = writer.build_artifact_writer_child_environment()

    assert marker == OUTER_ENVIRONMENT_MARKER
    assert tuple(child_environment.items()) == CHILD_ENVIRONMENT_ITEMS
    assert outer_name not in child_environment
    assert "synthetic-private-value" not in child_environment.values()
    assert writer.validate_artifact_writer_child_environment(child_environment) is None
    assert outer_environment.value_access_count == 0
    assert outer_environment.entry_enumeration_count == 0


@pytest.mark.parametrize(
    "mutation",
    (
        "remove-systemroot",
        "remove-windir",
        "systemroot-case",
        "windir-case",
        "systemroot-value",
        "windir-value",
        "extra-name",
        "reverse-order",
        "transfer-outer",
    ),
)
def test_artifact_writer_rejects_inner_environment_drift(mutation: str) -> None:
    writer = _writer()
    environment = writer.build_artifact_writer_child_environment()
    if mutation == "remove-systemroot":
        environment.pop("SYSTEMROOT")
    elif mutation == "remove-windir":
        environment.pop("WINDIR")
    elif mutation == "systemroot-case":
        environment["systemroot"] = environment.pop("SYSTEMROOT")
    elif mutation == "windir-case":
        environment["windir"] = environment.pop("WINDIR")
    elif mutation == "systemroot-value":
        environment["SYSTEMROOT"] = r"C:\WINDOWS"
    elif mutation == "windir-value":
        environment["WINDIR"] = r"D:\Windows"
    elif mutation == "extra-name":
        environment["PATH"] = r"C:\hostile"
    elif mutation == "reverse-order":
        environment = dict(reversed(tuple(environment.items())))
    else:
        environment["SECRET"] = "synthetic-private-value"

    with pytest.raises(
        RuntimeError,
        match=r"^artifact inner environment drift$",
    ) as error:
        writer.validate_artifact_writer_child_environment(environment)

    assert "synthetic-private-value" not in str(error.value)
    assert tuple(environment) != ("SYSTEMROOT", "WINDIR") or tuple(
        environment.items()
    ) != CHILD_ENVIRONMENT_ITEMS


def test_artifact_writer_rejects_any_powershell_command_or_module_resolution() -> None:
    assert LAUNCHER_PATH.is_file()
    raw = LAUNCHER_PATH.read_bytes()
    assert 1 <= len(raw) <= 1_048_576
    assert raw.endswith(b"\n")
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in raw
    assert b"\x00" not in raw
    source = raw.decode("utf-8", errors="strict")
    assert source.encode("utf-8") == raw
    for required in (
        "$ErrorActionPreference='Stop'",
        "$script:C6ArtifactLauncherRevision='complete-suite-artifact-launcher-v1'",
        "$script:C6ArtifactPythonPath='C:\\Python314\\python.exe'",
        "$script:C6ArtifactPythonArguments=[string[]]@('-I','-S','-B','-X','utf8')",
        "$script:C6ArtifactChildEnvironment=[ordered]@{",
        "SYSTEMROOT='C:\\Windows'",
        "WINDIR='C:\\Windows'",
        "$script:C6ArtifactRequestCapBytes=524288",
        "$script:C6ArtifactOutputCapBytes=65536",
        "$script:C6ArtifactDeadlineMilliseconds=120000",
        "$script:C6ArtifactTerminationGraceMilliseconds=5000",
        "$script:C6ArtifactFrameHeaderCharacters=94",
        "$script:C6ArtifactFramePayloadCapCharacters=699052",
        "$script:C6ArtifactFrameTotalCapCharacters=699146",
        "$script:C6ArtifactNativeVectorCapUtf16Units=30000",
    ):
        assert required in source

    completed = subprocess.run(
        (
            SHELL_PATH,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            POWERSHELL_AST_NODE_AUDIT,
        ),
        input=source,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    node_types = tuple(completed.stdout.splitlines())
    assert "CommandAst" not in node_types
    assert "FunctionDefinitionAst" not in node_types
    assert "UsingStatementAst" not in node_types

    lowered = source.casefold()
    for forbidden in (
        "#requires",
        "add-type",
        "get-childitem",
        "sort-object",
        "import-module",
        "get-module",
        "invoke-expression",
        "new-object",
        "start-process",
        "scriptblock]::create",
        "using module",
        "using namespace",
        "psmodulepath",
        ".psm1",
    ):
        assert forbidden not in lowered


def test_artifact_writer_frame_accepts_exact_max_and_rejects_one_over(
    tmp_path: Path,
) -> None:
    maximum_request = b'{"p":"' + (b"a" * 524_279) + b'"}\n'
    assert len(maximum_request) == 524_288
    maximum_frame = _canonical_artifact_frame(maximum_request)
    assert len(maximum_frame) == 699_146

    completed = _run_launcher_frame_validation(tmp_path, maximum_frame)

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert completed.stdout == (
        f"524288:{sha256(maximum_request).hexdigest()}"
    )

    one_over_request = b'{"p":"' + (b"a" * 524_280) + b'"}\n'
    assert len(one_over_request) == 524_289
    one_over_frame = _canonical_artifact_frame(one_over_request)
    assert len(one_over_frame) == 699_146

    rejected = _run_launcher_frame_validation(tmp_path, one_over_frame)

    assert rejected.returncode != 0
    assert rejected.stdout == ""

    source = LAUNCHER_PATH.read_text(encoding="utf-8")
    _assert_launcher_frame_dominance(source)
    allocation_begin = source.index(FRAME_ALLOCATION_BEGIN)
    allocation_end = source.index(FRAME_ALLOCATION_END) + len(FRAME_ALLOCATION_END)
    allocation_region = source[allocation_begin:allocation_end]
    without_allocation = source[:allocation_begin] + source[allocation_end:]
    reordered = without_allocation.replace(
        FRAME_HEADER_BEGIN,
        allocation_region + "\n" + FRAME_HEADER_BEGIN,
        1,
    )
    with pytest.raises(AssertionError):
        _assert_launcher_frame_dominance(reordered)


@pytest.mark.parametrize(
    "mutation",
    (
        "truncated-header",
        "truncated-payload",
        "duplicated",
        "prefix",
        "total-field",
        "request-field",
        "payload-field",
        "uppercase-hash",
        "wrong-hash",
        "corrupt-payload",
        "noncanonical-base64",
        "nul-payload",
        "invalid-json",
    ),
)
def test_artifact_writer_frame_rejects_truncated_duplicated_or_corrupted_input(
    tmp_path: Path,
    mutation: str,
) -> None:
    request = b'{"p":"ok"}\n'
    frame = _canonical_artifact_frame(request)
    fields = frame.split(":", 5)
    assert len(fields) == 6
    if mutation == "truncated-header":
        changed = frame[:93]
    elif mutation == "truncated-payload":
        changed = frame[:-1]
    elif mutation == "duplicated":
        changed = frame + frame
    elif mutation == "prefix":
        changed = "C7ARF1:" + frame[7:]
    elif mutation == "total-field":
        changed = _replace_artifact_frame_field(
            frame,
            1,
            f"{int(fields[1]) + 1:07d}",
        )
    elif mutation == "request-field":
        changed = _replace_artifact_frame_field(
            frame,
            2,
            f"{len(request) - 1:06d}",
        )
    elif mutation == "payload-field":
        changed = _replace_artifact_frame_field(
            frame,
            3,
            f"{len(fields[5]) - 1:06d}",
        )
    elif mutation == "uppercase-hash":
        changed = _replace_artifact_frame_field(
            frame,
            4,
            "A" + fields[4][1:],
        )
    elif mutation == "wrong-hash":
        replacement = "0" if fields[4][0] != "0" else "1"
        changed = _replace_artifact_frame_field(
            frame,
            4,
            replacement + fields[4][1:],
        )
    elif mutation == "corrupt-payload":
        replacement = "A" if fields[5][0] != "A" else "B"
        changed = frame[:94] + replacement + fields[5][1:]
    elif mutation == "noncanonical-base64":
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        payload = fields[5]
        data_index = len(payload.rstrip("=")) - 1
        sextet = alphabet.index(payload[data_index])
        assert sextet % 4 == 0
        noncanonical = (
            payload[:data_index]
            + alphabet[sextet + 1]
            + payload[data_index + 1 :]
        )
        assert base64.b64decode(noncanonical) == request
        changed = frame[:94] + noncanonical
    elif mutation == "nul-payload":
        changed = frame[:94] + "\x00" + fields[5][1:]
    else:
        changed = _canonical_artifact_frame(b'{"p": }\n')

    completed = _run_launcher_frame_validation(tmp_path, changed)

    assert completed.returncode != 0
    assert completed.stdout == ""


def test_artifact_writer_native_vector_accepts_30000_rejects_30001(
    tmp_path: Path,
) -> None:
    executable = r"C:\Program Files\Python\python.exe"
    arguments = (
        "",
        "plain",
        "has space",
        "has\ttab",
        'embedded"quote',
        "trailing\\",
        'slashes\\\\"quote',
        "non-bmp-\U0001f642",
    )
    expected_units, expected_hash = _independent_windows_native_vector(
        executable,
        arguments,
    )

    completed = _run_launcher_native_vector_validation(
        tmp_path,
        executable=executable,
        arguments=arguments,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert completed.stdout == (
        "complete-suite-windows-native-vector-v1:"
        f"{expected_units}:{expected_hash}"
    )

    boundary_executable = r"C:\x.exe"
    fixed_units = len(boundary_executable.encode("utf-16-le")) // 2 + 2
    exact_argument = "a" * (30_000 - fixed_units)
    exact_units, exact_hash = _independent_windows_native_vector(
        boundary_executable,
        (exact_argument,),
    )
    assert exact_units == 30_000

    exact = _run_launcher_native_vector_validation(
        tmp_path,
        executable=boundary_executable,
        arguments=(exact_argument,),
    )

    assert exact.returncode == 0, exact.stderr
    assert exact.stderr == ""
    assert exact.stdout == (
        "complete-suite-windows-native-vector-v1:30000:" + exact_hash
    )

    one_over = _run_launcher_native_vector_validation(
        tmp_path,
        executable=boundary_executable,
        arguments=(exact_argument + "a",),
    )

    assert one_over.returncode != 0
    assert one_over.stdout == ""

    source = LAUNCHER_PATH.read_text(encoding="utf-8")
    _assert_launcher_native_vector_dominance(source)
    constructor = (
        "$script:C6ArtifactStartInfo="
        "[System.Diagnostics.ProcessStartInfo]::new()\n"
    )
    reordered = source.replace(
        NATIVE_VECTOR_BEGIN,
        constructor + NATIVE_VECTOR_BEGIN,
        1,
    )
    with pytest.raises(AssertionError):
        _assert_launcher_native_vector_dominance(reordered)


@pytest.mark.parametrize(
    ("executable", "arguments"),
    (
        (None, ("ok",)),
        (7, ("ok",)),
        ("", ("ok",)),
        ("python.exe", ("ok",)),
        ("C:\\x\x00.exe", ("ok",)),
        ("\ud800", ("ok",)),
        ("\udfff", ("ok",)),
        (r"C:\x.exe", None),
        (r"C:\x.exe", "scalar"),
        (r"C:\x.exe", (None,)),
        (r"C:\x.exe", (7,)),
        (r"C:\x.exe", ("nul\x00",)),
        (r"C:\x.exe", ("\ud800",)),
        (r"C:\x.exe", ("\udfff",)),
        (r"C:\x.exe", ("\ud800\ud800",)),
        (r"C:\x.exe", ("\ud800a",)),
        (r"C:\x.exe", ("a\ud800",)),
    ),
    ids=(
        "null-executable",
        "non-string-executable",
        "empty-executable",
        "relative-executable",
        "nul-executable",
        "high-surrogate-executable",
        "low-surrogate-executable",
        "null-argument-list",
        "scalar-argument-list",
        "null-argument",
        "non-string-argument",
        "nul-argument",
        "high-surrogate-argument",
        "low-surrogate-argument",
        "high-high-argument",
        "high-ordinary-argument",
        "trailing-high-argument",
    ),
)
def test_artifact_writer_rejects_native_vector_budget_bypass(
    tmp_path: Path,
    executable: object,
    arguments: object,
) -> None:
    completed = _run_launcher_native_vector_validation(
        tmp_path,
        executable=executable,
        arguments=arguments,
    )

    assert completed.returncode != 0
    assert completed.stdout == ""


def test_artifact_writer_launcher_accepts_exact_synthetic_one_child_lifecycle(
    tmp_path: Path,
) -> None:
    request = b'{"p":"synthetic"}\n'
    expected_output_path = str(tmp_path / "synthetic-result.txt")
    helper_path = _write_synthetic_launcher_child(
        tmp_path,
        behavior="success",
        request=request,
        expected_output_path=expected_output_path,
    )
    before_members = {entry.name for entry in tmp_path.iterdir()}

    completed = _run_launcher_child_lifecycle(
        tmp_path,
        request=request,
        expected_output_path=expected_output_path,
        helper_path=helper_path,
        working_directory=tmp_path,
    )

    expected_stdout = expected_output_path.encode("utf-8") + b"\n"
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert completed.stdout == (
        f"ok:0:{len(expected_stdout)}:{sha256(expected_stdout).hexdigest()}"
    )
    assert not Path(expected_output_path).exists()
    after_members = {entry.name for entry in tmp_path.iterdir()}
    assert after_members - before_members == {"child-lifecycle-harness.ps1"}
    _assert_launcher_child_dominance(
        LAUNCHER_PATH.read_text(encoding="utf-8")
    )


@pytest.mark.parametrize(
    "behavior",
    (
        "nonzero",
        "timeout",
        "closed-pipes-timeout",
        "dual-pressure",
        "stdout-cap",
        "stderr-cap",
        "malformed-stdout",
        "malformed-stderr",
        "stderr-nonempty",
        "wrong-output",
        "crlf-output",
        "extra-output",
    ),
)
def test_artifact_writer_launcher_rejects_nonzero_timeout_or_output_cap(
    tmp_path: Path,
    behavior: str,
) -> None:
    request = b'{"p":"synthetic-failure"}\n'
    expected_output_path = str(tmp_path / "synthetic-result.txt")
    helper_path = _write_synthetic_launcher_child(
        tmp_path,
        behavior=behavior,
        request=request,
        expected_output_path=expected_output_path,
    )
    before_members = {entry.name for entry in tmp_path.iterdir()}
    started = time.monotonic()

    completed = _run_launcher_child_lifecycle(
        tmp_path,
        request=request,
        expected_output_path=expected_output_path,
        helper_path=helper_path,
        working_directory=tmp_path,
        deadline_ms=(
            250
            if behavior in {"timeout", "closed-pipes-timeout"}
            else 5_000
        ),
    )
    elapsed = time.monotonic() - started

    assert completed.returncode != 0
    assert completed.stdout == ""
    if behavior == "closed-pipes-timeout":
        assert elapsed < 5.75
    if behavior == "dual-pressure":
        assert elapsed < 4.5
    assert not Path(expected_output_path).exists()
    after_members = {entry.name for entry in tmp_path.iterdir()}
    assert after_members - before_members == {"child-lifecycle-harness.ps1"}


def test_artifact_writer_rejects_unexpected_extra_child() -> None:
    source = LAUNCHER_PATH.read_text(encoding="utf-8")
    _assert_launcher_child_dominance(source)
    construction = source[
        source.index(FRAME_PAYLOAD_END) : source.index(NATIVE_VECTOR_BEGIN)
    ]
    for required in (
        "'-I'",
        "'-S'",
        "'-B'",
        "'-X'",
        "'utf8'",
        "$script:C6ArtifactAuthenticatedWriterPath",
        "'--expected-request-sha256'",
        "$script:C6ArtifactValidatedRequestSha256",
    ):
        assert required in construction

    second_static_start = source.replace(
        CHILD_LIFECYCLE_END,
        (
            "$script:C6ArtifactSecondProcess="
            "[Diagnostics.Process]::Start($script:C6ArtifactStartInfo)\n"
            + CHILD_LIFECYCLE_END
        ),
        1,
    )
    with pytest.raises(AssertionError):
        _assert_launcher_child_dominance(second_static_start)

    second_instance_start = source.replace(
        CHILD_LIFECYCLE_END,
        "$script:C6ArtifactProcess.Start()\n" + CHILD_LIFECYCLE_END,
        1,
    )
    with pytest.raises(AssertionError):
        _assert_launcher_child_dominance(second_instance_start)

    reflection_start = source.replace(
        CHILD_LIFECYCLE_END,
        (
            "[System.Diagnostics.Process].InvokeMember("
            "'Start',[Reflection.BindingFlags]::InvokeMethod,$null,$null,@())\n"
            + CHILD_LIFECYCLE_END
        ),
        1,
    )
    with pytest.raises(AssertionError):
        _assert_launcher_child_dominance(reflection_start)

    child_begin = source.index(CHILD_LIFECYCLE_BEGIN)
    child_end = source.index(CHILD_LIFECYCLE_END)
    child_region = source[child_begin:child_end]
    raw_child_region = child_region.replace(
        "$script:C6ArtifactValidatedNativeExecutable",
        "$script:C6ArtifactNativeExecutable",
        1,
    )
    raw_snapshot_mutant = (
        source[:child_begin] + raw_child_region + source[child_end:]
    )
    with pytest.raises(AssertionError):
        _assert_launcher_child_dominance(raw_snapshot_mutant)


def test_artifact_writer_rejects_lifecycle_termination_control_mutants() -> None:
    source = LAUNCHER_PATH.read_text(encoding="utf-8")
    _assert_launcher_child_dominance(source)
    mutants = (
        source.replace(
            CHILD_LIFECYCLE_END,
            "$c6ArtifactProcess.Kill($true)\n" + CHILD_LIFECYCLE_END,
            1,
        ),
        source.replace(
            CHILD_LIFECYCLE_END,
            (
                "$c6ArtifactProcess.WaitForExit("
                "$script:C6ArtifactTerminationGraceMilliseconds)\n"
                + CHILD_LIFECYCLE_END
            ),
            1,
        ),
        source.replace(
            CHILD_LIFECYCLE_END,
            "$c6ArtifactProcess.WaitForExit()\n" + CHILD_LIFECYCLE_END,
            1,
        ),
        source.replace(
            CHILD_LIFECYCLE_BEGIN,
            (
                CHILD_LIFECYCLE_BEGIN
                + "\n$script:C6ArtifactDeadlineStopwatch.Restart()"
            ),
            1,
        ),
        source.replace(
            CHILD_LIFECYCLE_END,
            (
                "[Threading.Tasks.Task]::WaitAny(@(),1)\n"
                + CHILD_LIFECYCLE_END
            ),
            1,
        ),
        source.replace(
            CHILD_LIFECYCLE_END,
            "$c6ArtifactProcess.WaitForExitAsync()\n" + CHILD_LIFECYCLE_END,
            1,
        ),
        source.replace(
            (
                "$c6ArtifactProcess.Kill($true)\n"
                "            }\n"
                "        } catch {\n"
                "            $c6ArtifactChildTerminationFailed=$true\n"
                "        }\n"
                "        try {\n"
                "            if (-not $c6ArtifactProcess.WaitForExit("
                "$script:C6ArtifactTerminationGraceMilliseconds))"
            ),
            (
                "$c6ArtifactProcess.WaitForExit("
                "$script:C6ArtifactTerminationGraceMilliseconds)\n"
                "            }\n"
                "        } catch {\n"
                "            $c6ArtifactChildTerminationFailed=$true\n"
                "        }\n"
                "        try {\n"
                "            if (-not $c6ArtifactProcess.Kill($true))"
            ),
            1,
        ),
    )
    for mutant in mutants:
        with pytest.raises(AssertionError):
            _assert_launcher_child_dominance(mutant)


def test_artifact_writer_rejects_lifecycle_pipe_drain_mutants() -> None:
    source = LAUNCHER_PATH.read_text(encoding="utf-8")
    _assert_launcher_child_dominance(source)
    mutants = (
        source.replace(
            "$c6ArtifactStdoutMemory.Length+$c6ArtifactStdoutRead -gt",
            "$c6ArtifactStdoutMemory.Length+$c6ArtifactStdoutRead -le",
            1,
        ),
        source.replace(
            "$c6ArtifactStderrMemory.Length+$c6ArtifactStderrRead -gt",
            "$c6ArtifactStderrMemory.Length+$c6ArtifactStderrRead -le",
            1,
        ),
        source.replace("$c6ArtifactStderrEof=$false", "$c6ArtifactStderrEof=$true", 1),
        source.replace(
            "$c6ArtifactStdoutTask=$c6ArtifactStdoutStream.ReadAsync(",
            "$c6ArtifactStdoutTask=$null # removed reschedule\n# ",
            1,
        ),
        source.replace(
            "$c6ArtifactStderrTask=$c6ArtifactStderrStream.ReadAsync(",
            "$c6ArtifactStderrTask=$null # removed reschedule\n# ",
            1,
        ),
    )
    for mutant in mutants:
        with pytest.raises(AssertionError):
            _assert_launcher_child_dominance(mutant)


def test_artifact_writer_root_creating_mode_publishes_exact_bytes_and_ledger() -> None:
    writer = _writer()
    root, leaf = _root_and_leaf("operator-prompt", "provider-approval")
    content = b"Approve the bounded synthetic request.\n"
    request = _decode(
        _canonical_request(
            mode="operator-prompt",
            root=root,
            leaf=leaf,
            content=content,
        ),
        writer=writer,
    )
    root_path = Path(root)
    output_path = root_path / leaf
    assert not root_path.exists()

    receipt = writer.publish_artifact_writer_request(request)

    assert receipt.output_path == str(output_path)
    assert receipt.output_sha256 == sha256(content).hexdigest()
    assert receipt.before_members == ()
    assert receipt.after_members == (leaf,)
    assert tuple((entry.kind, entry.path) for entry in receipt.creation_ledger) == (
        ("directory", root),
        ("file", str(output_path)),
    )
    assert receipt.creation_ledger[0].size == 0
    assert receipt.creation_ledger[0].sha256 is None
    assert receipt.creation_ledger[1].size == len(content)
    assert receipt.creation_ledger[1].sha256 == sha256(content).hexdigest()
    assert receipt.parent_identity == receipt.reopened_parent_identity
    assert receipt.root_identity == receipt.reopened_root_identity
    assert receipt.output_identity == receipt.reopened_output_identity
    assert output_path.read_bytes() == content


def test_artifact_writer_rejects_preexisting_root_without_cleanup() -> None:
    writer = _writer()
    root, leaf = _root_and_leaf("operator-prompt", "provider-approval")
    root_path = Path(root)
    root_path.mkdir()
    sentinel = root_path / "preexisting.txt"
    sentinel.write_bytes(b"retain me\n")
    request = _decode(
        _canonical_request(
            mode="operator-prompt",
            root=root,
            leaf=leaf,
            content=b"approve\n",
        ),
        writer=writer,
    )

    with pytest.raises(RuntimeError):
        writer.publish_artifact_writer_request(request)

    assert root_path.is_dir()
    assert sentinel.read_bytes() == b"retain me\n"
    assert not (root_path / leaf).exists()


def test_artifact_writer_retains_attempt_after_post_create_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _writer()
    root, leaf = _root_and_leaf("operator-prompt", "import-authorization")
    content = b"Approve the bounded synthetic import request.\n"
    request = _decode(
        _canonical_request(
            mode="operator-prompt",
            root=root,
            leaf=leaf,
            content=content,
        ),
        writer=writer,
    )
    output_path = Path(root) / leaf

    def fail_after_create(*_args: object) -> None:
        raise RuntimeError("synthetic post-create failure")

    monkeypatch.setattr(writer, "_after_artifact_leaf_created", fail_after_create)

    with pytest.raises(RuntimeError, match=r"^synthetic post-create failure$"):
        writer.publish_artifact_writer_request(request)

    assert Path(root).is_dir()
    assert output_path.read_bytes() == content


def test_artifact_writer_existing_root_mode_holds_exact_predecessor_and_publishes_leaf() -> None:
    writer = _writer()
    root, prompt_leaf = _root_and_leaf("operator-prompt", "provider-approval")
    prompt_content = b"Approve the bounded synthetic request.\n"
    prompt_raw = _canonical_request(
        mode="operator-prompt",
        root=root,
        leaf=prompt_leaf,
        content=prompt_content,
    )
    writer.publish_artifact_writer_request(
        _decode(prompt_raw, writer=writer)
    )
    attestation_leaf = "provider-approval.json"
    attestation_content = b'{"approved":true}\n'
    attestation_raw = _canonical_request(
        mode="operator-attestation",
        root=root,
        leaf=attestation_leaf,
        content=attestation_content,
    )

    receipt = writer.publish_artifact_writer_request(
        _decode(attestation_raw, writer=writer)
    )

    prompt_path = Path(root) / prompt_leaf
    attestation_path = Path(root) / attestation_leaf
    assert receipt.before_members == (prompt_leaf,)
    assert receipt.after_members == tuple(sorted((prompt_leaf, attestation_leaf)))
    assert tuple((entry.kind, entry.path) for entry in receipt.creation_ledger) == (
        ("file", str(attestation_path)),
    )
    assert receipt.predecessor_path == str(prompt_path)
    assert receipt.predecessor_sha256 == sha256(prompt_content).hexdigest()
    assert receipt.predecessor_identity == receipt.reopened_predecessor_identity
    assert prompt_path.read_bytes() == prompt_content
    assert attestation_path.read_bytes() == attestation_content


@pytest.mark.parametrize(
    "discriminator",
    (
        "candidate/specification",
        "candidate/quality-security",
        "closure/specification",
        "closure/quality-security",
        "final-docs/specification",
        "final-docs/quality-security",
    ),
)
def test_artifact_writer_host_review_modes_publish_and_cross_bind_predecessor(
    discriminator: str,
) -> None:
    writer = _writer()
    root, envelope_leaf = _root_and_leaf("host-review-envelope", discriminator)
    envelope_content = _host_review_content(
        "host-review-envelope",
        discriminator,
    )
    envelope_request = _decode(
        _canonical_request(
            mode="host-review-envelope",
            root=root,
            leaf=envelope_leaf,
            content=envelope_content,
        ),
        writer=writer,
    )

    envelope_receipt = writer.publish_artifact_writer_request(envelope_request)

    assert envelope_receipt.before_members == ()
    assert envelope_receipt.after_members == (envelope_leaf,)
    assert tuple(entry.kind for entry in envelope_receipt.creation_ledger) == (
        "directory",
        "file",
    )
    result_document = json.loads(
        _host_review_content("host-review-result", discriminator)
    )
    result_document["evaluation_envelope_sha256"] = sha256(
        envelope_content
    ).hexdigest()
    result_content = _canonical_document(result_document)
    result_leaf = "review-result.json"
    result_request = _decode(
        _canonical_request(
            mode="host-review-result",
            root=root,
            leaf=result_leaf,
            content=result_content,
        ),
        writer=writer,
    )

    result_receipt = writer.publish_artifact_writer_request(result_request)

    assert result_receipt.before_members == (envelope_leaf,)
    assert result_receipt.after_members == (envelope_leaf, result_leaf)
    assert tuple(entry.kind for entry in result_receipt.creation_ledger) == ("file",)
    assert result_receipt.predecessor_path == str(Path(root) / envelope_leaf)
    assert result_receipt.predecessor_sha256 == sha256(envelope_content).hexdigest()
    assert result_receipt.predecessor_identity is not None
    assert result_receipt.reopened_predecessor_identity == (
        result_receipt.predecessor_identity
    )
    assert (Path(root) / envelope_leaf).read_bytes() == envelope_content
    assert (Path(root) / result_leaf).read_bytes() == result_content


@pytest.mark.parametrize(
    "mutation",
    ("envelope-hash", "target", "subjects", "bundle"),
)
def test_artifact_writer_host_review_result_rejects_predecessor_binding_drift(
    mutation: str,
) -> None:
    writer = _writer()
    discriminator = "candidate/specification"
    root, envelope_leaf = _root_and_leaf("host-review-envelope", discriminator)
    envelope_content = _host_review_content(
        "host-review-envelope",
        discriminator,
    )
    writer.publish_artifact_writer_request(
        _decode(
            _canonical_request(
                mode="host-review-envelope",
                root=root,
                leaf=envelope_leaf,
                content=envelope_content,
            ),
            writer=writer,
        )
    )
    result_document = json.loads(
        _host_review_content("host-review-result", discriminator)
    )
    result_document["evaluation_envelope_sha256"] = sha256(
        envelope_content
    ).hexdigest()
    if mutation == "envelope-hash":
        result_document["evaluation_envelope_sha256"] = "0" * 64
    elif mutation == "target":
        result_document["target_tree"] = "f" * 40
    elif mutation == "subjects":
        result_document["subject_equivalence_sha256"] = "f" * 64
    else:
        result_document["host_review_input_bundle_aggregate_sha256"] = "f" * 64
    result_content = _canonical_document(result_document)
    result_leaf = "review-result.json"
    result_request = _decode(
        _canonical_request(
            mode="host-review-result",
            root=root,
            leaf=result_leaf,
            content=result_content,
        ),
        writer=writer,
    )

    with pytest.raises(RuntimeError):
        writer.publish_artifact_writer_request(result_request)

    assert (Path(root) / envelope_leaf).exists()
    assert not (Path(root) / result_leaf).exists()


def test_artifact_writer_host_review_result_rejects_invalid_predecessor_before_create() -> None:
    writer = _writer()
    discriminator = "closure/specification"
    root, envelope_leaf = _root_and_leaf("host-review-envelope", discriminator)
    root_path = Path(root)
    root_path.mkdir()
    (root_path / envelope_leaf).write_bytes(b"{}\n")
    result_document = json.loads(
        _host_review_content("host-review-result", discriminator)
    )
    result_document["evaluation_envelope_sha256"] = sha256(b"{}\n").hexdigest()
    result_leaf = "review-result.json"
    result_request = _decode(
        _canonical_request(
            mode="host-review-result",
            root=root,
            leaf=result_leaf,
            content=_canonical_document(result_document),
        ),
        writer=writer,
    )

    with pytest.raises(RuntimeError):
        writer.publish_artifact_writer_request(result_request)

    assert (root_path / envelope_leaf).read_bytes() == b"{}\n"
    assert not (root_path / result_leaf).exists()


@pytest.mark.parametrize(
    "mutation",
    ("missing-predecessor", "extra-member", "wrong-case-predecessor"),
)
def test_artifact_writer_rejects_missing_extra_or_wrong_case_predecessor_without_creation(
    mutation: str,
) -> None:
    writer = _writer()
    root, _ = _root_and_leaf("operator-attestation", "provider-approval")
    root_path = Path(root)
    root_path.mkdir()
    prompt_leaf = "provider-approval-prompt.txt"
    if mutation == "extra-member":
        (root_path / prompt_leaf).write_bytes(b"approve\n")
        (root_path / "extra.txt").write_bytes(b"retain extra\n")
    elif mutation == "wrong-case-predecessor":
        (root_path / "Provider-Approval-Prompt.txt").write_bytes(b"approve\n")
    request_raw = _canonical_request(
        mode="operator-attestation",
        root=root,
        leaf="provider-approval.json",
        content=b'{"approved":true}\n',
    )

    with pytest.raises(RuntimeError):
        writer.publish_artifact_writer_request(
            _decode(request_raw, writer=writer)
        )

    assert root_path.is_dir()
    assert not (root_path / "provider-approval.json").exists()
    if mutation == "extra-member":
        assert (root_path / "extra.txt").read_bytes() == b"retain extra\n"
    elif mutation == "wrong-case-predecessor":
        assert (root_path / "Provider-Approval-Prompt.txt").read_bytes() == b"approve\n"


def test_artifact_writer_rejects_preexisting_leaf_without_replace_retry_or_cleanup() -> None:
    writer = _writer()
    root, _ = _root_and_leaf("operator-attestation", "import-authorization")
    root_path = Path(root)
    root_path.mkdir()
    prompt = root_path / "import-authorization-prompt.txt"
    output = root_path / "import-authorization.json"
    prompt.write_bytes(b"approve import\n")
    output.write_bytes(b"preexisting output\n")
    request_raw = _canonical_request(
        mode="operator-attestation",
        root=root,
        leaf=output.name,
        content=b'{"approved":true}\n',
    )

    with pytest.raises(RuntimeError):
        writer.publish_artifact_writer_request(
            _decode(request_raw, writer=writer)
        )

    assert prompt.read_bytes() == b"approve import\n"
    assert output.read_bytes() == b"preexisting output\n"


def test_artifact_writer_rejects_predecessor_size_before_managed_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _writer()
    root, _ = _root_and_leaf("operator-attestation", "provider-approval")
    root_path = Path(root)
    root_path.mkdir()
    prompt = root_path / "provider-approval-prompt.txt"
    prompt.write_bytes(b"x" * 65_536 + b"\n")
    output = root_path / "provider-approval.json"
    request_raw = _canonical_request(
        mode="operator-attestation",
        root=root,
        leaf=output.name,
        content=b'{"approved":true}\n',
    )
    oversized_read_calls = 0
    original_read_exact = writer._ArtifactWriterNativeApi.read_exact

    def read_exact(self, handle: object, expected_size: int) -> bytes:
        nonlocal oversized_read_calls
        if expected_size > 65_536:
            oversized_read_calls += 1
        return original_read_exact(self, handle, expected_size)

    monkeypatch.setattr(writer._ArtifactWriterNativeApi, "read_exact", read_exact)

    with pytest.raises(RuntimeError):
        writer.publish_artifact_writer_request(
            _decode(request_raw, writer=writer)
        )

    assert oversized_read_calls == 0
    assert prompt.stat().st_size == 65_537
    assert not output.exists()


def test_artifact_writer_held_root_prevents_rename_before_leaf_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _writer()
    root, leaf = _root_and_leaf("operator-prompt", "provider-approval")
    root_path = Path(root)
    alternate = root_path.with_name(root_path.name + "-renamed")
    blocked = False

    def attempt_root_rename(*_args: object) -> None:
        nonlocal blocked
        try:
            root_path.rename(alternate)
        except OSError:
            blocked = True

    monkeypatch.setattr(writer, "_before_artifact_leaf_create", attempt_root_rename)
    request_raw = _canonical_request(
        mode="operator-prompt",
        root=root,
        leaf=leaf,
        content=b"approve\n",
    )

    writer.publish_artifact_writer_request(_decode(request_raw, writer=writer))

    assert blocked is True
    assert root_path.is_dir()
    assert not alternate.exists()
    assert (root_path / leaf).read_bytes() == b"approve\n"


def test_artifact_writer_held_predecessor_blocks_write_before_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _writer()
    root, prompt_leaf = _root_and_leaf("operator-prompt", "provider-approval")
    prompt_raw = _canonical_request(
        mode="operator-prompt",
        root=root,
        leaf=prompt_leaf,
        content=b"approve\n",
    )
    writer.publish_artifact_writer_request(_decode(prompt_raw, writer=writer))
    prompt_path = Path(root) / prompt_leaf
    blocked = False

    def attempt_predecessor_write(*_args: object) -> None:
        nonlocal blocked
        try:
            prompt_path.write_bytes(b"mutated\n")
        except OSError:
            blocked = True

    monkeypatch.setattr(
        writer,
        "_after_artifact_predecessor_held",
        attempt_predecessor_write,
    )
    attestation_raw = _canonical_request(
        mode="operator-attestation",
        root=root,
        leaf="provider-approval.json",
        content=b'{"approved":true}\n',
    )

    writer.publish_artifact_writer_request(
        _decode(attestation_raw, writer=writer)
    )

    assert blocked is True
    assert prompt_path.read_bytes() == b"approve\n"


def test_artifact_writer_held_output_blocks_write_and_delete_after_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _writer()
    root, leaf = _root_and_leaf("operator-prompt", "import-authorization")
    output_path = Path(root) / leaf
    blocked_actions: list[str] = []

    def attempt_output_mutation(*_args: object) -> None:
        try:
            output_path.write_bytes(b"mutated\n")
        except OSError:
            blocked_actions.append("write")
        try:
            output_path.unlink()
        except OSError:
            blocked_actions.append("delete")

    monkeypatch.setattr(writer, "_after_artifact_leaf_created", attempt_output_mutation)
    request_raw = _canonical_request(
        mode="operator-prompt",
        root=root,
        leaf=leaf,
        content=b"approve import\n",
    )

    writer.publish_artifact_writer_request(_decode(request_raw, writer=writer))

    assert blocked_actions == ["write", "delete"]
    assert output_path.read_bytes() == b"approve import\n"


def _run_isolated_artifact_writer(
    raw: bytes,
    *,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        (
            r"C:\Python314\python.exe",
            "-I",
            "-S",
            "-B",
            "-X",
            "utf8",
            str(WRITER_PATH),
            "--expected-request-sha256",
            sha256(raw).hexdigest(),
        ),
        input=raw,
        cwd=SKILLS_ROOT.parents[1],
        env=(
            dict(CHILD_ENVIRONMENT_ITEMS)
            if environment is None
            else environment
        ),
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_artifact_writer_isolated_python_child_publishes_one_exact_path() -> None:
    root, leaf = _root_and_leaf("operator-prompt", "provider-approval")
    content = b"Approve the bounded isolated request.\n"
    raw = _canonical_request(
        mode="operator-prompt",
        root=root,
        leaf=leaf,
        content=content,
    )
    output_path = Path(root) / leaf

    completed = _run_isolated_artifact_writer(raw)

    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    assert completed.stderr == b""
    assert completed.stdout == str(output_path).encode("utf-8") + b"\n"
    assert output_path.read_bytes() == content


@pytest.mark.parametrize(
    "environment",
    (
        {"SYSTEMROOT": r"C:\Windows"},
        {"SYSTEMROOT": r"C:\WINDOWS", "WINDIR": r"C:\Windows"},
        {
            "SYSTEMROOT": r"C:\Windows",
            "WINDIR": r"C:\Windows",
            "SECRET_CANARY": "synthetic-private-value",
        },
    ),
)
def test_artifact_writer_isolated_python_child_rejects_environment_drift_before_root_creation(
    environment: dict[str, str],
) -> None:
    root, leaf = _root_and_leaf("operator-prompt", "provider-approval")
    raw = _canonical_request(
        mode="operator-prompt",
        root=root,
        leaf=leaf,
        content=b"approve\n",
    )

    completed = _run_isolated_artifact_writer(raw, environment=environment)

    assert completed.returncode != 0
    assert completed.stdout == b""
    assert b"artifact inner runtime drift" in completed.stderr
    assert b"synthetic-private-value" not in completed.stderr
    assert not Path(root).exists()


@pytest.mark.parametrize(
    "mutation",
    (
        "image",
        "native-executable",
        "missing-isolation",
        "argument-order",
        "extra-argument",
        "helper",
        "request-hash",
        "managed-argv",
    ),
)
def test_artifact_writer_rejects_python_argv_or_isolation_drift(
    mutation: str,
) -> None:
    writer = _writer()
    helper = r"D:\task9-detached\tests\skills\complete_suite_artifact_writer.py"
    request_hash = "a" * 64
    managed_argv = (helper, "--expected-request-sha256", request_hash)
    native_argv = (
        r"C:\Python314\python.exe",
        "-I",
        "-S",
        "-B",
        "-X",
        "utf8",
        *managed_argv,
    )
    image = r"C:\Python314\python.exe"
    if mutation == "image":
        image = r"C:\Python314\pythonw.exe"
    elif mutation == "native-executable":
        native_argv = (r"C:\hostile\python.exe", *native_argv[1:])
    elif mutation == "missing-isolation":
        native_argv = (native_argv[0], *native_argv[2:])
    elif mutation == "argument-order":
        native_argv = (
            *native_argv[:1],
            "-S",
            "-I",
            *native_argv[3:],
        )
    elif mutation == "extra-argument":
        native_argv = (*native_argv, "extra")
    elif mutation == "helper":
        native_argv = (*native_argv[:6], r"D:\hostile\writer.py", *native_argv[7:])
    elif mutation == "request-hash":
        native_argv = (*native_argv[:-1], "b" * 64)
    else:
        managed_argv = (helper, "--request", request_hash)

    with pytest.raises(RuntimeError, match=r"^artifact native process drift$"):
        writer.validate_artifact_writer_native_process_contract(
            observed_image=image,
            observed_argv=native_argv,
            managed_argv=managed_argv,
        )


def test_artifact_writer_native_process_contract_accepts_exact_vector() -> None:
    writer = _writer()
    helper = r"D:\task9-detached\tests\skills\complete_suite_artifact_writer.py"
    request_hash = "a" * 64
    managed_argv = (helper, "--expected-request-sha256", request_hash)

    assert writer.validate_artifact_writer_native_process_contract(
        observed_image=r"C:\Python314\python.exe",
        observed_argv=(
            r"C:\Python314\python.exe",
            "-I",
            "-S",
            "-B",
            "-X",
            "utf8",
            *managed_argv,
        ),
        managed_argv=managed_argv,
    ) is None


def test_artifact_writer_native_process_check_precedes_stdin_decode() -> None:
    tree = ast.parse(WRITER_PATH.read_text(encoding="utf-8"))
    main = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_artifact_writer_main"
    )
    validation_line = next(
        node.lineno
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "validate_artifact_writer_native_process_contract"
    )
    stdin_read_line = next(
        node.lineno
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "read"
    )
    assert validation_line < stdin_read_line


def test_artifact_writer_rejects_any_shell_dynamic_code_or_process_surface() -> None:
    assert WRITER_PATH.is_file()
    source = WRITER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module != "__future__":
                imports.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
            ):
                calls.add(f"{node.func.value.id}.{node.func.attr}")

    assert imports <= set(ALLOWED_IMPORTS)
    assert not imports & {
        "asyncio",
        "importlib",
        "multiprocessing",
        "pathlib",
        "shlex",
        "shutil",
        "socket",
        "subprocess",
        "tempfile",
    }
    assert not calls & {
        "compile",
        "eval",
        "exec",
        "open",
        "os.listdir",
        "os.makedirs",
        "os.mkdir",
        "os.open",
        "os.popen",
        "os.remove",
        "os.rename",
        "os.replace",
        "os.rmdir",
        "os.scandir",
        "os.spawnl",
        "os.spawnle",
        "os.spawnv",
        "os.spawnve",
        "os.system",
        "os.unlink",
        "os.walk",
    }
    lowered = source.casefold()
    for forbidden in (
        "add-type",
        "get-childitem",
        "sort-object",
        "import-module",
        "get-module",
        "powershell",
        "pwsh",
        "cmd.exe",
        "useshellexecute",
    ):
        assert forbidden not in lowered
