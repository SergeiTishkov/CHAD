# 0039 CHAD never answers allow: only deny or skip

Source: the owner, 2026-11-02
Scope: rules, engine, docs, skills

## Business
The owner, 2026-11-02, a requirement of the project: CHAD never approves a command. It has two
possible answers and no third:
- **deny**: the command is forbidden (the reason says why), or CHAD ran it itself and the
  reason carries its output. Also when CHAD is meant to work but fails: the reason gives the
  cause, so the agent can tell the user that CHAD is broken and needs fixing.
- **skip** (no decision, `{}`): CHAD hands the call back and the harness decides with its own
  permission flow. This is the answer when CHAD is switched off (Off mode) and, in Selective
  mode, for a command no Selective rule covers. The code also skips a tool other than Bash or
  PowerShell and an empty command (no statements).

Why, in the owner's words: this is Cross Harness Allow/Deny, and the point of the project is to
give many different agent harnesses one behaviour by the simplest, plainest means. Every harness
with a pre-command hook can refuse a call with a text for the model, or leave the call alone.
What an `allow` leads to differs between harnesses: their own permission rules, prompts and
protected paths.

Since 0019 no path in `chad.policy.Engine` answers `allow`. What still contradicts the rule:
`messages.allow` is still defined (only a test uses it), and nothing stops a later change from
answering `allow` again. SPEC §3.2 listed `allow` with `updatedInput` among CHAD's answers (fixed
before this task). Task 0024 had proposed `allow` for background calls.

What departs from the deny/skip split today: when the hook client fails (the dispatcher does not
start or does not answer, a payload it cannot read, its own exception), it skips (fail-open).
That is CHAD failing, not CHAD switched off, so it becomes deny with the cause.

## Implementation
The rule at the top of `CLAUDE.md` and in SPEC §1 and §3.2. A test that walks every decision
path of the engine (modes, rules, approvals, control requests, add-selective, errors) and fails
on any answer other than deny or skip, and on a skip outside the skip cases above;
`messages.allow` removed, so there is nothing to call.

Fail-closed hook client: on any failure it answers `deny` with the cause and says CHAD is broken
and needs fixing. It must still write valid JSON when everything else fails. SPEC §3.2 and §6.4
(giving up on the dispatcher) and README ("Falls back to Claude Code") change with it.

## Items
- DONE - The rule at the top of CLAUDE.md: deny or skip, never allow
- DONE - SPEC §1 states it; §3.2 no longer lists allow among CHAD's answers
- DONE - The owner's answer on skip (Off mode, uncovered Selective) and on failures, written here
- DONE - Remove messages.allow and its test
- DONE - A test over every decision path: only deny or skip, skip only in the skip cases
- DONE - Hook client fails closed: deny with the cause and "CHAD needs fixing"
- DONE - A test that each failure of the hook client answers deny with the cause
- DONE - SPEC §3.2/§6.4, README and the chad skill: skip when CHAD is off or hands the call back, deny when it fails
- DONE - The dispatcher closing the connection without an answer is a failure with its cause
  (it stopped or crashed, a command may have done part of its work), not an empty answer
- DONE - When CHAD's own modules do not load, the client still answers: skip for other tools
  and in Off mode (if the mode can be read), deny with the import error otherwise
