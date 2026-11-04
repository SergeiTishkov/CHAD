# 0021 The test suite and the lint check pass again after 0019

Source: the owner, 2026-11-02: review of 0019
Scope: engine, tests, ci

## Business
0019 changed CHAD's answer for approved commands from `allow` to `deny` with the result, but
changed no test. On 2026-11-02, `pytest` gave 19 failed, 260 passed, 3 skipped: the tests still
expect `allow`, or the rerun message that 0019 removed (`test_policy.py`, `test_server.py`,
`test_audit_messages.py`, `test_hook_flow.py`, `test_cli.py`). `ruff format --check` also
fails on `src/chad/executor.py` and `src/chad/messages.py`. CI is red on every push since
0019.

## Implementation
Update the expectations to the new answer (`deny` that starts with `[CHAD] COMMAND EXECUTED`)
and check the exit code and output where the old tests checked `allow`. Do this together with
0022, so the unit tests do not run real commands. Format the two files.

## Items
- DONE - Expectations for deny-with-result in the unit and integration tests
- DONE - Tests for the executed, timed out, incomplete and could-not-run messages
- DONE - ruff format on executor.py and messages.py
- DONE - pytest and ruff pass locally (322 passed, 3 skipped, 2026-11-02); CI runs on the next push
- DONE - Integration tests approve harmless `echo` / `Write-Output` commands in the shape of the
  old ones (`echo push origin main`, `echo git reset --hard` for the deny switch), in a
  per-test folder `harness.WORK`; the add-selective test checks the executed output instead of
  `updatedInput`
- DONE - `test_claude_code.py`: the allow-rule test is renamed for what it checks now (CHAD runs
  the command, the model reads its output)
