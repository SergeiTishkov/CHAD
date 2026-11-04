# 0045 The app's own texts say "the harness", not Claude Code

Source: the owner, 2026-11-05, looking at the Rules and mode screenshot: "Off - Claude Code
decides" should go. The app itself must not name Claude Code, because it is meant to be run from
any harness (only Claude Code today). The docs may name Claude Code, with "or another harness"
where the text applies to harnesses in general. Selective mode should be explained better:
commands marked Selective go through CHAD, the rest go to the harness's own approval.
Scope: ui, engine, cli, docs

## Business
CHAD is "Cross Harness": Claude Code is the one harness it supports today, not the only one it
is meant for. What a person or the model reads from the running app (the window, the tray
tooltip, `chad mode`, `chad install`, the config template, the refusal texts) names the harness
in general. Code comments, the Claude Code adapter's docs, and README/SPEC passages about the
Claude Code integration itself still name Claude Code, because that is what they describe. The
env var name `CLAUDE_CODE_GIT_BASH_PATH` stays: CHAD reads it.

## Items
- DONE - Mode Off label: "Off - the harness decides" (window and tray tooltip)
- DONE - Mode descriptions: Selective "Commands marked Selective go through CHAD; the rest go to
  the harness's own approval.", Off "... the harness asks for approval itself." (window and
  `chad mode`)
- DONE - Refusal texts, executor errors, installer's last line and the config.yaml template say
  "the harness"
- DONE - README and SPEC mode passages: the harness, with Claude Code named where it is the case
  today; Selective explained as marked commands through CHAD, the rest to the harness
- DONE - Screenshots in docs/images rendered again
