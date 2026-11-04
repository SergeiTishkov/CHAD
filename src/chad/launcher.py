"""Starting the dispatcher on demand, detached from whoever asked."""

from __future__ import annotations

import os
import subprocess
import sys
import time

from chad import paths, protocol
from chad.locks import FileLock

START_TIMEOUT_SECONDS = 20.0


def _python() -> str:
    # pythonw has no console to flash on Windows; the dispatcher writes to its own log.
    if sys.platform == "win32":
        windowed = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if os.path.exists(windowed):
            return windowed
    return sys.executable


def spawn() -> None:
    """Start a dispatcher outside the caller's process tree and job object.

    Claude Code reaps the hook process when it answers; a dispatcher left in its tree would
    go down with it.
    """
    command = [_python(), "-m", "chad.dispatcher"]
    env = {**os.environ, "CHAD_HOME": str(paths.data_root())}
    common = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "env": env,
        "cwd": str(paths.data_root()),
    }
    if sys.platform != "win32":
        subprocess.Popen(command, start_new_session=True, **common)
        return
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(
            command, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **common
        )
    except OSError:
        # The job does not allow breaking away: start it detached inside the job.
        subprocess.Popen(command, creationflags=flags, **common)


def ensure_dispatcher(timeout: float = START_TIMEOUT_SECONDS) -> bool:
    """True once a dispatcher answers, starting one if none does."""
    if protocol.ping() is not None:
        return True
    paths.ensure_root()
    deadline = time.monotonic() + timeout
    with FileLock(paths.launch_lock_file()) as lock:
        if not lock.acquire(timeout):
            return protocol.ping() is not None
        # Whoever held the lock before us may have started it already.
        if protocol.ping() is not None:
            return True
        spawn()
        while time.monotonic() < deadline:
            if protocol.ping(0.5) is not None:
                return True
            time.sleep(0.1)
    return False
