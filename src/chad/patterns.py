"""Allow-rule patterns: words where * stands for one or more whole words.

`git commit -m *` covers a commit with any message, and nothing else git can do. Without a
wildcard, approving a commit forever would cover only that one message; the `*` marks the part
of the command the user does not care about.

A `*` needs at least one word. `git commit -m` with no message is therefore not covered by
`git commit -m *`; CHAD asks about it on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from chad.analysis import Dialect, redirect_words, words

WILDCARD = "*"


def _collapse(terms: list[str]) -> tuple[str, ...]:
    """Adjacent wildcards become one; two would quietly demand two words."""
    result: list[str] = []
    for term in terms:
        if not term or (term == WILDCARD and result and result[-1] == WILDCARD):
            continue
        result.append(term)
    return tuple(result)


@dataclass(frozen=True)
class Pattern:
    terms: tuple[str, ...]

    @staticmethod
    def of(terms: list[str]) -> Pattern:
        return Pattern(_collapse(terms))

    @staticmethod
    def parse(text: str) -> Pattern:
        return Pattern.of(words(text or ""))

    @property
    def is_empty(self) -> bool:
        return not self.terms

    @property
    def is_literal(self) -> bool:
        return WILDCARD not in self.terms

    @property
    def text(self) -> str:
        return " ".join(self.terms)

    def matches(self, statement: str, dialect: Dialect = "bash") -> bool:
        return self.matches_words(tuple(words(statement, dialect)))

    def matches_words(self, items: tuple[str, ...]) -> bool:
        return _match(self.terms, items)

    def subsumes(self, other: Pattern) -> bool:
        """True when everything `other` allows, this allows too."""
        return _subsumes(self.terms, other.terms)

    def __str__(self) -> str:
        return self.text


def _wildcard_ends(start: int, size: int, guarded: frozenset[int]) -> range:
    """Where a wildcard starting at `start` may end: one or more words, none of them guarded."""
    end = start
    while end < size and end not in guarded:
        end += 1
    return range(start + 1, end + 1)


def _match(terms: tuple[str, ...], items: tuple[str, ...]) -> bool:
    # A redirect to a file is matched only by a rule that names it.
    guarded = redirect_words(items)

    @cache
    def match_from(t: int, i: int) -> bool:
        if t == len(terms):
            return i == len(items)
        if terms[t] == WILDCARD:
            return any(match_from(t + 1, j) for j in _wildcard_ends(i, len(items), guarded))
        return i < len(items) and items[i] == terms[t] and match_from(t + 1, i + 1)

    return match_from(0, 0)


def _subsumes(mine: tuple[str, ...], theirs: tuple[str, ...]) -> bool:
    guarded = redirect_words(theirs)

    @cache
    def subsumes_from(m: int, t: int) -> bool:
        if m == len(mine):
            return t == len(theirs)
        if mine[m] == WILDCARD:
            return any(subsumes_from(m + 1, j) for j in _wildcard_ends(t, len(theirs), guarded))
        # A literal covers only an identical literal: their wildcard can produce words this refuses.
        return (
            t < len(theirs)
            and theirs[t] != WILDCARD
            and theirs[t] == mine[m]
            and subsumes_from(m + 1, t + 1)
        )

    return subsumes_from(0, 0)
