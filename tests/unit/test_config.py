from __future__ import annotations

from pathlib import Path

from chad import config


def test_missing_file_is_created_with_defaults(isolated_home: Path) -> None:
    loaded = config.load()
    assert loaded == config.Config()
    text = (isolated_home / "config.yaml").read_text(encoding="utf-8")
    assert "hookTimeoutSeconds: 3600" in text
    assert "findRulesPageSize: 50" in text and loaded.find_rules_page_size == 50


def test_values_are_read(isolated_home: Path) -> None:
    (isolated_home / "config.yaml").write_text(
        "hookTimeoutSeconds: 120\nsafetyMarginSeconds: 20\nlaunchUi: false\nuiCommand: [a, b]\n"
        "findRulesPageSize: 10\n",
        encoding="utf-8",
    )
    loaded = config.load()
    assert loaded.find_rules_page_size == 10
    assert loaded.hook_timeout_seconds == 120
    assert loaded.approval_budget_seconds == 100
    assert loaded.launch_ui is False
    assert loaded.ui_command == ("a", "b")


def test_corrupt_file_means_defaults(isolated_home: Path) -> None:
    (isolated_home / "config.yaml").write_text("hookTimeoutSeconds: [unclosed\n", encoding="utf-8")
    assert config.load() == config.Config()


def test_budget_never_drops_below_five_seconds() -> None:
    assert (
        config.Config(hook_timeout_seconds=10, safety_margin_seconds=30).approval_budget_seconds
        == 5
    )
