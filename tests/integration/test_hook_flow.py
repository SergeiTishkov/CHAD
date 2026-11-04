"""The hook client and the dispatcher as separate processes, as Claude Code runs them."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from chad import paths, protocol, switches
from chad.allowlist import AllowList
from chad.patterns import Pattern
from chad.policy import ADD_SELECTIVE_MARKER, ALLOW_DENY_LIST_MARKER
from chad.switches import Mode

from . import harness
from .harness import (
    Hook,
    audit_decisions,
    decision,
    executed,
    payload,
    pending,
    pid_alive,
    reason,
    run_hook,
    state,
    ui,
    wait_for,
)


def test_cold_start_then_ask_and_allow_once() -> None:
    assert protocol.ping() is None
    hook = Hook(payload("echo push origin main"))
    (item,) = pending()
    assert item["command"] == "echo push origin main"
    assert item["description"] == "integration test"
    assert ui("decide", id=item["id"], decision="allowOnce")["ok"]
    assert "--- stdout ---\npush origin main\n" in executed(hook.result())
    assert protocol.ping() is not None
    assert audit_decisions() == ["allowOnce"]


def test_allow_forever_then_rule_runs_without_asking() -> None:
    hook = Hook(payload('echo commit -m "first"'))
    (item,) = pending()
    ui(
        "decide",
        id=item["id"],
        decision="allowForever",
        selections=[{"index": 0, "modes": ["keep", "keep", "keep", "wild"]}],
    )
    assert "commit -m first" in executed(hook.result())
    assert "commit -m second" in executed(run_hook(payload('echo commit -m "second"')))
    assert not state()["pending"]
    assert audit_decisions() == ["allowForever", "allowedByRule"]
    assert "echo commit -m *" in paths.audit_log_file().read_text(encoding="utf-8")


def test_a_command_runs_in_the_folder_of_the_call() -> None:
    switches.set_mode(Mode.ALLOW_ALL)
    (harness.WORK / "marker.txt").write_text("x", encoding="utf-8")
    assert "marker.txt" in executed(run_hook(payload("ls")))
    assert "marker.txt" in executed(run_hook(payload("Get-ChildItem -Name", tool="PowerShell")))


def test_a_missing_working_folder_is_refused_with_its_cause() -> None:
    switches.set_mode(Mode.ALLOW_ALL)
    gone = payload("echo hi")
    gone["cwd"] = str(harness.WORK / "deleted")
    text = reason(run_hook(gone))
    assert text.startswith("[CHAD] CHAD COULD NOT RUN THE COMMAND. It did not run.")
    assert "The working folder does not exist" in text and "deleted" in text
    absent = payload("echo hi")
    del absent["cwd"]
    text = reason(run_hook(absent))
    assert text.startswith("[CHAD] CHAD COULD NOT RUN THE COMMAND. It did not run.")
    assert "the hook payload has no cwd" in text and "CHAD needs fixing" in text
    assert audit_decisions() == ["error", "error"]


def test_user_denial_with_reason() -> None:
    hook = Hook(payload("npm publish"))
    (item,) = pending()
    ui("decide", id=item["id"], decision="deny", reason="wrong registry")
    output = hook.result()
    assert decision(output) == "deny"
    assert "wrong registry" in reason(output)
    assert "Do not send this command again" in reason(output)


def test_concurrent_commands_queue_in_order() -> None:
    first = Hook(payload("echo one", session="a"))
    pending(1)
    second = Hook(payload("echo two", session="b"))
    items = pending(2)
    assert [i["command"] for i in items] == ["echo one", "echo two"]
    ui("decide", id=items[1]["id"], decision="deny")
    ui("decide", id=items[0]["id"], decision="allowOnce")
    assert "--- stdout ---\none\n" in executed(first.result())
    assert "REJECTED BY THE USER" in reason(second.result())


def test_killed_hook_withdraws_its_question() -> None:
    hook = Hook(payload("sleep 100"))
    pending()
    hook.kill()
    wait_for(lambda: not state()["pending"], message="the question to be withdrawn")


def test_concurrent_cold_starts_share_one_dispatcher() -> None:
    switches.set_mode(Mode.ALLOW_ALL)
    hooks = [Hook(payload(f"echo {n}")) for n in range(5)]
    for n, hook in enumerate(hooks):
        assert f"--- stdout ---\n{n}\n" in executed(hook.result(60))
    log = paths.log_file("dispatcher").read_text(encoding="utf-8")
    assert log.count("listening on port") == 1
    # The names README and the CHAD IS BROKEN deny give.
    assert sorted(p.name for p in paths.data_root().glob("*.log*")) == [
        "audit.log",
        "dispatcher.log",
        "hook.log",
    ]


def test_modes_take_effect_on_the_next_command() -> None:
    switches.set_mode(Mode.ALLOW_ALL)
    executed(run_hook(payload("echo anything")))
    switches.set_mode(Mode.OFF)
    assert run_hook(payload("echo anything")) == {}
    switches.set_mode(Mode.SELECTIVE)
    assert run_hook(payload("echo anything")) == {}
    assert audit_decisions() == ["allowAllMode", "handedToHarness"]


def test_off_mode_never_starts_the_dispatcher() -> None:
    switches.set_mode(Mode.OFF)
    assert run_hook(payload("ls")) == {}
    assert protocol.ping() is None


def test_deny_list_refuses_in_every_mode() -> None:
    switches.set_deny(True)
    for mode in (Mode.CHAD, Mode.ALLOW_ALL, Mode.SELECTIVE):
        switches.set_mode(mode)
        output = run_hook(payload("cd x && rm -rf build", tool="PowerShell"))
        assert decision(output) == "deny", mode
        assert "Rule: rm -rf" in reason(output)


def test_other_tools_and_empty_commands_get_no_decision_and_garbage_a_deny() -> None:
    assert run_hook({"tool_name": "Read", "tool_input": {"file_path": "x"}}) == {}
    assert run_hook(payload("   ")) == {}
    for garbage in ("not json at all", ""):
        output = run_hook(garbage)
        assert decision(output) == "deny"
        assert "CHAD IS BROKEN" in reason(output)
        assert "could not be read" in reason(output)


def test_live_reload_of_a_hand_edited_allow_list() -> None:
    switches.set_mode(Mode.CHAD)
    hook = Hook(payload("echo test"))
    (item,) = pending()
    ui("decide", id=item["id"], decision="deny")
    hook.result()
    allow_file = paths.allow_list_file()
    allow_file.write_text(
        "version: 1\nallowed:\n  - {kind: regex, value: '^echo (test|lint)$'}\n", encoding="utf-8"
    )
    future = time.time() + 5
    os.utime(allow_file, (future, future))
    assert "--- stdout ---\nlint\n" in executed(run_hook(payload("echo lint")))


def test_policy_marker_opens_the_window_even_when_off() -> None:
    switches.set_mode(Mode.OFF)
    output = run_hook(payload(f"echo {ALLOW_DENY_LIST_MARKER}"))
    assert decision(output) == "deny"
    assert "window is now open" in reason(output)
    assert state()["requestedView"] == "policy"


def test_add_selective_command_end_to_end() -> None:
    switches.set_mode(Mode.SELECTIVE)
    original = payload("Write-Output run build -- --prod", tool="PowerShell", timeout=120000)
    assert run_hook(original) == {}
    marker = Hook(payload(ADD_SELECTIVE_MARKER, tool="PowerShell"))
    (item,) = pending()
    assert item["purpose"] == "addSelective"
    assert item["command"] == "Write-Output run build -- --prod"
    answer = ui(
        "decide",
        id=item["id"],
        decision="allowSelective",
        selections=[{"index": 0, "modes": ["keep", "keep", "keep", "keep", "wild"]}],
    )
    assert answer["ok"], answer
    assert "--prod" in executed(marker.result())
    output = run_hook(payload("Write-Output run build -- --dev", tool="PowerShell"))
    assert "--dev" in executed(output)


def test_add_selective_without_a_capture_is_an_error() -> None:
    switches.set_mode(Mode.SELECTIVE)
    output = run_hook(payload(ADD_SELECTIVE_MARKER, session="fresh"))
    assert decision(output) == "deny"
    assert "no recent command" in reason(output)


def test_expiry_answers_before_the_hook_timeout() -> None:
    paths.config_file().write_text(
        "hookTimeoutSeconds: 10\nsafetyMarginSeconds: 5\nlaunchUi: false\n", encoding="utf-8"
    )
    started = time.monotonic()
    output = run_hook(payload("sleep 1"))
    assert "NO DECISION IN TIME" in reason(output)
    assert 4.5 < time.monotonic() - started < 15
    assert audit_decisions() == ["expired"]


def test_shutdown_denies_whatever_is_pending() -> None:
    hook = Hook(payload("ls"))
    pending()
    pid = protocol.read_runtime().pid
    ui("shutdown")
    assert "CHAD shut down" in reason(hook.result())
    wait_for(lambda: not pid_alive(pid), message="the dispatcher to exit")
    assert not paths.runtime_file().exists()


def test_fail_closed_when_the_data_root_is_unusable(tmp_path: Path, monkeypatch) -> None:
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("CHAD_HOME", str(blocker))
    output = run_hook(payload("ls"))
    assert decision(output) == "deny"
    assert "CHAD IS BROKEN" in reason(output) and "chad mode off" in reason(output)
    output = run_hook(payload(f"{ALLOW_DENY_LIST_MARKER}"))
    assert decision(output) == "deny"
    assert "could not be opened" in reason(output)


def test_a_command_sees_the_environment_of_its_own_hook() -> None:
    switches.set_mode(Mode.ALLOW_ALL)
    command = 'echo "marker=[$CHAD_TEST_MARKER]"'
    # The first hook starts the dispatcher, so the dispatcher's own environment has "first".
    first = executed(run_hook(payload(command), env={"CHAD_TEST_MARKER": "first"}))
    assert "marker=[first]" in first
    second = executed(run_hook(payload(command), env={"CHAD_TEST_MARKER": "second"}))
    assert "marker=[second]" in second
    powershell = payload('Write-Output "marker=[$env:CHAD_TEST_MARKER]"', tool="PowerShell")
    assert "marker=[]" in executed(run_hook(powershell))


def test_a_non_ascii_command_reaches_the_shell_and_the_audit_log_as_written() -> None:
    # Claude Code writes the payload as raw UTF-8 (checked with 2.1.312), not as \u escapes.
    switches.set_mode(Mode.ALLOW_ALL)
    text = "тест — ок"
    commands = {
        "Bash": f"printf '%s' '{text}' > bash.txt",
        "PowerShell": f"[IO.File]::WriteAllText(\"$PWD/ps.txt\", '{text}')",
    }
    for tool, command in commands.items():
        body = json.dumps(payload(command, tool=tool), ensure_ascii=False)
        assert "Exit code: 0" in executed(run_hook(body))
    assert (harness.WORK / "bash.txt").read_bytes().decode("utf-8") == text
    assert (harness.WORK / "ps.txt").read_bytes().decode("utf-8") == text
    log = paths.audit_log_file().read_text(encoding="utf-8")
    assert all(command in log for command in commands.values())


def test_a_rule_covers_a_redirect_only_to_the_file_it_names() -> None:
    AllowList(paths.allow_list_file()).add_pattern(Pattern.parse("echo * > out.log"))
    assert "Exit code: 0" in executed(run_hook(payload("echo hello there > out.log")))
    assert (harness.WORK / "out.log").read_text(encoding="utf-8") == "hello there\n"
    # Another file in the folder is not the rule's; one outside it is never remembered.
    for command in ("echo hi > other.log", "echo hi > ../out.log"):
        hook = Hook(payload(command))
        (item,) = pending()
        assert item["command"] == command
        ui("decide", id=item["id"], decision="deny")
        assert decision(hook.result()) == "deny"
    assert not (harness.WORK / "other.log").exists()
    assert not (harness.WORK.parent / "out.log").exists()


def test_a_powershell_call_by_literal_path_is_remembered_and_runs_again() -> None:
    (harness.WORK / "tool.cmd").write_text("@echo called %1\r\n", encoding="ascii")
    calls = [
        (f'& "{harness.WORK / "tool.cmd"}" one', f'& "{harness.WORK / "tool.cmd"}" two', "called"),
        (f"& '{sys.executable}' -c 'print(41)'", f"& '{sys.executable}' -c 'print(42)'", "4"),
    ]
    for first, again, marker in calls:
        hook = Hook(payload(first, tool="PowerShell"))
        (item,) = pending()
        assert item["statements"][0]["storable"]
        words = item["statements"][0]["words"]
        modes = ["keep"] * (len(words) - 1) + ["wild"]
        ui(
            "decide",
            id=item["id"],
            decision="allowForever",
            selections=[{"index": 0, "modes": modes}],
        )
        assert marker in executed(hook.result())
        assert marker in executed(run_hook(payload(again, tool="PowerShell")))
    assert not state()["pending"]
    # A computed target is still asked about.
    hook = Hook(payload("& $env:ComSpec /c echo x", tool="PowerShell"))
    (item,) = pending()
    assert item["statements"][0]["blocking"] == ["& call operator"]
    ui("decide", id=item["id"], decision="deny")
    assert decision(hook.result()) == "deny"
