"""The engine in process. The same paths run again through real processes in tests/integration.

The engine runs approved commands through a FakeShell (tests/unit/conftest.py), which records
them; CHAD's answer for a command it ran is a deny that carries the result."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from chad import paths, switches
from chad.config import Config
from chad.patterns import Pattern
from chad.policy import ADD_SELECTIVE_MARKER, ALLOW_DENY_LIST_MARKER, Engine
from chad.switches import Mode


def payload(command: str, tool: str = "Bash", session: str = "s1", **extra: Any) -> dict:
    return {
        "session_id": session,
        "cwd": "C:/work",
        "permission_mode": "default",
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": {"command": command, "description": "test", **extra},
    }


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


@pytest.fixture
def engine(isolated_home: Path, shell: Any) -> Engine:
    paths.ensure_root()
    return Engine(
        Config(hook_timeout_seconds=3600),
        opener=lambda _: None,
        execute=shell,
        start_background=shell.start,
    )


def run(scenario: Callable[[], Awaitable[None]]) -> None:
    asyncio.run(scenario())


async def answered(engine: Engine, command: str, **kwargs: Any) -> tuple[asyncio.Task, str]:
    """Start a hook call that will need the user, and return it with its pending id."""
    task = asyncio.create_task(engine.hook(payload(command, **kwargs)))
    for _ in range(100):
        await asyncio.sleep(0)
        if engine.queue.items:
            return task, engine.queue.items[-1].id
    raise AssertionError("nothing was queued")


def audit_decisions() -> list[str]:
    log = paths.audit_log_file()
    if not log.exists():
        return []
    return [line.split(" | ")[1] for line in log.read_text(encoding="utf-8").splitlines()]


def test_other_tools_and_empty_commands_get_no_decision(engine: Engine) -> None:
    async def scenario() -> None:
        assert await engine.hook({"tool_name": "Read", "tool_input": {}}) == {}
        assert await engine.hook(payload("   # just a comment")) == {}

    run(scenario)


def test_off_mode_hands_back(engine: Engine) -> None:
    switches.set_mode(Mode.OFF)
    run(lambda: _expect(engine, "rm x", None))


async def _expect(engine: Engine, command: str, expected: str | None) -> None:
    assert decision(await engine.hook(payload(command))) == expected


def test_allow_all_runs_the_command_and_returns_its_output(engine: Engine, shell: Any) -> None:
    switches.set_mode(Mode.ALLOW_ALL)

    async def scenario() -> None:
        text = executed(await engine.hook(payload("anything at all", tool="PowerShell")))
        assert "ran anything at all" in text
        assert "Do not retry it" in text

    run(scenario)
    assert shell.calls == [("anything at all", "C:/work", "powershell")]
    assert audit_decisions() == ["allowAllMode"]


def test_rule_allows_every_statement_or_none(engine: Engine, shell: Any) -> None:
    engine.allow.add_exact("git status")
    engine.allow.add_pattern(Pattern.parse("git log *"))

    async def scenario() -> None:
        executed(await engine.hook(payload("git status && git log -5")))
        task, item_id = await answered(engine, "git status && git push")
        assert shell.commands == ["git status && git log -5"]
        engine.decide(item_id, "allowOnce")
        executed(await task)

    run(scenario)
    assert shell.commands == ["git status && git log -5", "git status && git push"]
    assert audit_decisions() == ["allowedByRule", "allowOnce"]
    assert "pattern: git log *" in paths.audit_log_file().read_text(encoding="utf-8")


def test_blocking_construct_is_never_auto_allowed(engine: Engine) -> None:
    engine.allow.add_pattern(Pattern.parse("echo *"))

    async def scenario() -> None:
        task, item_id = await answered(engine, "echo $(whoami)")
        item = engine.queue.get(item_id)
        assert item.statements[0].blocking == ("command substitution",)
        engine.decide(item_id, "deny", "no")
        assert decision(await task) == "deny"

    run(scenario)


def test_deny_list_beats_allow_all_and_rules(engine: Engine) -> None:
    switches.set_deny(True)
    switches.set_mode(Mode.ALLOW_ALL)
    engine.allow.add_pattern(Pattern.parse("git *"))

    async def scenario() -> None:
        output = await engine.hook(payload("git status; git push --force"))
        assert decision(output) == "deny"
        assert "Rule: git push --force" in reason(output)

    run(scenario)
    assert audit_decisions() == ["deniedByRule"]


def test_deny_list_is_ignored_while_unarmed(engine: Engine) -> None:
    switches.set_mode(Mode.ALLOW_ALL)

    async def scenario() -> None:
        executed(await engine.hook(payload("git push --force")))

    run(scenario)


def test_user_denial_reaches_the_model_and_runs_nothing(engine: Engine, shell: Any) -> None:
    async def scenario() -> None:
        task, item_id = await answered(engine, "npm publish")
        engine.decide(item_id, "deny", "not today")
        output = await task
        assert decision(output) == "deny"
        assert "not today" in reason(output)

    run(scenario)
    assert shell.calls == []
    assert audit_decisions() == ["deniedByUser"]


def test_allow_forever_stores_the_built_rule(engine: Engine, shell: Any) -> None:
    async def scenario() -> None:
        task, item_id = await answered(engine, 'git commit -m "one" && npm test')
        engine.decide(
            item_id,
            "allowForever",
            selections=[{"index": 0, "modes": ["keep", "keep", "keep", "wild"]}],
        )
        executed(await task)
        executed(await engine.hook(payload('git commit -m "two" && npm test')))

    run(scenario)
    assert [e.key for e in engine.allow.entries] == ["pattern:git commit -m *", "exact:npm test"]
    assert shell.commands == ['git commit -m "one" && npm test', 'git commit -m "two" && npm test']


def test_once_tick_keeps_a_statement_out_of_the_list(engine: Engine) -> None:
    async def scenario() -> None:
        task, item_id = await answered(engine, "a && b")
        engine.decide(item_id, "allowForever", selections=[{"index": 1, "once": True}])
        executed(await task)

    run(scenario)
    assert [e.key for e in engine.allow.entries] == ["exact:a"]
    assert "remembered 1 of 2" in paths.audit_log_file().read_text(encoding="utf-8")


def test_allow_selectively_writes_selective_rules(engine: Engine) -> None:
    async def scenario() -> None:
        task, item_id = await answered(engine, "git status")
        engine.decide(item_id, "allowSelective")
        await task

    run(scenario)
    assert engine.allow.entries[0].selective


def test_a_rule_that_does_not_cover_its_statement_is_refused(engine: Engine) -> None:
    async def scenario() -> None:
        task, item_id = await answered(engine, "git status")
        result = engine.ui(
            {
                "action": "decide",
                "id": item_id,
                "decision": "allowForever",
                "selections": [{"index": 0, "modes": ["keep", "drop"]}],
            }
        )
        assert not result["ok"] and "would not allow" in result["error"]
        assert engine.queue.get(item_id) is not None
        engine.decide(item_id, "deny")
        await task

    run(scenario)
    assert engine.allow.entries == []


def test_deciding_twice_fails(engine: Engine) -> None:
    async def scenario() -> None:
        task, item_id = await answered(engine, "x")
        engine.decide(item_id, "allowOnce")
        await task
        result = engine.ui({"action": "decide", "id": item_id, "decision": "allowOnce"})
        assert not result["ok"] and "no longer waiting" in result["error"]

    run(scenario)


def test_expiry_denies_and_runs_nothing(engine: Engine, shell: Any) -> None:
    engine.budget = 0.05

    async def scenario() -> None:
        output = await engine.hook(payload("sleep 1"))
        assert "NO DECISION IN TIME" in reason(output)
        assert not engine.queue.items

    run(scenario)
    assert shell.calls == []
    assert audit_decisions() == ["expired"]


def test_shutdown_answers_everything_pending(engine: Engine) -> None:
    async def scenario() -> None:
        task, _ = await answered(engine, "x")
        engine.shutdown()
        assert "CHAD shut down" in reason(await task)

    run(scenario)


def test_cancelled_hook_withdraws_its_question(engine: Engine) -> None:
    async def scenario() -> None:
        task, _ = await answered(engine, "x")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not engine.queue.items

    run(scenario)


def test_queue_is_fifo_and_raises_attention(engine: Engine) -> None:
    async def scenario() -> None:
        before = engine.attention_version
        first, first_id = await answered(engine, "one")
        second, second_id = await answered(engine, "two")
        assert [i.command for i in engine.queue.items] == ["one", "two"]
        assert engine.attention_version == before + 2
        assert engine.requested_view == "approval"
        engine.decide(second_id, "allowOnce")
        engine.decide(first_id, "allowOnce")
        assert "ran one" in executed(await first)
        assert "ran two" in executed(await second)

    run(scenario)


def test_policy_marker_opens_the_window_even_when_off(engine: Engine) -> None:
    switches.set_mode(Mode.OFF)

    async def scenario() -> None:
        output = await engine.hook(payload(f"echo hi {ALLOW_DENY_LIST_MARKER.upper()}"))
        assert decision(output) == "deny"
        assert "window" in reason(output)
        assert engine.requested_view == "policy"

    run(scenario)
    assert audit_decisions() == ["windowOpened"]


def test_selective_mode_runs_selective_rows_and_hands_back_the_rest(
    engine: Engine, shell: Any
) -> None:
    switches.set_mode(Mode.SELECTIVE)
    engine.allow.add_exact("git status", selective=True)
    engine.allow.add_exact("git log")

    async def scenario() -> None:
        executed(await engine.hook(payload("git status")))
        assert await engine.hook(payload("git log")) == {}
        assert not engine.queue.items

    run(scenario)
    assert shell.commands == ["git status"]
    assert audit_decisions() == ["allowedBySelectiveRule", "handedToHarness"]


def test_add_selective_flow_runs_the_captured_call(engine: Engine, shell: Any) -> None:
    switches.set_mode(Mode.SELECTIVE)

    async def scenario() -> None:
        assert await engine.hook(payload("npm run build", timeout=60000)) == {}
        task = asyncio.create_task(engine.hook(payload(f"  {ADD_SELECTIVE_MARKER}  ")))
        await asyncio.sleep(0.01)
        (item,) = engine.queue.items
        assert item.purpose == "addSelective" and item.command == "npm run build"
        bad = engine.ui({"action": "decide", "id": item.id, "decision": "allowForever"})
        assert not bad["ok"]
        engine.decide(item.id, "allowSelective")
        assert "ran npm run build" in executed(await task)
        executed(await engine.hook(payload("npm run build")))

    run(scenario)
    assert shell.calls == [
        ("npm run build", "C:/work", "bash"),
        ("npm run build", "C:/work", "bash"),
    ]


def test_add_selective_runs_the_captured_call_in_its_own_shell(engine: Engine, shell: Any) -> None:
    switches.set_mode(Mode.SELECTIVE)

    async def scenario() -> None:
        await engine.hook(payload("Get-Date", tool="PowerShell"))
        task = asyncio.create_task(engine.hook(payload(ADD_SELECTIVE_MARKER)))
        await asyncio.sleep(0.01)
        engine.decide(engine.queue.items[0].id, "allowSelective")
        executed(await task)

    run(scenario)
    assert shell.calls == [("Get-Date", "C:/work", "powershell")]
    assert engine.allow.match("Get-Date", "powershell", selective_only=True).allowed


def test_add_selective_errors(engine: Engine) -> None:
    async def scenario() -> None:
        output = await engine.hook(payload(ADD_SELECTIVE_MARKER))
        assert "only works in Selective" in reason(output)
        switches.set_mode(Mode.SELECTIVE)
        output = await engine.hook(payload(ADD_SELECTIVE_MARKER))
        assert "no recent command" in reason(output)
        # Appended to another command, the marker is just a comment.
        assert await engine.hook(payload(f"ls {ADD_SELECTIVE_MARKER}")) == {}

    run(scenario)


def test_add_selective_rechecks_the_deny_list(engine: Engine) -> None:
    switches.set_mode(Mode.SELECTIVE)

    async def scenario() -> None:
        await engine.hook(payload("git reset --hard"))
        switches.set_deny(True)
        output = await engine.hook(payload(ADD_SELECTIVE_MARKER))
        assert "deny list" in reason(output)

    run(scenario)


def test_ui_actions_mutate_through_the_engine(engine: Engine) -> None:
    opened: list[str] = []
    engine._opener = opened.append
    assert engine.ui({"action": "setMode", "mode": "selective"})["state"]["mode"] == "selective"
    assert switches.current_mode() is Mode.SELECTIVE
    assert engine.ui({"action": "setDeny", "value": True})["state"]["deny"] is True
    state = engine.ui({"action": "addAllow", "value": "git log *", "selective": True})["state"]
    assert state["allowList"]["entries"][0]["key"] == "pattern:git log *"
    assert engine.ui({"action": "setSelective", "key": "pattern:git log *", "value": False})["ok"]
    state = engine.ui(
        {"action": "editAllow", "key": "pattern:git log *", "value": 'git log "-5" *'}
    )
    assert state["state"]["allowList"]["entries"][0]["words"] == ["git", "log", '"-5"', "*"]
    assert not engine.ui({"action": "editAllow", "key": 'pattern:git log "-5" *', "value": " "})[
        "ok"
    ]
    assert engine.ui(
        {"action": "editAllow", "key": 'pattern:git log "-5" *', "value": "git log *"}
    )["ok"]
    assert engine.ui({"action": "deleteAllow", "key": "pattern:git log *"})["ok"]
    assert engine.ui({"action": "addDeny", "value": "npm publish"})["ok"]
    assert not engine.ui({"action": "addDeny", "value": "npm publish"})["ok"]
    assert engine.ui({"action": "setDenyRule", "key": "NPM PUBLISH", "value": False})["ok"]
    state = engine.ui({"action": "moveDeny", "key": "npm publish", "index": 0})["state"]
    assert state["denyList"]["rules"][0] == {
        "key": "npm publish",
        "words": "npm publish",
        "enabled": False,
    }
    assert engine.ui({"action": "open", "target": "audit"})["ok"]
    assert opened == [str(paths.audit_log_file())]
    assert not engine.ui({"action": "open", "target": "C:/Windows"})["ok"]
    assert not engine.ui({"action": "setMode", "mode": "yolo"})["ok"]
    assert not engine.ui({"action": "moveAllow", "key": "x", "index": "1"})["ok"]
    assert not engine.ui({"action": "nope"})["ok"]


def test_state_and_change_notifications(engine: Engine) -> None:
    seen: list[int] = []
    stop = engine.listen(lambda: seen.append(1))
    engine.ui({"action": "showPolicy"})
    stop()
    engine.ui({"action": "showPolicy"})
    state = engine.state()
    assert state["requestedView"] == "policy"
    assert state["attentionVersion"] == 2
    assert state["mode"] == "chad"
    assert [m["id"] for m in state["modes"]] == ["chad", "allowAll", "selective", "off"]
    assert len(seen) == 2  # the attention bump and the action itself


def test_the_call_timeout_caps_the_time_limit(engine: Engine, shell: Any) -> None:
    switches.set_mode(Mode.ALLOW_ALL)

    async def scenario() -> None:
        executed(await engine.hook(payload("echo a", timeout=120_000)))
        executed(await engine.hook(payload("echo b")))
        executed(await engine.hook(payload("echo c", timeout=7_200_000)))
        for invalid in ("soon", True, -5, 0):
            executed(await engine.hook(payload("echo d", timeout=invalid)))

    run(scenario)
    # Without a valid timeout, and above it, CHAD's own maxCommandSeconds applies.
    assert shell.limits == [120.0, 1800.0, 1800.0, 1800.0, 1800.0, 1800.0, 1800.0]


def test_an_approved_call_keeps_its_timeout(engine: Engine, shell: Any) -> None:
    async def scenario() -> None:
        task, item_id = await answered(engine, "npm test", timeout=30_000)
        engine.decide(item_id, "allowOnce")
        executed(await task)

    run(scenario)
    assert shell.limits == [30.0]


def test_a_background_call_is_started_and_answered_at_once(engine: Engine, shell: Any) -> None:
    switches.set_mode(Mode.ALLOW_ALL)

    async def scenario() -> dict:
        return await engine.hook(payload("npm run dev", run_in_background=True))

    output = asyncio.run(scenario())
    assert shell.calls == []
    assert shell.started == [("npm run dev", "C:/work", "bash")]
    assert decision(output) == "deny"
    text = reason(output)
    assert text.startswith("[CHAD] COMMAND STARTED IN THE BACKGROUND. Process id: 4242.")
    assert "Do not start it again" in text
    assert str(Path("C:/work") / "background.log") in text
    assert "4242" in text.splitlines()[-1]
    assert "everything" not in text and "tasklist" in text
    assert audit_decisions() == ["allowAllMode"]
    assert "background; pid=4242" in paths.audit_log_file().read_text(encoding="utf-8")


def test_an_approved_background_call_starts_in_its_own_shell(engine: Engine, shell: Any) -> None:
    async def scenario() -> str:
        task, item_id = await answered(
            engine, "Start-Sleep 60", tool="PowerShell", run_in_background=True
        )
        engine.decide(item_id, "allowOnce")
        return reason(await task)

    text = asyncio.run(scenario())
    assert text.startswith("[CHAD] COMMAND STARTED IN THE BACKGROUND.")
    assert shell.started == [("Start-Sleep 60", "C:/work", "powershell")]
    assert shell.calls == []


def test_a_captured_background_call_starts_in_the_background(engine: Engine, shell: Any) -> None:
    switches.set_mode(Mode.SELECTIVE)

    async def scenario() -> str:
        await engine.hook(payload("npm run dev", run_in_background=True))
        task = asyncio.create_task(engine.hook(payload(ADD_SELECTIVE_MARKER)))
        await asyncio.sleep(0.01)
        engine.decide(engine.queue.items[0].id, "allowSelective")
        return reason(await task)

    assert asyncio.run(scenario()).startswith("[CHAD] COMMAND STARTED IN THE BACKGROUND.")
    assert shell.started == [("npm run dev", "C:/work", "bash")]


def test_a_background_start_that_fails_names_the_cause(engine: Engine, shell: Any) -> None:
    switches.set_mode(Mode.ALLOW_ALL)

    async def fail(command: str, cwd: str, dialect: str, environment: Any) -> Any:
        raise FileNotFoundError("The working folder does not exist: C:/work.")

    engine._start_background = fail

    async def scenario() -> dict:
        return await engine.hook(payload("npm run dev", run_in_background=True))

    text = reason(asyncio.run(scenario()))
    assert text.startswith("[CHAD] CHAD COULD NOT RUN THE COMMAND. It did not run.")
    assert "The working folder does not exist: C:/work." in text
    assert audit_decisions() == ["error"]


def test_the_hook_environment_reaches_every_run(engine: Engine, shell: Any) -> None:
    session = {"PATH": "C:/session/bin", "PROJECT": "one"}

    async def scenario() -> None:
        switches.set_mode(Mode.ALLOW_ALL)
        executed(await engine.hook(payload("echo a"), session))
        await engine.hook(payload("npm run dev", run_in_background=True), session)
        executed(await engine.hook(payload("echo b")))
        switches.set_mode(Mode.CHAD)
        task = asyncio.create_task(engine.hook(payload("npm test"), session))
        for _ in range(100):
            await asyncio.sleep(0)
            if engine.queue.items:
                break
        engine.decide(engine.queue.items[0].id, "allowOnce")
        executed(await task)
        switches.set_mode(Mode.SELECTIVE)
        await engine.hook(payload("make"), session)
        task = asyncio.create_task(engine.hook(payload(ADD_SELECTIVE_MARKER)))
        await asyncio.sleep(0.01)
        engine.decide(engine.queue.items[0].id, "allowSelective")
        executed(await task)

    run(scenario)
    # Direct, background, no environment sent (the dispatcher's own), approved, add-selective:
    # the captured call's environment, not the marker call's.
    assert shell.environments == [session, session, None, session, session]
