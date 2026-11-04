# 0040 The stop command given for a background call stops everything it started

Source: found 2026-11-02 while checking 0029; follows from 0024
Scope: engine, docs

## Business
0024's answer for a background call tells the agent to stop it with `taskkill /T /F /PID n`
(`//T //F //PID` from Git Bash), "and everything it started". On Windows with Git Bash that
does not hold. Checked 2026-11-02: `sleep 30` alone → stopped; `sleep 31; echo x` → the
command exits 0, the log gets its exit line, and `sleep.exe` keeps running. The 0024
integration test checked only the exit line, not the child.

Cause (the same as in 0029): Git Bash forks by starting a new Windows process that then starts
the program, so `sleep.exe`'s parent is a process that no longer exists, and `taskkill /T`,
which walks parent ids, does not reach it. A single command is not affected because bash runs
it in place.

## Implementation
The owner, 2026-11-02: no job objects or other machinery for this. A long command stopped part
way is rare; CHAD either works or it does not. The answer is made true instead: the stop
command ends the command and the processes Windows records as its children, and a program a
compound Bash command started can keep running; the agent checks with `tasklist` and stops it
by its own process id. SPEC §6.4 states the limit.

## Items
- DONE - Work out the plan with 0029 and write it here
- DONE - The background answer no longer promises to stop "everything it started" and says how
  to find what is left; unit test
- DONE - SPEC §6.4: the background bullet and the stopping limit
