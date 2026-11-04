# 0015 An opt-in test against a real Claude Code run

Source: the owner, 2026-10-06
Scope: tests

## Business
The hook contract is observed, not documented in full, so a real `claude -p` run checks that
allow and deny round trips work. It spends tokens, so it runs only when asked.

## Implementation
`tests/integration/test_claude_code.py`, enabled with `CHAD_E2E_CLAUDE=1`; the hook is passed
with `--settings` for the run only, so no user settings change.

## Items
- DONE - Opt-in claude -p round trips
