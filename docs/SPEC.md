# CHAD — Cross Harness Allow/Deny

Specification, version 1. This document is the contract the implementation and its tests are
written against. Where the code and this document disagree, one of them is a bug.

## 1. Purpose

Coding agents run shell commands. CHAD decides which of them run, from a desktop application,
for Claude Code's `Bash` and `PowerShell` tools:

- a policy of **allow rules** (exact, word-wildcard patterns, regex) the user builds while
  approving commands, statement by statement;
- a **deny list** of destructive commands that are refused outright, whatever else says yes;
- a persistent **approval window** with a queue, so several agents waiting at once each get an
  answer, and a word-tile editor that turns "allow this one command" into "allow this shape of
  command";
- four **modes** answering "who decides": CHAD asks, CHAD allows everything, only Selective rules
  run through CHAD, or CHAD steps aside and Claude Code decides.

CHAD executes commands it owns in its dispatcher. Bash calls run in Bash and PowerShell calls
run in PowerShell. After execution CHAD answers `PreToolUse` with `deny`, carrying the exit code
and bounded output in the reason so Claude Code does not launch the command a second time.
Commands CHAD hands back (Off mode or uncovered calls in Selective mode) continue through Claude
Code's normal permission flow.

**CHAD never answers `allow`.** It has two answers. **deny**, in Claude Code's terms a refused
call: the reason says the command was refused and why, or CHAD ran it and here is its result,
or CHAD could not run it and why, or CHAD itself failed and why. **Skip** (no decision): CHAD
hands the call back and the harness decides itself; this is for Off mode and, in Selective
mode, a command no Selective rule covers. This
holds for every mode, path and future change. Refusing with a text and leaving a call alone are
what every harness's pre-command hook supports, so they give every harness the same behaviour;
what an `allow` leads to differs between harnesses.

## 2. Terminology

