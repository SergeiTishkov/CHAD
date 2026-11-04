"""audit.log: one line per decision, for the user reading back what happened and why."""

from __future__ import annotations

import threading
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from chad import paths


class Decision(StrEnum):
    ALLOWED_BY_RULE = "allowedByRule"
    ALLOWED_BY_SELECTIVE_RULE = "allowedBySelectiveRule"
    ALLOW_ONCE = "allowOnce"
    ALLOW_FOREVER = "allowForever"
    ALLOW_SELECTIVE = "allowSelective"
    ALLOW_ALL_MODE = "allowAllMode"
    DENIED_BY_USER = "deniedByUser"
    DENIED_BY_RULE = "deniedByRule"
    EXPIRED = "expired"
    HANDED_TO_HARNESS = "handedToHarness"
    REFUSED_OUTSIDE_SELECTIVE = "refusedOutsideSelective"
    RULES_LOOKUP = "rulesLookup"
    WINDOW_OPENED = "windowOpened"
    ERROR = "error"


_lock = threading.Lock()


def _flat(text: str | None) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")


def _timestamp(now: datetime | None = None) -> str:
    # A time that carries its zone keeps it; the current time, or one without a zone, is local.
    moment = (
        now if now is not None and now.tzinfo is not None else (now or datetime.now()).astimezone()
    )
    offset = moment.strftime("%z")  # +0400
    return f"{moment:%Y-%m-%d %H:%M:%S} {offset[:3]}:{offset[3:]}"


def format_line(
    decision: Decision,
    tool: str | None,
    session: str | None,
    cwd: str | None,
    command: str | None,
    note: str | None = None,
    now: datetime | None = None,
) -> str:
    fields = [
        _timestamp(now),
        str(decision),
        tool or "-",
        f"session={session or '-'}",
        f"cwd={cwd or '-'}",
        f"cmd={_flat(command)}",
    ]
    if note:
        fields.append(f"note={_flat(note)}")
    return " | ".join(fields)


def record(
    decision: Decision,
    tool: str | None,
    session: str | None,
    cwd: str | None,
    command: str | None,
    note: str | None = None,
    path: Path | None = None,
) -> None:
    """Append one line. Write errors are ignored."""
    try:
        target = path or paths.audit_log_file()
        line = format_line(decision, tool, session, cwd, command, note)
        with _lock, open(target, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
    except Exception:
        pass
