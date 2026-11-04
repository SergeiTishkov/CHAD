"""Selective mode that refuses the rest, the rule list in its refusal, and the two lookups the
agent can send: #chad:find-rules and #chad:check. Everything runs in process with a FakeShell;
tests/integration runs the same paths through real processes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from test_policy import audit_decisions, decision, engine, executed, payload, reason, run

from chad import messages, paths, switches
from chad.config import Config
from chad.patterns import Pattern
from chad.policy import ADD_SELECTIVE_MARKER, Engine
from chad.switches import Mode

__all__ = ["engine"]  # the fixture, shared with test_policy


def strict(listing: bool = False) -> None:
    switches.set_mode(Mode.SELECTIVE)
    switches.set_selective_refuse(True)
    switches.set_selective_list(listing)


def selective(engine: Engine, *rules: str) -> None:
    for rule in rules:
        engine.allow.add_pattern(Pattern.parse(rule), selective=True)


def answer(engine: Engine, command: str, **kwargs: Any) -> str:
    """The reason of a call CHAD refused or answered without running anything."""
    output = asyncio.run(engine.hook(payload(command, **kwargs)))
    assert decision(output) == "deny", output
    return reason(output)


# -- the refusal -------------------------------------------------------------------------------


def test_an_uncovered_command_is_refused_not_handed_back(engine: Engine, shell: Any) -> None:
    strict()
    selective(engine, "git status")
    text = answer(engine, "git push")
    assert text.startswith("[CHAD] Refused: no Selective rule covers this command. It did not run.")
    assert "Not covered: git push (no Selective rule matches it)" in text
    assert "Do not send this command again as it is" in text
    assert shell.calls == []
    assert audit_decisions() == ["refusedOutsideSelective"]


def test_a_refused_command_is_not_captured_for_add_selective(engine: Engine) -> None:
    strict()
    answer(engine, "npm run build")
    assert "no recent command" in answer(engine, ADD_SELECTIVE_MARKER)


def test_a_covered_command_still_runs(engine: Engine, shell: Any) -> None:
    strict(listing=True)
    selective(engine, "git log *")

    async def scenario() -> None:
        executed(await engine.hook(payload("git log -5")))

    run(scenario)
    assert shell.commands == ["git log -5"]
    assert audit_decisions() == ["allowedBySelectiveRule"]


def test_an_ordinary_rule_does_not_count(engine: Engine, shell: Any) -> None:
    strict()
    engine.allow.add_exact("git status")
    assert "Not covered: git status" in answer(engine, "git status")
    assert shell.calls == []


def test_each_uncovered_statement_is_named_with_its_reason(engine: Engine) -> None:
    strict()
    selective(engine, "git status", "echo *")
    text = answer(engine, "git status && echo $(whoami) && make all")
    assert "Not covered: git status" not in text
    assert (
        "Not covered: echo $(whoami) (it contains command substitution, which no rule can allow)"
        in text
    )
    assert "Not covered: make all (no Selective rule matches it)" in text


def test_without_listing_the_rules_stay_hidden(engine: Engine) -> None:
    strict(listing=False)
    selective(engine, "git status", "git log *")
    text = answer(engine, "git push")
    assert "CHAD does not show its rules here" in text
    assert "git log *" not in text and "#chad:find-rules" not in text


def test_listing_shows_the_selective_rules_for_the_same_program(engine: Engine) -> None:
    strict(listing=True)
    selective(engine, "git status", "git log *", "npm test")
    engine.allow.add_exact("git push")  # an ordinary rule: not the agent's to use here
    engine.allow.add_pattern(Pattern.parse("gitk *"), selective=True)
    text = answer(engine, "git push --force")
    assert "Selective rules for `git` (2):\n  git status\n  git log *\n" in text
    assert "npm test" not in text and "gitk" not in text
    assert messages.RULE_READING in text and messages.LOOKUP_HINT in text


def test_the_list_is_for_the_first_uncovered_statement(engine: Engine) -> None:
    strict(listing=True)
    selective(engine, "git status", "npm test")
    text = answer(engine, "git status && npm run build")
    assert "Selective rules for `npm` (1):\n  npm test\n" in text


def test_a_long_list_is_cut_to_twenty(engine: Engine) -> None:
    strict(listing=True)
    selective(engine, *(f"git command{i}" for i in range(25)))
    text = answer(engine, "git push")
    assert "Selective rules for `git` (20 of 25):" in text
    assert "git command19" in text and "git command20" not in text


def test_a_regex_naming_the_program_is_listed(engine: Engine) -> None:
    strict(listing=True)
    # Regex rules are written in the file by hand; the list picks the edit up live.
    engine.allow.path.write_text(
        "version: 1\nallowed:\n"
        "  - {kind: regex, value: '^git (fetch|pull)$', selective: true}\n"
        "  - {kind: regex, value: '^npm ci$', selective: true}\n",
        encoding="utf-8",
    )
    text = answer(engine, "git push")
    assert "Selective rules for `git` (1):\n  regex: ^git (fetch|pull)$\n" in text


def test_no_rule_for_the_program_says_so(engine: Engine) -> None:
    strict(listing=True)
    selective(engine, "git status")
    text = answer(engine, "FOO=1 cargo build")
    assert "No Selective rule is for `cargo`." in text
    assert messages.LOOKUP_HINT in text


def test_the_deny_list_comes_first(engine: Engine) -> None:
    strict(listing=True)
    switches.set_deny(True)
    text = answer(engine, "git reset --hard")
    assert "on the deny list" in text and "no Selective rule" not in text


def test_the_switches_change_nothing_outside_selective(engine: Engine, shell: Any) -> None:
    switches.set_selective_refuse(True)
    switches.set_selective_list(True)
    switches.set_mode(Mode.ALLOW_ALL)

    async def scenario() -> None:
        executed(await engine.hook(payload("git push")))
        switches.set_mode(Mode.OFF)
        assert await engine.hook(payload("git push")) == {}

    run(scenario)
    assert shell.commands == ["git push"]


def test_with_refuse_off_the_rest_goes_to_the_harness(engine: Engine) -> None:
    switches.set_mode(Mode.SELECTIVE)
    switches.set_selective_list(True)  # alone it changes nothing

    async def scenario() -> None:
        assert await engine.hook(payload("git push")) == {}

    run(scenario)
    assert audit_decisions() == ["handedToHarness"]


# -- #chad:find-rules --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "setup",
    [
        lambda: switches.set_mode(Mode.CHAD),
        lambda: switches.set_mode(Mode.OFF),
        lambda: switches.set_mode(Mode.SELECTIVE),
        lambda: (switches.set_mode(Mode.SELECTIVE), switches.set_selective_refuse(True)),
        lambda: (switches.set_mode(Mode.SELECTIVE), switches.set_selective_list(True)),
    ],
)
def test_lookups_answer_only_while_selective_refuses_and_lists(
    engine: Engine, shell: Any, setup: Any
) -> None:
    setup()
    for command in ("#chad:find-rules git", "#chad:check git status"):
        text = answer(engine, command)
        assert text.startswith("[CHAD] CHAD ERROR. The command did not run.")
        assert messages.LOOKUP_OFF in text
    assert shell.calls == []


def test_find_rules_ranks_rules_with_more_words_first(engine: Engine) -> None:
    strict(listing=True)
    selective(engine, "npm run push", "git status", "git push", "git push origin *")
    engine.allow.add_exact("git push --force")  # ordinary: never listed
    text = answer(engine, "#chad:find-rules GIT push")
    assert text.startswith("[CHAD] SELECTIVE RULES. This was a request to CHAD; nothing ran.")
    assert "Search: GIT push\nRules 1-4 of 4:\n" in text
    listed = [line.strip() for line in text.splitlines() if line.startswith("  ")]
    assert listed == ["git push", "git push origin *", "npm run push", "git status"]
    assert "More rules match" not in text
    assert audit_decisions() == ["rulesLookup"]


def test_find_rules_without_words_lists_every_selective_rule(engine: Engine) -> None:
    strict(listing=True)
    selective(engine, "git status", "npm test")
    text = answer(engine, "#chad:find-rules")
    assert "Search: every Selective rule\nRules 1-2 of 2:\n  git status\n  npm test" in text


def test_find_rules_pages(isolated_home: Path, shell: Any) -> None:
    paths.ensure_root()
    engine = Engine(Config(find_rules_page_size=3), opener=lambda _: None, execute=shell)
    strict(listing=True)
    selective(engine, *(f"git sub{i}" for i in range(7)))
    first = answer(engine, "#chad:find-rules git")
    assert "Rules 1-3 of 7:\n  git sub0\n  git sub1\n  git sub2\n" in first
    assert "A narrower search is the better next step" in first
    assert "`#chad:find-rules --page 2 git`" in first
    last = answer(engine, "#chad:find-rules --page 3 git")
    assert "Rules 7-7 of 7:\n  git sub6\n" in last and "More rules match" not in last
    past = answer(engine, "#chad:find-rules --PAGE 4 git")
    assert "Page 4 is past the end: 7 rules match, on 3 page(s)." in past


def test_find_rules_with_no_match(engine: Engine) -> None:
    strict(listing=True)
    selective(engine, "git status")
    assert "No Selective rule contains any of these words" in answer(
        engine, "#chad:find-rules cargo"
    )


@pytest.mark.parametrize(
    ("command", "problem"),
    [
        ("#chad:find-rules --page", "--page takes a page number from 1"),
        ("#chad:find-rules --page 0 git", "--page takes a page number from 1"),
        ("#chad:find-rules --page two git", "--page takes a page number from 1"),
        ("#chad:find-rules git\nrm -rf x", "on the same line as #chad:find-rules"),
    ],
)
def test_find_rules_that_cannot_be_read(engine: Engine, command: str, problem: str) -> None:
    strict(listing=True)
    text = answer(engine, command)
    assert text.startswith("[CHAD] CHAD ERROR.") and problem in text


def test_a_marker_counts_only_at_the_start_of_the_command(engine: Engine, shell: Any) -> None:
    strict(listing=True)
    selective(engine, "echo *")

    async def scenario() -> None:
        executed(await engine.hook(payload("echo hi #chad:find-rules git")))
        # Glued to other text it is a plain comment, which is an empty command.
        assert await engine.hook(payload("#chad:find-rulesgit")) == {}

    run(scenario)
    assert "SELECTIVE RULES" in answer(engine, "  #CHAD:Find-Rules\tgit  ")


# -- #chad:check -------------------------------------------------------------------------------


def test_check_says_a_covered_command_would_run(engine: Engine, shell: Any) -> None:
    strict(listing=True)
    selective(engine, "git status", "git log *")
    text = answer(engine, "#chad:check git status && git log -5")
    assert text.startswith("[CHAD] CHECK: WOULD RUN. This was a request to CHAD; nothing ran.")
    assert "Command: git status && git log -5" in text
    assert "- git status: covered by exact: git status" in text
    assert "- git log -5: covered by pattern: git log *" in text
    assert "send the command itself, without #chad:check" in text
    assert shell.calls == []
    assert audit_decisions() == ["rulesLookup"]


def test_check_names_what_would_be_refused(engine: Engine, shell: Any) -> None:
    strict(listing=True)
    switches.set_deny(True)
    selective(engine, "git *", "echo *")
    text = answer(engine, "#chad:check git push && echo $(whoami) && make && git reset --hard")
    assert text.startswith("[CHAD] CHECK: WOULD BE REFUSED.")
    assert "- git push: covered by pattern: git *" in text
    assert "- echo $(whoami): contains command substitution, which no rule can allow" in text
    assert "- make: no Selective rule matches it" in text
    assert "- git reset --hard: on the deny list (rule: git reset --hard)" in text
    assert messages.RULE_READING in text
    assert shell.calls == []


def test_check_reads_the_command_as_the_calling_tool(engine: Engine) -> None:
    strict(listing=True)
    selective(engine, "Get-ChildItem *")
    assert "WOULD RUN" in answer(engine, "#chad:check Get-ChildItem src", tool="PowerShell")
    # `$(...)` in PowerShell is a subexpression: never allowed by a rule.
    text = answer(engine, "#chad:check Get-ChildItem $(pwd)", tool="PowerShell")
    assert "WOULD BE REFUSED" in text and "subexpression" in text


@pytest.mark.parametrize(
    ("command", "problem"),
    [
        ("#chad:check", "Put the command to check after #chad:check"),
        ("#chad:check   ", "Put the command to check after #chad:check"),
        ("#chad:check # only a comment", "Put the command to check after #chad:check"),
        ("#chad:check git status\nrm -rf x", "on the same line as #chad:check"),
    ],
)
def test_check_without_a_command_on_its_line(
    engine: Engine, shell: Any, command: str, problem: str
) -> None:
    strict(listing=True)
    text = answer(engine, command)
    assert text.startswith("[CHAD] CHAD ERROR.") and problem in text
    assert shell.calls == []


# -- the window --------------------------------------------------------------------------------


def test_the_window_sees_and_sets_both_switches(engine: Engine) -> None:
    state = engine.state()
    assert state["selectiveRefuse"] is False and state["selectiveList"] is False
    state = engine.ui({"action": "setSelectiveRefuse", "value": True})["state"]
    assert state["selectiveRefuse"] is True and switches.selective_refuses()
    state = engine.ui({"action": "setSelectiveList", "value": True})["state"]
    assert state["selectiveList"] is True and switches.selective_lists()
    state = engine.ui({"action": "setSelectiveRefuse", "value": False})["state"]
    assert state["selectiveRefuse"] is False
    assert state["selectiveList"] is True  # kept for the next time refusing is on


def test_the_selective_description_says_what_happens_to_the_rest(engine: Engine) -> None:
    def selective_line() -> str:
        modes = engine.state()["modes"]
        return next(m["description"] for m in modes if m["id"] == "selective")

    assert "the rest go to the harness's own approval" in selective_line()
    switches.set_selective_refuse(True)
    assert selective_line() == switches.SELECTIVE_REFUSING
    assert [m["id"] for m in engine.state()["modes"]] == ["chad", "allowAll", "selective", "off"]
