from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Each test gets a fresh data root; the real user environment stays untouched."""
    home = tmp_path / "chad-home"
    home.mkdir()
    monkeypatch.setenv("CHAD_HOME", str(home))
    monkeypatch.setenv("CHAD_ISOLATED", "1")
    monkeypatch.setenv("CHAD_UI_DISABLED", "1")
    # Keeps every process a test starts away from the real Claude Code settings.
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
    return home
