# 0025 A command that leaves a process behind returns when it exits

Source: the owner, 2026-11-02: review of 0019
Scope: engine

## Business
When a command starts a process that outlives it (`server &`, `nohup ...`, `Start-Process`
with inherited handles), that process keeps stdout and stderr open. 0019's executor waits for
both streams to close until the whole remaining limit has passed. Then it kills the process
tree, the process left behind included, and reports `TIMED OUT` with exit code -1, although the
command exited at once with a real code.

Checked on 2026-11-02 on Windows, `executor.run` with a 5 s limit (3 s for the last one):
- `echo hi; sleep 8 & exit 0` (Bash) → 5.0 s, `timed_out`, exit -1, output `hi`.
- `echo hi; nohup sleep 8 >/dev/null 2>&1 & exit 0` → 0.1 s, exit 0: the child does not hold
  the streams.
- `Start-Process -NoNewWindow powershell ...; exit 0` → 5.0 s, `timed_out`, exit -1.
- `Start-Process -WindowStyle Hidden powershell ...; exit 0` → 0.6 s, exit 0.
- `sleep 9 & exit 7` → `timed_out`, exit -1 instead of 7, and `sleep.exe` was still running
  afterwards. On Windows `_kill_process_tree` returns early when the shell has already exited,
  so the child left behind is not killed; the text above ("kills the process tree, the process
  left behind included") holds only for the POSIX branch (`killpg`).

Since 0024 a call with `run_in_background: true` takes its own path and is not affected.

## Implementation
The owner, 2026-11-02: do not wait for what the command left running. Long tasks are usually run
for their side effect, not their output; take what has come back and return it, and say in the
answer that the work is not finished.

After the shell exits, CHAD reads the streams for 0.5 s more (`STREAM_GRACE_SECONDS`), so what is
already in the pipe is not lost. Still open after that → `left_running`: the answer is
`COMMAND EXECUTED. Exit code: n. A PROCESS IT STARTED IS STILL RUNNING.` with the real exit code
and the output so far; it says the work is not finished, CHAD neither waited for nor stopped the
process, and a background call (0024) is the way to follow it. Audit note `leftRunning=true`.
CHAD keeps reading the open streams in the background (output discarded beyond the capture), so
the process left running does not get a broken pipe when it writes. A timeout while the shell
itself still runs is unchanged.

## Items
- DONE - Grace period after exit; real exit code; leave detached children alone; test
- DONE - The answer says a process the command started is still running; message test
- DONE - The streams are read on after the answer, so the child's later writes do not fail;
  integration test where the child writes to stdout after the answer and then leaves a file
- DONE - Integration tests: Bash `&` with exit 5, PowerShell `Start-Process -NoNewWindow`, and
  `nohup ... >/dev/null` (streams closed, not marked)
- DONE - SPEC §6.4 and §12
- Result, same checks as above: `echo hi; sleep 8 & exit 0` → 0.6 s, exit 0, marked;
  `Start-Process -NoNewWindow` → 0.9 s, marked; `nohup` and `-WindowStyle Hidden` → not marked.
- Observation: the Windows early return in `_kill_process_tree` (shell already exited) is left
  as it is; after this change it only matters for a timeout, when the shell is still running.
