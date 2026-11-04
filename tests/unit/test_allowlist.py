from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from chad.allowlist import AllowList, AllowListError, Entry, Kind
from chad.patterns import Pattern


@pytest.fixture
def store(isolated_home: Path) -> AllowList:
    return AllowList(isolated_home / "allow-list.yaml")


def keys(store: AllowList) -> list[str]:
    return [e.key for e in store.entries]


def hand_edit(store: AllowList, text: str) -> None:
    store.path.write_text(text, encoding="utf-8")
    future = time.time() + 5
    os.utime(store.path, (future, future))


def test_missing_file_is_created_empty(store: AllowList) -> None:
    assert store.entries == []
    assert "version: 1" in store.path.read_text(encoding="utf-8")


def test_exact_is_case_sensitive_and_whole(store: AllowList) -> None:
    assert store.add_exact('git commit -m "fix it"')
    assert store.match('git commit -m "fix it"').matched_by == "exact"
    assert not store.match('git commit -m "Fix it"').allowed
    assert not store.match("git commit -m fix it").allowed
    assert not store.add_exact('git commit -m "fix it"')


def test_pattern_matches_by_words(store: AllowList) -> None:
    assert store.add_pattern(Pattern.parse("git commit -m *"))
    hit = store.match('git commit -m "a b c"')
    assert hit.allowed and hit.matched_by == "pattern: git commit -m *"
    assert not store.match("git commit --amend").allowed


def test_literal_pattern_is_stored_as_exact(store: AllowList) -> None:
    assert store.add_pattern(Pattern.parse("npm test"))
    assert store.entries == [Entry(Kind.EXACT, "npm test")]


def test_regex_is_searched_and_invalid_regex_never_matches(store: AllowList) -> None:
    hand_edit(
        store,
        "allowed:\n"
        "  - {kind: regex, value: '^npm (test|run lint)$'}\n"
        "  - {kind: regex, value: '([unclosed'}\n",
    )
    assert store.match("npm run lint").matched_by == "regex: ^npm (test|run lint)$"
    assert not store.match("npm run build").allowed
    assert len(store.entries) == 2


def test_selective_only_consults_selective_rows(store: AllowList) -> None:
    store.add_exact("git status")
    store.add_exact("git log", selective=True)
    assert not store.match("git status", selective_only=True).allowed
    hit = store.match("git log", selective_only=True)
    assert hit.allowed and hit.selective


def test_selective_rows_come_first(store: AllowList) -> None:
    store.add_exact("a")
    store.add_exact("b", selective=True)
    store.add_exact("c")
    store.add_exact("d", selective=True)
    assert keys(store) == ["exact:b", "exact:d", "exact:a", "exact:c"]


def test_adding_a_pattern_prunes_its_own_tier(store: AllowList) -> None:
    store.add_exact("git commit -m one")
    store.add_pattern(Pattern.parse("git commit -m *"))
    store.add_exact("git commit -m two", selective=True)
    store.add_exact("git status")
    store.add_pattern(Pattern.parse("git commit *"))
    assert keys(store) == ["exact:git commit -m two", "exact:git status", "pattern:git commit *"]


def test_ordinary_pattern_never_removes_a_selective_row(store: AllowList) -> None:
    store.add_pattern(Pattern.parse("git log *"), selective=True)
    assert store.add_pattern(Pattern.parse("git *"))
    assert keys(store) == ["pattern:git log *", "pattern:git *"]


def test_covered_pattern_is_skipped_unless_it_raises_the_tier(store: AllowList) -> None:
    store.add_pattern(Pattern.parse("git *"))
    assert not store.add_pattern(Pattern.parse("git log *"))
    assert store.add_pattern(Pattern.parse("git log *"), selective=True)
    store.add_pattern(Pattern.parse("npm *"), selective=True)
    assert not store.add_pattern(Pattern.parse("npm run *"))
    assert not store.add_pattern(Pattern.parse("npm run *"), selective=True)


def test_regex_is_never_pruned(store: AllowList) -> None:
    hand_edit(store, "allowed:\n  - {kind: regex, value: '^git log'}\n")
    store.add_pattern(Pattern.parse("git *"))
    assert keys(store) == ["regex:^git log", "pattern:git *"]


def test_re_adding_as_selective_promotes(store: AllowList) -> None:
    store.add_exact("a")
    store.add_exact("b")
    assert store.add_exact("b", selective=True)
    assert store.entries[0] == Entry(Kind.EXACT, "b", True)
    assert not store.add_exact("b")


