---
name: chad-allow-deny-list
description: >-
  Bring up CHAD's policy window, where the user looks through, searches, reorders, edits,
  switches on and off or deletes the shell-command rules and picks CHAD's mode. Use for requests
  such as "open CHAD", "show my CHAD rules", "which commands are allowed", "what is on the deny
  list", "delete that CHAD rule", "tidy up the allow list", "take back an allow forever". It only
  opens the window; to change the mode from a sentence, use the chad skill.
---

# Opening CHAD's policy window

Send this as the entire command, through Bash or PowerShell:

```
#chad:allow-deny-list
```

To either shell the line is a comment, so it cannot do anything by itself. CHAD's hook spots
it, puts the policy window in front of the user, and replies with a refusal headed
`[CHAD] CHAD ERROR.` that says the window is open. That refusal means it worked: no command was
supposed to run. Tell the user where to look, and you are done.

No preparation is needed. The marker starts the dispatcher when it is down, and it works in
Off mode as well, since the window is how the user turns CHAD back on.

## The window

- At the top: the mode (CHAD, Allow all, Selective, Off) and the switch that arms the deny list.
- **Allowed**: commands that run without a question. The *kind* column tells how a rule is
  compared: `exact` matches one statement as written, `pattern` uses `*` for one or more words,
  `regex` is an expression someone put into the file by hand. A rule ticked **Selective** is
  used in Selective mode too; those rules are always listed first. Rows can be dragged into a
  new order, edited word by word, or deleted.
- **Denied**: commands refused without a question. Each rule can be ticked off without deleting
  it. A deny rule catches a statement that has all of the rule's words, in whatever order.
- A search box narrows the open tab. Changes apply at once; there is nothing to save.

## How rules get their `*`

The approval window shows every statement of a new command as a row of word tiles. The user
keeps a word, turns it into `*`, or removes it. Say the command was `git commit -m "hello"` and
the message tile became `*`: the stored rule is `git commit -m *`, good for any commit message
and for no other git command. A new pattern also deletes the older, narrower rules it now
covers, so an **Allow forever** can leave the list shorter than before.

When a command is a chain (`a && b`), each statement has a tick to allow it this one time
without keeping a rule for it. The chain itself always runs complete.

## If the window does not appear

- The refusal says the window **could not be opened**: the dispatcher did not respond. Ask the
  user to run `chad open` in their own terminal. Do not try other ways of starting it.
- You get normal shell output, or nothing: the hook is not loaded in this session, so the line
  went to a real shell and was ignored as a comment. Let the user know; the tray icon's menu
  opens the same window.

## The files behind it

`allow-list.yaml` and `deny-list.yaml` live in CHAD's data folder, and CHAD notices edits to
them while it runs. Change them only on the user's request, and first say which rule you are
about to touch and wait for a yes.
