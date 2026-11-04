"""Unit tests run no shell command: the engine gets a stand-in for chad.executor.run and
chad.background.start, and the real ones fail the test if anything reaches them. The real ones
are tested in tests/integration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from chad import background, executor, policy, switches
from chad.analysis import Dialect, analyze
from chad.background import Started
from chad.executor import CapturedOutput, ExecutionResult
from chad.switches import Mode


class FakeShell:
    """Records each command instead of running it, and answers as if it printed `ran <command>`."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Dialect]] = []
        self.limits: list[float] = []
        self.started: list[tuple[str, str, Dialect]] = []
        self.environments: list[Mapping[str, str] | None] = []

    async def __call__(
        self,
        command: str,
        cwd: str,
        dialect: Dialect,
        timeout_seconds: float,
        max_output_bytes: int,
        environment: Mapping[str, str] | None = None,
    ) -> ExecutionResult:
        self.calls.append((command, cwd, dialect))
        self.environments.append(environment)
        self.limits.append(timeout_seconds)
        out = f"ran {command}".encode()
        return ExecutionResult(
            exit_code=0,
            stdout=CapturedOutput(out, b"", len(out), max_output_bytes),
            stderr=CapturedOutput(b"", b"", 0, max_output_bytes),
            timed_out=False,
            duration_seconds=0.0,
            time_limit_seconds=timeout_seconds,
        )

    async def start(
        self, command: str, cwd: str, dialect: Dialect, environment: Mapping[str, str] | None = None
    ) -> Started:
        """Stands in for chad.background.start."""
        self.started.append((command, cwd, dialect))
        self.environments.append(environment)
        return Started(4242, Path(cwd) / "background.log")

    @property
    def commands(self) -> list[str]:
        return [command for command, _, _ in self.calls]


@pytest.fixture(autouse=True)
def only_deny_or_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every answer of every engine in the unit tests is deny, or a skip where one is allowed.

    CHAD never answers allow (CLAUDE.md). It skips for a tool it does not handle, in Off mode,
    for an empty command, and in Selective mode for a command no Selective rule covers, unless
    Selective mode refuses those.
    """
    real = policy.Engine.hook

    async def checked(self: policy.Engine, payload: dict, environment: object = None) -> dict:
        mode = switches.current_mode()
        hands_back = mode is Mode.OFF or (
            mode is Mode.SELECTIVE and not switches.selective_refuses()
        )
        output = await real(self, payload, environment)
        if output == {}:
            call = policy._Call(payload)
            assert (
                call.tool not in policy.TOOLS
                or hands_back
                or analyze(call.command, call.dialect).is_empty
            ), f"no decision outside the skip cases: {payload}"
        else:
            decision = output["hookSpecificOutput"]["permissionDecision"]
            assert decision == "deny", f"CHAD answered {decision!r}: {payload}"
        return output

    monkeypatch.setattr(policy.Engine, "hook", checked)


@pytest.fixture(autouse=True)
def no_real_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    async def refuse(*_: object) -> ExecutionResult:
        raise AssertionError("a unit test reached a real shell; give the Engine a FakeShell")

    monkeypatch.setattr(executor, "run", refuse)
    monkeypatch.setattr(policy, "run_command", refuse)
    monkeypatch.setattr(background, "start", refuse)
    monkeypatch.setattr(policy, "start_in_background", refuse)


@pytest.fixture
def shell() -> FakeShell:
    return FakeShell()
