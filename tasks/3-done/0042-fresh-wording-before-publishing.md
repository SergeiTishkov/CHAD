# 0042 Texts in fresh wording before publishing

Source: the owner, 2026-11-05
Scope: engine, skills, docs

## Business
Before the repository goes public, the owner wants its prose written anew: the skills, the
texts the model reads, the comments of the default deny list, docstrings and the spec passages
that describe them. Behaviour stays as it is. Kept as they are: the name CHAD, the `[CHAD]`
headings the skills and tests key on (`COMMAND EXECUTED.`, `Refused: this command is on the
deny list.` and the others), the marker commands, skill names, file names and the set of
default deny rules.

CLAUDE.md states the commit rule in neutral terms: the project is 100% vibe coded and all code
checks are done by AI. Task files say where a request came from without referring to other
copies of the program. The README screenshots show the current windows.

## Implementation
Rewrite by hand, then compare the tree word by word with the earlier text and repeat until the
only shared runs of six or more words are headings, file names, product names and code idioms.

## Items
- DONE - The three skills rewritten
- DONE - Model-facing texts in messages.py and hook.py rewritten; headings kept; tests follow
- DONE - Deny list header, category comments, examples and docstrings in denylist.py,
  patterns.py, allowlist.py, config.py, switches.py, userenv.py rewritten
- DONE - SPEC passages (architecture, switches, analysis, words, pruning, deny list, control
  requests, approval, deny reasons) and README lines rewritten; "killswitch" is now mode Off
- DONE - Tray menu labels, the policy tab name, window size, the colour palette and the UI
  package description changed; SPEC §9.1 follows
- DONE - CLAUDE.md commit rule in neutral wording; tasks 0002, 0019, 0033-0038 reworded
- DONE - README: the managed-policy list no longer offers "ask" for an unreachable dispatcher
  (0039 made it deny)
- DONE - Screenshots regenerated; the policy picture takes the window's real width
