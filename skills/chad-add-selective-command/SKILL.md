---
name: chad-add-selective-command
description: >-
  In Selective mode, turns the command Claude Code just prompted about into a Selective rule in
  CHAD, then runs it. The user starts it, after saying no to Claude Code's prompt for that
  command.
disable-model-invocation: true
---

# Making the last prompted command a Selective rule

Use the shell tool the rejected command used (Bash or PowerShell) and send only this line:

```
#chad:add-selective-command
```

It has to be the whole command, or CHAD will not see it as a request. Leave the original
command out: CHAD saved the last command it passed to Claude Code in this session. It opens
the approval window in its Selective form, where the user decides which words stay fixed and
which become `*`.

What comes back:

- `[CHAD] COMMAND EXECUTED.` with the command's output: the user chose *Add selectively and
  run*. The rule is saved, and the command already ran once, in its own shell. Do not run it
  again.
- `[CHAD] COMMAND TIMED OUT.` or `[CHAD] COMMAND RESULT INCOMPLETE.`: the rule is saved, and the
  command may have done some of its work. Report what the message says; no automatic rerun.
- `[CHAD] COMMAND REJECTED BY THE USER.`: the user cancelled. Nothing more to do.
- `[CHAD] Refused: this command is on the deny list.`: a deny rule blocks it, so it neither ran
  nor became a rule. A rephrased version is caught as well.
- `[CHAD] CHAD ERROR.` mentioning *no recent command*: there was no prompt to add from. The user
  first rejects Claude Code's prompt for the command, then starts this skill again.
- `[CHAD] CHAD ERROR.` saying it *only works in Selective Allowlist mode*: let the user know.

Leave the rest to CHAD: do not retype the command, edit `allow-list.yaml` or switch modes.
