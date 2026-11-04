"""Finding and supervising the Electron UI process."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import subprocess
import sys
from pathlib import Path

from chad import paths
from chad.config import Config

log = logging.getLogger("chad.ui")

RESTART_SECONDS = 10.0
# Set by VS Code (and so by Claude Code inside it) for its children; inherited by the UI it would
# start Electron as plain Node.
INHERITED_ONLY = ("ELECTRON_RUN_AS_NODE",)
PACKAGED_NAMES = ("CHAD.exe", "CHAD", "chad")


def ui_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    for name in INHERITED_ONLY:
        env.pop(name, None)
    env["CHAD_HOME"] = str(paths.data_root())
    return env


def ui_folder() -> Path:
    return paths.project_root() / "ui"


def resolve_command(config: Config, data_root: Path, ui: Path | None = None) -> list[str] | None:
    """The configured command, else the packaged app, else the development Electron."""
    tail = ["--data-root", str(data_root)]
    if config.ui_command:
        return [*config.ui_command, *tail]
    ui = ui or ui_folder()
    release = ui / "release"
    if release.is_dir():
        for folder in sorted(release.iterdir()):
            for name in PACKAGED_NAMES:
                candidate = folder / name
                if folder.is_dir() and candidate.is_file():
                    return [str(candidate), *tail]
    electron = ui / "node_modules" / "electron" / "dist"
    electron /= "electron.exe" if sys.platform == "win32" else "electron"
    if electron.is_file() and (ui / "dist").is_dir():
        return [str(electron), str(ui), *tail]
    return None


class UiSupervisor:
    """Keeps one UI process running, restarting it within RESTART_SECONDS if it exits."""

    def __init__(self, command: list[str], log_path: Path) -> None:
        self.command = command
        self.log_path = log_path
        self.process: subprocess.Popen[bytes] | None = None

    def _start(self) -> None:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        with open(self.log_path, "ab") as output:
            self.process = subprocess.Popen(
                self.command,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                creationflags=flags,
                env=ui_environment(),
            )
        log.info("UI started (pid %s): %s", self.process.pid, self.command)

    async def run(self, interval: float = RESTART_SECONDS) -> None:
        while True:
            if self.process is None or self.process.poll() is not None:
                try:
                    self._start()
                except OSError:
                    log.exception("could not start the UI")
            await asyncio.sleep(interval)

    def stop(self) -> None:
        process, self.process = self.process, None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(3)
            return
        process.kill()
