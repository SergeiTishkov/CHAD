"""What the hook prints back to Claude Code, and the words the model reads in a refusal.

CHAD has two answers: deny with a reason, or no decision. There is no allow (CLAUDE.md). Each
deny reason says what happened and what the model should do next.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from chad import PREFIX
from chad.executor import ExecutionResult

NO_DECISION: dict[str, Any] = {}


def deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def chad_broken(cause: str, log: Path | None = None) -> dict[str, Any]:
    """CHAD was meant to decide and failed: the model is told so, and how to work meanwhile."""
    return deny(
        f"{PREFIX} CHAD IS BROKEN. The command did not run.\n{cause}\n"
        + (f"Details: {log}\n" if log else "")
        + "CHAD needs fixing before it can decide again. Do not send the command again by "
        "yourself; tell the user that CHAD failed, with the cause above.\n"
        "Until it is repaired, the user can type `chad mode off` in a terminal of their own, and "
        "the harness handles approval without CHAD."
    )


def rejected_by_user(reason: str | None) -> str:
    given = (reason or "").strip()
    return (
        f"{PREFIX} COMMAND REJECTED BY THE USER. It did not run.\n"
        + (f"The user's reason: {given}\n" if given else "No reason was given.\n")
        + "Do not send this command again. Respond to what the user said, or ask them what to "
        "do instead."
    )


def denied_by_rule(rule: str, statement: str) -> str:
    return (
        f"{PREFIX} Refused: this command is on the deny list.\n"
        f"Rule: {rule}\n"
        f"Statement: {statement}\n"
        "The rule compares words in any order, so a reworded command is refused as well. Do "
        "not look for a way around it: explain to the user what you meant to do, and leave the "
        "choice to them."
    )


RULE_READING = (
    "How the rules read: an exact rule is the whole statement, word for word. In a pattern, `*` "
    "stands for one or more whole words, never for a redirection. A regex rule is searched in "
    "the statement. Each statement of a chain (`&&`, `||`, `;`, `|`) must match a rule on its "
    "own, and a statement with command substitution, eval or a similar construct never matches."
)

LOOKUP_HINT = (
    "To look further, send one of these as the whole command; CHAD answers it and runs nothing:\n"
    "  #chad:find-rules <words>   the Selective rules that contain any of the words\n"
    "  #chad:check <command>      whether that command would run now, and if not, why"
)


def outside_selective(
    uncovered: Sequence[tuple[str, str]],
    program: str | None,
    rules: Sequence[str] | None,
    total: int = 0,
) -> str:
    """Selective mode refuses what its rules do not cover. `rules` is None when the user keeps
    the rules from the agent; otherwise the rules for `program`, of `total` such rules."""
    lines = [
        f"{PREFIX} Refused: no Selective rule covers this command. It did not run.",
        "CHAD is in Selective Allowlist mode, where it refuses every command its Selective rules "
        "do not cover.",
    ]
    lines.extend(f"Not covered: {text} ({why})" for text, why in uncovered)
    if rules is None:
        lines.append(
            "CHAD does not show its rules here. Ask the user which commands are allowed, or to "
            "add a rule."
        )
    else:
        name = f"`{program}`" if program else "this program"
        if not total:
            lines.append(f"No Selective rule is for {name}.")
        else:
            shown = f"{len(rules)} of {total}" if len(rules) < total else str(total)
            lines.append(f"Selective rules for {name} ({shown}):")
            lines.extend(f"  {rule}" for rule in rules)
        lines.extend((RULE_READING, LOOKUP_HINT))
    lines.append(
        "Do not send this command again as it is. Use a command the Selective rules cover, or "
        "ask the user to add a rule or to change the mode."
    )
    return "\n".join(lines)


def rules_found(
    query: Sequence[str],
    rules: Sequence[str],
    first: int,
    total: int,
    page: int,
    pages: int,
    has_more: bool,
) -> str:
    """The answer to #chad:find-rules: one page of the Selective rules that matched."""
    searched = " ".join(query)
    lines = [
        f"{PREFIX} SELECTIVE RULES. This was a request to CHAD; nothing ran.",
        f"Search: {searched}" if searched else "Search: every Selective rule",
    ]
    if not total:
        lines.append(
            "No Selective rule contains any of these words. Try other words, or ask the user to "
            "add a rule."
        )
    elif not rules:
        lines.append(f"Page {page} is past the end: {total} rules match, on {pages} page(s).")
    else:
        lines.append(f"Rules {first + 1}-{first + len(rules)} of {total}:")
        lines.extend(f"  {rule}" for rule in rules)
        if has_more:
            command = " ".join(("#chad:find-rules", "--page", str(page + 1), *query))
            lines.append(
                "More rules match. A narrower search is the better next step; the next page is "
                f"`{command}`."
            )
    lines.append(RULE_READING)
    return "\n".join(lines)


