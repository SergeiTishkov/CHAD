"""Driving real CHAD processes: the hook client as Claude Code runs it, and a scripted UI.

The dispatcher runs every command it approves, so the commands the tests approve are harmless
(`echo` in the shape of the real command) and run in the test's own empty folder, WORK.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from chad import paths, protocol

# The working folder of the commands a test runs; tests/integration/conftest.py sets it per test.
WORK = Path()


def payload(command: str, tool: str = "Bash", session: str = "session-1", **extra: Any) -> dict:
    return {
        "session_id": session,
        "transcript_path": "",
        "cwd": str(WORK),
        "permission_mode": "default",
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": {"command": command, "description": "integration test", **extra},
        "tool_use_id": "toolu_test",
    }


LIVE_HOOKS: list[Hook] = []


class Hook:
    """One `python -m chad.hook` process, exactly as the settings.json entry starts it."""

    def __init__(self, body: dict | str, env: dict[str, str] | None = None) -> None:
        """`env` adds variables to the hook's environment, as the harness session would."""
        LIVE_HOOKS.append(self)
        text = body if isinstance(body, str) else json.dumps(body)
        self.process = subprocess.Popen(
            [sys.executable, "-m", "chad.hook"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, **(env or {})},
        )
        assert self.process.stdin is not None
        self.process.stdin.write(text.encode("utf-8"))
        self.process.stdin.close()

    def result(self, timeout: float = 30) -> dict:
        stdout, stderr = self.process.communicate(timeout=timeout)
        assert self.process.returncode == 0, stderr.decode(errors="replace")
        return json.loads(stdout)

    def kill(self) -> None:
        self.process.kill()
        self.process.communicate()


def run_hook(body: dict | str, timeout: float = 30, env: dict[str, str] | None = None) -> dict:
    return Hook(body, env).result(timeout)


def decision(output: dict) -> str | None:
    return (output.get("hookSpecificOutput") or {}).get("permissionDecision")


def reason(output: dict) -> str:
    return output["hookSpecificOutput"]["permissionDecisionReason"]


def executed(output: dict) -> str:
    """The reason of a call CHAD ran: a deny that carries the result."""
    assert decision(output) == "deny"
    text = reason(output)
    assert text.startswith("[CHAD] COMMAND EXECUTED. Exit code: 0."), text
    return text


def ui(action: str, **fields: Any) -> dict:
    return protocol.request({"op": "ui", "action": action, **fields})


def state() -> dict:
    return ui("getState")["state"]


def wait_for(predicate, timeout: float = 20, message: str = "condition") -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {message}")


def pending(count: int = 1, timeout: float = 30) -> list[dict]:
    """The queue once it holds `count` items; the dispatcher may still be starting."""

    def ready() -> list[dict] | None:
        try:
            items = state()["pending"]
        except protocol.DispatcherUnavailable:
            return None
        return items if len(items) >= count else None

    return wait_for(ready, timeout, f"{count} pending command(s)")


def audit_decisions() -> list[str]:
    log = paths.audit_log_file()
    if not log.exists():
        return []
    return [line.split(" | ")[1] for line in log.read_text(encoding="utf-8").splitlines()]


def pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000 | 0x00100000, False, pid)
        if not handle:
            return False
        try:
            # WAIT_TIMEOUT (258) means still running.
            return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == 258
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def finish_test() -> None:
    """Leave nothing running: a hook still starting a dispatcher would outlive the test."""
    deadline = time.monotonic() + 30
    while True:
        stop_dispatcher()
        if all(h.process.poll() is not None for h in LIVE_HOOKS):
            break
        if time.monotonic() > deadline:
            for hook in LIVE_HOOKS:
                hook.process.kill()
            stop_dispatcher()
            break
        time.sleep(0.2)
    LIVE_HOOKS.clear()


def stop_dispatcher() -> None:
    """Ask the dispatcher to exit; kill it if it will not."""
    runtime = protocol.read_runtime()
    if runtime is None:
        return
    try:
        protocol.request({"op": "ui", "action": "shutdown"}, timeout=3)
    except protocol.DispatcherUnavailable:
        pass
    deadline = time.monotonic() + 10
    while pid_alive(runtime.pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if pid_alive(runtime.pid):
        subprocess.run(["taskkill", "/F", "/PID", str(runtime.pid)], capture_output=True)