def test_set_selective_lands_on_the_boundary(store: AllowList) -> None:
    for name in "abc":
        store.add_exact(name)
    store.add_exact("s", selective=True)
    assert store.set_selective("exact:c", True)
    assert keys(store) == ["exact:s", "exact:c", "exact:a", "exact:b"]
    assert store.set_selective("exact:s", False)
    assert keys(store) == ["exact:c", "exact:s", "exact:a", "exact:b"]
    assert not store.set_selective("exact:s", False)
    assert not store.set_selective("exact:missing", True)


def test_move_is_clamped_within_the_tier(store: AllowList) -> None:
    store.add_exact("s1", selective=True)
    store.add_exact("s2", selective=True)
    store.add_exact("a")
    store.add_exact("b")
    assert store.move("exact:b", 0)
    assert keys(store) == ["exact:s1", "exact:s2", "exact:b", "exact:a"]
    assert store.move("exact:s1", 99)
    assert keys(store) == ["exact:s2", "exact:s1", "exact:b", "exact:a"]
    assert not store.move("exact:a", 99)


def test_edit_replaces_the_rule_where_it_stands(store: AllowList) -> None:
    store.add_exact("s", selective=True)
    store.add_exact("git log -5")
    store.add_exact("npm test")
    assert store.edit("exact:git log -5", Pattern.parse("git log *"))
    assert keys(store) == ["exact:s", "pattern:git log *", "exact:npm test"]
    assert store.edit("pattern:git log *", Pattern.parse("git log --oneline"))
    assert keys(store) == ["exact:s", "exact:git log --oneline", "exact:npm test"]
    assert store.edit("exact:s", Pattern.parse("git status"))
    assert store.entries[0] == Entry(Kind.EXACT, "git status", True)
    assert not store.edit("exact:npm test", Pattern.parse("npm  test"))


def test_an_edited_pattern_prunes_its_own_tier(store: AllowList) -> None:
    store.add_exact("npm run build", selective=True)
    store.add_exact("npm run lint")
    store.add_exact("npm test")
    store.add_exact("npm run build")
    assert store.edit("exact:npm test", Pattern.parse("npm run *"))
    assert keys(store) == ["exact:npm run build", "pattern:npm run *"]
    assert store.entries[0].selective


def test_edit_refuses_a_duplicate_a_regex_and_a_missing_rule(store: AllowList) -> None:
    hand_edit(store, "allowed:\n  - {kind: regex, value: '^ls'}\n  - {kind: exact, value: a}\n")
    store.add_exact("b")
    with pytest.raises(AllowListError, match="already listed"):
        store.edit("exact:b", Pattern.parse("a"))
    with pytest.raises(AllowListError, match="regex"):
        store.edit("regex:^ls", Pattern.parse("ls"))
    with pytest.raises(AllowListError, match="no longer listed"):
        store.edit("exact:gone", Pattern.parse("c"))
    assert keys(store) == ["regex:^ls", "exact:a", "exact:b"]


def test_remove(store: AllowList) -> None:
    store.add_exact("a")
    assert store.remove("exact:a")
    assert not store.remove("exact:a")
    assert not store.match("a").allowed


def test_changes_survive_a_reload(store: AllowList) -> None:
    store.add_pattern(Pattern.parse("git log *"), selective=True)
    store.add_exact("npm test")
    again = AllowList(store.path)
    assert again.entries == store.entries


def test_hand_edits_are_ordered_and_deduplicated(store: AllowList) -> None:
    hand_edit(
        store,
        "allowed:\n"
        "  - {kind: exact, value: a}\n"
        "  - {kind: pattern, value: 'git  *  *', selective: true}\n"
        "  - {kind: exact, value: a}\n"
        "  - {kind: exact, value: ''}\n",
    )
    assert keys(store) == ["pattern:git *", "exact:a"]


def test_malformed_file_allows_nothing_and_is_not_overwritten(store: AllowList) -> None:
    store.add_exact("git status")
    hand_edit(store, "allowed: [unclosed\n")
    assert not store.match("git status").allowed
    assert store.error and "allow-list.yaml" in store.error
    with pytest.raises(AllowListError):
        store.add_exact("x")
    assert store.path.read_text(encoding="utf-8") == "allowed: [unclosed\n"


def test_unknown_kind_makes_the_file_malformed(store: AllowList) -> None:
    hand_edit(store, "allowed:\n  - {kind: exact, value: a}\n  - {kind: regx, value: b}\n")
    assert not store.match("a").allowed
    assert store.error and "regx" in store.error


def test_fixing_the_file_clears_the_error(store: AllowList) -> None:
    hand_edit(store, "allowed: 7\n")
    assert store.error
    hand_edit(store, "allowed:\n  - {kind: exact, value: ok}\n")
    assert store.match("ok").allowed
    assert store.error is None
