from __future__ import annotations

import sys
from pathlib import Path

from chad import paths
from chad.config import Config
from chad.uilaunch import resolve_command, ui_environment


def test_environment_drops_electron_run_as_node() -> None:
    env = ui_environment({"ELECTRON_RUN_AS_NODE": "1", "PATH": "x"})
    assert "ELECTRON_RUN_AS_NODE" not in env
    assert env["PATH"] == "x"
    assert env["CHAD_HOME"] == str(paths.data_root())


def test_configured_command_wins(tmp_path: Path) -> None:
    command = resolve_command(Config(ui_command=("C:/x/CHAD.exe",)), tmp_path / "root", tmp_path)
    assert command == ["C:/x/CHAD.exe", "--data-root", str(tmp_path / "root")]


def test_packaged_app_before_development_electron(tmp_path: Path) -> None:
    electron = tmp_path / "node_modules" / "electron" / "dist"
    electron.mkdir(parents=True)
    (electron / ("electron.exe" if sys.platform == "win32" else "electron")).touch()
    (tmp_path / "dist").mkdir()
    root = tmp_path / "root"
    assert resolve_command(Config(), root, tmp_path)[1:] == [
        str(tmp_path),
        "--data-root",
        str(root),
    ]

    packaged = tmp_path / "release" / "win-unpacked"
    packaged.mkdir(parents=True)
    (packaged / "CHAD.exe").touch()
    assert resolve_command(Config(), root, tmp_path) == [
        str(packaged / "CHAD.exe"),
        "--data-root",
        str(root),
    ]


def test_nothing_built(tmp_path: Path) -> None:
    assert resolve_command(Config(), tmp_path / "root", tmp_path) is None
