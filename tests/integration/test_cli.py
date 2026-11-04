"""`chad` as a user runs it, against an isolated data root."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from chad import protocol, switches
from chad.switches import Mode

from .harness import decision, executed, payload, run_hook


def chad(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "chad", *args], capture_output=True, text=True, timeout=60
    )


def test_mode_switching_reaches_the_next_hook_call() -> None:
    assert chad("mode", "allow-all").returncode == 0
    assert switches.current_mode() is Mode.ALLOW_ALL
    executed(run_hook(payload("echo anything")))
    result = chad("mode", "off")
    assert "off" in result.stdout
    assert run_hook(payload("echo anything")) == {}
    chad("mode", "chad")
    assert switches.current_mode() is Mode.CHAD


def test_deny_switch() -> None:
    # Deny rules match words anywhere in a statement, so an echo of the words is enough.
    chad("deny", "on")
    assert switches.deny_enabled()
    chad("mode", "allow-all")
    output = run_hook(payload("echo git reset --hard"))
    assert (
        decision(output) == "deny"
        and "deny list" in output["hookSpecificOutput"]["permissionDecisionReason"]
    )
    chad("deny", "off")
    assert "git reset --hard" in executed(run_hook(payload("echo git reset --hard")))


def test_start_status_stop() -> None:
    assert "not running" in chad("status").stdout
    assert chad("start").returncode == 0
    pid = protocol.ping()
    assert pid is not None
    status = chad("status").stdout
    assert f"pid {pid}" in status and "Pending:    0" in status
    assert chad("restart").returncode == 0
    assert protocol.ping() not in (None, pid)
    assert chad("stop").returncode == 0
    assert protocol.ping() is None


def test_open_starts_the_dispatcher_and_requests_the_policy_view() -> None:
    assert chad("open").returncode == 0
    state = protocol.request({"op": "ui", "action": "getState"})["state"]
    assert state["requestedView"] == "policy"


def test_bad_arguments() -> None:
    assert chad("mode", "yolo").returncode == 2


def test_install_into_temporary_folders(tmp_path: Path) -> None:
    claude, bin_dir = tmp_path / "claude", tmp_path / "bin"
    result = chad("install", "--claude-dir", str(claude), "--bin-dir", str(bin_dir))
    assert result.returncode == 0, result.stderr
    settings = json.loads((claude / "settings.json").read_text(encoding="utf-8"))
    assert settings["hooks"]["PreToolUse"][0]["matcher"] == "Bash|PowerShell"
    assert (claude / "skills" / "chad" / "SKILL.md").is_file()
    result = chad("uninstall", "--claude-dir", str(claude), "--bin-dir", str(bin_dir))
    assert result.returncode == 0, result.stderr
    assert json.loads((claude / "settings.json").read_text(encoding="utf-8")) == {}


def test_install_refuses_the_real_folders_while_isolated() -> None:
    result = chad(
        "install", "--claude-dir", str(Path.home() / ".claude"), "--bin-dir", str(Path.home())
    )
    assert result.returncode == 1
    assert "CHAD_ISOLATED" in result.stderr
