"""The last call each session handed to Claude Code while in Selective mode.

`#chad:add-selective-command` has no other way to know which command the user means: by the
time the skill runs, the original call has been rejected at Claude Code's prompt.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

TTL_SECONDS = 600
MAX_SESSIONS = 128


@dataclass(frozen=True)
class Capture:
    tool: str
    command: str
    tool_input: dict[str, Any]
    cwd: str
    session_id: str
    taken_at: float = field(compare=False)
    environment: dict[str, str] | None = field(default=None, compare=False, repr=False)


class CaptureStore:
    def __init__(
        self,
        ttl: float = TTL_SECONDS,
        max_sessions: int = MAX_SESSIONS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._max = max_sessions
        self._clock = clock
        self._lock = threading.Lock()
        self._items: OrderedDict[str, Capture] = OrderedDict()

    def put(
        self,
        session_id: str,
        tool: str,
        tool_input: dict[str, Any],
        cwd: str = "",
        environment: dict[str, str] | None = None,
    ) -> None:
        capture = Capture(
            tool,
            str(tool_input.get("command") or ""),
            dict(tool_input),
            cwd,
            session_id,
            self._clock(),
            environment,
        )
        with self._lock:
            self._items.pop(session_id, None)
            self._items[session_id] = capture
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def take(self, session_id: str) -> Capture | None:
        """The session's latest capture, at most once and only while it is fresh."""
        with self._lock:
            capture = self._items.pop(session_id, None)
        if capture is None or self._clock() - capture.taken_at > self._ttl:
            return None
        return capture

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