| Term | Meaning |
|---|---|
| Harness | The agent host whose shell tool is intercepted. Claude Code is the primary harness. |
| Hook client | `python -m chad.hook`: the short-lived process Claude Code runs for every shell tool call. |
| Dispatcher | `python -m chad.dispatcher`: the long-running process that owns policy, approvals and the audit log. |
| UI | The Electron tray application. It owns every visible surface and no policy. |
| Statement | One command of a chained line (`a && b; c | d` has four). |
| Dialect | `bash` (Claude Code's `Bash` tool) or `powershell` (its `PowerShell` tool). |
| Data root | The folder holding config, policy files, audit log and runtime files. |
| User environment | Persistent per-user environment variables: `HKCU\Environment` on Windows. |

## 3. Architecture

```
Claude Code ──stdin JSON──▶ hook client ──TCP 127.0.0.1 + token──▶ dispatcher ◀──TCP──▶ Electron UI
            ◀─stdout JSON──             ◀──── verdict ────────────            push state / decisions
```

- One dispatcher per data root. It listens on `127.0.0.1` on an ephemeral port and writes
  `dispatcher.json` (`pid`, `port`, `token`, `protocol`) into the data root. Every request must
  carry the token. The data root is per-user, so only the user (and their processes) can read
  the token.
- The hook client has no rules of its own. It reads the payload, returns at once in Off mode,
  starts the dispatcher when none is running, forwards the payload and prints the answer.
- The UI holds no policy. Every mutation is a request to the dispatcher, which validates it.

### 3.1 Wire protocol

Newline-delimited JSON over TCP. One request per connection, one response line, except
`subscribe`, which keeps the connection open and streams state.

| `op` | Request fields | Response |
|---|---|---|
| `ping` | — | `{"ok": true, "pid": n}` |
| `hook` | `payload`: the raw hook stdin object; `environment`: the hook process's environment variables (optional) | `{"ok": true, "output": {...}}` — `output` is printed by the hook client verbatim |
| `ui` | `action` + action fields (§9.3) | `{"ok": bool, "error": str?, "state": UiState?}` |
| `subscribe` | — | one `{"state": UiState}` line now and one after every change |

A request with a missing or wrong token gets `{"ok": false, "error": "unauthorized"}`.

### 3.2 Hook contract (Claude Code)

Input (observed from Claude Code 2.1): `session_id`, `transcript_path`, `cwd`, `permission_mode`,
`hook_event_name` (`PreToolUse`), `tool_name` (`Bash` | `PowerShell`), `tool_input`
(`command`, `description`, optional `timeout`, `run_in_background`), `tool_use_id`.
Unknown fields are ignored; missing optional fields are tolerated.

Output is one of:

- **deny**: `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
  "permissionDecisionReason": "..."}}`; the reason is shown to the model, so it is written for
  it: why the command was refused, the result of CHAD running it, or why CHAD failed;
- **no decision**: `{}` — Claude Code continues with its own permission flow. CHAD answers it
  for a tool other than Bash or PowerShell, in Off mode, for an empty command, and in Selective
  mode for a command no Selective rule covers (§6.3).

Claude Code also accepts `allow`; CHAD never sends it (§1). CHAD-owned calls are executed by the
dispatcher and returned as `deny`, so Claude Code's `permissions.deny` / `permissions.ask` rules
and protected paths do not apply to the execution. A hook `deny` applies in every permission
mode, `bypassPermissions` included. Hooks fire for tool calls inside subagents too.

The hook client always exits 0 and always prints valid JSON. A failure of CHAD itself is
**deny** with the cause, never no decision: the dispatcher does not start, does not answer, or
refuses the request; the hook input cannot be read; the hook client raises; CHAD's own code
does not load. The reason starts `[CHAD] CHAD IS BROKEN. The command did not run.`, gives the
cause and the hook log, tells the model not to retry and to tell the user, and says the user can
run `chad mode off` in their own terminal to work without CHAD until it is fixed. In Off mode
the hook client answers no decision without contacting the dispatcher, so Off mode still works
when the dispatcher does not; when CHAD's code does not load, the client still reads the mode
if it can. Control requests (§7) get their own `deny` when the dispatcher cannot be reached.

Registration (written by the installer into the user's `~/.claude/settings.json`):

```json
{"hooks": {"PreToolUse": [{"matcher": "Bash|PowerShell", "hooks": [
  {"type": "command", "command": "\"<venv python>\" -m chad.hook", "timeout": 3600}]}]}}
```

## 4. Modes and switches

Switches are user environment variables. The hook client and the dispatcher read them anew
for **each** call, so a change applies from the next command, without a restart.
Values `1`, `true`, `yes`, `on`, `y` (any case, surrounding space ignored) are on; anything else,
including empty, is off.

| Variable | Effect |
|---|---|
| `CHAD_DISABLED` | Mode **Off**: the hook client returns no decision without contacting the dispatcher. Claude Code decides. |
| `CHAD_SELECTIVE_ALLOWLIST` | Mode **Selective**: CHAD runs statements covered by Selective rules; anything else goes to Claude Code. |
| `CHAD_ALLOW_ALL` | Mode **Allow all**: CHAD runs every command without asking. Nothing is written to the allow list. |
| `CHAD_DENY` | Deny list armed, whatever the mode; a match is refused even when an allow rule, Allow all or the user would let it run. |

Exactly one mode applies; when several variables are set by hand the precedence is
Off > Selective > Allow all > CHAD (the default when none is set).

Setting a mode from the UI or the CLI writes all three mode variables (the new one on, the
others removed), so a stale one cannot reassert itself later. Off is written as removal, not
as `0`.

Where switches are read from:

- **Normal operation**: the user environment only (`HKCU\Environment` on Windows, written the
  same way `setx` does, followed by a best-effort `WM_SETTINGCHANGE` broadcast off the calling
  thread). The process environment does not count for switches: Claude Code copied it at
  start-up, so a value inherited from there may be out of date.
- **Isolated mode** (`CHAD_ISOLATED=1` in the process environment): a JSON file
  `user-environment.json` in the data root stands in for the user environment. Tests and
  development builds use it so they never read or write the real switches. On platforms
  without a registry the same file is the user environment.

Other variables (process environment):

| Variable | Effect |
|---|---|
| `CHAD_HOME` | Data root. Default: `%LOCALAPPDATA%\CHAD` on Windows, `$XDG_STATE_HOME/chad` or `~/.local/state/chad` elsewhere. Also read from the user environment when absent from the process. Required when `CHAD_ISOLATED` is on. |
| `CHAD_ISOLATED` | See above. |
| `CHAD_UI_DISABLED` | The dispatcher does not launch the Electron UI (headless operation, tests). Read from the user environment too. |

## 5. Command analysis

`analyze(command, dialect)` cuts a line into statements and marks **blocking constructs**:
parts whose effect the text alone does not reveal. A statement with one always goes to the
user, whatever the allow rules say, and approving it stores no rule.

Each statement has `text` (as written, trimmed), `normalized` (whitespace outside quotes
collapsed to single spaces, comments removed) and `blocking` (a list of construct names).

### 5.1 Common rules

- Statement separators outside quotes and groups: `;`, newline, `&&`, `||`, `|`. A group runs
  from an opening `(`, `$(`, `{` (and the other openers below) to the closing character that
  matches it; a closing character that matches no open group is an ordinary character.
- A `#` that starts a word begins a comment running to the end of the line. Comments are
  removed from `normalized`; they cannot change what runs.
- Fd duplication (`2>&1`, `>&2`, `1>&2`, `N<&M`, `>&-`) is not redirection: it writes nowhere new.
- Redirection to the null device is not blocking: `/dev/null` (bash), `$null` and `NUL`
  (PowerShell; `NUL` also bash on Windows).
- Redirection (`>`, `>>`, `<`, `&>`, `>|`, `*>`, with a stream number) to a plain relative path
  in the working folder is not blocking: the target is one word of letters, digits, `.`, `-`,
  `_` and `/` (and `\` in PowerShell), not starting with a separator and with no `..` part
  (`out.log`, `logs/run.txt`, `.\out.txt`). A rule covers it only by naming it (§6.1).
- Any other redirection is `file redirection`: a variable, glob, quote, `~`, drive, absolute
  path or `..` in the target. CHAD reads text only: a link the agent made earlier in the folder
  is followed like any file.

### 5.2 bash

- `'...'` is literal. `"..."` honours `\"`, `\\`, `\$`, `` \` ``. `$'...'` is literal with
  backslash escapes. Outside quotes `\x` escapes one character.
- Single `&` (not part of `&&`, `>&`, `&>`) ends a statement (background job). `|&` separates.
- `{` opens a group only as a word of its own where a command starts (at the start of a
  statement or after `(`, `{`, `;`, `|`, `&`). Elsewhere, as in `{a,b}` or `find -exec {}`, it
  is an ordinary character. `${ }` is a group.
- Blocking: `$( )` command substitution, `` ` `` command substitution, `<( )` / `>( )` process
  substitution, here-documents (`<<`) and here-strings (`<<<`), and `eval`, `exec`, `source` or
  `.` as the command word (the first word after any `NAME=value` assignments).
- **Literal here-document exception.** `$(cat <<'EOF' ... EOF)` (also `<<-` and `"EOF"`), with a
  quoted delimiter, expands nothing: it is the idiom Claude Code uses for multi-line commit
  messages. It is consumed whole as literal text, inside or outside double quotes, and is not
  blocking. Its newlines do not split statements. As in bash, the body ends at the first line
  that is exactly the delimiter (leading tabs stripped for `<<-`), and `)` must follow it;
  otherwise the substitution is blocking as usual.

### 5.3 powershell

- `'...'` is literal with `''` as an escaped quote. `"..."` with `""` as an escaped quote.
- Blocking: `` ` `` escape (inside or outside quotes), `$( )` and `@( )` subexpressions, `( )`
  expressions (they run the pipeline inside them), `&` call operator with a computed target,
  `--%` stop-parsing token, `iex` / `Invoke-Expression` as a word anywhere.
- `&` calling a literal path is not blocking: a single-quoted string, a double-quoted string
  with no `$` or `` ` ``, or a bare word of letters, digits, `.`, `-`, `_`, `/`, `\` and `:`,
  followed by a space, `;`, `|` or the end (`& 'C:\Program Files\Git\bin\git.exe' status`,
  `& .\run.cmd`). A variable, a member access, `( )` or a script block after `&` stays blocking.
- `{ }` (script blocks, hashtables) is a group and is not blocking.
- `<#` block comments start with `<` and count as redirection.

### 5.4 Words

`words(statement)` cuts a normalized statement at whitespace that is not inside quotes. The
quotes stay in the word, since an exact rule compares them too: `"hello world"` is a single
word. A redirection operator is a word of its own with its stream prefix: `make 2>err.txt` is
`make`, `2>`, `err.txt`; `*>` and `&>` are operators in both dialects, since rule text is read
the same way for both. An fd duplication (`2>&1`) stays in its word. This is what patterns are built from and what the approval window lays out as tiles.

## 6. Policy

### 6.1 Allow rules

`allow-list.yaml` in the data root:

```yaml
version: 1
allowed:
  - {kind: exact, value: git status, selective: false}
  - {kind: pattern, value: git commit -m *, selective: true}
  - {kind: regex, value: '^npm (test|run lint)$', selective: false}
```

- **exact**: equals the normalized statement (case-sensitive).
- **pattern**: words where `*` stands for **one or more** whole words. Adjacent `*` collapse into
  one. A pattern with no `*` is stored as exact. A `*` never stands for a redirection to a file
  or its target: `echo *` does not match `echo hi > out.log`, `echo * > out.log` does, and
  `echo * > *` matches nothing. Redirection to the null device is an ordinary word. The same
  holds when one pattern is checked to subsume another.
- A regex rule is written by hand and sees the whole statement, redirects included; statements
  whose redirects are blocking never reach it.
- **regex**: Python `re.search` against the normalized statement; written by hand. An invalid
  regex stays listed but never matches.
- Order is the user's. Selective rows always precede ordinary rows.
- **Selective** rows run in both CHAD and Selective mode; ordinary rows only in CHAD mode.
- Adding a pattern removes entries it makes redundant (exacts it matches, patterns it subsumes)
  within the same tier, and is itself skipped when an existing pattern of the same or higher
  tier already subsumes it. An ordinary pattern leaves Selective rows alone, since Selective
  mode looks at nothing else. Regex rows are never removed this way.
- Pattern `A` subsumes `B` when everything `B` matches, `A` matches: a literal of `A` covers only an
  identical literal of `B`; a `*` of `A` covers one or more terms of `B`, literal or `*`.
- The file is reloaded when its modification time or size changes (checked on each access).
  Writes are atomic (temporary file + replace, retried briefly for scanners holding the file).
- A malformed file allows nothing and is **not overwritten**: mutations fail with an error that
  names the file, until the user fixes or deletes it. A missing file is created empty.

### 6.2 Deny rules

`deny-list.yaml`, consulted only while `CHAD_DENY` is on:

```yaml
version: 1
denied:
  - {words: rm -rf, enabled: true}
```

- A statement is caught when it contains **all** of a rule's words; their order does not
  matter, nor does case.
- The statement's words are taken apart at whitespace and at `" ' ` ( ) { } ; | & < >`, so a
  command inside another shell or a subexpression is still seen. A word with `/` or `\` also
  contributes its last part, with and without a final `.exe`: `/bin/rm`, `\rm` and `rm.exe`
  all count as `rm`.
- All statements of a chain are checked. The refusal names the first enabled rule, in list
  order, that catches one of them.
- Joined short flags are one word: `rm -rf` does not catch `rm -rfv`. The default list
  therefore lists the usual spellings one by one.
- When the file is missing, it is written with the default list. When it cannot be parsed, the
  default list is used in memory and the file is left as it is.
- `enabled: false` keeps a rule in the list without applying it.

Default rules: `rm -rf`, `rm -fr`, `rm -r -f`, `rm --recursive --force`,
`Remove-Item -Recurse -Force`, `del /s /q`, `rd /s /q`, `rmdir /s /q`, `git reset --hard`,
`git clean -fdx`, `git clean -fd`, `git push --force`, `git push -f`, `git branch -D`,
`Format-Volume`, `Clear-Disk`, `diskpart`, `mkfs`, `vssadmin delete shadows`, `wbadmin delete`,
`wevtutil cl`, `cipher /w`, `bcdedit /set`, `reg delete`, `Set-ExecutionPolicy Unrestricted`,
`Set-ExecutionPolicy Bypass`, `Set-MpPreference -DisableRealtimeMonitoring`, `net user /delete`,
`Stop-Computer`, `Restart-Computer`, `shutdown /s`, `shutdown /r`.

### 6.3 Decision order

For a hook payload whose `tool_name` is `Bash` or `PowerShell` (anything else: no decision):

1. Control requests (§7), before everything, mode Off included.
2. Mode Off → no decision. (The hook client checks this itself and never contacts the dispatcher.)
3. Empty command (no statements) → no decision.
4. Deny list armed and a statement matches → **deny**, naming the rule and the statement.
5. Mode Selective → if every statement has no blocking construct and matches a Selective rule,
   execute it in CHAD and **deny** with its exit code and output; otherwise capture the call (§7.2)
   and return no decision. Never asks.
6. Mode Allow all → execute in CHAD and **deny** with the result.
7. Mode CHAD → if every statement has no blocking construct and matches any rule, execute in CHAD
   and **deny** with the result; otherwise queue for approval (§8), run it after approval, and
   **deny** with the result. A user rejection or an expired approval does not run the command.

A chain is decided as a whole.

A command runs in the payload's `cwd`, in the shell of the tool that made the call. There is no
fallback folder: a call without `cwd`, or with a `cwd` that does not exist, is not run and is
answered **deny** with `CHAD COULD NOT RUN THE COMMAND` and the cause (§12).

The shells are the ones Claude Code's tools run. Bash: Git Bash (`CLAUDE_CODE_GIT_BASH_PATH`
first). PowerShell: PowerShell 7 when installed (`pwsh` on the PATH of the call's environment,
then `%ProgramFiles%\PowerShell\7`, then the Microsoft Store install in
`%LOCALAPPDATA%\Microsoft\WindowsApps`), else Windows PowerShell 5.1. Claude Code 2.1 tells the
model which edition it has (`&&`, `??` and the like exist only in 7), so the same edition keeps
those commands working.

The command runs with the environment of the hook that made the call: the harness starts the
hook, so its environment is the session's (an activated virtual environment, PATH, variables set
for the session). The hook client sends it with the request; a request without it runs with the
dispatcher's environment. Either way `CHAD_EXECUTING=1` is added: it tells a script that CHAD
runs it (`CLAUDECODE=1` may come with the hook's environment, so it does not tell the two
apart); CHAD itself does not read it. The shell's own profile is not loaded (`--noprofile
--norc`, `-NoProfile`).

A `cd` inside a command changes nothing after it: Claude Code sees a refused call, so the next
call arrives with the same `cwd`. A folder change counts only within one call (`cd sub && make`).

### 6.4 Budget

`config.yaml` (created with comments when missing; a corrupt file means defaults):

| Key | Default | Meaning |
|---|---|---|
| `hookTimeoutSeconds` | 3600 | Must equal the `timeout` registered for the hook. |
| `safetyMarginSeconds` | 30 | The dispatcher answers at least this long before the hook timeout. |
| `maxCommandSeconds` | 1800 | Upper limit for one command, capped by the remaining CHAD budget. |
| `maxOutputBytes` | 30000 | Combined stdout and stderr budget returned to the model. |
| `launchUi` | true | Start the Electron UI with the dispatcher. |
| `uiCommand` | `[]` | Explicit UI command line (list of strings); see §9.4. |

An approval not decided within `hookTimeoutSeconds - safetyMarginSeconds` is answered **deny**
(`NO DECISION IN TIME`) and removed from the queue. The hook client waits that long plus 15 s
before giving up on the dispatcher and answering deny (`CHAD IS BROKEN`, §3.2). Command
execution uses whatever
time remains in that budget, up to `maxCommandSeconds`; a command that reaches its limit is
stopped and answered **deny** with its exit status and partial output. Oversized output is cut
to `maxOutputBytes` while keeping its beginning and end. Claude Code 2.1 passes a deny reason
of 126000 characters to the model whole (measured); the 30000 default keeps one command's
output from taking a large share of the model's context, and is what Claude Code's own Bash
tool passes inline.

When the shell exits, CHAD reads its streams for at most 0.5 s more. If they are still open, a
process the command started holds them (`server &`, `Start-Process -NoNewWindow`): CHAD answers
at once with the real exit code and the output so far, says that process is still running, and
neither waits for it nor stops it. CHAD keeps reading those streams while the dispatcher runs,
so the process never writes into a closed pipe; what it writes later is not returned.

Stopping a command (at its time limit, or when the dispatcher shuts down) is one attempt to
stop its process tree: `taskkill /T /F` on Windows, the process group elsewhere. When the
dispatcher shuts down, every command it is running is stopped this way and its hook gets no
answer, so the hook client answers deny (`CHAD IS BROKEN`: the dispatcher closed the
connection without an answer, and the command may have done part of its work). Limit on
Windows: Git Bash forks by starting a
new process that then starts the program, so a program started by a compound Bash command
(`sleep 20; echo done`) has a parent that no longer exists, `taskkill /T` does not reach it, and
it keeps running. A single command is reached, because bash runs it in place. CHAD does not try
harder: long commands stopped part way are rare.

The call's own hints, when the harness sends them (Claude Code's Bash and PowerShell tools do;
other harnesses may not, and then CHAD's limits apply):

- `timeout` (milliseconds, a positive number) caps the limit above: a command runs for at most
  the smallest of `timeout`, `maxCommandSeconds` and the remaining budget. Anything else in the
  field is ignored.
- `run_in_background: true`: CHAD starts the command in its own process group and answers
  **deny** at once with its process id, the log file that receives its stdout and stderr
  (`background/<time>-<id>.log` in the data root), and the command that stops it
  (`taskkill /T /F /PID n`; `taskkill //T //F //PID n` from Git Bash, which would turn `/T`
  into a path), with the limit below. When the command exits, CHAD appends
  `[CHAD] The command exited with code n.` to the log. CHAD does not stop a background command
  itself, also not when the dispatcher shuts down; then the exit line is not written. Claude
  Code's own tools for background shells do not know these processes. In PowerShell
  both streams go through the pipeline as text, because a redirected error stream is written as
  XML.

## 7. Control requests

An agent can reach CHAD only by sending a shell command, so CHAD reserves a few marker
commands for itself. Each is a comment in bash and in PowerShell: should one reach a real
shell, nothing happens.

### 7.1 `#chad:allow-deny-list`

Recognised anywhere in the command, case-insensitively. The dispatcher asks the UI to show the
policy view in front of the user and answers **deny** saying the window is now open and
nothing ran. It works in mode Off too, because the window is how CHAD is switched on again,
and it starts the dispatcher when none is running. If the dispatcher cannot be reached the answer is **deny** with
"could not be opened".

### 7.2 `#chad:add-selective-command`

Counts only as the **whole** command (trimmed, any case). Added to the end of another command
it is just a comment, so it cannot make that command a control request.

In Selective mode, every call handed to Claude Code is captured: the latest per `session_id`,
kept 10 minutes, at most 128 sessions (oldest evicted), taken at most once. The flow:

1. The user rejects Claude Code's prompt and invokes the `/chad-add-selective-command` skill,
   which runs the marker.
2. Not in Selective mode → **deny** (error). No capture for this session → **deny** (error
   telling the user to reject the prompt first and invoke the skill again).
3. Deny list check on the captured command → **deny** if it matches.
4. The approval window opens in "add to Selective" form: only *Add selectively and run* and
   *Cancel*. Confirming requires every statement to be free of blocking constructs and covered,
   either already or by the rule being built.
5. On confirm: re-check the mode and the deny list, store the rules as Selective, verify that
   every statement is now covered by a Selective rule, then run the captured command in the shell
   that originally received it and answer **deny** with its exit code and output.
6. Cancel → **deny** (rejected by the user). Expiry → **deny** (no decision in time).

## 8. Approval

- Pending commands form a FIFO queue. A command arriving while another is on screen joins the
  back; the window does not switch under the user's hands.
- Each pending item carries: id, command, tool, Claude's one-line `description`, cwd,
  `session_id`, `permission_mode`, deadline, purpose (`approve` | `addSelective`), and per
  statement: text, normalized text, whether a rule already allows it (and which), blocking
  constructs, whether a rule could be stored for it, the word list.
- Decisions: **Allow once**, **Allow forever**, **Allow selectively**, **Deny** (with an optional
  reason the model will read). An approval runs the command in CHAD; the hook returns **deny**
  with the execution result. A rejection does not run it.
- Per statement the user may edit the rule being built: each word is *kept* (literal), *wild*
  (`*`) or *dropped*. Dropping a word from a rule usually stops it matching its own statement;
  **Allow forever** and **Allow selectively** stay unavailable while a rule about to be stored
  would not cover the statement it came from. The UI shows this check; the dispatcher makes it
  again.
- In a chain, each storable statement has a tick to allow it this time only, so no rule is kept
  for it. What runs stays the same.
- Only storable statements are written: not already allowed, no blocking construct.
- Allow forever writes ordinary rules; Allow selectively writes Selective rules (and promotes an
  identical ordinary rule). The audit note records "remembered k of n" when ticks held some back.
- A decision for an unknown or already-decided id fails with an error and changes nothing.
- On dispatcher shutdown every pending item is answered **deny** ("CHAD shut down").

## 9. User interface (Electron)

### 9.1 Window and tray

- One window per data root (single-instance lock), hidden on close, hidden on Escape.
- Tray icon tooltip and first menu line state the mode / pending count. Menu: *Rules and
  mode…*, *Edit allow-list.yaml*, *Edit deny-list.yaml*, *Edit config.yaml*, *Show audit.log*,
  *Show the CHAD folder*, *Quit CHAD* (stops the dispatcher and the UI).
- The window comes to the front when a new command is queued or a control request asks for it:
  the dispatcher increments an `attentionVersion` and sets `requestedView`; the UI raises the
  window whenever the version changes, and on its first state only if the version is non-zero (so
  a UI started at logon stays in the tray).
- `CHAD_UI_HIDDEN=1` (automated tests) keeps the window off screen: raising it is only counted.
- The decision buttons are disabled for 900 ms after a command appears, so a keystroke or click
  aimed at whatever was under the pointer cannot answer it. Focus never lands on a decision.

### 9.2 Views

- **Approval**: "Command i of n" with previous/next, a countdown to the deadline, the command,
  Claude's description, one card per statement (state line, word tiles with *Keep* and `*`
  toggles, a live "Allows: …" preview that turns into an error when it would not cover the
  statement), the context (tool, cwd, session, permission mode), the decision buttons. Deny is
  two-step: the first click reveals a reason box, the second confirms.
