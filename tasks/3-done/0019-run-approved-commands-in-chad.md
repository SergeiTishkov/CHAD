# 0019 CHAD runs the commands it approves and returns the result through a deny

Source: the owner, 2026-10-06
Scope: engine, skills, docs

## Business
Until this change CHAD only answered `allow`, and Claude Code ran the command itself. Claude
Code's own `permissions.deny`/`permissions.ask` rules and protected paths still applied to
those calls. Now CHAD runs every command it approves in its own dispatcher and answers `deny`
with the exit code and the output. That way Claude Code never starts the command itself, and
the agent finds the result in the text of the refusal. Calls CHAD hands back (Off mode, a
command no Selective rule covers) still go through Claude Code's normal flow. A rejected or
expired approval runs nothing.

## Implementation
`chad/executor.py` runs Bash calls in Bash (`CLAUDE_CODE_GIT_BASH_PATH`, then Git's usual
paths, then PATH) and PowerShell calls in PowerShell through `-EncodedCommand`. It keeps the
beginning and end of stdout and stderr up to `maxOutputBytes` (100000), decodes PowerShell's
CLIXML error stream, and kills the process tree at the limit. The limit is the remaining hook
budget, at most `maxCommandSeconds` (1800). `chad/policy.py` runs allowed calls inline and
approved ones as tasks; an interrupted hook stops its command. `chad/messages.py` reports
`COMMAND EXECUTED`, `TIMED OUT`, `RESULT INCOMPLETE` or `COULD NOT RUN`. The add-selective flow
runs the captured command in its own shell instead of asking for a rerun. SPEC, README and both
skills describe the new answer.

The review of 2026-11-02 found what this left open; the tasks that fix it name 0019.

## Items
- DONE - Executor with bounded output and time limit
- DONE - Policy runs approved calls and answers deny with the result
- DONE - Messages for executed, timed out, incomplete, could not run
- DONE - maxCommandSeconds and maxOutputBytes in config.yaml
- DONE - SPEC, README and skills
