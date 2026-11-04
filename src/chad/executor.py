"""Run an approved shell call inside the CHAD dispatcher and retain bounded output."""

from __future__ import annotations

import asyncio
import base64
import os
import shutil
import signal
import subprocess
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from chad.analysis import Dialect

EXECUTING_VARIABLE = "CHAD_EXECUTING"


@dataclass(frozen=True)
class CapturedOutput:
    """The whole stream up to a limit, or its beginning and end when it grows larger."""

    head: bytes
    tail: bytes
    total_bytes: int
    capture_limit: int

    @property
    def exceeded_capture_limit(self) -> bool:
        return self.total_bytes > self.capture_limit

    def render(self, byte_limit: int) -> tuple[str, int, int]:
        """Return a readable excerpt, source bytes retained, and source bytes omitted."""
        limit = max(0, byte_limit)
        if self.total_bytes == 0:
            return "", 0, 0

        if not self.exceeded_capture_limit:
            source = self.head + self.tail
            if len(source) <= limit:
                return source.decode("utf-8", errors="replace"), len(source), 0
            first = limit // 2
            last = limit - first
            front = source[:first]
            back = source[-last:] if last else b""
            kept = len(front) + len(back)
            omitted = self.total_bytes - kept
            marker = f"\n... [{omitted} bytes omitted by CHAD] ...\n"
            return (
                front.decode("utf-8", errors="replace")
                + marker
                + back.decode("utf-8", errors="replace"),
                kept,
                omitted,
            )

        first = limit // 2
        last = limit - first
        front = self.head[:first]
        back = self.tail[-last:] if last else b""
        kept = len(front) + len(back)
        omitted = self.total_bytes - kept
        marker = f"\n... [{omitted} bytes omitted by CHAD] ...\n"
        return (
            front.decode("utf-8", errors="replace")
            + marker
            + back.decode("utf-8", errors="replace"),
            kept,
            omitted,
        )


@dataclass(frozen=True)
class ExecutionResult:
    exit_code: int
    stdout: CapturedOutput
    stderr: CapturedOutput
    timed_out: bool
    duration_seconds: float
    time_limit_seconds: float
    execution_note: str | None = None
    # The shell exited but a process it started still holds stdout or stderr open.
    left_running: bool = False


# run() and anything standing in for it:
# (command, cwd, dialect, timeout_seconds, max_output_bytes, environment).
Executor = Callable[
    [str, str, Dialect, float, int, Mapping[str, str] | None], Awaitable[ExecutionResult]
]


class _Capture:
    def __init__(self, limit: int) -> None:
        self.limit = max(0, limit)
        self.head_limit = (self.limit + 1) // 2
        self.tail_limit = self.limit - self.head_limit
        self.head = bytearray()
        self.tail = bytearray()
        self.total = 0

    def add(self, chunk: bytes) -> None:
        self.total += len(chunk)
        head_room = self.head_limit - len(self.head)
        if head_room > 0:
            self.head.extend(chunk[:head_room])
            chunk = chunk[head_room:]
        if self.tail_limit and chunk:
            self.tail.extend(chunk)
            if len(self.tail) > self.tail_limit:
                del self.tail[: len(self.tail) - self.tail_limit]

    def finish(self) -> CapturedOutput:
        return CapturedOutput(bytes(self.head), bytes(self.tail), self.total, self.limit)


# How long the streams may stay open after the shell exits: enough to read what is already in
# the pipe. Longer means a process the command started holds them; CHAD does not wait for it.
STREAM_GRACE_SECONDS = 0.5

# Readers still draining the streams of a process a finished command left running.
_draining: set[asyncio.Task[None]] = set()


async def _read_stream(reader: asyncio.StreamReader, capture: _Capture) -> None:
    with suppress(asyncio.CancelledError):
        while chunk := await reader.read(65536):
            capture.add(chunk)