- **Policy**: four mode radio buttons with one-line descriptions; the deny-list switch; tabs
  *Allowed* (kind, rule with an *Edit* button, Selective tick, Delete, drag grip) and *Denied*
  (enabled tick, words, Delete, drag grip); a search box filtering the visible tab; a summary line with counts and the
  file path. Deleting a regex or deny rule asks for confirmation. Dragging an allowed row across
  the Selective boundary clamps at the boundary; only the tick changes a row's tier. *Edit* on
  an exact or pattern row shows its words as tiles: each can be retyped, made `*`, moved left or
  right, or removed, and *+ Word* adds one. *Save* replaces the row in place; *Cancel* leaves it.
  While the editor is open the table does not redraw, so typing is not interrupted.
- Errors from the dispatcher appear as a transient toast.

### 9.3 UI actions

`getState`, `setMode {mode}`, `setDeny {value: bool}`, `decide {id, decision, reason?,
selections?}`, `setSelective {key, value}`, `moveAllow {key, index}`, `deleteAllow {key}`,
`addAllow {value, selective?}`, `editAllow {key, value}`, `setDenyRule {key, value}`, `moveDeny {key, index}`,
`deleteDeny {key}`, `addDeny {value}`, `showPolicy`,
`open {target: allow|deny|config|audit|folder}`, `shutdown`.

