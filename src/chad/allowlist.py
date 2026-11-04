"""The ordered allow list: commands CHAD lets through without asking.

The YAML file stores the list and can be edited by hand. Matching and every change go through
this module, so the window cannot apply rules of its own.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

import yaml

from chad import atomic
from chad.analysis import Dialect, words
from chad.patterns import Pattern


class Kind(StrEnum):
    EXACT = "exact"
    PATTERN = "pattern"
    REGEX = "regex"


@dataclass(frozen=True)
class Entry:
    kind: Kind
    value: str
    selective: bool = False

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.value}"


@dataclass(frozen=True)
class Match:
    allowed: bool
    matched_by: str | None = None
    selective: bool = False


NO_MATCH = Match(False)

HEADER = """\
# CHAD allow list. Order is the window's order; Selective rows always come first.
#
# kind: exact   - the whole statement, word for word
#       pattern - words where * stands for one or more words: git commit -m *
#       regex   - Python regular expression searched in the statement (anchor it yourself)
# selective: true - the row also runs in Selective Allowlist mode
#
# Every statement of a chained command is checked on its own. Statements with command
# substitution, eval, a redirect outside the working folder and similar constructs are never
# auto-allowed. A * never stands for a redirect: write `> out.log` in the rule itself.
# Edits are picked up live. The window rewrites this file; comments below are not kept.

