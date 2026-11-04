# 0028 Remove what 0019 left unused

Source: the owner, 2026-11-02: review of 0019
Scope: engine

## Business
0019 left code that nothing uses: the executor sets `CHAD_EXECUTING=1` for every command, and
nothing reads it. (`messages.allow`, used only by a test, is removed under 0039.)

## Implementation
Decide whether `CHAD_EXECUTING` has a use (for example, a hook client started inside a command
CHAD runs). If it has none, remove it.

## Items
- DONE - CHAD_EXECUTING: kept, as a marker for scripts that CHAD runs them, documented in SPEC
  §6.3. Since 0026 a command gets the hook's environment, which may carry Claude Code's
  `CLAUDECODE=1`, so `CHAD_EXECUTING` is the one way to tell a run by CHAD apart. Not a
  recursion guard: a hook started inside a command CHAD runs goes to the same dispatcher, which
  answers it concurrently, so nothing blocks. Integration test: the variable is `1`, also when
  the hook's environment has another value
- DONE - Nothing else from 0019 is unused (every function and constant in executor, messages
  and background is referenced); `messages.allow` stays with 0039
