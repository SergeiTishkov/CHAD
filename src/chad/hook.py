"""The PreToolUse hook Claude Code runs before every Bash and PowerShell call.

`python -m chad.hook` reads the payload on stdin and prints a decision on stdout. It holds no
policy and always exits 0 with valid JSON. CHAD answers deny or skips (no decision), never allow.
It skips only when CHAD is switched off or the dispatcher hands the call back. When CHAD itself
fails, here or in the dispatcher, the answer is deny with the cause, so the agent can tell the
user that CHAD needs fixing.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any

try:
    from chad import config, lookup, messages, paths, protocol, switches
    from chad.launcher import ensure_dispatcher
    from chad.policy import ADD_SELECTIVE_MARKER, ALLOW_DENY_LIST_MARKER, TOOLS
    from chad.switches import Mode

    LOAD_ERROR: str | None = None
except Exception as exc:  # a broken install or a bad edit: main() still answers
    LOAD_ERROR = f"{type(exc).__name__}: {exc}"

# How much longer than the approval budget the client waits for the dispatcher's answer.
GRACE_SECONDS = 15.0

log = logging.getLogger("chad.hook")


def _control_failure(command: str) -> dict[str, Any] | None:
    """The deny a control request gets when the dispatcher cannot be reached."""
    lowered = command.lower()
    if ALLOW_DENY_LIST_MARKER in lowered:
        return messages.deny(messages.WINDOW_NOT_OPENED)
    if command.strip().lower() == ADD_SELECTIVE_MARKER:
        return messages.deny(
            messages.error("CHAD could not be reached, so nothing was added. Tell the user.")
        )
    if lookup.parse(command) is not None:
        return messages.deny(
            messages.error(
                "CHAD could not be reached, so the Selective rules could not be looked up. "
                "Tell the user."
            )
        )
    return None


def decide(payload: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    if str(payload.get("tool_name") or "") not in TOOLS:
        return messages.NO_DECISION
    tool_input = payload.get("tool_input")
    command = str((tool_input or {}).get("command") or "") if isinstance(tool_input, dict) else ""
    failure = _control_failure(command)
    try:
        if failure is None and switches.current_mode() is Mode.OFF:
            return messages.NO_DECISION
        if not ensure_dispatcher():
            log.warning("no dispatcher")
            cause = "The CHAD dispatcher was not running, and starting it failed."
            return failure or messages.chad_broken(cause, paths.log_file("hook"))
        settings = config.load()
        # Never outlive Claude Code's own timeout for the hook: it would discard the answer.
        left = settings.hook_timeout_seconds - (time.monotonic() - started) - 2
        wait = max(1.0, min(settings.approval_budget_seconds + GRACE_SECONDS, left))
        # The harness starts the hook, so the hook's environment is the session's: CHAD runs the
        # command with it rather than with the dispatcher's own.
        request = {"op": "hook", "payload": payload, "environment": dict(os.environ)}
        answer = protocol.request(request, wait)
        output = answer.get("output")
        if answer.get("ok") and isinstance(output, dict):
            return output
        log.warning("dispatcher answered %s", answer)
        cause = f"The dispatcher refused the request: {answer.get('error') or answer}."
    except Exception as exc:
        log.exception("hook failed")
        cause = f"The hook client failed: {type(exc).__name__}: {exc}"
    return failure or messages.chad_broken(cause, _log_path())


def _log_path() -> Any:
    try:
        return paths.log_file("hook")
    except Exception:
        return None


def _not_loaded(raw: bytes) -> dict[str, Any]:
    """The answer when CHAD's own modules do not load: deny, unless CHAD is switched off."""
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
        tool = payload.get("tool_name") if isinstance(payload, dict) else None
    except Exception:
        tool = None
    if tool is not None and tool not in ("Bash", "PowerShell"):
        return {}
    try:
        from chad import switches as mode_switches

        if mode_switches.current_mode() is mode_switches.Mode.OFF:
            return {}
    except Exception:
        pass
    reason = (
        "[CHAD] CHAD IS BROKEN. The command did not run.\n"
        f"CHAD's own code could not be loaded: {LOAD_ERROR}\n"
        "CHAD needs fixing before it can decide again. Do not send the command again by "
        "yourself; tell the user that CHAD failed, with the cause above. The file tools still "
        "work.\n"
        "Until it is repaired, the user can type `chad mode off` in a terminal of their own, and "
        "the harness handles approval without CHAD."
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def main() -> int:
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        raw = b""
    if LOAD_ERROR is not None:
        output = _not_loaded(raw)
    else:
        try:
            logging.basicConfig(
                filename=paths.log_file("hook"),
                level=logging.INFO,
                format="%(asctime)s %(levelname)s %(message)s",
                encoding="utf-8",
            )
        except Exception:
            pass
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
            if isinstance(payload, dict):
                output = decide(payload)
            else:
                output = messages.chad_broken("The hook input is not a JSON object.", _log_path())
        except Exception as exc:
            log.exception("unreadable hook input")
            cause = f"The hook input could not be read: {type(exc).__name__}: {exc}"
            output = messages.chad_broken(cause, _log_path())
    sys.stdout.write(json.dumps(output))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
