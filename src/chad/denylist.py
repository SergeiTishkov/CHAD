"""The deny list: commands CHAD refuses without asking, in every mode but Off.

Matching ignores word order and position. A rule is a set of words, and a statement is caught
when it contains each of them: `rm -rf` is found in `rm -rf dist`, in `rm dist -rf`, in
`rm -v -rf ./out`, and in any other statement where both words occur.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from chad import atomic

SEPARATORS = re.compile(r"[\s\"'`(){};|&<>]+")

DEFAULT_RULES = (
    # Recursive, forced removal of files and folders.
    "rm -rf",
    "rm -fr",
    "rm -r -f",
    "rm --recursive --force",
    "Remove-Item -Recurse -Force",
    "del /s /q",
    "rd /s /q",
    "rmdir /s /q",
    # Git: discarding local changes, rewriting what was pushed, dropping branches.
    "git reset --hard",
    "git clean -fdx",
    "git clean -fd",
    "git push --force",
    "git push -f",
    "git branch -D",
    # Wiping or repartitioning drives.
    "Format-Volume",
    "Clear-Disk",
    "diskpart",
    "mkfs",
    # Erasing restore points, backups, logs and free space.
    "vssadmin delete shadows",
    "wbadmin delete",
    "wevtutil cl",
    "cipher /w",
    # Startup settings and registry keys.
    "bcdedit /set",
    "reg delete",
    # Script policy and antivirus.
    "Set-ExecutionPolicy Unrestricted",
    "Set-ExecutionPolicy Bypass",
    "Set-MpPreference -DisableRealtimeMonitoring",
    # User accounts, power off and reboot.
    "net user /delete",
    "Stop-Computer",
    "Restart-Computer",
    "shutdown /s",
    "shutdown /r",
)

HEADER = """\
# CHAD deny list.
#
# Used only while CHAD_DENY is on. When a statement matches an enabled rule, CHAD refuses it
# without showing it to the user, in any mode except Off, even if an allow rule covers it.
#
# Each rule is a set of words, compared without regard to case or order: the statement has to
# contain all of them. "rm -rf" therefore finds rm -rf dist, rm dist -rf and rm -v -rf ./out
# Quotes, parentheses and braces count as separators: a command inside another shell or a
# subexpression is still found, and /bin/rm, \\rm and rm.exe are all read as rm.
#
# Joined short flags form one word, so "git clean -fd" and "-fdx" are different words.
# Set enabled: false to keep a rule in the file without using it.
# Edits are picked up live. The window rewrites this file; comments below are not kept.

"""


def _words(text: str | None) -> list[str]:
    return [w for w in SEPARATORS.split((text or "").lower()) if w]


def bag_of(statement: str | None) -> frozenset[str]:
    """Every word of the statement once, and for a word with a path, its last part as well."""
    bag: set[str] = set()
    for word in _words(statement):
        bag.add(word)
        base = re.split(r"[/\\]", word)[-1]
        if base:
            bag.add(base)
        for item in (word, base):
            if item.endswith(".exe") and len(item) > 4:
                bag.add(item[:-4])
    return frozenset(bag)


@dataclass(frozen=True)
class DenyRule:
    words: str
    enabled: bool = True

    @property
    def parts(self) -> tuple[str, ...]:
        return tuple(_words(self.words))

    @property
    def is_empty(self) -> bool:
        return not self.parts

    def matches(self, bag: frozenset[str]) -> bool:
        parts = self.parts
        return bool(parts) and all(part in bag for part in parts)


def _same(left: str, right: str) -> bool:
    return left.strip().lower() == right.strip().lower()


class DenyListError(Exception):
    pass


class DenyList:
    """In-memory deny rules backed by deny-list.yaml, reloaded when the file changes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._rules: list[DenyRule] = []
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
            self._rules = [DenyRule(w) for w in DEFAULT_RULES]
            self._error = None
            self._save()
            return
        try:
            document = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
            items = document.get("denied") or [] if isinstance(document, dict) else None
            if items is None or not isinstance(items, list):
                raise ValueError("expected a mapping with a 'denied' list")
            rules = []
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("each rule must be a mapping with 'words'")
                rule = DenyRule(
                    str(item.get("words") or "").strip(), bool(item.get("enabled", True))
                )
                if not rule.is_empty and not any(_same(r.words, rule.words) for r in rules):
                    rules.append(rule)
            self._rules = rules
            self._error = None
        except (OSError, ValueError, yaml.YAMLError) as exc:
            # An unreadable file means the built-in rules; the file itself is left as it is.
            self._rules = [DenyRule(w) for w in DEFAULT_RULES]
            self._error = f"{self.path} could not be read ({exc}); using the built-in rules."
        self._stamp = self._file_stamp()

    def _refresh(self) -> None:
        if self._file_stamp() != self._stamp:
            self._load()

    def _save(self) -> None:
        body = yaml.safe_dump(
            {
                "version": 1,
                "denied": [{"words": r.words, "enabled": r.enabled} for r in self._rules],
            },
            sort_keys=False,
            allow_unicode=True,
            width=1000,
        )
        atomic.write_text(self.path, HEADER + body)
        self._stamp = self._file_stamp()

    def _mutable(self) -> None:
        self._refresh()
        if self._error:
            raise DenyListError(self._error)

    # -- queries -----------------------------------------------------------------------------

    @property
    def error(self) -> str | None:
        """Why the file on disk could not be used, if it could not."""
        with self._lock:
            self._refresh()
            return self._error

    @property
    def rules(self) -> list[DenyRule]:
        with self._lock:
            self._refresh()
            return list(self._rules)

    def match(self, statement: str) -> DenyRule | None:
        """The first enabled rule the statement trips, in list order."""
        bag = bag_of(statement)
        with self._lock:
            self._refresh()
            return next((r for r in self._rules if r.enabled and r.matches(bag)), None)

    def first_match(self, statements: Iterable[str]) -> tuple[DenyRule, str] | None:
        for statement in statements:
            rule = self.match(statement)
            if rule:
                return rule, statement
        return None

    # -- mutations ---------------------------------------------------------------------------

    def add(self, words: str) -> bool:
        rule = DenyRule(words.strip())
        with self._lock:
            self._mutable()
            if rule.is_empty or any(_same(r.words, rule.words) for r in self._rules):
                return False
            self._rules.append(rule)
            self._save()
            return True

    def remove(self, words: str) -> bool:
        with self._lock:
            self._mutable()
            before = len(self._rules)
            self._rules = [r for r in self._rules if not _same(r.words, words)]
            if len(self._rules) == before:
                return False
            self._save()
            return True

    def set_enabled(self, words: str, enabled: bool) -> bool:
        with self._lock:
            self._mutable()
            for index, rule in enumerate(self._rules):
                if _same(rule.words, words):
                    if rule.enabled == enabled:
                        return False
                    self._rules[index] = replace(rule, enabled=enabled)
                    self._save()
                    return True
            return False

    def move(self, words: str, index: int) -> bool:
        """Put a rule at a new position. When a statement matches several, the refusal names
        the earliest one."""
        with self._lock:
            self._mutable()
            source = next((i for i, r in enumerate(self._rules) if _same(r.words, words)), None)
            if source is None:
                return False
            rule = self._rules.pop(source)
            target = max(0, min(index, len(self._rules)))
            self._rules.insert(target, rule)
            if target == source:
                return False
            self._save()
            return True
