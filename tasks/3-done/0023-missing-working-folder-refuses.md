# 0023 A command whose working folder does not exist does not run

Source: the owner, 2026-11-02: review of 0019
Scope: engine

## Business
0019's executor runs the command in the home folder when the payload's `cwd` is missing or does
not exist (`executor._working_directory`). A command meant for a project then runs somewhere
else: `git reset --hard` or `rm -rf build` in the home folder. Claude Code itself would fail
instead.

## Implementation
No fallback: a missing or non-existent folder answers `CHAD COULD NOT RUN THE COMMAND`, names
the folder, and says nothing ran. Audit line with the reason. SPEC §12.

## Items
- DONE - Refuse instead of falling back to the home folder; test; SPEC §6.3 and §12
- DONE - The answer names the cause. Two causes are told apart: a payload without `cwd`
  (Claude Code sends `cwd` with every call, so its hook format changed or CHAD's hook client is
  broken; the text says CHAD needs fixing) and a `cwd` that does not exist (deleted or moved
  during the session; the text names the folder). Audit decision `error` with the cause
- DONE - Tests: the executor raises with each cause; through the real hook both causes come
  back as `CHAD COULD NOT RUN THE COMMAND` with the cause