def checked(command: str, findings: Sequence[str], runs: bool) -> str:
    """The answer to #chad:check: whether the command would run now, statement by statement."""
    verdict = "WOULD RUN" if runs else "WOULD BE REFUSED"
    lines = [
        f"{PREFIX} CHECK: {verdict}. This was a request to CHAD; nothing ran.",
        f"Command: {command}",
        *(f"- {finding}" for finding in findings),
    ]
    if runs:
        lines.append("To run it, send the command itself, without #chad:check.")
    else:
        lines.extend((RULE_READING, "Change the command, or ask the user to add a rule."))
    return "\n".join(lines)


LOOKUP_OFF = (
    "#chad:find-rules and #chad:check answer only while CHAD is in Selective Allowlist mode, "
    "refuses the commands its Selective rules do not cover, and shows those rules to the agent. "
    "That is not the case now. Nothing ran. Ask the user which commands are allowed."
)


def expired() -> str:
    return (
        f"{PREFIX} NO DECISION IN TIME. The command did not run.\n"
        "Nobody answered the approval window before the hook's time limit. Do not send it "
        "again by yourself; tell the user it still needs their answer."
    )


def error(explanation: str) -> str:
    return f"{PREFIX} CHAD ERROR. The command did not run.\n{explanation}"


def execution_failed(explanation: str) -> dict[str, Any]:
    return deny(
        f"{PREFIX} CHAD COULD NOT RUN THE COMMAND. It did not run.\n{explanation}\n"
        "Do not try again by yourself; tell the user what stopped CHAD from starting it."
    )


def execution_budget_expired() -> dict[str, Any]:
    return execution_failed(
        "The CHAD time budget ran out before the command could start. No shell was launched."
    )