async def _finish_streams(
    tasks: tuple[asyncio.Task[None], asyncio.Task[None]],
    captures: tuple[_Capture, _Capture],
    timeout: float,
    keep_reading: bool = False,
) -> tuple[tuple[CapturedOutput, CapturedOutput], bool]:
    """The output so far, and whether both streams closed within `timeout`.

    With `keep_reading`, streams still open go on being read in the background, so a process
    left running never writes into a closed pipe; otherwise their readers are cancelled.
    """
    _, pending = await asyncio.wait(tasks, timeout=max(0.0, timeout))
    for task in pending:
        if keep_reading:
            _draining.add(task)
            task.add_done_callback(_draining.discard)
        else:
            task.cancel()
    if pending and not keep_reading:
        await asyncio.gather(*pending, return_exceptions=True)
    stdout, stderr = captures
    return (stdout.finish(), stderr.finish()), not pending


async def run(
    command: str,
    cwd: str,
    dialect: Dialect,
    timeout_seconds: float,
    max_output_bytes: int,
    environment: Mapping[str, str] | None = None,
) -> ExecutionResult:
    """Run one complete command line using the shell that made the hook call."""
    environment = command_environment(environment)
    argv = _arguments(command, dialect, search_path(environment))
    working_directory = _working_directory(cwd)
    capture_limit = max(2_000, max_output_bytes)
    started = time.monotonic()

    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=working_directory,
        env=environment,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **own_process_group(),
    )
    assert process.stdout is not None and process.stderr is not None
    captures = (_Capture(capture_limit), _Capture(capture_limit))
    streams = (
        asyncio.create_task(_read_stream(process.stdout, captures[0])),
        asyncio.create_task(_read_stream(process.stderr, captures[1])),
    )
    timed_out = False
    left_running = False
    execution_note = None

    try:
        await asyncio.wait_for(process.wait(), timeout=max(0.01, timeout_seconds))
        (stdout, stderr), streams_closed = await _finish_streams(
            streams, captures, STREAM_GRACE_SECONDS, keep_reading=True
        )
        left_running = not streams_closed
    except TimeoutError:
        timed_out = True
        await _kill_process_tree(process)
        await process.wait()
        (stdout, stderr), _ = await _finish_streams(streams, captures, 0.5)
    except asyncio.CancelledError:
        await _kill_process_tree(process)
        await process.wait()
        await _finish_streams(streams, captures, 0.5)
        raise
    except Exception as exc:
        execution_note = f"CHAD could not collect a complete result: {exc}"
        await _kill_process_tree(process)
        if process.returncode is None:
            await process.wait()
        (stdout, stderr), _ = await _finish_streams(streams, captures, 0.5)

    elapsed = time.monotonic() - started
    if dialect == "powershell":
        stderr = _clean_powershell_errors(stderr)
    return ExecutionResult(
        exit_code=(
            -1 if timed_out else process.returncode if process.returncode is not None else -1
        ),
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        duration_seconds=elapsed,
        time_limit_seconds=max(0.0, timeout_seconds),
        execution_note=execution_note,
        left_running=left_running,
    )


def command_environment(environment: Mapping[str, str] | None) -> dict[str, str]:
    """The hook's environment when it sent one, else the dispatcher's; marked as run by CHAD."""
    chosen = dict(environment) if environment is not None else os.environ.copy()
    chosen[EXECUTING_VARIABLE] = "1"
    return chosen


