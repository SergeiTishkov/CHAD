"""The one place where CHAD decides: hook calls, control requests and the user's answers.

Everything the UI shows comes from `state()` and everything it changes goes through `ui()`, so
the window can never disagree with what the dispatcher enforces.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from chad import audit, background, lookup, messages, paths, switches
from chad.allowlist import AllowList, AllowListError, Entry, Kind
from chad.analysis import (
    Analysis,
    Dialect,
    Statement,
    analyze,
    dialect_for_tool,
    words,
)
from chad.approvals import (
    ApprovalQueue,
    Choice,
    PendingItem,
    Purpose,
    SelectionError,
    StatementInfo,
    parse_selections,
    rules_to_store,
)
from chad.audit import Decision
from chad.background import Starter
from chad.background import start as start_in_background
from chad.captures import CaptureStore
from chad.config import Config
from chad.denylist import DenyList, DenyListError
from chad.executor import Executor
from chad.executor import run as run_command
from chad.patterns import Pattern
from chad.switches import Mode

TOOLS = ("Bash", "PowerShell")
ALLOW_DENY_LIST_MARKER = "#chad:allow-deny-list"
ADD_SELECTIVE_MARKER = "#chad:add-selective-command"
OPEN_TARGETS = ("allow", "deny", "config", "audit", "folder")


class ActionError(Exception):
    """A UI request that cannot be carried out; the message is shown to the user."""


class _Call:
    """The parts of a hook payload CHAD looks at."""

    def __init__(self, payload: dict[str, Any], environment: dict[str, str] | None = None) -> None:
        # The environment the command runs with; None means the dispatcher's own.
        self.environment = environment
        self.tool = str(payload.get("tool_name") or "")
        tool_input = payload.get("tool_input")
        self.tool_input: dict[str, Any] = tool_input if isinstance(tool_input, dict) else {}
        self.command = str(self.tool_input.get("command") or "")
        self.description = str(self.tool_input.get("description") or "")
        self.cwd = str(payload.get("cwd") or "")
        self.session_id = str(payload.get("session_id") or "")
        self.permission_mode = str(payload.get("permission_mode") or "")
        # Optional hints of Claude Code's Bash and PowerShell tools; without them CHAD's own
        # limits apply. `timeout` is in milliseconds.
        timeout = self.tool_input.get("timeout")
        valid = isinstance(timeout, int | float) and not isinstance(timeout, bool) and timeout > 0
        self.timeout_seconds: float | None = timeout / 1000 if valid else None
        self.background = self.tool_input.get("run_in_background") is True

    @property
    def dialect(self) -> Dialect:
        return dialect_for_tool(self.tool)

    def audit(
        self, decision: Decision, note: str | None = None, command: str | None = None
    ) -> None:
        audit.record(decision, self.tool, self.session_id, self.cwd, command or self.command, note)


def default_opener(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)
    else:
        import subprocess

        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])


class Engine:
    def __init__(
        self,
        config: Config,
        allow: AllowList | None = None,
        deny: DenyList | None = None,
        *,
        opener: Callable[[str], None] = default_opener,
        on_shutdown: Callable[[], None] = lambda: None,
        execute: Executor | None = None,
        start_background: Starter | None = None,
    ) -> None:
        # Shared limit for approval and execution, leaving the configured hook safety margin.
        self.budget = config.approval_budget_seconds
        self.max_command_seconds = max(1, config.max_command_seconds)
        self.max_output_bytes = max(2_000, config.max_output_bytes)
        self.page_size = max(1, config.find_rules_page_size)
        self.allow = allow or AllowList(paths.allow_list_file())
        self.deny = deny or DenyList(paths.deny_list_file())
        self.captures = CaptureStore()
        self.queue = ApprovalQueue(self.changed)
        self.attention_version = 0
        self.requested_view: str | None = None
        self._listeners: list[Callable[[], None]] = []
        self._opener = opener
        self._on_shutdown = on_shutdown
        self._running: dict[str, asyncio.Task[None]] = {}
        self._execute = execute or run_command
        self._start_background = start_background or start_in_background

    # -- change notification -----------------------------------------------------------------

    def listen(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback)

    def changed(self) -> None:
        for callback in list(self._listeners):
            callback()

    def _attention(self, view: str) -> None:
        self.attention_version += 1
        self.requested_view = view
        self.changed()

    # -- hook calls --------------------------------------------------------------------------

    async def hook(
        self, payload: dict[str, Any], environment: dict[str, str] | None = None
    ) -> dict[str, Any]:
        call = _Call(payload, environment)
        if call.tool not in TOOLS:
            return messages.NO_DECISION
        deadline = time.monotonic() + self.budget

        # Control requests come first: the window is where CHAD gets switched back on.
        if ALLOW_DENY_LIST_MARKER in call.command.lower():
            self._attention("policy")
            call.audit(Decision.WINDOW_OPENED)
            return messages.deny(messages.WINDOW_OPENED)
        if call.command.strip().lower() == ADD_SELECTIVE_MARKER:
            return await self._add_selective(call, deadline)
        request = lookup.parse(call.command)
        if request is not None:
            return self._lookup(call, request)

        mode = switches.current_mode()
        if mode is Mode.OFF:
            return messages.NO_DECISION
        analysis = analyze(call.command, call.dialect)
        if analysis.is_empty:
            return messages.NO_DECISION

        refusal = self._deny_check(call, analysis)
        if refusal:
            return refusal

        if mode is Mode.SELECTIVE:
            matched = self._all_allowed(analysis, call.dialect, selective_only=True)
            if matched is not None:
                return await self._run_command(
                    call,
                    Decision.ALLOWED_BY_SELECTIVE_RULE,
                    deadline,
                    "selectiveRule=" + "; ".join(matched),
                )
            if switches.selective_refuses():
                return self._refuse_outside_selective(call, analysis)
            self.captures.put(
                call.session_id, call.tool, call.tool_input, call.cwd, call.environment
            )
            call.audit(Decision.HANDED_TO_HARNESS)
            return messages.NO_DECISION

        if mode is Mode.ALLOW_ALL:
            return await self._run_command(call, Decision.ALLOW_ALL_MODE, deadline, "mode=allowAll")

        matched = self._all_allowed(analysis, call.dialect, selective_only=False)
        if matched is not None:
            return await self._run_command(
                call, Decision.ALLOWED_BY_RULE, deadline, "rule=" + "; ".join(matched)
            )

        item = self._pending(
            call.command,
            call.tool,
            call.dialect,
            call,
            analysis,
            Purpose.APPROVE,
            call.tool_input,
            deadline,
            call.environment,
        )
        return await self._wait(item, call, deadline)

    def _deny_check(
        self, call: _Call, analysis: Analysis, command: str | None = None
    ) -> dict[str, Any] | None:
        if not switches.deny_enabled():
            return None
        hit = self.deny.first_match(s.normalized for s in analysis.statements)
        if hit is None:
            return None
        rule, statement = hit
        call.audit(Decision.DENIED_BY_RULE, f"rule={rule.words}", command)
        return messages.deny(messages.denied_by_rule(rule.words, statement))

    def _all_allowed(
        self, analysis: Analysis, dialect: Dialect, selective_only: bool
    ) -> list[str] | None:
        """What allowed each statement, or None when any statement is not allowed."""
        matched = []
        for statement in analysis.statements:
            if statement.blocking:
                return None
            hit = self.allow.match(statement.normalized, dialect, selective_only)
            if not hit.allowed:
                return None
            matched.append(hit.matched_by or "")
        return matched

    # -- Selective mode that refuses the rest --------------------------------------------------

    def _selective_rules(self) -> list[Entry]:
        return [e for e in self.allow.entries if e.selective]

    def _uncovered(self, analysis: Analysis, dialect: Dialect) -> list[tuple[Statement, str]]:
        """The statements no Selective rule covers, each with the reason."""
        found = []
        for statement in analysis.statements:
            if statement.blocking:
                constructs = ", ".join(statement.blocking)
                found.append((statement, f"it contains {constructs}, which no rule can allow"))
            elif not self.allow.match(statement.normalized, dialect, selective_only=True).allowed:
                found.append((statement, "no Selective rule matches it"))
        return found

    def _refuse_outside_selective(self, call: _Call, analysis: Analysis) -> dict[str, Any]:
        uncovered = self._uncovered(analysis, call.dialect)
        call.audit(
            Decision.REFUSED_OUTSIDE_SELECTIVE,
            "uncovered=" + "; ".join(s.text for s, _ in uncovered),
        )
        shown = [(s.text, why) for s, why in uncovered]
        if not switches.selective_lists():
            return messages.deny(messages.outside_selective(shown, None, None))
        program = lookup.program_of(uncovered[0][0].normalized, call.dialect) if uncovered else None
        rules = lookup.for_program(self._selective_rules(), program) if program else []
        return messages.deny(
            messages.outside_selective(
                shown,
                program,
                [lookup.shown(e) for e in rules[: lookup.SHORT_LIST]],
                len(rules),
            )
        )

    def _lookup(self, call: _Call, request: lookup.Request) -> dict[str, Any]:
        """#chad:find-rules and #chad:check; open only while Selective mode refuses and lists."""
        listing = (
            switches.current_mode() is Mode.SELECTIVE
            and switches.selective_refuses()
            and switches.selective_lists()
        )
        if not listing:
            call.audit(Decision.ERROR, f"{request.kind} request while rule lookup is off")
            return messages.deny(messages.error(messages.LOOKUP_OFF))
        if request.kind is lookup.RequestKind.CHECK:
            return self._check(call, request.text)
        try:
            query, number = lookup.read_find(request.text)
        except lookup.FindError as exc:
            call.audit(Decision.ERROR, f"find-rules: {exc}")
            return messages.deny(messages.error(f"{exc} Nothing ran."))
        page = lookup.find(self._selective_rules(), query, number, self.page_size)
        call.audit(Decision.RULES_LOOKUP, f"find-rules; matches={page.total}; page={page.number}")
        return messages.deny(
            messages.rules_found(
                query,
                [lookup.shown(e) for e in page.rules],
                page.first,
                page.total,
                page.number,
                page.pages,
                page.has_more,
            )
        )

    def _check(self, call: _Call, command: str) -> dict[str, Any]:
        """Whether a command would run now, by the same rules a real call meets."""
        analysis = analyze(command, call.dialect)
        if "\n" in command or "\r" in command:
            problem = "Put the command to check on the same line as #chad:check; `a && b` works."
        elif analysis.is_empty:
            problem = "Put the command to check after #chad:check, on the same line."
        else:
            problem = None
        if problem:
            call.audit(Decision.ERROR, f"check: {problem}")
            return messages.deny(messages.error(f"{problem} Nothing ran."))
        findings = []
        runs = True
        for statement in analysis.statements:
            hit = self.deny.first_match([statement.normalized]) if switches.deny_enabled() else None
            if hit is not None:
                findings.append(
                    f"{statement.text}: on the deny list (rule: {hit[0].words}), refused "
                    "whatever the allow rules say"
                )
            elif statement.blocking:
                constructs = ", ".join(statement.blocking)
                findings.append(f"{statement.text}: contains {constructs}, which no rule can allow")
            else:
                match = self.allow.match(statement.normalized, call.dialect, selective_only=True)
                if match.allowed:
                    rule = match.matched_by or ""
                    rule = f"exact: {statement.normalized}" if rule == "exact" else rule
                    findings.append(f"{statement.text}: covered by {rule}")
                    continue
                findings.append(f"{statement.text}: no Selective rule matches it")
            runs = False
        call.audit(Decision.RULES_LOOKUP, f"check; runs={str(runs).lower()}")
        return messages.deny(messages.checked(command, findings, runs))

    def _pending(
        self,
        command: str,
        tool: str,
        dialect: Dialect,
        call: _Call,
        analysis: Analysis,
        purpose: Purpose,
        tool_input: dict[str, Any] | None = None,
        deadline: float | None = None,
        environment: dict[str, str] | None = None,
    ) -> PendingItem:
        selective_only = purpose is Purpose.ADD_SELECTIVE
        execution_deadline = deadline if deadline is not None else time.monotonic() + self.budget
        statements = tuple(
            StatementInfo.of(
                s, dialect, self.allow.match(s.normalized, dialect, selective_only).matched_by
            )
            for s in analysis.statements
        )
        item = PendingItem(
            command=command,
            tool=tool,
            dialect=dialect,
            description=call.description,
            cwd=call.cwd,
            session_id=call.session_id,
            permission_mode=call.permission_mode,
            purpose=purpose,
            statements=statements,
            deadline=time.time() + max(0.0, execution_deadline - time.monotonic()),
            tool_input=dict(tool_input or {}),
            via_tool=call.tool,
            budget_deadline=execution_deadline,
            environment=environment,
        )
        self.queue.add(item)
        self._attention("approval")
        return item

    async def _wait(self, item: PendingItem, call: _Call, deadline: float) -> dict[str, Any]:
        try:
            remaining = max(0.0, deadline - time.monotonic())
            return await asyncio.wait_for(asyncio.shield(item.future), remaining)
        except TimeoutError:
            output = messages.deny(messages.expired())
            if self.queue.resolve(item.id, output):
                call.audit(Decision.EXPIRED, command=item.command)
                return item.future.result()
            # A decision at the edge of the budget means CHAD already owns the command.
            # Wait for its bounded run instead of letting Claude Code run it a second time.
            return await asyncio.shield(item.future)
        except asyncio.CancelledError:
            # Claude Code stopped waiting (the user interrupted it): withdraw the question.
            if self.queue.resolve(item.id, messages.NO_DECISION):
                call.audit(Decision.ERROR, "withdrawn: the hook went away", item.command)
            else:
                task = self._running.get(item.id)
                if task is not None and not task.done():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                    call.audit(
                        Decision.ERROR, "execution stopped because the hook went away", item.command
                    )
            raise

    async def _run_command(
        self,
        call: _Call,
        decision: Decision,
        deadline: float,
        note: str | None = None,
    ) -> dict[str, Any]:
        remaining = deadline - time.monotonic() - 1.0
        if remaining <= 0:
            call.audit(Decision.ERROR, "time budget ended before command execution")
            return messages.execution_budget_expired()

        if call.background:
            return await self._run_in_background(call, decision, note)
        limit = min(float(self.max_command_seconds), remaining)
        if call.timeout_seconds is not None:
            limit = min(limit, call.timeout_seconds)
        try:
            result = await self._execute(
                call.command,
                call.cwd,
                call.dialect,
                limit,
                self.max_output_bytes,
                call.environment,
            )
        except asyncio.CancelledError:
            call.audit(Decision.ERROR, "command execution cancelled")
            raise
        except Exception as exc:
            call.audit(Decision.ERROR, f"execution could not start: {exc}")
            return messages.execution_failed(str(exc))

        audit_parts = [part for part in (note, f"exitCode={result.exit_code}") if part]
        audit_parts.append(f"duration={result.duration_seconds:.3f}s")
        if result.timed_out:
            audit_parts.append(f"timedOutAfter={result.time_limit_seconds:.3f}s")
        if result.execution_note:
            audit_parts.append("resultIncomplete=true")
        if result.left_running:
            audit_parts.append("leftRunning=true")
        call.audit(decision, "; ".join(audit_parts))
        return messages.executed(result, self.max_output_bytes)

    async def _run_in_background(
        self, call: _Call, decision: Decision, note: str | None
    ) -> dict[str, Any]:
        try:
            started = await self._start_background(
                call.command, call.cwd, call.dialect, call.environment
            )
        except Exception as exc:
            call.audit(Decision.ERROR, f"background start failed: {exc}")
            return messages.execution_failed(str(exc))
        parts = (note, "background", f"pid={started.pid}", f"log={started.log}")
        call.audit(decision, "; ".join(part for part in parts if part))
        stop = background.stop_command(started.pid, call.dialect)
        return messages.started_in_background(started.pid, str(started.log), stop)

    def _start_approved_execution(
        self, item: PendingItem, decision: Decision, note: str, deadline: float
    ) -> None:
        claimed = self.queue.take(item.id)
        if claimed is None:
            raise ActionError("That command is no longer waiting; it was decided or expired.")
        task = asyncio.create_task(
            self._finish_approved_execution(claimed, decision, note, deadline)
        )
        self._running[item.id] = task

    async def _finish_approved_execution(
        self, item: PendingItem, decision: Decision, note: str, deadline: float
    ) -> None:
        call = _Call(
            {
                "tool_name": item.tool,
                "cwd": item.cwd,
                "session_id": item.session_id,
                "tool_input": item.tool_input,
            },
            item.environment,
        )
        call.command = item.command
        try:
            try:
                output = await self._run_command(call, decision, deadline, note)
            except asyncio.CancelledError:
                self.queue.complete(item, messages.NO_DECISION)
                raise
            except Exception as exc:
                call.audit(Decision.ERROR, f"execution failed: {exc}")
                output = messages.execution_failed(str(exc))
            self.queue.complete(item, output)
        finally:
            self._running.pop(item.id, None)

    async def _add_selective(self, call: _Call, deadline: float) -> dict[str, Any]:
        if switches.current_mode() is not Mode.SELECTIVE:
            call.audit(Decision.ERROR, "add-selective outside Selective mode")
            return messages.deny(messages.NOT_SELECTIVE)
        capture = self.captures.take(call.session_id)
        analysis = analyze(capture.command, dialect_for_tool(capture.tool)) if capture else None
        if capture is None or analysis is None or analysis.is_empty:
            call.audit(Decision.ERROR, "add-selective with nothing captured")
            return messages.deny(messages.NOTHING_CAPTURED)
        refusal = self._deny_check(call, analysis, capture.command)
        if refusal:
            return refusal
        item = self._pending(
            capture.command,
            capture.tool,
            dialect_for_tool(capture.tool),
            call,
            analysis,
            Purpose.ADD_SELECTIVE,
            capture.tool_input,
            deadline,
            capture.environment,
        )
        return await self._wait(item, call, deadline)

    # -- decisions ---------------------------------------------------------------------------

    def decide(
        self, item_id: str, decision: str, reason: str | None = None, selections: Any = None
    ) -> None:
        item = self.queue.get(str(item_id))
        if item is None:
            raise ActionError("That command is no longer waiting; it was decided or expired.")
        try:
            choice = Choice(decision)
        except ValueError:
            raise ActionError(f"Unknown decision {decision!r}.") from None
        adding = item.purpose is Purpose.ADD_SELECTIVE
        if adding and choice not in (Choice.ALLOW_SELECTIVE, Choice.DENY):
            raise ActionError("Here the only choices are Add selectively and Cancel.")
        call = _Call(
            {
                "tool_name": item.tool,
                "cwd": item.cwd,
                "session_id": item.session_id,
            }
        )
        call.command = item.command

        if choice is Choice.DENY:
            call.audit(Decision.DENIED_BY_USER, (reason or "").strip() or None)
            self.queue.resolve(item.id, messages.deny(messages.rejected_by_user(reason)))
            return

        # The deny list and the mode may have changed while the item was on screen.
        analysis = analyze(item.command, item.dialect)
        refusal = self._deny_check(call, analysis)
        if refusal:
            self.queue.resolve(item.id, refusal)
            raise ActionError("The command is now on the deny list, so it was refused.")
        if adding and switches.current_mode() is not Mode.SELECTIVE:
            call.audit(Decision.ERROR, "add-selective after leaving Selective mode")
            self.queue.resolve(item.id, messages.deny(messages.NOT_SELECTIVE))
            raise ActionError("CHAD is no longer in Selective mode; nothing was added.")

        try:
            chosen = parse_selections(selections, item.statements)
        except SelectionError as exc:
            raise ActionError(str(exc)) from None

        if choice is Choice.ALLOW_ONCE:
            self._start_approved_execution(
                item, Decision.ALLOW_ONCE, "approved once by user", item.budget_deadline
            )
            return

        if adding:
            for statement, selection in zip(item.statements, chosen, strict=True):
                if statement.blocking:
                    raise ActionError(
                        f"{statement.text!r} contains {', '.join(statement.blocking)}; "
                        "no rule can allow it."
                    )
                if statement.allowed_by is None and selection.once:
                    raise ActionError("Every statement has to be covered by a Selective rule.")
        try:
            rules = rules_to_store(item.statements, chosen)
        except SelectionError as exc:
            raise ActionError(str(exc)) from None

        selective = choice is Choice.ALLOW_SELECTIVE
        try:
            for rule in rules:
                if rule.pattern is not None:
                    self.allow.add_pattern(rule.pattern, selective)
                else:
                    self.allow.add_exact(rule.exact or "", selective)
        except AllowListError as exc:
            raise ActionError(str(exc)) from None

        storable = sum(1 for s in item.statements if s.storable)
        notes = [f"rule={r.text}" for r in rules]
        if len(rules) < storable:
            notes.append(f"remembered {len(rules)} of {storable}")
        decision_kind = Decision.ALLOW_SELECTIVE if selective else Decision.ALLOW_FOREVER

        if not adding:
            self._start_approved_execution(
                item,
                decision_kind,
                "; ".join(notes) or "approved by user",
                item.budget_deadline,
            )
            return
        uncovered = [
            s.text
            for s in analysis.statements
            if not self.allow.match(s.normalized, item.dialect, selective_only=True).allowed
        ]
        if uncovered:
            self.queue.resolve(
                item.id,
                messages.deny(
                    messages.error(
                        "The rule was stored but does not cover every statement of the command. "
                        "Tell the user."
                    )
                ),
            )
            raise ActionError(
                "Stored, but these statements are not covered by a Selective rule: "
                + "; ".join(uncovered)
            )
        self._start_approved_execution(
            item,
            decision_kind,
            f"promoted from Selective request; remembered {len(rules)} statement(s)",
            item.budget_deadline,
        )

    def shutdown(self) -> None:
        for item in self.queue.drain(lambda _: messages.deny(messages.shut_down())):
            audit.record(
                Decision.ERROR,
                item.tool,
                item.session_id,
                item.cwd,
                item.command,
                "CHAD shut down before a decision",
            )

        for task in self._running.values():
            task.cancel()

    # -- the UI ------------------------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        mode = switches.current_mode()
        return {
            "mode": str(mode),
            "modes": [
                {"id": str(m), "description": switches.description(m)}
                for m in switches.DESCRIPTIONS
            ],
            "deny": switches.deny_enabled(),
            "selectiveRefuse": switches.selective_refuses(),
            "selectiveList": switches.selective_lists(),
            "pending": [item.to_ui() for item in self.queue.items],
            "attentionVersion": self.attention_version,
            "requestedView": self.requested_view,
            "allowList": {
                "path": str(self.allow.path),
                "error": self.allow.error,
                "entries": [
                    {
                        "key": e.key,
                        "kind": str(e.kind),
                        "value": e.value,
                        "selective": e.selective,
                        # The words the window's editor shows; quotes stay with their word.
                        "words": [] if e.kind is Kind.REGEX else words(e.value),
                    }
                    for e in self.allow.entries
                ],
            },
            "denyList": {
                "path": str(self.deny.path),
                "error": self.deny.error,
                "rules": [
                    {"key": r.words, "words": r.words, "enabled": r.enabled}
                    for r in self.deny.rules
                ],
            },
            "dataRoot": str(paths.data_root()),
            "budgetSeconds": self.budget,
            "pid": os.getpid(),
        }

    def ui(self, request: dict[str, Any]) -> dict[str, Any]:
        """Carry out one UI action and answer with the new state, or with the error."""
        try:
            self._act(str(request.get("action") or ""), request)
        except (ActionError, AllowListError, DenyListError) as exc:
            self.changed()
            return {"ok": False, "error": str(exc), "state": self.state()}
        self.changed()
        return {"ok": True, "state": self.state()}

    def _act(self, action: str, request: dict[str, Any]) -> None:
        key = str(request.get("key") or "")
        value = request.get("value")
        index = request.get("index")
        match action:
            case "getState":
                pass
            case "setMode":
                try:
                    switches.set_mode(Mode(str(request.get("mode"))))
                except ValueError:
                    raise ActionError(f"Unknown mode {request.get('mode')!r}.") from None
            case "setDeny":
                switches.set_deny(bool(value))
            case "setSelectiveRefuse":
                switches.set_selective_refuse(bool(value))
            case "setSelectiveList":
                switches.set_selective_list(bool(value))
            case "decide":
                self.decide(
                    str(request.get("id")),
                    str(request.get("decision")),
                    request.get("reason"),
                    request.get("selections"),
                )
            case "setSelective":
                self.allow.set_selective(key, bool(value))
            case "moveAllow":
                self.allow.move(key, _index(index))
            case "deleteAllow":
                self.allow.remove(key)
            case "addAllow":
                pattern = Pattern.parse(str(value or ""))
                if pattern.is_empty:
                    raise ActionError("Type the command or pattern to allow.")
                self.allow.add_pattern(pattern, bool(request.get("selective")))
            case "editAllow":
                pattern = Pattern.parse(str(value or ""))
                if pattern.is_empty:
                    raise ActionError("Type the command or pattern to allow.")
                self.allow.edit(key, pattern)
            case "setDenyRule":
                self.deny.set_enabled(key, bool(value))
            case "moveDeny":
                self.deny.move(key, _index(index))
            case "deleteDeny":
                self.deny.remove(key)
            case "addDeny":
                if not self.deny.add(str(value or "")):
                    raise ActionError("That deny rule is empty or already listed.")
            case "showPolicy":
                self._attention("policy")
            case "open":
                self._open(str(request.get("target") or ""))
            case "shutdown":
                self._on_shutdown()
            case _:
                raise ActionError(f"Unknown action {action!r}.")

    def _open(self, target: str) -> None:
        files = {
            "allow": self.allow.path,
            "deny": self.deny.path,
            "config": paths.config_file(),
            "audit": paths.audit_log_file(),
            "folder": paths.data_root(),
        }
        if target not in files:
            raise ActionError(f"Unknown target {target!r}; expected one of {OPEN_TARGETS}.")
        path = files[target]
        if target == "audit" and not path.exists():
            path.touch()
        try:
            self._opener(str(path))
        except OSError as exc:
            raise ActionError(f"Could not open {path}: {exc}") from None


def _index(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ActionError("index must be a whole number")
    return value
