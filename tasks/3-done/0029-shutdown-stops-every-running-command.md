# 0029 Shutting CHAD down stops every command it is running

Source: the owner, 2026-11-02: review of 0019
Scope: engine

## Business
`Engine.shutdown` cancels the commands started after an approval (`_running`), but not those
started directly by an allow rule, Allow all or Selective mode. Their processes run in their own
process group or session, so they may outlive the dispatcher. Their hooks then get no answer.

## Implementation
The owner, 2026-11-02: keep it simple. CHAD already tries once to stop every command it runs
when it shuts down (above); that is enough. No job objects. The answer the hook gets comes with
0039 (fail-closed: the dispatcher hung up without answering → `deny` with the cause). The Git
Bash limit is written in SPEC §6.4 and not worked around.

## Items
- DONE - Check what happens today, and write it here. Checked 2026-11-02 through the real hook,
  stopping the dispatcher (`shutdown`) while `sleep 20; echo done` ran:
  - run by Allow all: the hook got `{}` (no decision) 2.3 s later, the audit says
    `error ... command execution cancelled`, and `sleep.exe` kept running;
  - run after an approval: the hook got `{}` 0.8 s later, same audit line, `sleep.exe` kept
    running.
  So a command run directly is stopped too, not only an approved one: when `serve()` returns,
  `asyncio.run` cancels every task left, and the executor's cancel branch stops the process
  tree. Two things are wrong instead:
  - the tree is not stopped: on Windows with Git Bash, `taskkill /T` does not reach the
    program a compound command started. Git Bash forks by starting a new Windows process that
    then starts the program, so `sleep.exe`'s parent id names a process that is gone. Also on
    a plain timeout: `sleep 20; echo done` with a 2 s limit → `TIMED OUT`, `sleep.exe` still
    running. `sleep 18` alone is stopped (bash runs it in place). The same cause breaks the
    stop command of background calls (0040);
  - the answer is no decision, so Claude Code may run a command CHAD has half run. Under 0039
    this is CHAD failing, so it becomes `deny`: the command was stopped part way because CHAD
    shut down, its effects may have occurred, do not rerun it.
  A dispatcher killed outright (`taskkill /F`) stops nothing; the processes in their own group
  keep running.
- DONE - Work out the plan (with 0040) and write it here
- DONE - SPEC §6.4: what shutdown does and the Git Bash limit
- Not done, the owner's decision 2026-11-02: tracking commands in one place and stopping
  process trees with job objects
