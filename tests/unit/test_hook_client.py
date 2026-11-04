"""The hook client fails closed: when CHAD itself fails, the answer is deny with the cause."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from chad import hook, paths, protocol, switches
from chad.policy import ALLOW_DENY_LIST_MARKER
from chad.switches import Mode


def payload(command: str = "ls", tool: str = "Bash") -> dict:
    return {"tool_name": tool, "tool_input": {"command": command}, "cwd": "C:/work"}


def broken(output: dict) -> str:
    """The reason of a CHAD-is-broken deny; fails on any other answer."""
    specific = output["hookSpecificOutput"]
    assert specific["permissionDecision"] == "deny"
    reason = specific["permissionDecisionReason"]
    assert reason.startswith("[CHAD] CHAD IS BROKEN. The command did not run.")
    assert "CHAD needs fixing" in reason and "chad mode off" in reason
    return reason


def run_client(stdin: bytes, *before: str) -> dict:
    """`python -m chad.hook` as a process; `before` runs first, to break the client."""
    code = "\n".join(
        [*before, "import runpy", "runpy.run_module('chad.hook', run_name='__main__')"]
    )
    result = subprocess.run(
        [sys.executable, "-c", code], input=stdin, capture_output=True, timeout=60, env=os.environ
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return json.loads(result.stdout)


@pytest.fixture
def no_dispatcher(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hook, "ensure_dispatcher", lambda: False)


def test_a_dispatcher_that_does_not_start_is_a_deny(no_dispatcher: None) -> None:
    reason = broken(hook.decide(payload()))
    assert "starting it failed" in reason
    assert reason.splitlines()[2].endswith("Details: " + str(paths.log_file("hook")))
    assert paths.log_file("hook").name == "hook.log"


def test_a_dispatcher_that_does_not_answer_is_a_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hook, "ensure_dispatcher", lambda: True)

    def silent(*_: object) -> dict:
        raise protocol.DispatcherUnavailable("timed out")

    monkeypatch.setattr(protocol, "request", silent)
    assert "DispatcherUnavailable: timed out" in broken(hook.decide(payload()))


def test_a_refused_request_is_a_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hook, "ensure_dispatcher", lambda: True)
    monkeypatch.setattr(protocol, "request", lambda *_: {"ok": False, "error": "unauthorized"})
    assert "refused the request: unauthorized" in broken(hook.decide(payload()))


def test_off_mode_and_other_tools_still_skip(no_dispatcher: None) -> None:
    assert hook.decide(payload(tool="Read")) == {}
    switches.set_mode(Mode.OFF)
    assert hook.decide(payload()) == {}


def test_a_control_request_keeps_its_own_refusal(no_dispatcher: None) -> None:
    output = hook.decide(payload(ALLOW_DENY_LIST_MARKER))
    assert "window could not be opened" in output["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("stdin", [b"not json at all", b"", b"[1, 2]"])
def test_unreadable_input_is_a_deny(stdin: bytes) -> None:
    broken(run_client(stdin))


def test_code_that_does_not_load_is_a_deny_unless_chad_is_off(isolated_home: Path) -> None:
    sabotage = "import sys; sys.modules['chad.policy'] = None"
    body = json.dumps(payload()).encode()
    reason = broken(run_client(body, sabotage))
    assert "could not be loaded: ModuleNotFoundError" in reason
    assert run_client(json.dumps(payload(tool="Read")).encode(), sabotage) == {}
    switches.set_mode(Mode.OFF)
    assert run_client(body, sabotage) == {}
