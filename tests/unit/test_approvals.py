from __future__ import annotations

import asyncio

import pytest

from chad.analysis import analyze
from chad.approvals import (
    ApprovalQueue,
    PendingItem,
    Purpose,
    Selection,
    SelectionError,
    StatementInfo,
    WordMode,
    build_rule,
    parse_selections,
    rules_to_store,
)

K, W, D = WordMode.KEEP, WordMode.WILD, WordMode.DROP


def info(command: str, allowed_by: str | None = None) -> StatementInfo:
    (statement,) = analyze(command).statements
    return StatementInfo.of(statement, "bash", allowed_by)


def test_statement_info() -> None:
    s = info('git commit -m "fix it"')
    assert s.words == ("git", "commit", "-m", '"fix it"')
    assert s.storable
    assert not info("git status", "exact").storable
    assert not info("echo $(date)").storable
    assert s.to_ui()["storable"] is True


def test_all_kept_is_the_exact_statement_with_its_quotes() -> None:
    rule = build_rule(info('git commit -m "fix it"'), Selection((K, K, K, K)))
    assert rule.exact == 'git commit -m "fix it"'
    assert rule.pattern is None


def test_wild_words_make_a_pattern() -> None:
    rule = build_rule(info('git commit -m "fix it"'), Selection((K, K, K, W)))
    assert rule.text == "git commit -m *"


def test_dropping_a_word_that_breaks_coverage_is_refused() -> None:
    with pytest.raises(SelectionError, match="would not allow its own statement"):
        build_rule(info("git commit -m x"), Selection((K, K, D, K)))
    with pytest.raises(SelectionError):
        build_rule(info("git status"), Selection((D, D)))


def test_dropping_a_word_next_to_a_wildcard_still_covers() -> None:
    rule = build_rule(info("git log -5 --oneline"), Selection((K, W, D, K)))
    assert rule.text == "git * --oneline"


def test_word_count_must_match() -> None:
    with pytest.raises(SelectionError, match="expected 2"):
        build_rule(info("git status"), Selection((K,)))


def test_parse_selections_defaults_to_keep_everything() -> None:
    statements = [info("git status"), info("npm test")]
    chosen = parse_selections([{"index": 1, "modes": ["keep", "wild"], "once": True}], statements)
    assert chosen[0] == Selection((K, K))
    assert chosen[1] == Selection((K, W), once=True)
    assert parse_selections(None, statements)[1] == Selection((K, K))


@pytest.mark.parametrize(
    "raw",
    [{"index": 0}, [1], [{"index": 5}], [{"index": "0"}], [{"index": 0, "modes": ["sometimes"]}]],
)
def test_parse_selections_rejects_garbage(raw: object) -> None:
    with pytest.raises(SelectionError):
        parse_selections(raw, [info("git status")])


def test_rules_to_store_skips_allowed_blocking_and_once() -> None:
    statements = [info("a x"), info("b", "exact"), info("echo $(c)"), info("d y")]
    selections = [
        Selection((K, W)),
        Selection((K,)),
        Selection((K, K)),
        Selection((K, K), once=True),
    ]
    assert [r.text for r in rules_to_store(statements, selections)] == ["a *"]


def item(command: str = "ls") -> PendingItem:
    return PendingItem(
        command=command,
        tool="Bash",
        dialect="bash",
        description="list",
        cwd="C:/x",
        session_id="s",
        permission_mode="default",
        purpose=Purpose.APPROVE,
        statements=(info(command),),
        deadline=1_000.5,
    )


def test_queue_is_fifo_and_resolves_futures() -> None:
    async def scenario() -> None:
        changes: list[int] = []
        queue = ApprovalQueue(lambda: changes.append(len(queue)))
        first, second = queue.add(item("a")), queue.add(item("b"))
        assert [i.command for i in queue.items] == ["a", "b"]
        assert queue.resolve(second.id, {"x": 1})
        assert await second.future == {"x": 1}
        assert not queue.resolve(second.id, {"x": 2})
        drained = queue.drain(lambda i: {"bye": i.command})
        assert [i.command for i in drained] == ["a"]
        assert await first.future == {"bye": "a"}
        assert changes == [1, 2, 1, 0]

    asyncio.run(scenario())


def test_item_to_ui() -> None:
    async def scenario() -> None:
        ui = item("git status").to_ui()
        assert ui["deadline"] == 1_000_500
        assert ui["purpose"] == "approve"
        assert ui["statements"][0]["words"] == ["git", "status"]

    asyncio.run(scenario())
