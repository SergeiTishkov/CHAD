from __future__ import annotations

import json
from pathlib import Path

import pytest

from chad import installer, paths, switches, userenv
from chad.installer import InstallError, Options

CHAD = {"type": "command", "command": '"C:/old/python.exe" -m chad.hook', "timeout": 60}
OTHER = {"type": "command", "command": "lint.sh"}


def test_merge_replaces_an_old_chad_hook_and_keeps_the_rest() -> None:
    settings = {
        "model": "opus",
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [CHAD, OTHER]},
                {"matcher": "Edit", "hooks": [OTHER]},
            ],
            "Stop": [{"hooks": [OTHER]}],
        },
    }
    merged = installer.merge_hook(settings, '"C:/new/python.exe" -m chad.hook', 3600)
    assert merged["model"] == "opus"
    assert merged["hooks"]["Stop"] == settings["hooks"]["Stop"]
    assert merged["hooks"]["PreToolUse"] == [
        {"matcher": "Bash", "hooks": [OTHER]},
        {"matcher": "Edit", "hooks": [OTHER]},
        {
            "matcher": "Bash|PowerShell",
            "hooks": [
                {"type": "command", "command": '"C:/new/python.exe" -m chad.hook', "timeout": 3600}
            ],
        },
    ]
    assert settings["hooks"]["PreToolUse"][0]["hooks"] == [CHAD, OTHER]  # input untouched


def test_remove_cleans_up_empty_sections() -> None:
    settings = {"hooks": {"PreToolUse": [{"matcher": "Bash|PowerShell", "hooks": [CHAD]}]}}
    assert installer.remove_hook(settings) == {}
    assert installer.remove_hook({"x": 1}) == {"x": 1}


def test_hook_command_uses_forward_slashes() -> None:
    assert installer.hook_command(r"C:\repo\.venv\Scripts\python.exe") == (
        '"C:/repo/.venv/Scripts/python.exe" -m chad.hook'
    )


def test_shims() -> None:
    shims = installer.shim_files(r"C:\repo\.venv\Scripts\python.exe")
    assert shims["chad.cmd"] == '@"C:\\repo\\.venv\\Scripts\\python.exe" -m chad %*\r\n'
    assert shims["chad"] == '#!/bin/sh\nexec "/c/repo/.venv/Scripts/python.exe" -m chad "$@"\n'


def test_the_repository_ships_the_three_skills() -> None:
    assert installer.skill_names() == [
        "chad",
        "chad-add-selective-command",
        "chad-allow-deny-list",
    ]


@pytest.fixture
def options(tmp_path: Path) -> Options:
    return Options(claude_dir=tmp_path / "claude", bin_dir=tmp_path / "bin")


def test_install_and_uninstall(options: Options) -> None:
    settings_path = options.claude_dir / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")

    lines: list[str] = []
    installer.install(Options(options.claude_dir, options.bin_dir, deny=True), lines.append)

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["theme"] == "dark"
    (group,) = settings["hooks"]["PreToolUse"]
    assert group["matcher"] == "Bash|PowerShell"
    assert group["hooks"][0]["timeout"] == 3600
    assert group["hooks"][0]["command"].endswith("-m chad.hook")
    assert list(options.claude_dir.glob("settings.json.chad-backup-*"))

    for name in installer.skill_names():
        assert (options.claude_dir / "skills" / name / "SKILL.md").is_file()
    assert (options.bin_dir / "chad.cmd").is_file()
    assert userenv.get("CHAD_HOME") == str(paths.data_root())
    assert switches.deny_enabled()
    assert installer.get_autostart().endswith("-m chad.dispatcher")
    assert paths.allow_list_file().is_file() and paths.deny_list_file().is_file()
    assert any("Restart the harness" in line for line in lines)

    # Running it again changes nothing that matters and leaves one hook.
    installer.install(options, lambda _: None)
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert len(settings["hooks"]["PreToolUse"]) == 1

    switches.set_mode(switches.Mode.SELECTIVE)
    installer.uninstall(options, lambda _: None)
    assert json.loads(settings_path.read_text(encoding="utf-8")) == {"theme": "dark"}
    assert not switches.deny_enabled()
    assert switches.current_mode() == switches.Mode.CHAD
    assert not any((options.claude_dir / "skills").iterdir())
    assert not (options.bin_dir / "chad.cmd").exists()
    assert userenv.get("CHAD_HOME") is None
    assert installer.get_autostart() is None
    assert paths.data_root().is_dir()


def test_uninstall_purge_deletes_the_data(options: Options) -> None:
    installer.install(options, lambda _: None)
    root = paths.data_root()
    installer.uninstall(Options(options.claude_dir, options.bin_dir, purge=True), lambda _: None)
    assert not root.exists()


def test_broken_settings_stop_the_install_before_anything_changes(options: Options) -> None:
    settings_path = options.claude_dir / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(InstallError, match="not valid JSON"):
        installer.install(options, lambda _: None)
    assert settings_path.read_text(encoding="utf-8") == "{ not json"
    assert userenv.get("CHAD_HOME") is None
    assert not options.bin_dir.exists()


def test_isolated_mode_refuses_the_configured_claude_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "configured"))
    configured = Options(claude_dir=tmp_path / "configured", bin_dir=tmp_path / "bin")
    with pytest.raises(InstallError, match="CHAD_ISOLATED"):
        installer.install(configured, lambda _: None)


def test_isolated_mode_refuses_the_real_user_folders() -> None:
    real = Options(claude_dir=Path.home() / ".claude", bin_dir=installer.default_bin_dir())
    with pytest.raises(InstallError, match="CHAD_ISOLATED"):
        installer.install(real, lambda _: None)
    with pytest.raises(InstallError, match="CHAD_ISOLATED"):
        installer.uninstall(real, lambda _: None)
