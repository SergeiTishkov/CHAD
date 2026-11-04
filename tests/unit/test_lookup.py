from __future__ import annotations

import pytest

from chad import lookup
from chad.allowlist import Entry, Kind
from chad.lookup import RequestKind


@pytest.mark.parametrize(
    ("command", "kind", "text"),
    [
        ("#chad:find-rules git push", RequestKind.FIND, "git push"),
        ("  #CHAD:FIND-RULES  ", RequestKind.FIND, ""),
        ("#chad:find-rules\tgit", RequestKind.FIND, "git"),
        ("#chad:check git status && git log", RequestKind.CHECK, "git status && git log"),
        ("#chad:check", RequestKind.CHECK, ""),
        ("#chad:check git a\ngit b", RequestKind.CHECK, "git a\ngit b"),
    ],
)
def test_a_marker_at_the_start_is_a_request(command: str, kind: RequestKind, text: str) -> None:
    assert lookup.parse(command) == lookup.Request(kind, text)


@pytest.mark.parametrize(
    "command",
    ["git status #chad:check x", "#chad:checkx", "#chad:find-rulesgit", "#chad", "", "ls"],
)
def test_anything_else_is_not(command: str) -> None:
    assert lookup.parse(command) is None


def test_a_rule_as_the_agent_reads_it() -> None:
    assert lookup.shown(Entry(Kind.EXACT, "git status")) == "git status"
    assert lookup.shown(Entry(Kind.PATTERN, "git log *")) == "git log *"
    assert lookup.shown(Entry(Kind.REGEX, "^npm (ci|test)$")) == "regex: ^npm (ci|test)$"


@pytest.mark.parametrize(
    ("statement", "program"),
    [
        ("git push", "git"),
        ("FOO=1 BAR=2 cargo build", "cargo"),
        ('"C:/tools/x.exe" --help', '"C:/tools/x.exe"'),
        ("A=1", None),
    ],
)
def test_the_program_of_a_statement(statement: str, program: str | None) -> None:
    assert lookup.program_of(statement, "bash") == program


def test_rules_for_a_program() -> None:
    entries = [
        Entry(Kind.EXACT, "git status"),
        Entry(Kind.PATTERN, "GIT log *"),
        Entry(Kind.PATTERN, "gitk *"),
        Entry(Kind.REGEX, "^git (fetch|pull)$"),
        Entry(Kind.REGEX, "^npm ci$"),
    ]
    found = lookup.for_program(entries, "git")
    assert [e.value for e in found] == ["git status", "GIT log *", "^git (fetch|pull)$"]


def test_find_ranks_by_words_found_then_list_order() -> None:
    entries = [
        Entry(Kind.EXACT, "npm run push"),
        Entry(Kind.EXACT, "git status"),
        Entry(Kind.PATTERN, "git push *"),
        Entry(Kind.EXACT, "cargo build"),
        Entry(Kind.REGEX, "^git push( --tags)?$"),
    ]
    page = lookup.find(entries, ("git", "PUSH"), 1, 10)
    assert [e.value for e in page.matches] == [
        "git push *",
        "^git push( --tags)?$",
        "npm run push",
        "git status",
    ]
    assert page.total == 4 and page.pages == 1 and not page.has_more


def test_find_without_words_matches_everything() -> None:
    entries = [Entry(Kind.EXACT, "a"), Entry(Kind.EXACT, "b")]
    assert lookup.find(entries, (), 1, 10).total == 2


def test_pages() -> None:
    entries = [Entry(Kind.EXACT, f"git {i}") for i in range(7)]
    first = lookup.find(entries, ("git",), 1, 3)
    assert [e.value for e in first.rules] == ["git 0", "git 1", "git 2"]
    assert (first.first, first.pages, first.has_more) == (0, 3, True)
    last = lookup.find(entries, ("git",), 3, 3)
    assert [e.value for e in last.rules] == ["git 6"] and not last.has_more
    assert lookup.find(entries, ("git",), 4, 3).rules == ()
    assert lookup.find(entries, ("git",), 1, 0).size == 1


@pytest.mark.parametrize(
    ("text", "query", "page"),
    [
        ("git push", ("git", "push"), 1),
        ("", (), 1),
        ("--page 3 git", ("git",), 3),
        ("--PAGE 2", (), 2),
    ],
)
def test_reading_a_find_request(text: str, query: tuple[str, ...], page: int) -> None:
    assert lookup.read_find(text) == (query, page)


@pytest.mark.parametrize("text", ["--page", "--page 0", "--page -1 git", "--page x", "git\nls"])
def test_a_find_request_that_cannot_be_read(text: str) -> None:
    with pytest.raises(lookup.FindError):
        lookup.read_find(text)
