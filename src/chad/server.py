"""The dispatcher's listening side: one request per connection, except `subscribe`."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import os
import secrets
from typing import Any

from chad.policy import Engine
from chad.protocol import HOST, LINE_LIMIT, PROTOCOL, Runtime

log = logging.getLogger("chad.server")

# Subscribers also get changes nobody announced (a hand-edited YAML file, `chad mode` run in a
# terminal), by comparing the state this often.
POLL_SECONDS = 1.0


class Server:
    def __init__(self, engine: Engine, token: str | None = None) -> None:
        self.engine = engine
        self.token = token or secrets.token_urlsafe(32)
        self._server: asyncio.Server | None = None
        self.port = 0

    async def start(self, port: int = 0) -> Runtime:
        self._server = await asyncio.start_server(self._handle, HOST, port, limit=LINE_LIMIT)
        self.port = self._server.sockets[0].getsockname()[1]
        return Runtime(os.getpid(), self.port, self.token, PROTOCOL)

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), 2)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            try:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError
            except ValueError:
                await _send(writer, {"ok": False, "error": "bad request"})
                return
            if not hmac.compare_digest(str(message.get("token") or ""), self.token):
                await _send(writer, {"ok": False, "error": "unauthorized"})
                return
            await self._dispatch(message, reader, writer)
        except (ConnectionError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            pass
        except Exception:
            log.exception("request failed")
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _dispatch(
        self, message: dict[str, Any], reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        match message.get("op"):
            case "ping":
                await _send(writer, {"ok": True, "pid": os.getpid()})
            case "hook":
                payload = message.get("payload")
                if not isinstance(payload, dict):
                    await _send(writer, {"ok": False, "error": "payload must be an object"})
                    return
                output = await self._hook(payload, _environment(message.get("environment")), reader)
                if output is not None:
                    await _send(writer, {"ok": True, "output": output})
            case "ui":
                await _send(writer, self.engine.ui(message))
            case "subscribe":
                await self._subscribe(reader, writer)
            case other:
                await _send(writer, {"ok": False, "error": f"unknown op {other!r}"})

    async def _hook(
        self,
        payload: dict[str, Any],
        environment: dict[str, str] | None,
        reader: asyncio.StreamReader,
    ) -> dict[str, Any] | None:
        """Decide, unless the hook client hangs up first: then the question is withdrawn."""
        decision = asyncio.create_task(self.engine.hook(payload, environment))
        hangup = asyncio.create_task(reader.read(1))
        done, _ = await asyncio.wait({decision, hangup}, return_when=asyncio.FIRST_COMPLETED)
        if decision in done:
            hangup.cancel()
            return decision.result()
        decision.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await decision
        return None

    async def _subscribe(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        changed = asyncio.Event()
        stop_listening = self.engine.listen(changed.set)
        hangup = asyncio.create_task(reader.read(1))
        last = ""
        try:
            while not hangup.done():
                state = json.dumps({"state": self.engine.state()})
                if state != last:
                    writer.write(state.encode("utf-8") + b"\n")
                    await writer.drain()
                    last = state
                changed.clear()
                waiter = asyncio.create_task(changed.wait())
                await asyncio.wait({waiter, hangup}, timeout=POLL_SECONDS)
                waiter.cancel()
        finally:
            stop_listening()
            hangup.cancel()


async def _send(writer: asyncio.StreamWriter, answer: dict[str, Any]) -> None:
    writer.write(json.dumps(answer).encode("utf-8") + b"\n")
    await writer.drain()


def _environment(value: Any) -> dict[str, str] | None:
    """The hook's environment, when it sent a usable one."""
    if not isinstance(value, dict) or not value:
        return None
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        return None
    return value
