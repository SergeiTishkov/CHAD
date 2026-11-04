---
name: chad
description: >-
  CHAD (Cross Harness Allow/Deny) decides about Bash and PowerShell calls before they run. Use
  this skill to change its mode or its deny list on request (phrases like "turn CHAD off",
  "switch CHAD back on", "approve everything", "quit prompting me for each command", "ask me
  again before commands", "Selective mode on/off", "arm the deny list"), and to read any tool
  result that begins with "[CHAD]", or a command that sits for a long time before it runs. To
  look at or edit the rule lists themselves, use chad-allow-deny-list instead.
---

# Working with CHAD

CHAD is a `PreToolUse` hook on the Bash and PowerShell tools. Each call goes to a local CHAD
process (the dispatcher) before anything runs. The dispatcher compares the command with the
user's rule lists; for a command it has not seen, it shows the user an approval window.

When the answer is yes, CHAD runs the command itself, in the same kind of shell the call asked
for, and hands back the result inside a `deny`. The `deny` is the delivery mechanism: it stops
Claude Code from running the same command a second time.

## Answers that start with `[CHAD]`

| Heading | What happened | What to do |
|---|---|---|
| `COMMAND EXECUTED.` | CHAD ran it. | The exit code and output are the result. Never repeat it, never call it blocked. |
| `COMMAND TIMED OUT.` | CHAD ran it and killed it at the limit. | Output is partial, changes may already be made. Do not start it again on your own. |
| `COMMAND RESULT INCOMPLETE.` | CHAD started it, the outcome is not confirmed. | Assume it may have acted. Do not start it again. |
| `COMMAND STARTED IN THE BACKGROUND.` | CHAD launched it and did not wait. | Follow the log file it names; stop it with the command it gives. |
| `CHAD COULD NOT RUN THE COMMAND.` | Nothing started. | Pass the reason on to the user; no automatic retry. |
| `COMMAND REJECTED BY THE USER.` | The user said no, maybe with a reason. | Deal with the reason or ask; do not send the same command again. |
| `Refused: this command is on the deny list.` | A deny rule matched. | Rules match words regardless of order, so a rephrased command is caught too. Explain to the user what you were trying to do. |
| `NO DECISION IN TIME.` | Nobody answered before the hook limit. | The user has not seen to it yet; say so instead of retrying. |
| `CHAD ERROR.` | Nothing ran. | Do what the message says. |
| `CHAD IS BROKEN.` | CHAD itself failed; nothing ran. | Tell the user the cause. In their own terminal, `chad restart` often helps, and `chad mode off` lets them work without CHAD meanwhile. |

Two answers come without the prefix:

- Claude Code shows its own permission prompt: CHAD passed the call back. That happens in Off
  mode, and in Selective mode for a command no Selective rule covers. Claude Code's own `ask`
  rules apply to it.
- A refusal with no `[CHAD]` at the start comes from a `deny` rule in Claude Code's settings.
  Name that rule to the user; do not try other phrasings.

A call that hangs before running is almost always waiting for the user in the approval window.
Calls wait their turn there one after another.

## Modes

One mode is active at a time. CHAD reads it again for every call, so a switch counts from the
next command on; nothing restarts.

| Command | Mode | Behaviour |
|---|---|---|
| `chad mode chad` | CHAD (default) | Commands covered by an allow rule run straight away; others wait for the user in CHAD's window. |
| `chad mode allow-all` | Allow all | Every command runs without a question; the allow list is left untouched. |
| `chad mode selective` | Selective | Only commands covered by rules ticked Selective run in CHAD; the rest go to Claude Code's prompt. |
| `chad mode off` | Off | CHAD does not take part; Claude Code handles approval alone. |

`chad status` prints the mode, whether the deny list is armed and whether the dispatcher is up.
The policy window offers the same four modes at its top (the chad-allow-deny-list skill opens
it). Use the CLI when the user names a mode; offer the window when they want an overview.

The modes are stored as three user environment variables: `CHAD_DISABLED`, `CHAD_ALLOW_ALL`
and `CHAD_SELECTIVE_ALLOWLIST`. `chad mode` sets all three together. If someone edits them
directly and more than one is on, Off takes precedence over Selective, and Selective over
Allow all.

## Selective mode in detail

A call runs in CHAD only if each of its statements is covered by a Selective rule and has no
construct whose effect the text does not show (`$(...)`, a redirect to a file, `eval`, and so
on). Otherwise the whole call goes to Claude Code's prompt, and CHAD keeps it for ten minutes.
Should the user reject that prompt and want the command as a Selective rule, they run
`/chad-add-selective-command` themselves. Never start that skill without them.

## Deny list

`chad deny on` arms it, `chad deny off` disarms it. While armed, a matching command is refused
without a question, whatever the mode and whatever the allow list says. The default rules cover
the usual ways to lose data or weaken the machine: recursive forced removal, `git reset --hard`,
force pushes, formatting disks, wiping event logs and similar. Off mode is the one exception,
because CHAD is not asked at all then.

If the user wants it armed for a piece of work, mention that it stays on until someone turns it
off, and ask when that should be unless they already said.

## Switching for the user

`chad mode ...` and `chad deny ...` are shell commands like any other, so in CHAD mode they go
through the approval window too. Just run them. A rejection is the user's answer: leave it at
that and do not look for a way around it.

## Files

The data folder is `%LOCALAPPDATA%\CHAD`, or whatever `CHAD_HOME` points to. It holds
`allow-list.yaml`, `deny-list.yaml`, `config.yaml`, `audit.log` (one line for each decision),
and the logs `dispatcher.log`, `hook.log` and `ui.log`.
