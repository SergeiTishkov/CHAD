from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from chad import paths, protocol
from chad.config import Config
from chad.locks import FileLock
from chad.policy import Engine
from chad.server import Server, _environment


class Running:
    def __init__(self, shell: Any) -> None:
        self.loop = asyncio.new_event_loop()
        self.engine = Engine(Config(), opener=lambda _: None, execute=shell)
        self.server = Server(self.engine)
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        runtime = self.call(self.server.start())
        protocol.write_runtime(runtime)

    def call(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(10)

    def in_loop(self, function):
        async def wrapper():
            return function()

        return self.call(wrapper())

    def stop(self) -> None:
        self.call(self.server.close())
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


@pytest.fixture
def running(isolated_home: Path, shell: Any) -> Iterator[Running]:
    paths.ensure_root()
    instance = Running(shell)
    yield instance
    instance.stop()


def raw(port: int, line: str) -> dict:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(line.encode() + b"\n")
        return json.loads(sock.makefile().readline())


def test_ping_and_runtime(running: Running) -> None:
    runtime = protocol.read_runtime()
    assert runtime and runtime.port == running.server.port
    assert protocol.ping() == runtime.pid


def test_token_is_required(running: Running) -> None:
    assert raw(running.server.port, json.dumps({"op": "ping"})) == {
        "ok": False,
        "error": "unauthorized",
    }
    assert raw(running.server.port, "not json")["error"] == "bad request"


def test_unknown_op(running: Running) -> None:
    assert protocol.request({"op": "dance"})["error"] == "unknown op 'dance'"


def test_ui_round_trip(running: Running) -> None:
    answer = protocol.request({"op": "ui", "action": "addAllow", "value": "git *"})
    assert answer["ok"]
    assert answer["state"]["allowList"]["entries"][0]["key"] == "pattern:git *"


def test_hook_waits_for_the_user(running: Running) -> None:
    result: dict = {}

    def ask() -> None:
        result.update(
            protocol.request(
                {"op": "hook", "payload": {"tool_name": "Bash", "tool_input": {"command": "ls"}}},
                timeout=10,
            )
        )

    asker = threading.Thread(target=ask)
    asker.start()
    item_id = _wait_for_pending(running)
    answer = protocol.request(
        {"op": "ui", "action": "decide", "id": item_id, "decision": "allowOnce"}
    )
    assert answer["ok"]
    asker.join(5)
    output = result["output"]["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert output["permissionDecisionReason"].startswith("[CHAD] COMMAND EXECUTED. Exit code: 0.")


def _wait_for_pending(running: Running) -> str:
    for _ in range(200):
        items = running.in_loop(lambda: [i.id for i in running.engine.queue.items])
        if items:
            return items[0]
        time.sleep(0.02)
    raise AssertionError("nothing pending")


def test_hanging_up_withdraws_the_question(running: Running) -> None:
    runtime = protocol.read_runtime()
    sock = socket.create_connection(("127.0.0.1", runtime.port), timeout=5)
    message = {
        "op": "hook",
        "token": runtime.token,
        "payload": {"tool_name": "Bash", "tool_input": {"command": "ls"}},
    }
    sock.sendall(json.dumps(message).encode() + b"\n")
    _wait_for_pending(running)
    sock.close()
    for _ in range(200):
        if not running.in_loop(lambda: running.engine.queue.items):
            return
        time.sleep(0.02)
    raise AssertionError("the question was not withdrawn")


def test_subscribe_streams_changes(running: Running) -> None:
    runtime = protocol.read_runtime()
    with socket.create_connection(("127.0.0.1", runtime.port), timeout=5) as sock:
        sock.sendall(json.dumps({"op": "subscribe", "token": runtime.token}).encode() + b"\n")
        stream = sock.makefile(encoding="utf-8")
        first = json.loads(stream.readline())["state"]
        protocol.request({"op": "ui", "action": "showPolicy"})
        second = json.loads(stream.readline())["state"]
        assert second["attentionVersion"] == first["attentionVersion"] + 1
        assert second["requestedView"] == "policy"


def test_subscribe_notices_hand_edits(running: Running) -> None:
    runtime = protocol.read_runtime()
    with socket.create_connection(("127.0.0.1", runtime.port), timeout=5) as sock:
        sock.sendall(json.dumps({"op": "subscribe", "token": runtime.token}).encode() + b"\n")
        stream = sock.makefile(encoding="utf-8")
        json.loads(stream.readline())
        paths.allow_list_file().write_text(
            "allowed:\n  - {kind: exact, value: by hand}\n", encoding="utf-8"
        )
        state = json.loads(stream.readline())["state"]
        assert state["allowList"]["entries"][0]["value"] == "by hand"


def test_request_without_dispatcher(isolated_home: Path) -> None:
    assert protocol.ping() is None
    with pytest.raises(protocol.DispatcherUnavailable):
        protocol.request({"op": "ping"})


def test_file_lock_is_exclusive(tmp_path: Path) -> None:
    first, second = FileLock(tmp_path / "x.lock"), FileLock(tmp_path / "x.lock")
    assert first.try_acquire()
    assert not second.try_acquire()
    assert not second.acquire(0.1)
    first.release()
    assert second.try_acquire()
    second.release()


def test_only_a_usable_environment_is_passed_on() -> None:
    assert _environment({"PATH": "C:/bin"}) == {"PATH": "C:/bin"}
    for unusable in (None, {}, "PATH=C:/bin", {"PATH": 1}, ["PATH"]):
        assert _environment(unusable) is None
