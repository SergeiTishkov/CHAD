from __future__ import annotations

import pytest

from chad.patterns import Pattern


@pytest.mark.parametrize(
    ("pattern", "statement", "expected"),
    [
        ("git commit -m *", 'git commit -m "fix it"', True),
        ("git commit -m *", "git commit -m one two", True),
        ("git commit -m *", "git commit -m", False),
        ("git commit -m *", "git push -m x", False),
        ("git * --oneline", "git log -5 --oneline", True),
        ("git * --oneline", "git --oneline", False),
        ("* --version", "node --version", True),
        ("npm test", "npm test", True),
        ("npm test", "npm test --watch", False),
        ("npm test", "NPM test", False),
        ("echo *", "echo hi > out.log", False),
        ("echo *", "echo hi > ~/.bashrc", False),
        ("echo *", "echo hi 2>/dev/null", True),
        ("echo *", "echo hi 2>&1", True),
        ("echo * > out.log", "echo hi there > out.log", True),
        ("echo * > out.log", "echo hi > other.log", False),
        ("echo * > *", "echo hi > out.log", False),
        ("dotnet test *> red-run.log", "dotnet test *> red-run.log", True),
        ("ls *", 'ls "my dir"', True),
    ],
)
def test_matches(pattern: str, statement: str, expected: bool) -> None:
    assert Pattern.parse(pattern).matches(statement) is expected


def test_adjacent_wildcards_collapse() -> None:
    pattern = Pattern.of(["git", "*", "*", "x"])
    assert pattern.text == "git * x"
    assert pattern.matches("git a x")


def test_literal_and_empty() -> None:
    assert Pattern.parse("git status").is_literal
    assert not Pattern.parse("git *").is_literal
    assert Pattern.parse("   ").is_empty


@pytest.mark.parametrize(
    ("broad", "narrow", "expected"),
    [
        ("git *", "git commit -m *", True),
        ("git commit *", "git commit -m *", True),
        ("git commit -m *", "git commit -m *", True),
        ("git commit -m *", "git commit *", False),
        ("git * x", "git a b x", True),
        ("git a", "git *", False),
        ("* status", "git status", True),
        ("git *", "git", False),
        ("echo *", "echo * > out.log", False),
        ("echo * > out.log", "echo a > out.log", True),
    ],
)
def test_subsumes(broad: str, narrow: str, expected: bool) -> None:
    assert Pattern.parse(broad).subsumes(Pattern.parse(narrow)) is expected