Allow rows are keyed `kind:value`; deny rows by their words (case-insensitive). `addAllow` takes
a command or a `*` pattern typed by the user and stores it like a rule built in the approval
window (with the same pruning). `editAllow` re-reads the edited text the same way and replaces
the row where it stands, in its tier; a pattern prunes the rules of that tier it makes
redundant. It refuses an empty rule, a rule already listed and a regex row (those are edited in
the file). Each allow entry in the state carries `words`, the rule split as the editor shows it.

`selections` is a list of `{index, modes?, once?}`: the statement index, one of `keep` / `wild` /
`drop` per word, and the "only once" tick. A statement without an entry keeps every word.

### 9.4 Launch

The dispatcher starts the UI unless `launchUi` is false or `CHAD_UI_DISABLED` is on, and
restarts it within 10 s if it exits. The command is `uiCommand` when set; otherwise the packaged
executable under `ui/release/` if built; otherwise the development Electron binary from
`ui/node_modules` with the `ui/` folder. `ELECTRON_RUN_AS_NODE` is removed from the UI's
environment: VS Code sets it for its children, and a dispatcher started from Claude Code inside
VS Code inherits it. The UI is passed `--data-root <path>` and finds the dispatcher through
`dispatcher.json`, re-reading it whenever it reconnects.

