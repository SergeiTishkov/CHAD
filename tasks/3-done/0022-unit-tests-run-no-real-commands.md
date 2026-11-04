# 0022 Unit tests do not run real shell commands

Source: the owner, 2026-11-02: review of 0019
Scope: engine, tests

## Business
Since 0019 the policy unit tests run every command they approve, in a real shell:
`git commit -m "one" && npm test`, `npm run build`, `Get-Date`. Their payload's `cwd` is
`C:/work`, which does not exist, so the executor falls back to the home folder (see 0023). On
2026-11-02 nothing changed on the owner's machine only because the home folder is not a git
repository. A test run must never run a command with effects outside its temporary folder.

## Implementation
Unit tests of `chad.policy.Engine` get a stand-in executor (injected into `Engine`, as the
opener already is) that records the command and returns a fixed result. The real executor is
covered by integration tests that run harmless commands (`echo`, `Write-Output`, `exit 3`,
`sleep`) in the test's temporary folder: both shells, exit codes, output limits, timeout and
kill of the process tree.

## Items
- DONE - Engine takes the executor as a parameter; unit tests pass a stand-in
- DONE - Integration tests of the real executor in a temporary folder (`tests/integration/test_executor.py`): both shells, exit codes, stderr kept apart, PowerShell errors as plain text, the working folder, large output keeping both ends, a timed-out `sleep 30`
- DONE - `tests/unit/conftest.py` replaces the real executor with one that fails the test, so a
  unit test that reaches a real shell fails instead of running the command
- DONE - Integration payloads use the test's own folder as `cwd` instead of `C:/work`
- Observation: `asyncio.run` around the real executor on Windows leaves a "unclosed transport"
  warning at garbage collection; the dispatcher keeps one long-lived loop and does not hit it.
  Killing a background child that holds the streams is 0025.
