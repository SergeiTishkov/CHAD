"""The user environment: persistent per-user variables.

On Windows this is HKCU\\Environment, the key `setx` writes and every new process inherits.
CHAD reads the key itself rather than its own environment, which was copied when the process
started. A switch changed in any shell is therefore seen on the next command, even by a Claude
Code session that was already open.

In isolated mode (and on platforms without a registry) a JSON file in the data root stands in
for it, so tests and development installs never touch the real switches.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from chad import atomic, paths

FILE_NAME = "user-environment.json"


def _use_registry() -> bool:
    return sys.platform == "win32" and not paths.is_isolated()


def _file() -> Path:
    return paths.data_root() / FILE_NAME


def _read_file() -> dict[str, str]:
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def get(name: str) -> str | None:
    if not _use_registry():
        return _read_file().get(name)
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value)
    except OSError:
        # Unreadable reads as unset.
        return None


def set(name: str, value: str | None) -> None:
    """Set or (with None) remove a variable. Removal, not a falsy value, is how "off" looks."""
    if not _use_registry():
        data = _read_file()
        if value is None:
            data.pop(name, None)
        else:
            data[name] = value
        atomic.write_text(_file(), json.dumps(data, indent=2, sort_keys=True) + "\n")
        return

    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        if value is None:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    _broadcast_change()


def _broadcast_change() -> None:
    """Tell running shells and Explorer that the environment moved.

    Best effort and off the calling thread: the broadcast waits on every top-level window that
    does not answer, which can take seconds, and nothing in CHAD depends on it.
    """

    def send() -> None:
        try:
            import ctypes

            hwnd_broadcast, wm_settingchange, smto_abortifhung = 0xFFFF, 0x001A, 0x0002
            result = ctypes.c_ulong()
            ctypes.windll.user32.SendMessageTimeoutW(
                hwnd_broadcast,
                wm_settingchange,
                0,
                "Environment",
                smto_abortifhung,
                1000,
                ctypes.byref(result),
            )
        except Exception:
            pass

    threading.Thread(target=send, daemon=True).start()