## 10. Dispatcher lifecycle

- Single instance per data root through an exclusive lock on `dispatcher.lock`. A second start
  exits immediately with status 0.
- The hook client starts a missing dispatcher detached from its own process tree (so the harness
  reaping the hook does not take it down) while holding `launch.lock`, re-checks after taking the
  lock (another client may have started it), and waits up to 20 s for a successful `ping`.
- `chad install` registers per-user autostart at logon by default (`HKCU\...\Run` on Windows).

## 11. Audit log

`audit.log`, append-only, one line per decision, never fatal:

`2026-10-06 21:04:11 +04:00 | allowForever | Bash | session=… | cwd=… | cmd=git status | note=…`

Newlines in the command are written as `\n`. Decisions: `allowedByRule`,
`allowedBySelectiveRule`, `allowOnce`, `allowForever`, `allowSelective`, `allowAllMode`,
`deniedByUser`, `deniedByRule`, `expired`, `handedToHarness`, `windowOpened`, `error`.

## 12. Messages to the model

Deny reasons are read by the model; each says what happened and what to do next. All start
with `[CHAD]`.

- Rejected by the user: `COMMAND REJECTED BY THE USER. It did not run.` + the user's reason or
  "No reason was given." + not to send the command again, but to respond to the reason or ask
  the user.
