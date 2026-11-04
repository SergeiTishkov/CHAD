"""The long-running process that decides: `python -m chad.dispatcher`.

One per data root. A second start finds the lock taken and exits quietly, which is what makes
it safe for every hook call to start one when it finds none answering.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys
from logging.handlers import RotatingFileHandler

from chad import config as config_module
from chad import paths, protocol, switches
from chad.locks import FileLock
from chad.policy import Engine
from chad.server import Server
from chad.uilaunch import UiSupervisor, resolve_command

log = logging.getLogger("chad.dispatcher")


def _setup_logging() -> None:
    handler = RotatingFileHandler(
        paths.log_file("dispatcher"), maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


async def serve() -> None:
    config = config_module.load()
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    engine = Engine(config, on_shutdown=stop.set)
    server = Server(engine)
    runtime = await server.start()
    protocol.write_runtime(runtime)
    log.info(
        "listening on port %s (pid %s), data root %s", runtime.port, runtime.pid, paths.data_root()
    )

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            with contextlib.suppress(ValueError, OSError):
                signal.signal(getattr(signal, name), lambda *_: loop.call_soon_threadsafe(stop.set))

    supervisor: UiSupervisor | None = None
    watchdog: asyncio.Task[None] | None = None
    if config.launch_ui and not switches.ui_disabled():
        command = resolve_command(config, paths.data_root())
        if command:
            supervisor = UiSupervisor(command, paths.log_file("ui"))
            watchdog = asyncio.create_task(supervisor.run())
        else:
            log.warning("no UI found: build it in ui/ or set uiCommand in config.yaml")

    await stop.wait()
    log.info("shutting down")
    engine.shutdown()
    await asyncio.sleep(0.2)  # let pending hook answers reach their clients
    if watchdog:
        watchdog.cancel()
    if supervisor:
        supervisor.stop()
    await server.close()
    current = protocol.read_runtime()
    if current and current.pid == os.getpid():
        with contextlib.suppress(OSError):
            paths.runtime_file().unlink()


def main() -> int:
    paths.ensure_root()
    lock = FileLock(paths.dispatcher_lock_file())
    if not lock.try_acquire():
        return 0
    try:
        _setup_logging()
        asyncio.run(serve())
    except Exception:
        log.exception("dispatcher failed")
        return 1
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
