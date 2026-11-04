"""`chad install` / `chad uninstall`: wiring CHAD into the current user's Claude Code.

Everything goes to per-user locations: the hook into the user's Claude Code settings, the skills
into the user's skills folder, the switches into the user environment. No project is touched.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from chad import atomic, paths, switches, userenv
from chad import config as config_module
from chad.allowlist import AllowList
from chad.denylist import DenyList

HOOK_MODULE = "chad.hook"
MATCHER = "Bash|PowerShell"
HOME_VARIABLE = "CHAD_HOME"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "CHAD"
AUTOSTART_FILE = "autostart.json"


class InstallError(Exception):
    pass


def default_claude_dir() -> Path:
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(configured) if configured else Path.home() / ".claude"


def default_bin_dir() -> Path:
    return Path.home() / ".local" / "bin"


def skills_source() -> Path:
    return paths.project_root() / "skills"


def skill_names(source: Path | None = None) -> list[str]:
    source = source or skills_source()
    if not source.is_dir():
        return []
    return sorted(p.name for p in source.iterdir() if (p / "SKILL.md").is_file())


def _forward(path: str | Path) -> str:
    return str(path).replace("\\", "/")


def _windowed(python: str) -> str:
    candidate = Path(python).with_name("pythonw.exe")
    return str(candidate) if sys.platform == "win32" and candidate.exists() else python


def hook_command(python: str | None = None) -> str:
    # Claude Code runs hook commands through Git Bash on Windows: a quoted forward-slash path
    # works there and in cmd alike.
    return f'"{_forward(python or sys.executable)}" -m {HOOK_MODULE}'


# -- settings.json ------------------------------------------------------------------------------


def _is_chad_hook(hook: Any) -> bool:
    return isinstance(hook, dict) and HOOK_MODULE in str(hook.get("command") or "")


def remove_hook(settings: dict[str, Any]) -> dict[str, Any]:
    """Settings without any CHAD hook; every other hook and setting is kept as it was."""
    result = json.loads(json.dumps(settings))
    hooks = result.get("hooks")
    if not isinstance(hooks, dict) or not isinstance(hooks.get("PreToolUse"), list):
        return result
    groups = []
    for group in hooks["PreToolUse"]:
        if isinstance(group, dict) and isinstance(group.get("hooks"), list):
            kept = [h for h in group["hooks"] if not _is_chad_hook(h)]
            if not kept:
                continue
            group = {**group, "hooks": kept}
        groups.append(group)
    if groups:
        hooks["PreToolUse"] = groups
    else:
        del hooks["PreToolUse"]
    if not hooks:
        del result["hooks"]
    return result


def merge_hook(settings: dict[str, Any], command: str, timeout: int) -> dict[str, Any]:
    result = remove_hook(settings)
    hooks = result.setdefault("hooks", {})
    hooks.setdefault("PreToolUse", []).append(
        {"matcher": MATCHER, "hooks": [{"type": "command", "command": command, "timeout": timeout}]}
    )
    return result


def _read_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig") or "{}")
    except ValueError as exc:
        raise InstallError(f"{path} is not valid JSON ({exc}); fix it and run again.") from None
    if not isinstance(data, dict):
        raise InstallError(f"{path} does not hold a JSON object; fix it and run again.")
    return data


def _write_settings(path: Path, before: dict[str, Any], after: dict[str, Any]) -> Path | None:
    if before == after and path.exists():
        return None
    backup = None
    if path.exists():
        backup = path.with_name(f"{path.name}.chad-backup-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_text(path, json.dumps(after, indent=2) + "\n")
    return backup


# -- autostart --------------------------------------------------------------------------------


def _autostart_registry() -> bool:
    return sys.platform == "win32" and not paths.is_isolated()


def get_autostart() -> str | None:
    if not _autostart_registry():
        try:
            data = json.loads((paths.data_root() / AUTOSTART_FILE).read_text(encoding="utf-8"))
            return str(data["command"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return str(winreg.QueryValueEx(key, RUN_VALUE)[0])
    except OSError:
        return None


def set_autostart(command: str | None) -> None:
    if not _autostart_registry():
        target = paths.data_root() / AUTOSTART_FILE
        if command is None:
            target.unlink(missing_ok=True)
        else:
            atomic.write_text(target, json.dumps({"command": command}))
        return
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if command is None:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, command)


def autostart_command(python: str | None = None) -> str:
    return f'"{_windowed(python or sys.executable)}" -m chad.dispatcher'


# -- shims ------------------------------------------------------------------------------------


def _bash_path(path: str) -> str:
    text = _forward(path)
    if len(text) > 1 and text[1] == ":":
        return f"/{text[0].lower()}{text[2:]}"
    return text


def shim_files(python: str | None = None) -> dict[str, str]:
    python = python or sys.executable
    return {
        "chad.cmd": f'@"{python}" -m chad %*\r\n',
        "chad": f'#!/bin/sh\nexec "{_bash_path(python)}" -m chad "$@"\n',
    }


# -- install / uninstall ----------------------------------------------------------------------


@dataclass(frozen=True)
class Options:
    claude_dir: Path
    bin_dir: Path
    autostart: bool = True
    deny: bool = False
    purge: bool = False


def _guard(options: Options) -> None:
    """In isolated mode, refuse the real Claude Code and bin folders."""
    if not paths.is_isolated():
        return
    real = {Path.home() / ".claude", default_claude_dir(), default_bin_dir()}
    for folder in (options.claude_dir, options.bin_dir):
        if folder.resolve() in {r.resolve() for r in real}:
            raise InstallError(
                f"CHAD_ISOLATED is on: refusing to write to {folder}. Pass --claude-dir and "
                "--bin-dir, or unset CHAD_ISOLATED."
            )


def install(options: Options, say: Callable[[str], None] = print) -> None:
    _guard(options)
    settings_path = options.claude_dir / "settings.json"
    before = _read_settings(settings_path)  # fail before changing anything

    root = paths.ensure_root()
    settings = config_module.load()
    AllowList(paths.allow_list_file())
    DenyList(paths.deny_list_file())
    say(f"Data folder: {root}")

    userenv.set(HOME_VARIABLE, str(root))
    say(f"User environment: {HOME_VARIABLE}={root}")
    if options.deny:
        switches.set_deny(True)
        say(f"User environment: {switches.DENY}=1 (deny list armed)")

    after = merge_hook(before, hook_command(), settings.hook_timeout_seconds)
    backup = _write_settings(settings_path, before, after)
    say(f"Hook: {settings_path}" + (f" (previous file saved as {backup.name})" if backup else ""))

    skills = options.claude_dir / "skills"
    for name in skill_names():
        target = skills / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(skills_source() / name, target)
        say(f"Skill: {target}")

    options.bin_dir.mkdir(parents=True, exist_ok=True)
    for name, text in shim_files().items():
        (options.bin_dir / name).write_bytes(text.encode("utf-8"))
        if not name.endswith(".cmd"):
            os.chmod(options.bin_dir / name, 0o755)
    say(f"Command: {options.bin_dir / 'chad'}")
    if _forward(options.bin_dir).lower() not in _forward(os.environ.get("PATH", "")).lower():
        say(f"  Note: {options.bin_dir} is not on PATH; add it to run `chad` from any shell.")

    if sys.platform != "win32":
        say("Autostart: Windows only; the hook starts the dispatcher when a command arrives")
    elif options.autostart:
        set_autostart(autostart_command())
        say("Autostart: the dispatcher starts at logon")
    else:
        set_autostart(None)
    say("Done. Restart the harness so it picks up the hook.")


def uninstall(options: Options, say: Callable[[str], None] = print) -> None:
    _guard(options)
    settings_path = options.claude_dir / "settings.json"
    before = _read_settings(settings_path)
    if settings_path.exists():
        backup = _write_settings(settings_path, before, remove_hook(before))
        if backup:
            say(f"Hook removed from {settings_path} (previous file saved as {backup.name})")

    for name in skill_names():
        target = options.claude_dir / "skills" / name
        if target.exists():
            shutil.rmtree(target)
            say(f"Skill removed: {target}")

    for name in shim_files():
        (options.bin_dir / name).unlink(missing_ok=True)

    root = paths.data_root()
    set_autostart(None)
    switches.set_mode(switches.Mode.CHAD)
    switches.set_deny(False)
    userenv.set(HOME_VARIABLE, None)
    say(f"User environment: {HOME_VARIABLE} and the mode and deny switches removed")

    if options.purge:
        shutil.rmtree(root, ignore_errors=True)
        say(f"Data folder deleted: {root}")
    else:
        say(f"Data folder kept: {root} (chad uninstall --purge deletes it)")