- Deny rule: `Refused: this command is on the deny list.` + rule + statement + that a reworded
  command is caught too, not to look for a way around it, and to explain the intent to the user.
- Expired: `NO DECISION IN TIME. The command did not run.` + nobody answered in time, not to
  send it again, and to tell the user it still needs an answer.
- A process the command started still runs (§6.4): `COMMAND EXECUTED. Exit code: n. A PROCESS IT
  STARTED IS STILL RUNNING.` + its work is not finished, CHAD did not wait for or stop it, the
  output is up to the command's exit, do not rerun; a background call is the way to follow it.
- Executed: `COMMAND EXECUTED. Exit code: n.` or `COMMAND TIMED OUT. Exit code: -1.` +
  intentional `deny` explanation, bounded stdout/stderr and a clear instruction not to retry.
- Started in the background: `COMMAND STARTED IN THE BACKGROUND. Process id: n.` + intentional
  `deny` explanation, "do not start it again", the log file, the exit line to look for, the stop
  command (§6.4).
- Could not start: `CHAD COULD NOT RUN THE COMMAND. It did not run.` + cause + instruction to
  tell the user and not retry automatically. Causes include a payload without `cwd` (Claude Code
  sends it with every call, so its hook format changed or CHAD's hook client is broken, and CHAD
  needs fixing) and a `cwd` that does not exist (deleted or moved during the session).
