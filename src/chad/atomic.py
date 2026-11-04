"""Writes that a reader never observes half done."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path


def write_text(path: Path, text: str) -> None:
    """Write through a temporary file in the same folder and replace the target.

    The replace is retried briefly: virus scanners and editors can hold a just-written policy
    file for a moment on Windows.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        for attempt in range(20):
            try:
                os.replace(temp, path)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.05)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
