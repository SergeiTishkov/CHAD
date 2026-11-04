from __future__ import annotations

from chad.captures import CaptureStore


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_latest_per_session_taken_once() -> None:
    store = CaptureStore()
    store.put("s", "Bash", {"command": "one"})
    store.put("s", "PowerShell", {"command": "two", "timeout": 5})
    capture = store.take("s")
    assert capture and capture.command == "two" and capture.tool == "PowerShell"
    assert capture.tool_input == {"command": "two", "timeout": 5}
    assert store.take("s") is None


def test_stale_capture_is_gone() -> None:
    clock = Clock()
    store = CaptureStore(ttl=600, clock=clock)
    store.put("s", "Bash", {"command": "x"})
    clock.now = 601
    assert store.take("s") is None


def test_oldest_session_is_evicted() -> None:
    store = CaptureStore(max_sessions=2)
    for session in ("a", "b", "c"):
        store.put(session, "Bash", {"command": session})
    assert len(store) == 2
    assert store.take("a") is None
    assert store.take("c") is not None


def test_captured_input_is_a_copy() -> None:
    store = CaptureStore()
    tool_input = {"command": "x"}
    store.put("s", "Bash", tool_input)
    tool_input["command"] = "changed"
    assert store.take("s").command == "x"
