"""A call that asks to run in the background: CHAD starts it and answers at once.

The command runs in its own process group with stdout and stderr in one log file under the data
root, which the agent reads while it runs. When it exits, CHAD appends a line with its exit code.
CHAD does not stop it: it runs until it ends or is stopped by its process id.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from chad import paths
from chad.analysis import Dialect
from chad.executor import (
    _bash_executable,
    _working_directory,
    command_environment,
    own_process_group,
    powershell_arguments,
    search_path,
)


@dataclass(frozen=True)
class Started:
    pid: int
    log: Path


# start() and anything standing in for it: (command, cwd, dialect, environment).
Starter = Callable[[str, str, Dialect, Mapping[str, str] | None], Awaitable[Started]]

# The tasks that wait for a background command to exit; kept so they are not collected.
_waiting: set[asyncio.Task[None]] = set()


def log_folder() -> Path:
    return paths.data_root() / "background"


async def start(
    command: str, cwd: str, dialect: Dialect, environment: Mapping[str, str] | None = None
) -> Started:
    chosen = command_environment(environment)
    argv = _arguments(command, dialect, search_path(chosen))
    working_directory = _working_directory(cwd)
    folder = log_folder()
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}.log"
    with log.open("wb") as output:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=working_directory,
            env=chosen,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=output,
            stderr=asyncio.subprocess.STDOUT,
            **own_process_group(),
        )
    task = asyncio.create_task(_record_exit(process, log))
    _waiting.add(task)
    task.add_done_callback(_waiting.discard)
    return Started(process.pid, log)


async def _record_exit(process: asyncio.subprocess.Process, log: Path) -> None:
    code = await process.wait()
    with log.open("ab") as output:
        output.write(f"\n[CHAD] The command exited with code {code}.\n".encode())


def _arguments(command: str, dialect: Dialect, path: str | None) -> list[str]:
    if dialect == "bash":
        return [_bash_executable(), "--noprofile", "--norc", "-c", command]
    # Both streams go to one file. PowerShell may write its error stream as XML when it is
    # redirected, so errors are turned into text inside the pipeline, terminating ones included.
    script = "\n".join(
        (
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)",
            "$ErrorActionPreference = 'Continue'",
            "$ProgressPreference = 'SilentlyContinue'",
            "$global:__chadFailed = $false",
            "& { try {",
            command,
            "} catch { $_ } } 2>&1 | ForEach-Object {",
            "  if ($_ -is [System.Management.Automation.ErrorRecord]) {",
            "    $global:__chadFailed = $true; $_.ToString()",
            "  } else { $_ }",
            "} | Out-String -Stream -Width 4096",
            "if ($null -ne $LASTEXITCODE) { exit $LASTEXITCODE }",
            "if ($global:__chadFailed) { exit 1 } else { exit 0 }",
        )
    )
    return powershell_arguments(script, path)


def stop_command(pid: int, dialect: Dialect) -> str:
    """How the agent stops a background command and its process tree, in the same shell."""
    if os.name != "nt":
        return f"kill -- -{pid}"
    # Git Bash turns an argument like /T into a path; a doubled slash passes it through.
    switch = "//" if dialect == "bash" else "/"
    return f"taskkill {switch}T {switch}F {switch}PID {pid}"
