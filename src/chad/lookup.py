"""What the agent may learn about the Selective rules while Selective mode refuses the rest.

A refusal can list the rules for the program the agent tried, and two control requests answer
the rest: `#chad:find-rules <words>` searches the Selective rules, `#chad:check <command>` says
whether a command would run. Both are comments in bash and PowerShell, so neither does anything
should it reach a shell.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from chad.allowlist import Entry, Kind
from chad.analysis import ASSIGNMENT, Dialect, words

FIND_RULES_MARKER = "#chad:find-rules"
CHECK_MARKER = "#chad:check"
PAGE_OPTION = "--page"
# How many rules a refusal lists for the program the agent tried.
SHORT_LIST = 20


class RequestKind(StrEnum):
    FIND = "find"
    CHECK = "check"


@dataclass(frozen=True)
class Request:
    kind: RequestKind
    text: str  # what follows the marker, trimmed


def parse(command: str) -> Request | None:
    """The control request a command is, when it starts with one of the markers (any case)."""
    stripped = command.strip()
    lowered = stripped.lower()
    for marker, kind in ((FIND_RULES_MARKER, RequestKind.FIND), (CHECK_MARKER, RequestKind.CHECK)):
        if lowered == marker or (
            lowered.startswith(marker) and lowered[len(marker)] in (" ", "\t", "\r", "\n")
        ):
            return Request(kind, stripped[len(marker) :].strip())
    return None


def shown(entry: Entry) -> str:
    """A rule as the agent reads it: its text, with `regex:` in front of a regular expression."""
    return f"regex: {entry.value}" if entry.kind is Kind.REGEX else entry.value


def program_of(statement: str, dialect: Dialect) -> str | None:
    """The program a statement calls: its first word after any `NAME=value` assignments."""
    for word in words(statement, dialect):
        if not ASSIGNMENT.match(word):
            return word
    return None


def for_program(entries: Sequence[Entry], program: str) -> list[Entry]:
    """The rules for one program: exact and pattern rules starting with it, regexes naming it."""
    wanted = program.lower()
    found = []
    for entry in entries:
        if entry.kind is Kind.REGEX:
            if wanted in entry.value.lower():
                found.append(entry)
        else:
            first = next(iter(words(entry.value)), "")
            if first.lower() == wanted:
                found.append(entry)
    return found


@dataclass(frozen=True)
class Page:
    query: tuple[str, ...]
    number: int
    size: int
    matches: tuple[Entry, ...]  # every match, best first

    @property
    def total(self) -> int:
        return len(self.matches)

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.size))

    @property
    def first(self) -> int:
        return (self.number - 1) * self.size

    @property
    def rules(self) -> tuple[Entry, ...]:
        return self.matches[self.first : self.first + self.size]

    @property
    def has_more(self) -> bool:
        return self.first + self.size < self.total


class FindError(ValueError):
    """A #chad:find-rules request that cannot be read; the message is for the model."""


def read_find(text: str) -> tuple[tuple[str, ...], int]:
    """The search words and the page number of a #chad:find-rules request."""
    if "\n" in text or "\r" in text:
        raise FindError("Put the search words on the same line as #chad:find-rules.")
    tokens = text.split()
    page = 1
    if tokens and tokens[0].lower() == PAGE_OPTION:
        if len(tokens) < 2 or not tokens[1].isdigit() or int(tokens[1]) < 1:
            raise FindError(f"{PAGE_OPTION} takes a page number from 1: {PAGE_OPTION} 2.")
        page = int(tokens[1])
        tokens = tokens[2:]
    return tuple(tokens), page


def find(entries: Sequence[Entry], query: Sequence[str], page: int, size: int) -> Page:
    """The rules that contain any of the words (any case); more words found ranks higher.

    With no words every rule matches. Rules with the same count keep the list's own order.
    """
    wanted = [w.lower() for w in query]
    scored = []
    for index, entry in enumerate(entries):
        text = shown(entry).lower()
        score = sum(1 for w in wanted if w in text)
        if score or not wanted:
            scored.append((-score, index, entry))
    scored.sort(key=lambda item: (item[0], item[1]))
    return Page(tuple(query), page, max(1, size), tuple(entry for _, _, entry in scored))
