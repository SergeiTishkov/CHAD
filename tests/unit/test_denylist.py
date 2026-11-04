from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from chad.denylist import DEFAULT_RULES, DenyList, DenyListError, DenyRule, bag_of


def rule(words: str) -> DenyRule:
    return DenyRule(words)


@pytest.mark.parametrize(
    "statement",
    [
        "rm -rf dist",
        "rm dist -rf",
        "rm -v -rf ./out",
        "RM -RF x",
        'bash -c "rm -rf /"',
        "pwsh -c 'rm -rf x'",
        "echo $(rm -rf x)",
        "/bin/rm -rf x",
        "\\rm -rf x",
        "C:\\tools\\rm.exe -rf x",
        "{ rm -rf x; }",
    ],
)
def test_rm_rf_is_caught(statement: str) -> None:
    assert rule("rm -rf").matches(bag_of(statement))


@pytest.mark.parametrize("statement", ["rm -r x", "rm -rfv x", "git rm -r --cached x", "echo rm"])
def test_rm_rf_is_not_caught(statement: str) -> None:
    assert not rule("rm -rf").matches(bag_of(statement))


def test_windows_switches_are_words() -> None:
    assert rule("del /s /q").matches(bag_of("del /q /s C:\\temp"))
    assert rule("shutdown /r").matches(bag_of("shutdown.exe /r /t 0"))


def test_empty_rule_never_matches() -> None:
    assert not rule("  ").matches(bag_of("anything"))


@pytest.fixture
def store(isolated_home: Path) -> DenyList:
    return DenyList(isolated_home / "deny-list.yaml")


def test_missing_file_is_created_with_defaults(store: DenyList) -> None:
    assert [r.words for r in store.rules] == list(DEFAULT_RULES)
    assert all(r.enabled for r in store.rules)
    assert "CHAD_DENY" in store.path.read_text(encoding="utf-8")


def test_first_enabled_match_is_named(store: DenyList) -> None:
    hit = store.first_match(["git status", "git push --force origin main"])
    assert hit is not None
    assert hit[0].words == "git push --force"
    assert hit[1] == "git push --force origin main"


def test_disabled_rule_does_not_match(store: DenyList) -> None:
    assert store.set_enabled("GIT RESET --HARD", False)
    assert store.match("git reset --hard HEAD") is None
    assert not store.set_enabled("git reset --hard", False)
    assert "enabled: false" in store.path.read_text(encoding="utf-8")


def test_add_remove_move(store: DenyList) -> None:
    assert store.add("npm publish")
    assert not store.add("NPM publish")
    assert store.match("npm publish --tag x").words == "npm publish"
    assert store.move("npm publish", 0)
    assert store.rules[0].words == "npm publish"
    assert store.remove("npm publish")
    assert not store.remove("npm publish")


def test_hand_edits_are_picked_up(store: DenyList) -> None:
    store.path.write_text("denied:\n  - words: terraform destroy\n", encoding="utf-8")
    future = time.time() + 5
    os.utime(store.path, (future, future))
    assert [r.words for r in store.rules] == ["terraform destroy"]


def test_malformed_file_keeps_defaults_and_is_not_overwritten(store: DenyList) -> None:
    store.path.write_text("denied: [unclosed\n", encoding="utf-8")
    future = time.time() + 5
    os.utime(store.path, (future, future))
    assert store.match("rm -rf x") is not None
    assert store.error
    with pytest.raises(DenyListError):
        store.add("x")
    assert store.path.read_text(encoding="utf-8") == "denied: [unclosed\n"
