"""Background calls for real: started detached, output in a log file, the exit code appended."""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

from chad import background, executor, switches
from chad.analysis import Dialect
from chad.switches import Mode

from . import harness
from .harness import decision, payload, reason, run_hook, wait_for

EXITED = re.compile(r"\[CHAD\] The command exited with code (-?\d+)\.")


async def finished(log: Path, timeout: float = 30) -> str:
    """The log once CHAD has appended the exit line."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = log.read_text(encoding="utf-8", errors="replace")
        if EXITED.search(text):
            return text
        await asyncio.sleep(0.1)
    raise AssertionError(f"no exit line in {log}: {log.read_text(errors='replace')!r}")


def run_in_background(command: str, dialect: Dialect, cwd: Path) -> tuple[background.Started, str]:
    async def scenario() -> tuple[background.Started, str]:
        started = await background.start(command, str(cwd), dialect)
        return started, await finished(started.log)

    return asyncio.run(scenario())


def test_bash_output_and_exit_code_go_to_the_log(tmp_path: Path) -> None:
    started, log = run_in_background("echo out; echo err >&2; exit 3", "bash", tmp_path)
    assert started.log.parent == background.log_folder()
    assert "out\n" in log and "err\n" in log
    assert EXITED.search(log).group(1) == "3"


def test_powershell_errors_are_text_in_the_log(tmp_path: Path) -> None:
    _, log = run_in_background("Write-Output hi; Write-Error boom; exit 4", "powershell", tmp_path)
    assert "hi" in log and "boom" in log and "CLIXML" not in log
    assert EXITED.search(log).group(1) == "4"
    _, log = run_in_background("throw 'bad'", "powershell", tmp_path)
    assert "bad" in log and "CLIXML" not in log
    assert EXITED.search(log).group(1) == "1"


def test_the_command_runs_in_the_given_folder(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("x", encoding="utf-8")
    _, log = run_in_background("ls", "bash", tmp_path)
    assert "marker.txt" in log


def test_the_stop_command_in_the_answer_stops_it(tmp_path: Path) -> None:
    for dialect, command in (("bash", "sleep 60"), ("powershell", "Start-Sleep 60")):

        async def scenario(dialect: Dialect = dialect, command: str = command) -> str:
            started = await background.start(command, str(tmp_path), dialect)
            await asyncio.sleep(1)
            stop = background.stop_command(started.pid, dialect)
            result = await executor.run(stop, str(tmp_path), dialect, 30, 10_000)
            assert result.exit_code == 0, result.stdout.render(10_000)
            return await finished(started.log, 15)

        assert EXITED.search(asyncio.run(scenario()))


def test_a_background_call_through_the_hook() -> None:
    switches.set_mode(Mode.ALLOW_ALL)
    began = time.monotonic()
    output = run_hook(payload("echo first; sleep 2; echo second", run_in_background=True))
    assert time.monotonic() - began < 15
    assert decision(output) == "deny"
    text = reason(output)
    assert text.startswith("[CHAD] COMMAND STARTED IN THE BACKGROUND. Process id:")
    log = Path(re.search(r"grows while it runs: (.+)", text).group(1))

    def done() -> str | None:
        content = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        return content if EXITED.search(content) else None

    content = wait_for(done, 30, "the background command to finish")
    assert "first\n" in content and "second\n" in content
    assert harness.audit_decisions() == ["allowAllMode"]
