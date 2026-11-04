"""The client side of the dispatcher protocol: newline-delimited JSON over local TCP.

`dispatcher.json` in the data root says where the dispatcher listens and which token it wants.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chad import atomic, paths

PROTOCOL = 1
HOST = "127.0.0.1"
LINE_LIMIT = 16 * 1024 * 1024


class DispatcherUnavailable(Exception):
    pass


@dataclass(frozen=True)
class Runtime:
    pid: int
    port: int
    token: str
    protocol: int = PROTOCOL

    def to_json(self) -> str:
        return json.dumps(
            {"pid": self.pid, "port": self.port, "token": self.token, "protocol": self.protocol}
        )


def read_runtime(path: Path | None = None) -> Runtime | None:
    try:
        data = json.loads((path or paths.runtime_file()).read_text(encoding="utf-8"))
        return Runtime(
            int(data["pid"]), int(data["port"]), str(data["token"]), int(data["protocol"])
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_runtime(runtime: Runtime, path: Path | None = None) -> None:
    atomic.write_text(path or paths.runtime_file(), runtime.to_json())


def request(message: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
    """Send one request and return its one-line answer."""
    runtime = read_runtime()
    if runtime is None or runtime.protocol != PROTOCOL:
        raise DispatcherUnavailable("no dispatcher.json")
    body = (json.dumps({**message, "token": runtime.token}) + "\n").encode("utf-8")
    try:
        with socket.create_connection((HOST, runtime.port), timeout=min(timeout, 5.0)) as sock:
            sock.settimeout(timeout)
            sock.sendall(body)
            buffer = bytearray()
            while not buffer.endswith(b"\n"):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buffer.extend(chunk)
                if len(buffer) > LINE_LIMIT:
                    raise DispatcherUnavailable("answer too long")
    except OSError as exc:
        raise DispatcherUnavailable(str(exc)) from exc
    if not buffer:
        raise DispatcherUnavailable(
            "the dispatcher closed the connection without an answer (it stopped or crashed; a "
            "command it had started may have done part of its work)"
        )
    try:
        answer = json.loads(buffer.decode("utf-8"))
    except ValueError as exc:
        raise DispatcherUnavailable(f"unreadable answer: {exc}") from exc
    if not isinstance(answer, dict):
        raise DispatcherUnavailable("unreadable answer")
    return answer


def ping(timeout: float = 1.0) -> int | None:
    """The dispatcher's pid when one answers, else None."""
    try:
        answer = request({"op": "ping"}, timeout)
    except DispatcherUnavailable:
        return None
    return int(answer["pid"]) if answer.get("ok") and "pid" in answer else None
