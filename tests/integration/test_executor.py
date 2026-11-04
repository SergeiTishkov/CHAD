"""The real executor: Git Bash and PowerShell running harmless commands in a temp folder."""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path

import pytest

from chad import executor
from chad.analysis import Dialect
from chad.executor import ExecutionResult


def run(
    command: str, cwd: Path | str, dialect: Dialect = "bash", timeout: float = 30
) -> ExecutionResult:
    return asyncio.run(executor.run(command, str(cwd), dialect, timeout, 100_000))


def text(output: executor.CapturedOutput) -> str:
    return output.render(100_000)[0]


def test_bash_returns_stdout_and_the_exit_code(tmp_path: Path) -> None:
    result = run("echo hello; exit 3", tmp_path)
    assert result.exit_code == 3
    assert text(result.stdout) == "hello\n"
    assert not result.timed_out and result.execution_note is None


def test_bash_keeps_stderr_apart(tmp_path: Path) -> None:
    result = run("echo out; echo err >&2", tmp_path)
    assert text(result.stdout) == "out\n"
    assert text(result.stderr) == "err\n"


def test_powershell_returns_stdout_and_the_exit_code(tmp_path: Path) -> None:
    result = run("Write-Output hello; exit 4", tmp_path, "powershell")
    assert result.exit_code == 4
    assert text(result.stdout).strip() == "hello"


def test_powershell_errors_arrive_as_plain_text(tmp_path: Path) -> None:
    result = run("Write-Error boom", tmp_path, "powershell")
    stderr = text(result.stderr)
    assert "boom" in stderr
    assert "CLIXML" not in stderr and "<Objs" not in stderr


def test_a_command_runs_in_the_given_folder(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("x", encoding="utf-8")
    assert "marker.txt" in text(run("ls", tmp_path).stdout)
    assert "marker.txt" in text(run("Get-ChildItem -Name", tmp_path, "powershell").stdout)


def test_large_output_keeps_both_ends(tmp_path: Path) -> None:
    result = run("echo FIRST; head -c 300000 /dev/zero | tr '\\0' x; echo; echo LAST", tmp_path)
    assert result.stdout.exceeded_capture_limit
    rendered = result.stdout.render(4_000)[0]
    assert rendered.startswith("FIRST") and rendered.rstrip().endswith("LAST")
    assert "bytes omitted by CHAD" in rendered


def test_a_command_past_its_time_limit_is_stopped(tmp_path: Path) -> None:
    started = time.monotonic()
    result = run("echo started; sleep 30", tmp_path, timeout=1)
    assert result.timed_out and result.exit_code == -1
    assert time.monotonic() - started < 15
    assert "started" in text(result.stdout)


def test_no_working_folder_names_a_broken_hook(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="the hook payload has no cwd") as error:
        run("echo hi", "")
    assert "CHAD needs fixing" in str(error.value)


def test_a_missing_working_folder_is_named(tmp_path: Path) -> None:
    gone = tmp_path / "deleted"
    with pytest.raises(FileNotFoundError, match="The working folder does not exist") as error:
        run("echo hi", gone)
    assert str(gone) in str(error.value)


def test_a_process_left_running_does_not_hold_the_result(tmp_path: Path) -> None:
    # The child writes to the inherited stdout after the result is back, then leaves a file:
    # CHAD keeps reading the pipe, so the write does not fail and the child is not stopped.
    command = "(sleep 2; echo after; echo x > done.txt) & echo before; exit 5"

    async def scenario() -> tuple[ExecutionResult, float]:
        started = time.monotonic()
        result = await executor.run(command, str(tmp_path), "bash", 30, 100_000)
        elapsed = time.monotonic() - started
        for _ in range(100):
            if (tmp_path / "done.txt").exists():
                break
            await asyncio.sleep(0.1)
        return result, elapsed

    result, elapsed = asyncio.run(scenario())
    assert elapsed < 2
    assert result.exit_code == 5 and result.left_running and not result.timed_out
    assert text(result.stdout) == "before\n"
    assert (tmp_path / "done.txt").exists()


def test_a_powershell_process_left_running_does_not_hold_the_result(tmp_path: Path) -> None:
    command = (
        "Write-Output before; Start-Process -NoNewWindow powershell "
        "-ArgumentList '-NoProfile','-Command','Start-Sleep 5'"
    )
    started = time.monotonic()
    result = run(command, tmp_path, "powershell")
    assert time.monotonic() - started < 4
    assert result.exit_code == 0 and result.left_running and not result.timed_out
    assert text(result.stdout).strip() == "before"


def test_a_command_whose_streams_close_is_not_marked(tmp_path: Path) -> None:
    result = run("nohup sleep 3 >/dev/null 2>&1 & echo done", tmp_path)
    assert text(result.stdout) == "done\n" and not result.left_running


def test_powershell_runs_the_edition_claude_code_would() -> None:
    # PowerShell 7 when installed (GitHub's Windows runners have it), else Windows PowerShell 5.1.
    installed = shutil.which("pwsh") or (
        os.name == "nt"
        and any(
            (Path(os.environ.get(root, "")) / relative).is_file()
            for root, relative in (
                ("ProgramFiles", "PowerShell/7/pwsh.exe"),
                ("LOCALAPPDATA", "Microsoft/WindowsApps/pwsh.exe"),
            )
            if os.environ.get(root)
        )
    )
    result = run("Write-Output $PSVersionTable.PSVersion.Major", Path.cwd(), "powershell")
    assert text(result.stdout).strip() == ("7" if installed else "5")


def test_powershell_7_operators_work_when_pwsh_is_installed(tmp_path: Path) -> None:
    if not shutil.which("pwsh"):
        pytest.skip("PowerShell 7 is not installed")
    result = run("Write-Output one && Write-Output two; $null ?? 'three'", tmp_path, "powershell")
    assert text(result.stdout).split() == ["one", "two", "three"]


def test_a_command_knows_chad_runs_it(tmp_path: Path) -> None:
    # CHAD_EXECUTING=1 tells a script it runs under CHAD; CLAUDECODE=1 may come with the hook's
    # environment, so it does not tell the two apart.
    assert text(run('echo "[$CHAD_EXECUTING]"', tmp_path).stdout) == "[1]\n"
    environment = {**os.environ, "CHAD_EXECUTING": "0"}
    result = asyncio.run(
        executor.run('echo "[$CHAD_EXECUTING]"', str(tmp_path), "bash", 30, 10_000, environment)
    )
    assert text(result.stdout) == "[1]\n"
