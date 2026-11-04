"""Where CHAD keeps its files.

Everything durable lives in one data root, outside the source tree, so reinstalling or
updating the code never touches policy, configuration or the audit log.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HOME_VARIABLE = "CHAD_HOME"
ISOLATED_VARIABLE = "CHAD_ISOLATED"

TRUTHY = frozenset({"1", "true", "yes", "on", "y"})


def is_truthy(value: str | None) -> bool:
    """Only the listed values are on; anything else, including a typo, is off."""
    return value is not None and value.strip().lower() in TRUTHY


def is_isolated() -> bool:
    """Isolated installs (tests, development) never read or write the real user environment."""
    return is_truthy(os.environ.get(ISOLATED_VARIABLE))


def default_root() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "CHAD"
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "chad"


def data_root() -> Path:
    home = os.environ.get(HOME_VARIABLE, "").strip()
    if not home and is_isolated():
        raise RuntimeError(f"{ISOLATED_VARIABLE} requires {HOME_VARIABLE} to be set.")
    if not home and sys.platform == "win32":
        # A Claude Code started before `chad install` set CHAD_HOME has a stale environment;
        # the user environment in the registry is the live value. Elsewhere the user
        # environment is a file inside the data root, so it cannot name the root.
        from chad import userenv

        home = (userenv.get(HOME_VARIABLE) or "").strip()
    return Path(home).expanduser().resolve() if home else default_root()


def ensure_root() -> Path:
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def config_file() -> Path:
    return data_root() / "config.yaml"


def allow_list_file() -> Path:
    return data_root() / "allow-list.yaml"


def deny_list_file() -> Path:
    return data_root() / "deny-list.yaml"


def audit_log_file() -> Path:
    return data_root() / "audit.log"


def runtime_file() -> Path:
    return data_root() / "dispatcher.json"


def dispatcher_lock_file() -> Path:
    return data_root() / "dispatcher.lock"


def launch_lock_file() -> Path:
    return data_root() / "launch.lock"


def log_file(name: str) -> Path:
    return data_root() / f"{name}.log"


def project_root() -> Path:
    """The source checkout this package runs from (src/chad/ -> repo root)."""
    return Path(__file__).resolve().parent.parent.parent