- Incomplete result: `COMMAND RESULT INCOMPLETE.` + partial output and a warning that the command
  may have run; do not retry it.
- Window opened / could not be opened; add-selective errors: `CHAD ERROR. The command did not
  run.` + explanation.

## 13. CLI

`chad` (installed as a shim on the user's PATH):

| Command | Effect |
|---|---|
| `chad status` | Mode, deny list, dispatcher pid/port, data root, pending count. |
| `chad mode chad\|allow-all\|selective\|off` | Writes the mode switches. |
| `chad deny on\|off` | Writes `CHAD_DENY`. |
| `chad open` | Shows the policy window (starts the dispatcher if needed). |
| `chad start` / `stop` / `restart` | Dispatcher lifecycle. |
| `chad install` / `uninstall` | §14. |

`chad mode off` run by an agent is itself a shell command and goes through CHAD like any other.

## 14. Installation

`chad install` (idempotent), for the current user only:

1. Creates the data root with `config.yaml`, `allow-list.yaml`, `deny-list.yaml`.
2. Sets `CHAD_HOME` in the user environment.
3. Merges the hook (§3.2) into `~/.claude/settings.json` (or `$CLAUDE_CONFIG_DIR`), replacing a
   previous CHAD entry and keeping everything else; the previous file is backed up beside it.
4. Copies the skills from `skills/` into `~/.claude/skills/<name>/`.
5. Writes `chad` / `chad.cmd` shims into `~/.local/bin`.
6. Registers autostart (unless `--no-autostart`).

Options: `--claude-dir`, `--bin-dir`, `--no-autostart`, `--deny` (also arms the deny list).
`chad uninstall` reverses 2–6 and keeps the data root unless `--purge`.

## 15. Skills

Shipped in `skills/`, installed per user:

- `chad` — modes, deny list, reading CHAD's answers, turning it on/off.
- `chad-allow-deny-list` — opening the policy window (`#chad:allow-deny-list`).
- `chad-add-selective-command` — `disable-model-invocation: true`; the §7.2 flow.

## 16. Tests

- Unit tests for analysis, patterns, deny matching, stores, switches, config, approval queue,
  captures, messages, installer merge logic.
- Integration tests (preferred) run the real dispatcher and the real hook client as separate
  processes in an isolated data root and drive approvals through the real UI protocol: every
  decision path of §6.3, control requests, cold start and concurrent starts, deny when the
  dispatcher cannot start or the hook input cannot be read, expiry, live reload, mode switching through the CLI, install/uninstall
  into a temporary Claude config folder.
- Electron end-to-end tests (Playwright) run the real UI against a real dispatcher.
- An opt-in test (`CHAD_E2E_CLAUDE=1`) runs real `claude -p` with the hook registered through
  `--settings` and checks allow and deny round trips.