def executed(result: ExecutionResult, max_output_bytes: int) -> dict[str, Any]:
    """Return the command's actual result in the refusal text Claude Code will display."""
    budget = max(2_000, max_output_bytes)
    stdout_size = result.stdout.total_bytes
    stderr_size = result.stderr.total_bytes

    if not stderr_size:
        stdout_budget, stderr_budget = min(stdout_size, budget), 0
    elif not stdout_size:
        stdout_budget, stderr_budget = 0, min(stderr_size, budget)
    else:
        stdout_budget = min(stdout_size, int(budget * 0.7))
        stderr_budget = min(stderr_size, budget - stdout_budget)
        spare = budget - stdout_budget - stderr_budget
        extra_stdout = min(spare, stdout_size - stdout_budget)
        stdout_budget += extra_stdout
        spare -= extra_stdout
        stderr_budget += min(spare, stderr_size - stderr_budget)

    stdout, _, stdout_omitted = result.stdout.render(stdout_budget)
    stderr, _, stderr_omitted = result.stderr.render(stderr_budget)
    omitted = stdout_omitted + stderr_omitted
    total = stdout_size + stderr_size

    if result.execution_note:
        heading = f"{PREFIX} COMMAND RESULT INCOMPLETE. Exit code: {result.exit_code}."
    elif result.timed_out:
        heading = (
            f"{PREFIX} COMMAND TIMED OUT after {result.time_limit_seconds:.0f} seconds. "
            f"Exit code: {result.exit_code}."
        )
    elif result.left_running:
        heading = (
            f"{PREFIX} COMMAND EXECUTED. Exit code: {result.exit_code}. "
            "A PROCESS IT STARTED IS STILL RUNNING."
        )
    else:
        heading = f"{PREFIX} COMMAND EXECUTED. Exit code: {result.exit_code}."

    lines = [
        heading,
        'The harness marks this call "denied" intentionally; CHAD owns this execution.',
    ]
    if result.execution_note:
        lines.append(
            "CHAD started the command but could not confirm a complete result. Its effects may "
            "have occurred; do not retry it. Tell the user. " + result.execution_note
        )
    else:
        lines.append(
            "CHAD already ran the command. Do not retry it or report it as blocked. Treat the "
            "exit code and output below as the command's actual result."
        )
    if result.timed_out:
        lines.append("CHAD stopped the command at its time limit; the output is partial.")
    if result.left_running:
        lines.append(
            "The command has exited, but a process it started is still running and keeps its "
            "output open, so its work is not finished. CHAD did not wait for that process and "
            "did not stop it. The output below is what was written until the command exited; "
            "what the process writes later is not shown. Do not rerun the command to get it. To "
            "follow a long-running process, start it as a background call (run_in_background): "
            "CHAD then writes its output to a log file."
        )
    if omitted:
        lines.append(
            f"NOTE: {omitted} of {total} output bytes were omitted to stay within the "
            f"{budget}-byte limit. The beginning and end are shown; do not rerun just to "
            "retrieve the omitted middle."
        )
    lines.extend(
        (
            "",
            "--- stdout ---",
            stdout if stdout.strip() else "(empty)",
            "",
            "--- stderr ---",
            stderr if stderr.strip() else "(empty)",
        )
    )
    return deny("\n".join(lines))


def started_in_background(pid: int, log: str, stop: str) -> dict[str, Any]:
    """A call that asked to run in the background: CHAD started it and did not wait."""
    lines = (
        f"{PREFIX} COMMAND STARTED IN THE BACKGROUND. Process id: {pid}.",
        'The harness marks this call "denied" intentionally; CHAD owns this execution.',
        "CHAD started the command and did not wait for it. Do not start it again.",
        f"Its stdout and stderr go to this file, which grows while it runs: {log}",
        "Read that file for its output. When the command exits, CHAD adds a last line: "
        '"[CHAD] The command exited with code N."',
        "The harness's own tools for background shells do not know this process.",
        "The stop command below ends the command and the processes Windows records as its "
        "children. A program started by a compound Bash command (`a; b`, `a && b`) can keep "
        "running after it: check with `tasklist` and stop that one by its own process id.",
        f"To stop it, run: {stop}",
    )
    return deny("\n".join(lines))


def shut_down() -> str:
    return error("CHAD shut down before the user decided. Tell the user; do not retry on your own.")


WINDOW_OPENED = error(
    "The command was CHAD's marker for its policy window, not something to run. The window is "
    "now open in front of the user, and nothing ran. Do not send the marker again."
)

WINDOW_NOT_OPENED = error(
    "The command was CHAD's marker for its policy window, but the dispatcher did not respond, "
    "so the window could not be opened. Nothing ran. Ask the user to run `chad open`."
)

NOT_SELECTIVE = error(
    "#chad:add-selective-command only works in Selective Allowlist mode, and CHAD is not in that "
    "mode. Nothing was added. Tell the user."
)

NOTHING_CAPTURED = error(
    "There is no recent command to add: CHAD has not passed a command to the harness's own "
    "approval prompt lately. Tell the user to say no to that prompt for the command first, then "
    "start /chad-add-selective-command again."
)
