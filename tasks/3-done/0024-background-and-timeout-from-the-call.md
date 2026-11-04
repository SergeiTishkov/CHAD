# 0024 A background call and the call's own timeout are honoured

Source: the owner, 2026-11-02: review of 0019
Scope: engine, docs

## Business
Claude Code's Bash call carries `run_in_background` and `timeout` (ms) in `tool_input`; SPEC
§3.2 lists both. 0019's executor ignores them. An agent that starts `npm run dev` in the
background waits up to `maxCommandSeconds` (1800 s), and then CHAD kills the server and answers
`TIMED OUT`. A command the agent limited to 2 minutes may run 30.

CHAD never answers `allow` (0039), so a background call cannot be handed to Claude Code to
run: CHAD runs it too.

`timeout` and `run_in_background` are fields of Claude Code's Bash and PowerShell tools, not of
tool calls in general; Cursor, for one, has a separate hook for shell commands with its own
payload. CHAD treats both fields as optional hints: when they are missing, its own limits from
`config.yaml` apply (the owner confirmed, 2026-11-02).

## Implementation
`timeout` (ms, a positive number) caps the limit: the smallest of `timeout`, `maxCommandSeconds`
and the remaining budget. Anything else in the field is ignored. An approved call and a call
captured for add-selective keep the hints of the original call.

`run_in_background: true`: `chad.background.start` starts the command in its own process group,
stdout and stderr into one log file `background/<time>-<id>.log` in the data root, and answers
`deny` at once: `COMMAND STARTED IN THE BACKGROUND`, process id, log file, the exit line to look
for, and the command that stops it and everything it started (`taskkill /T /F /PID n`, from Git
Bash `taskkill //T //F //PID n`). When the command exits, CHAD appends
`[CHAD] The command exited with code n.` to the log. In Windows PowerShell both streams go
through the pipeline as text: tried redirecting the error stream to the file → the file got
`#< CLIXML` XML; tried `*>&1` → still XML and `Write-Error` alone exited 0; the pipeline with
`try/catch` gives plain text and the right exit codes, `throw` included.

CHAD does not stop a background command itself, also not when the dispatcher shuts down (then
no exit line is written). Claude Code's own tools for background shells do not know these
processes. SPEC §6.4 and §12.

## Items
- DONE - Work out the plan and write it here
- DONE - `timeout` from the call caps the limit, for direct, approved and add-selective calls; unit tests
- DONE - `run_in_background` starts the command detached with a log file and answers at once; unit tests with a stand-in starter
- DONE - Integration tests: both shells write output and the exit code to the log, PowerShell errors as text, the working folder, the stop command from the answer stops it in both shells, a background call through the real hook
- DONE - SPEC §6.4 and §12
- Observation: background log files are never deleted; nothing limits their size.