def own_process_group() -> dict[str, Any]:
    """Process options: no console window, and a group of its own so its tree can be stopped."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _arguments(command: str, dialect: Dialect, path: str | None = None) -> list[str]:
    if dialect == "bash":
        executable = _bash_executable()
        return [executable, "--noprofile", "--norc", "-c", command]

    script = "\n".join(
        (
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)",
            "$ErrorActionPreference = 'Continue'",
            "$ProgressPreference = 'SilentlyContinue'",
            command,
            "$__chadSucceeded = $?",
            "if ($null -ne $LASTEXITCODE) { exit $LASTEXITCODE }",
            "if ($__chadSucceeded) { exit 0 } else { exit 1 }",
        )
    )
    return powershell_arguments(script, path)


def powershell_arguments(script: str, path: str | None = None) -> list[str]:
    """PowerShell running `script` with no profile and no prompts; `path` is the PATH to search."""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return [
        _powershell_executable(path),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        encoded,
    ]


def _bash_executable() -> str:
    configured = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH", "").strip().strip('"')
    if configured and Path(configured).is_file():
        return configured

    if os.name == "nt":
        roots = [
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("LOCALAPPDATA"),
        ]
        for root in filter(None, roots):
            for relative in (
                "Git/bin/bash.exe",
                "Git/usr/bin/bash.exe",
                "Programs/Git/bin/bash.exe",
                "Programs/Git/usr/bin/bash.exe",
            ):
                candidate = Path(root) / relative
                if candidate.is_file():
                    return str(candidate)

    for name in ("bash", "bash.exe"):
        found = shutil.which(name)
        if found:
            return found

    raise FileNotFoundError(
        "The harness called Bash, but CHAD could not find bash. Set "
        "CLAUDE_CODE_GIT_BASH_PATH or add Bash to PATH; the command did not run."
    )


def _powershell_executable(search_path: str | None = None) -> str:
    """The edition Claude Code's PowerShell tool runs: PowerShell 7 when installed (a Microsoft
    Store install included), else Windows PowerShell 5.1. `search_path` is the PATH to look in."""
    found = shutil.which("pwsh", path=search_path)
    if found:
        return found
    if os.name != "nt":
        raise FileNotFoundError("CHAD could not find PowerShell (pwsh); the command did not run.")
    for root, relative in (
        ("ProgramFiles", "PowerShell/7/pwsh.exe"),
        ("LOCALAPPDATA", "Microsoft/WindowsApps/pwsh.exe"),
    ):
        base = os.environ.get(root)
        if base and (Path(base) / relative).is_file():
            return str(Path(base) / relative)
    found = shutil.which("powershell.exe", path=search_path) or shutil.which(
        "powershell", path=search_path
    )
    if found:
        return found
    system_root = os.environ.get("SystemRoot")
    if system_root:
        candidate = Path(system_root) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        if candidate.is_file():
            return str(candidate)
    raise FileNotFoundError("CHAD could not find PowerShell; the command did not run.")


def search_path(environment: Mapping[str, str]) -> str | None:
    """PATH of an environment, whatever the case of its name (Windows keeps `Path`)."""
    for name, value in environment.items():
        if name.upper() == "PATH":
            return value
    return None


def _working_directory(candidate: str) -> str:
    """The folder the call names; there is no fallback, a command runs where it was meant to."""
    if not candidate:
        raise FileNotFoundError(
            "The call carried no working folder: the hook payload has no cwd. The harness sends "
            "one with every call, so either its hook format changed or CHAD's hook client is "
            "broken. CHAD needs fixing before it can run commands."
        )
    if not Path(candidate).is_dir():
        raise FileNotFoundError(
            f"The working folder does not exist: {candidate}. It may have been deleted or moved "
            "during the session."
        )
    return candidate


def _clean_powershell_errors(output: CapturedOutput) -> CapturedOutput:
    """Decode Windows PowerShell's XML error stream when it is intact."""
    if output.exceeded_capture_limit:
        return output
    raw = (output.head + output.tail).decode("utf-8", errors="replace")
    if not raw.lstrip().startswith("#< CLIXML"):
        return output
    start = raw.find("<Objs")
    if start < 0:
        return output
    try:
        document = ElementTree.fromstring(raw[start:])
    except ElementTree.ParseError:
        return output

    parts = [
        element.text or "" for element in document.iter() if element.tag.rsplit("}", 1)[-1] == "S"
    ]
    text = "".join(parts)
    for encoded, decoded in (("_x000D_", "\r"), ("_x000A_", "\n"), ("_x0009_", "\t")):
        text = text.replace(encoded, decoded)
    text = text.strip()
    cleaned = _Capture(output.capture_limit)
    cleaned.add(text.encode("utf-8"))
    return cleaned.finish()


async def _kill_process_tree(process: asyncio.subprocess.Process) -> None:
    if os.name == "nt":
        if process.returncode is not None:
            return
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill.exe",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=flags,
            )
            await asyncio.wait_for(killer.wait(), timeout=5)
            if killer.returncode == 0:
                return
        except (OSError, TimeoutError):
            pass
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        return

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