"""


class AllowListError(Exception):
    pass


class AllowList:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._entries: list[Entry] = []
        self._regex: dict[str, re.Pattern[str]] = {}
        self._stamp: tuple[float, int] | None = None
        self._error: str | None = None
        self._load()

    # -- loading -----------------------------------------------------------------------------

    def _file_stamp(self) -> tuple[float, int] | None:
        try:
            stat = self.path.stat()
        except OSError:
            return None
        return (stat.st_mtime, stat.st_size)

    def _load(self) -> None:
        if not self.path.exists():
            self._entries = []
            self._error = None
            self._save()
            return
        try:
            document = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
            if not isinstance(document, dict) or not isinstance(
                document.get("allowed") or [], list
            ):
                raise ValueError("expected a mapping with an 'allowed' list")
            entries: list[Entry] = []
            for item in document.get("allowed") or []:
                if not isinstance(item, dict):
                    raise ValueError("each rule must be a mapping with 'kind' and 'value'")
                entry = self._entry(item)
                if entry and all(e.key != entry.key for e in entries):
                    entries.append(entry)
            # Hand edits may interleave the tiers; order them without rewriting the file.
            self._entries = [e for e in entries if e.selective] + [
                e for e in entries if not e.selective
            ]
            self._error = None
        except (OSError, ValueError, yaml.YAMLError) as exc:
            # A malformed allow list allows nothing, and is kept for the user to fix.
            self._entries = []
            self._error = (
                f"{self.path} could not be read ({exc}); nothing is allowed until it is fixed."
            )
        self._compile()
        self._stamp = self._file_stamp()

    @staticmethod
    def _entry(item: dict) -> Entry | None:
        kind_name = str(item.get("kind", "exact")).lower()
        if kind_name not in set(Kind):
            raise ValueError(f"unknown rule kind {kind_name!r}")
        kind = Kind(kind_name)
        value = str(item.get("value") or "").strip()
        if not value:
            return None
        if kind is Kind.PATTERN:
            pattern = Pattern.parse(value)
            if pattern.is_empty:
                return None
            if not pattern.is_literal:
                value = pattern.text
            else:
                kind = Kind.EXACT
        return Entry(kind, value, bool(item.get("selective", False)))

    def _compile(self) -> None:
        self._regex = {}
        for entry in self._entries:
            if entry.kind is Kind.REGEX:
                try:
                    self._regex[entry.key] = re.compile(entry.value)
                except re.error:
                    pass  # stays listed and editable, never allows anything

    def _refresh(self) -> None:
        if self._file_stamp() != self._stamp:
            self._load()

    def _save(self) -> None:
        body = yaml.safe_dump(
            {
                "version": 1,
                "allowed": [
                    {"kind": str(e.kind), "value": e.value, "selective": e.selective}
                    for e in self._entries
                ],
            },
            sort_keys=False,
            allow_unicode=True,
            width=1000,
        )
        atomic.write_text(self.path, HEADER + body)
        self._compile()
        self._stamp = self._file_stamp()

    def _mutable(self) -> None:
        self._refresh()
        if self._error:
            raise AllowListError(self._error)

    def _selective_count(self) -> int:
        return sum(1 for e in self._entries if e.selective)

    def _insert(self, entry: Entry) -> None:
        if entry.selective:
            self._entries.insert(self._selective_count(), entry)
        else:
            self._entries.append(entry)

    # -- queries -----------------------------------------------------------------------------

    @property
    def error(self) -> str | None:
        """Why the file on disk could not be used, if it could not."""
        with self._lock:
            self._refresh()
            return self._error

    @property
    def entries(self) -> list[Entry]:
        with self._lock:
            self._refresh()
            return list(self._entries)

    def match(
        self, statement: str, dialect: Dialect = "bash", selective_only: bool = False
    ) -> Match:
        if not statement.strip():
            return NO_MATCH
        with self._lock:
            self._refresh()
            statement_words = tuple(words(statement, dialect))
            for entry in self._entries:
                if selective_only and not entry.selective:
                    continue
                if entry.kind is Kind.EXACT:
                    hit = entry.value == statement
                    by = "exact"
                elif entry.kind is Kind.PATTERN:
                    hit = Pattern.parse(entry.value).matches_words(statement_words)
                    by = f"pattern: {entry.value}"
                else:
                    compiled = self._regex.get(entry.key)
                    hit = bool(compiled and compiled.search(statement))
                    by = f"regex: {entry.value}"
                if hit:
                    return Match(True, by, entry.selective)
        return NO_MATCH

    # -- mutations ---------------------------------------------------------------------------

    def add_exact(self, statement: str, selective: bool = False) -> bool:
        """Allow one normalized statement as it stands. Returns whether the list changed."""
        value = statement.strip()
        if not value:
            return False
        with self._lock:
            self._mutable()
            for index, entry in enumerate(self._entries):
                if entry.kind is Kind.EXACT and entry.value == value:
                    if selective and not entry.selective:
                        self._promote(index)
                        self._save()
                        return True
                    return False
            self._insert(Entry(Kind.EXACT, value, selective))
            self._save()
            return True

    def add_pattern(self, pattern: Pattern, selective: bool = False) -> bool:
        """Allow a wildcard pattern, pruning the rules it makes redundant in its tier."""
        if pattern.is_empty:
            return False
        if pattern.is_literal:
            return self.add_exact(pattern.text, selective)
        with self._lock:
            self._mutable()
            for index, entry in enumerate(self._entries):
                if entry.kind is Kind.PATTERN and entry.value == pattern.text:
                    if selective and not entry.selective:
                        self._promote(index)
                        self._save()
                        return True
                    return False
            # Already covered by a pattern of the same or a higher tier: nothing to add.
            if any(
                e.kind is Kind.PATTERN
                and (e.selective or not selective)
                and Pattern.parse(e.value).subsumes(pattern)
                for e in self._entries
            ):
                return False
            # Prune what the new rule makes redundant. An ordinary rule never removes a
            # Selective row: Selective mode still needs it.
            kept = []
            for entry in self._entries:
                redundant = entry.selective == selective and (
                    (entry.kind is Kind.EXACT and pattern.matches(entry.value))
                    or (entry.kind is Kind.PATTERN and pattern.subsumes(Pattern.parse(entry.value)))
                )
                if not redundant:
                    kept.append(entry)
            self._entries = kept
            self._insert(Entry(Kind.PATTERN, pattern.text, selective))
            self._save()
            return True

    def _promote(self, index: int) -> None:
        entry = replace(self._entries.pop(index), selective=True)
        self._entries.insert(self._selective_count(), entry)

    def set_selective(self, key: str, selective: bool) -> bool:
        with self._lock:
            self._mutable()
            index = next((i for i, e in enumerate(self._entries) if e.key == key), None)
            if index is None or self._entries[index].selective == selective:
                return False
            entry = replace(self._entries.pop(index), selective=selective)
            # Either way the row lands on the boundary between the tiers.
            self._entries.insert(self._selective_count(), entry)
            self._save()
            return True

    def move(self, key: str, index: int) -> bool:
        """Reorder within the row's own tier; a drop across the boundary clamps at its edge."""
        with self._lock:
            self._mutable()
            source = next((i for i, e in enumerate(self._entries) if e.key == key), None)
            if source is None:
                return False
            entry = self._entries.pop(source)
            boundary = self._selective_count()
            if entry.selective:
                target = max(0, min(index, boundary))
            else:
                target = max(boundary, min(index, len(self._entries)))
            self._entries.insert(target, entry)
            if target == source:
                return False
            self._save()
            return True

    def edit(self, key: str, pattern: Pattern) -> bool:
        """Replace an exact or pattern rule where it stands, in its tier; True if it changed.

        A pattern prunes the rules of its tier it makes redundant, as adding one does.
        """
        if pattern.is_empty:
            return False
        with self._lock:
            self._mutable()
            old = next((e for e in self._entries if e.key == key), None)
            if old is None:
                raise AllowListError("That rule is no longer listed.")
            if old.kind is Kind.REGEX:
                raise AllowListError("A regex rule is edited in the allow list file.")
            kind = Kind.EXACT if pattern.is_literal else Kind.PATTERN
            new = Entry(kind, pattern.text, old.selective)
            if new.key == old.key:
                return False
            if any(e.key == new.key for e in self._entries):
                raise AllowListError(f"{new.value} is already listed.")
            kept = []
            for entry in self._entries:
                if entry.key == old.key:
                    kept.append(new)
                    continue
                redundant = (
                    kind is Kind.PATTERN
                    and entry.selective == old.selective
                    and (
                        (entry.kind is Kind.EXACT and pattern.matches(entry.value))
                        or (
                            entry.kind is Kind.PATTERN
                            and pattern.subsumes(Pattern.parse(entry.value))
                        )
                    )
                )
                if not redundant:
                    kept.append(entry)
            self._entries = kept
            self._save()
            return True

    def remove(self, key: str) -> bool:
        with self._lock:
            self._mutable()
            before = len(self._entries)
            self._entries = [e for e in self._entries if e.key != key]
            if len(self._entries) == before:
                return False
            self._save()
            return True
