---
name: chad-selective-rules
description: >-
  Look up CHAD's Selective rules when CHAD refuses a command that no Selective rule covers
  ("[CHAD] Refused: no Selective rule covers this command."), or before sending a command in
  that setup: search the rules with #chad:find-rules and test a command with #chad:check.
  Neither runs anything.
---

# Finding a command the Selective rules allow

This applies in one setup: CHAD is in Selective Allowlist mode, refuses every command its
Selective rules do not cover, and shows those rules to the agent. The user picks all three in
CHAD's policy window. A refusal then looks like this:

```
[CHAD] Refused: no Selective rule covers this command. It did not run.
CHAD is in Selective Allowlist mode, where it refuses every command its Selective rules do not cover.
Not covered: git push origin main (no Selective rule matches it)
Selective rules for `git` (2):
  git status
  git log *
How the rules read: ...
```

It lists up to 20 rules for the same program as the refused statement. When the user keeps the
rules hidden, the refusal says so instead and the two requests below are refused too; ask the
user then.

## How the rules read

- An exact rule is the whole statement, word for word.
- In a pattern, `*` stands for one or more whole words. It never covers a redirection, so
  `echo *` does not allow `echo hi > out.txt`.
- A rule shown as `regex: ...` is a regular expression searched in the statement.
- Each statement of a chain (`&&`, `||`, `;`, `|`) must match a rule on its own.
- A statement with command substitution (`$(...)`), `eval`, a redirect to a file or a similar
  construct never matches, whatever the rules say.

## The two requests

Send each as the whole command, through the same shell tool (Bash or PowerShell), on one line.
CHAD answers with a refusal that carries the result; nothing runs.

### `#chad:find-rules <words>`

```
#chad:find-rules git log
```

Lists the Selective rules that contain any of the words (case does not matter), the rules
with more of the words first. With no words it lists every Selective rule. Answers come 50
rules to a page:

```
[CHAD] SELECTIVE RULES. This was a request to CHAD; nothing ran.
Search: git log
Rules 1-50 of 130:
  ...
More rules match. A narrower search is the better next step; the next page is
`#chad:find-rules --page 2 git log`.
```

Narrow the search with more specific words before paging: `git log --oneline` finds fewer
rules than `git`. `--page N` goes right after the marker.

### `#chad:check <command>`

```
#chad:check git log --oneline -5 && git status
```

Says whether the command would run now, statement by statement:

```
[CHAD] CHECK: WOULD RUN. This was a request to CHAD; nothing ran.
Command: git log --oneline -5 && git status
- git log --oneline -5: covered by pattern: git log *
- git status: covered by exact: git status
To run it, send the command itself, without #chad:check.
```

`WOULD BE REFUSED` names the statement that no rule covers, the construct no rule can allow,
or the deny-list rule that matched. A deny-list match is refused whatever the allow rules say; do not look for
another phrasing of it.

## What to do with the answer

- Rework the command into one the rules cover, check it if unsure, then send it without the
  marker.
- If no covered command does the job, tell the user which command you need and why. Adding
  rules is the user's decision; they do it in CHAD's window.
- Do not send a refused command again unchanged.
