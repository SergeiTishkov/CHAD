"""Modes and the deny switch, stored as user environment variables."""

from __future__ import annotations

import os
from enum import StrEnum

from chad import paths, userenv

DISABLED = "CHAD_DISABLED"
ALLOW_ALL = "CHAD_ALLOW_ALL"
SELECTIVE = "CHAD_SELECTIVE_ALLOWLIST"
DENY = "CHAD_DENY"
UI_DISABLED = "CHAD_UI_DISABLED"


class Mode(StrEnum):
    """How CHAD treats a command; one mode is in force at any moment."""

    ALLOW_ALL = "allowAll"
    CHAD = "chad"
    SELECTIVE = "selective"
    OFF = "off"


DESCRIPTIONS = {
    Mode.CHAD: "CHAD runs matching allow rules; new commands wait for your approval.",
    Mode.ALLOW_ALL: "CHAD runs every command without asking; the allow list is unchanged.",
    Mode.SELECTIVE: (
        "Commands marked Selective go through CHAD; the rest go to the harness's own approval."
    ),
    Mode.OFF: "CHAD is switched off and the harness asks for approval itself.",
}


def is_on(name: str) -> bool:
    return paths.is_truthy(userenv.get(name))


def resolve(off: bool, allow_all: bool, selective: bool) -> Mode:
    """When several are set: Off, then Selective, then Allow all."""
    if off:
        return Mode.OFF
    if selective:
        return Mode.SELECTIVE
    if allow_all:
        return Mode.ALLOW_ALL
    return Mode.CHAD


def current_mode() -> Mode:
    return resolve(is_on(DISABLED), is_on(ALLOW_ALL), is_on(SELECTIVE))


def set_mode(mode: Mode) -> None:
    """Write all three mode variables so a stale one cannot reassert itself later."""
    for name, wanted in (
        (DISABLED, Mode.OFF),
        (ALLOW_ALL, Mode.ALLOW_ALL),
        (SELECTIVE, Mode.SELECTIVE),
    ):
        userenv.set(name, "1" if mode == wanted else None)


def deny_enabled() -> bool:
    return is_on(DENY)


def set_deny(on: bool) -> None:
    userenv.set(DENY, "1" if on else None)


def ui_disabled() -> bool:
    return paths.is_truthy(os.environ.get(UI_DISABLED)) or is_on(UI_DISABLED)
