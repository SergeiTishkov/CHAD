from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from chad import paths, switches, userenv
from chad.switches import Mode


@pytest.mark.parametrize("value", ["1", "true", "YES", " on ", "y"])
def test_truthy_values(value: str) -> None:
    assert paths.is_truthy(value)


@pytest.mark.parametrize("value", [None, "", "0", "false", "off", "enable", "2"])
def test_everything_else_is_off(value: str | None) -> None:
    assert not paths.is_truthy(value)


def test_isolated_root_comes_from_chad_home(isolated_home: Path) -> None:
    assert paths.data_root() == isolated_home.resolve()


def test_isolated_mode_without_home_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHAD_HOME")
    with pytest.raises(RuntimeError):
        paths.data_root()


def test_default_root_outside_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.delenv("CHAD_ISOLATED")
    monkeypatch.delenv("CHAD_HOME")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert paths.data_root() == tmp_path / "chad"


def test_isolated_user_environment_is_a_file(isolated_home: Path) -> None:
    userenv.set("CHAD_DENY", "1")
    stored = json.loads((isolated_home / userenv.FILE_NAME).read_text(encoding="utf-8"))
    assert stored == {"CHAD_DENY": "1"}
    userenv.set("CHAD_DENY", None)
    assert userenv.get("CHAD_DENY") is None


def test_process_environment_does_not_count_for_switches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAD_ALLOW_ALL", "1")
    assert switches.current_mode() is Mode.CHAD


@pytest.mark.parametrize(
    ("off", "allow_all", "selective", "expected"),
    [
        (False, False, False, Mode.CHAD),
        (False, True, False, Mode.ALLOW_ALL),
        (False, False, True, Mode.SELECTIVE),
        (False, True, True, Mode.SELECTIVE),
        (True, True, True, Mode.OFF),
        (True, False, False, Mode.OFF),
    ],
)
def test_precedence(off: bool, allow_all: bool, selective: bool, expected: Mode) -> None:
    assert switches.resolve(off, allow_all, selective) is expected


@pytest.mark.parametrize("mode", list(Mode))
def test_set_mode_round_trips_and_clears_the_others(mode: Mode) -> None:
    for name in (switches.DISABLED, switches.ALLOW_ALL, switches.SELECTIVE):
        userenv.set(name, "1")
    switches.set_mode(mode)
    assert switches.current_mode() is mode
    names = (switches.DISABLED, switches.ALLOW_ALL, switches.SELECTIVE)
    on = [n for n in names if switches.is_on(n)]
    assert len(on) == (0 if mode is Mode.CHAD else 1)


def test_deny_switch_is_independent_of_mode() -> None:
    switches.set_mode(Mode.ALLOW_ALL)
    switches.set_deny(True)
    assert switches.deny_enabled()
    assert switches.current_mode() is Mode.ALLOW_ALL
    switches.set_deny(False)
    assert not switches.deny_enabled()


def test_selective_switches_are_off_by_default_and_independent_of_mode() -> None:
    assert not switches.selective_refuses() and not switches.selective_lists()
    switches.set_selective_refuse(True)
    switches.set_selective_list(True)
    for mode in Mode:
        switches.set_mode(mode)
        assert switches.selective_refuses() and switches.selective_lists()
    assert userenv.get(switches.SELECTIVE_REFUSE) == "1"
    assert userenv.get(switches.SELECTIVE_LIST) == "1"
    switches.set_selective_refuse(False)
    switches.set_selective_list(False)
    assert userenv.get(switches.SELECTIVE_REFUSE) is None
    assert userenv.get(switches.SELECTIVE_LIST) is None


def test_the_selective_description_follows_the_refuse_switch() -> None:
    assert switches.description(Mode.SELECTIVE) == switches.DESCRIPTIONS[Mode.SELECTIVE]
    switches.set_selective_refuse(True)
    assert switches.description(Mode.SELECTIVE) == switches.SELECTIVE_REFUSING
    for mode in (Mode.CHAD, Mode.ALLOW_ALL, Mode.OFF):
        assert switches.description(mode) == switches.DESCRIPTIONS[mode]


@pytest.mark.skipif(sys.platform != "win32", reason="registry backend")
@pytest.mark.skipif(
    os.environ.get("CHAD_TEST_REGISTRY") != "1",
    reason="writes to HKCU Environment; opt in with CHAD_TEST_REGISTRY=1",
)
def test_registry_backend_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Uses a throwaway variable name so the real switches are never touched."""
    import uuid

    monkeypatch.delenv("CHAD_ISOLATED")
    name = f"CHAD_TEST_{uuid.uuid4().hex[:8].upper()}"
    try:
        userenv.set(name, "1")
        assert userenv.get(name) == "1"
    finally:
        userenv.set(name, None)
    assert userenv.get(name) is None
