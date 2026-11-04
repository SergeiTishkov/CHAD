"""Which PowerShell CHAD picks: the edition Claude Code's PowerShell tool runs."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from chad import executor

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the Windows lookup")


def program(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(b"")
    return folder / name


@pytest.fixture
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A machine with only what each test installs: no PowerShell anywhere yet."""
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "ProgramFiles"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.setenv("SystemRoot", str(tmp_path / "Windows"))
    monkeypatch.setenv("PATHEXT", ".EXE")
    return tmp_path


def test_pwsh_on_the_path_comes_first(machine: Path) -> None:
    pwsh = program(machine / "tools", "pwsh.exe")
    program(machine / "ProgramFiles/PowerShell/7", "pwsh.exe")
    assert Path(executor._powershell_executable(str(pwsh.parent))) == pwsh


def test_pwsh_in_its_install_folder(machine: Path) -> None:
    pwsh = program(machine / "ProgramFiles/PowerShell/7", "pwsh.exe")
    program(machine / "bin", "powershell.exe")
    assert Path(executor._powershell_executable(str(machine / "bin"))) == pwsh


def test_pwsh_from_the_microsoft_store(machine: Path) -> None:
    pwsh = program(machine / "LocalAppData/Microsoft/WindowsApps", "pwsh.exe")
    assert Path(executor._powershell_executable(str(machine / "empty"))) == pwsh


def test_windows_powershell_without_pwsh(machine: Path) -> None:
    legacy = program(machine / "bin", "powershell.exe")
    assert Path(executor._powershell_executable(str(machine / "bin"))) == legacy
    system = program(machine / "Windows/System32/WindowsPowerShell/v1.0", "powershell.exe")
    assert Path(executor._powershell_executable(str(machine / "empty"))) == system


def test_no_powershell_at_all(machine: Path) -> None:
    with pytest.raises(FileNotFoundError, match="could not find PowerShell"):
        executor._powershell_executable(str(machine / "empty"))


def test_the_path_is_found_whatever_its_case() -> None:
    assert executor.search_path({"Path": "C:/a"}) == "C:/a"
    assert executor.search_path({"PATH": "C:/b"}) == "C:/b"
    assert executor.search_path({}) is None
