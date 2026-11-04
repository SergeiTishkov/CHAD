"""Commands waiting for the user, and the rules the user builds while deciding.

The queue holds pending items and their futures; deciding what an answer means (which rules get
written, what the model is told) belongs to the policy engine, so it can re-check everything at
the moment of the decision.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from chad.analysis import Dialect, Statement, words
from chad.patterns import WILDCARD, Pattern


class Purpose(StrEnum):
    APPROVE = "approve"
    ADD_SELECTIVE = "addSelective"


class Choice(StrEnum):
    ALLOW_ONCE = "allowOnce"
    ALLOW_FOREVER = "allowForever"
    ALLOW_SELECTIVE = "allowSelective"
    DENY = "deny"


class WordMode(StrEnum):
    KEEP = "keep"
    WILD = "wild"
    DROP = "drop"


class SelectionError(ValueError):
    pass


@dataclass(frozen=True)
class StatementInfo:
    text: str
    normalized: str
    words: tuple[str, ...]
    blocking: tuple[str, ...]
    allowed_by: str | None

    @staticmethod
    def of(statement: Statement, dialect: Dialect, allowed_by: str | None) -> StatementInfo:
        return StatementInfo(
            statement.text,
            statement.normalized,
            tuple(words(statement.normalized, dialect)),
            statement.blocking,
            allowed_by,
        )

    @property
    def storable(self) -> bool:
        """A rule is written only for a statement that needs one and that a rule can allow."""
        return self.allowed_by is None and not self.blocking and bool(self.words)

    def to_ui(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "normalized": self.normalized,
            "words": list(self.words),
            "blocking": list(self.blocking),
            "allowedBy": self.allowed_by,
            "storable": self.storable,
        }


@dataclass(frozen=True)
class Selection:
    modes: tuple[WordMode, ...]
    once: bool = False


@dataclass(frozen=True)
class RuleToStore:
    """Either `exact` (the statement as it stands) or `pattern` is set."""

    statement: StatementInfo
    exact: str | None = None
    pattern: Pattern | None = None

    @property
    def text(self) -> str:
        return self.exact if self.exact is not None else str(self.pattern)


def build_rule(statement: StatementInfo, selection: Selection) -> RuleToStore:
    if len(selection.modes) != len(statement.words):
        raise SelectionError(f"expected {len(statement.words)} word choices for {statement.text!r}")
    if all(mode is WordMode.KEEP for mode in selection.modes):
        # Kept as typed, quotes and all: rebuilding it from words would lose them.
        return RuleToStore(statement, exact=statement.normalized)
    terms = [
        WILDCARD if mode is WordMode.WILD else word
        for word, mode in zip(statement.words, selection.modes, strict=True)
        if mode is not WordMode.DROP
    ]
    pattern = Pattern.of(terms)
    if pattern.is_empty or not pattern.matches_words(statement.words):
        raise SelectionError(
            f"the rule {pattern.text or '(empty)'!r} would not allow its own statement "
            f"{statement.text!r}"
        )
    if pattern.is_literal:
        return RuleToStore(statement, exact=statement.normalized)
    return RuleToStore(statement, pattern=pattern)


def parse_selections(raw: Any, statements: Sequence[StatementInfo]) -> list[Selection]:
    """Selections from the UI, one per statement; missing ones keep every word."""
    chosen: list[Selection] = [Selection(tuple(WordMode.KEEP for _ in s.words)) for s in statements]
    if raw is None:
        return chosen
    if not isinstance(raw, list):
        raise SelectionError("selections must be a list")
    for item in raw:
        if not isinstance(item, dict):
            raise SelectionError("each selection must be an object")
        index = item.get("index")
        if not isinstance(index, int) or not 0 <= index < len(statements):
            raise SelectionError(f"no statement number {index!r}")
        modes = item.get("modes")
        if modes is None:
            modes = [WordMode.KEEP] * len(statements[index].words)
        try:
            parsed = tuple(WordMode(str(m)) for m in modes)
        except ValueError as exc:
            raise SelectionError(str(exc)) from None
        chosen[index] = Selection(parsed, bool(item.get("once", False)))
    return chosen


def rules_to_store(
    statements: Sequence[StatementInfo], selections: Sequence[Selection]
) -> list[RuleToStore]:
    """The rules a forever/selective decision writes: storable statements not ticked 'once'."""
    return [
        build_rule(statement, selection)
        for statement, selection in zip(statements, selections, strict=True)
        if statement.storable and not selection.once
    ]


_ids = itertools.count(1)


@dataclass
class PendingItem:
    command: str
    tool: str
    dialect: Dialect
    description: str
    cwd: str
    session_id: str
    permission_mode: str
    purpose: Purpose
    statements: tuple[StatementInfo, ...]
    deadline: float
    # For addSelective: the captured call to replay, and the tool the marker came through.
    tool_input: dict[str, Any] = field(default_factory=dict)
    via_tool: str = ""
    id: str = field(default_factory=lambda: str(next(_ids)))
    future: asyncio.Future[dict[str, Any]] = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )
    budget_deadline: float = field(default=0.0, repr=False)
    # The environment of the hook that made the call; never shown in the window.
    environment: dict[str, str] | None = field(default=None, repr=False)

    def to_ui(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "command": self.command,
            "tool": self.tool,
            "description": self.description,
            "cwd": self.cwd,
            "sessionId": self.session_id,
            "permissionMode": self.permission_mode,
            "purpose": str(self.purpose),
            "deadline": int(self.deadline * 1000),
            "statements": [s.to_ui() for s in self.statements],
        }


class ApprovalQueue:
    """FIFO. A new item joins the back, so the window never switches under the user's hands."""

    def __init__(self, on_change: Callable[[], None] = lambda: None) -> None:
        self._items: dict[str, PendingItem] = {}
        self._on_change = on_change

    def __len__(self) -> int:
        return len(self._items)

    @property
    def items(self) -> list[PendingItem]:
        return list(self._items.values())

    def add(self, item: PendingItem) -> PendingItem:
        self._items[item.id] = item
        self._on_change()
        return item

    def get(self, item_id: str) -> PendingItem | None:
        return self._items.get(str(item_id))

    def take(self, item_id: str) -> PendingItem | None:
        """Remove a decided item from the visible queue while its command is running."""
        item = self._items.pop(str(item_id), None)
        if item is not None:
            self._on_change()
        return item

    @staticmethod
    def complete(item: PendingItem, output: dict[str, Any]) -> bool:
        """Finish a claimed item's hook future once its execution result is ready."""
        if item.future.done():
            return False
        item.future.set_result(output)
        return True

    def resolve(self, item_id: str, output: dict[str, Any]) -> bool:
        item = self.take(item_id)
        if item is None:
            return False
        return self.complete(item, output)

    def drain(self, output: Callable[[PendingItem], dict[str, Any]]) -> list[PendingItem]:
        drained = self.items
        for item in drained:
            self.resolve(item.id, output(item))
        return drained
