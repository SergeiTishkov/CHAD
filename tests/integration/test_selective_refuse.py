"""Selective mode that refuses the rest, and the rule lookups, through the real hook client and
dispatcher processes."""

from __future__ import annotations

from chad import messages, paths, switches
from chad.allowlist import AllowList
from chad.patterns import Pattern
from chad.switches import Mode

from .harness import audit_decisions, decision, executed, payload, reason, run_hook, state, ui


def refusing(listing: bool) -> None:
    switches.set_mode(Mode.SELECTIVE)
    switches.set_selective_refuse(True)
    switches.set_selective_list(listing)
    allow = AllowList(paths.allow_list_file())
    allow.add_pattern(Pattern.parse("echo *"), selective=True)
    allow.add_exact("git status", selective=True)
    allow.add_exact("git push")  # ordinary: Selective mode does not use it


def refused(output: dict) -> str:
    assert decision(output) == "deny", output
    text = reason(output)
    assert text.startswith("[CHAD] Refused: no Selective rule covers this command."), text
    return text


def test_covered_commands_run_and_the_rest_is_refused_with_the_rules() -> None:
    refusing(listing=True)
    assert "--- stdout ---\nfrom chad\n" in executed(run_hook(payload("echo from chad")))
    text = refused(run_hook(payload("git push origin main")))
    assert "Not covered: git push origin main (no Selective rule matches it)" in text
    assert "Selective rules for `git` (1):\n  git status\n" in text
    assert messages.LOOKUP_HINT in text
    assert audit_decisions() == ["allowedBySelectiveRule", "refusedOutsideSelective"]


def test_find_rules_and_check_through_the_hook() -> None:
    refusing(listing=True)
    found = reason(run_hook(payload("#chad:find-rules git")))
    assert found.startswith("[CHAD] SELECTIVE RULES.")
    assert "Rules 1-1 of 1:\n  git status\n" in found and "git push" not in found
    checked = reason(run_hook(payload("#chad:check echo hi && git push", tool="PowerShell")))
    assert checked.startswith("[CHAD] CHECK: WOULD BE REFUSED.")
    assert "- echo hi: covered by pattern: echo *" in checked
    assert "- git push: no Selective rule matches it" in checked
    assert "WOULD RUN" in reason(run_hook(payload("#chad:check git status")))
    assert audit_decisions() == ["rulesLookup", "rulesLookup", "rulesLookup"]


def test_the_window_switches_reach_the_next_call() -> None:
    refusing(listing=True)
    run_hook(payload("echo warm up"))  # starts the dispatcher
    assert ui("setSelectiveList", value=False)["state"]["selectiveList"] is False
    text = refused(run_hook(payload("git push")))
    assert "CHAD does not show its rules here" in text and "git status" not in text
    assert "is not the case now" in reason(run_hook(payload("#chad:find-rules git")))
    assert ui("setSelectiveRefuse", value=False)["state"]["selectiveRefuse"] is False
    assert run_hook(payload("git push")) == {}
    assert state()["selectiveRefuse"] is False


def test_a_lookup_in_off_mode_is_answered_not_handed_back() -> None:
    switches.set_mode(Mode.OFF)
    output = run_hook(payload("#chad:check git status"))
    assert decision(output) == "deny"
    assert messages.LOOKUP_OFF in reason(output)
