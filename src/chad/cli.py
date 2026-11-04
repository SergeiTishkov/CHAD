"""`chad`: switching modes and managing the dispatcher from any shell."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from chad import FULL_NAME, installer, paths, protocol, switches
from chad.launcher import ensure_dispatcher
from chad.switches import Mode

MODE_NAMES = {
    "chad": Mode.CHAD,
    "allow-all": Mode.ALLOW_ALL,
    "selective": Mode.SELECTIVE,
    "off": Mode.OFF,
}
MODE_LABELS = {mode: name for name, mode in MODE_NAMES.items()}


def _status() -> int:
    mode = switches.current_mode()
    print(f"{FULL_NAME}")
    print(f"Mode:       {MODE_LABELS[mode]} - {switches.description(mode)}")
    print(f"Deny list:  {'armed' if switches.deny_enabled() else 'off'}")
    print(f"Selective:  {_selective_line()}")
    print(f"Data root:  {paths.data_root()}")
    runtime = protocol.read_runtime()
    if runtime and protocol.ping() == runtime.pid:
        pending = len(protocol.request({"op": "ui", "action": "getState"})["state"]["pending"])
        print(f"Dispatcher: running, pid {runtime.pid}, port {runtime.port}")
        print(f"Pending:    {pending}")
    else:
        print("Dispatcher: not running (starts with the first command)")
    return 0


def _mode(name: str) -> int:
    mode = MODE_NAMES[name]
    switches.set_mode(mode)
    print(f"Mode: {name} - {switches.description(mode)}")
    return 0


def _selective_line() -> str:
    if not switches.selective_refuses():
        return "other commands go to the harness"
    shown = "shown to" if switches.selective_lists() else "kept from"
    return f"other commands are refused; the rules are {shown} the agent"


def _selective(setting: str, value: str) -> int:
    on = value == "on"
    if setting == "refuse":
        switches.set_selective_refuse(on)
    else:
        switches.set_selective_list(on)
    print(f"Selective:  {_selective_line()}")
    if switches.current_mode() is not Mode.SELECTIVE:
        print("            (applies in Selective mode only: chad mode selective)")
    return 0


def _deny(value: str) -> int:
    switches.set_deny(value == "on")
    print(f"Deny list: {'armed' if value == 'on' else 'off'}")
    return 0


def _open() -> int:
    if not ensure_dispatcher():
        print("The dispatcher did not start; see dispatcher.log in the data root.", file=sys.stderr)
        return 1
    protocol.request({"op": "ui", "action": "showPolicy"})
    if switches.ui_disabled():
        print("No window: CHAD_UI_DISABLED is set.")
    return 0


def _start() -> int:
    if ensure_dispatcher():
        print(f"Dispatcher running, pid {protocol.ping()}")
        return 0
    print("The dispatcher did not start; see dispatcher.log in the data root.", file=sys.stderr)
    return 1


def _stop() -> int:
    pid = protocol.ping()
    if pid is None:
        print("Dispatcher not running")
        return 0
    try:
        protocol.request({"op": "ui", "action": "shutdown"}, timeout=5)
    except protocol.DispatcherUnavailable:
        pass
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and protocol.ping(0.3) is not None:
        time.sleep(0.1)
    if protocol.ping(0.3) is not None:
        print("The dispatcher is still answering.", file=sys.stderr)
        return 1
    print("Dispatcher stopped")
    return 0


def _options(args: argparse.Namespace) -> installer.Options:
    return installer.Options(
        claude_dir=args.claude_dir or installer.default_claude_dir(),
        bin_dir=args.bin_dir or installer.default_bin_dir(),
        autostart=not getattr(args, "no_autostart", False),
        deny=getattr(args, "deny", False),
        purge=getattr(args, "purge", False),
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="chad", description=FULL_NAME)
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="mode, deny list and dispatcher")
    mode = commands.add_parser("mode", help="switch the mode")
    mode.add_argument("mode", choices=list(MODE_NAMES))
    deny = commands.add_parser("deny", help="arm or disarm the deny list")
    deny.add_argument("value", choices=["on", "off"])
    selective = commands.add_parser(
        "selective",
        help="Selective mode: refuse uncovered commands, show the rules to the agent",
    )
    selective.add_argument("setting", choices=["refuse", "list"])
    selective.add_argument("value", choices=["on", "off"])
    commands.add_parser("open", help="show the allow/deny list window")
    commands.add_parser("start", help="start the dispatcher")
    commands.add_parser("stop", help="stop the dispatcher and the UI")
    commands.add_parser("restart", help="stop, then start the dispatcher")
    for name, text in (("install", "set CHAD up for this user"), ("uninstall", "undo install")):
        sub = commands.add_parser(name, help=text)
        sub.add_argument(
            "--claude-dir", type=_path, help="default: $CLAUDE_CONFIG_DIR or ~/.claude"
        )
        sub.add_argument("--bin-dir", type=_path, help="where the chad shims go; ~/.local/bin")
        if name == "install":
            sub.add_argument("--no-autostart", action="store_true", help="no start at logon")
            sub.add_argument("--deny", action="store_true", help="also arm the deny list")
        else:
            sub.add_argument("--purge", action="store_true", help="also delete the data folder")
    return root


def _path(text: str) -> Path:
    return Path(text).expanduser()


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        match args.command:
            case "status":
                return _status()
            case "mode":
                return _mode(args.mode)
            case "deny":
                return _deny(args.value)
            case "selective":
                return _selective(args.setting, args.value)
            case "open":
                return _open()
            case "start":
                return _start()
            case "stop":
                return _stop()
            case "restart":
                return _stop() or _start()
            case "install":
                installer.install(_options(args))
                return 0
            case "uninstall":
                _stop()
                installer.uninstall(_options(args))
                return 0
    except installer.InstallError as exc:
        print(f"chad: {exc}", file=sys.stderr)
        return 1
    except protocol.DispatcherUnavailable as exc:
        print(f"chad: the dispatcher did not answer ({exc})", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
