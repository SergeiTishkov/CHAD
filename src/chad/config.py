"""config.yaml: execution limits and UI launch settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from chad import atomic, paths

TEMPLATE = """\
# CHAD settings. CHAD writes this file with the defaults when it does not exist.

# Must equal the "timeout" registered for the CHAD hook in ~/.claude/settings.json.
# `chad install` writes the hook with this value.
hookTimeoutSeconds: 3600

# The dispatcher answers at least this long before the hook timeout runs out, so Claude Code
# always gets CHAD's decision rather than a timed-out hook.
safetyMarginSeconds: 30

# Upper bound for the shell command itself, even when the hook has more time left.
maxCommandSeconds: 1800

# Combined stdout and stderr budget returned to the agent.
maxOutputBytes: 30000

# Start the Electron tray UI together with the dispatcher.
launchUi: true

# Explicit UI command line, e.g. ["C:/tools/chad-ui/CHAD.exe"]. Empty means: the packaged UI
# under ui/release if it was built, otherwise the development Electron in ui/node_modules.
uiCommand: []
"""


@dataclass(frozen=True)
class Config:
    hook_timeout_seconds: int = 3600
    safety_margin_seconds: int = 30
    launch_ui: bool = True
    ui_command: tuple[str, ...] = ()
    max_command_seconds: int = 1800
    max_output_bytes: int = 30_000

    @property
    def approval_budget_seconds(self) -> float:
        """Time available for approval and execution while preserving the hook margin."""
        return float(max(5, self.hook_timeout_seconds - self.safety_margin_seconds))


def load(path: Path | None = None) -> Config:
    """Create the file when missing; a corrupt file means defaults rather than no dispatcher."""
    path = path or paths.config_file()
    if not path.exists():
        atomic.write_text(path, TEMPLATE)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            return Config()
        command = data.get("uiCommand") or []
        return Config(
            hook_timeout_seconds=int(data.get("hookTimeoutSeconds", 3600)),
            safety_margin_seconds=int(data.get("safetyMarginSeconds", 30)),
            launch_ui=bool(data.get("launchUi", True)),
            ui_command=tuple(str(part) for part in command) if isinstance(command, list) else (),
            max_command_seconds=int(data.get("maxCommandSeconds", 1800)),
            max_output_bytes=int(data.get("maxOutputBytes", 30_000)),
        )
    except (OSError, ValueError, TypeError, yaml.YAMLError):
        return Config()
