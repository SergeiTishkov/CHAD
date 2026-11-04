"""CHAD inside a real `claude -p` run. Opt in with CHAD_E2E_CLAUDE=1: it spends tokens.

The hook is passed with --settings for this one run, so the user's own Claude Code settings are
not changed. The data root is the test's temporary folder.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from chad import installer, paths, switches
from chad.allowlist import AllowList
from chad.switches import Mode

from .harness import audit_decisions

pytestmark = [
    pytest.mark.claude,
    pytest.mark.skipif(
        os.environ.get("CHAD_E2E_CLAUDE") != "1", reason="set CHAD_E2E_CLAUDE=1 to run"
    ),
    pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not on PATH"),
]


def claude(prompt: str, tmp_path: Path) -> str:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(installer.merge_hook({}, installer.hook_command(sys.executable), 3600)),
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
    result = subprocess.run(
        [shutil.which("claude") or "claude", "-p", prompt, "--settings", str(settings)],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
        cwd=tmp_path,
    )
    return result.stdout + result.stderr


def test_an_allow_rule_runs_the_command_and_the_model_reads_its_output(tmp_path: Path) -> None:
    AllowList(paths.allow_list_file()).add_exact("echo chad-e2e-allowed")
    output = claude(
        "Run exactly this shell command with the Bash tool and tell me its output: "
        "echo chad-e2e-allowed",
        tmp_path,
    )
    assert "allowedByRule" in audit_decisions(), output
    assert "chad-e2e-allowed" in output


def test_a_deny_rule_reaches_the_model(tmp_path: Path) -> None:
    switches.set_mode(Mode.ALLOW_ALL)
    switches.set_deny(True)
    output = claude(
        "Run exactly this shell command with the Bash tool: git reset --hard HEAD~0 . "
        "If it is refused, quote the first line of the refusal.",
        tmp_path,
    )
    assert "deniedByRule" in audit_decisions(), output
    assert "deny list" in output.lower()
