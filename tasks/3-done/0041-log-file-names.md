# 0041 Log files are named hook.log.log

Source: the agent, found while doing 0039; the owner's standing rule that a found bug is fixed
(2026-11-02)
Scope: engine, docs

## Business
README, SPEC and the chad skill name the logs `hook.log`, `dispatcher.log` and `ui.log`, and
the `CHAD IS BROKEN` deny (0039) points the user at the hook log. `paths.log_file(name)` adds
`.log` itself, and every caller passed a name that already ended in `.log`, so the files on disk
were `hook.log.log`, `dispatcher.log.log` and `ui.log.log`. Someone following the docs or the
deny reason found no such file.

## Implementation
The callers pass `hook`, `dispatcher`, `ui`. A test that the names on disk are the documented
ones.

## Items
- DONE - Callers in hook.py and dispatcher.py pass the bare name
- DONE - Test: the dispatcher and hook logs are written as dispatcher.log and hook.log, and the
  CHAD IS BROKEN deny names hook.log
