# 0046 Selective mode that refuses everything else

Source: the owner, 2026-11-05, looking at the four mode cards: Selective could come in two
kinds, "the rest goes to the harness" (today's) and "the rest is denied". The first is the case
the owner had: the harness's own approval broke, and the commands marked Selective kept working
through CHAD while everything else stayed with the harness. The second is a restricted setup:
a fixed set of commands is allowed and nothing else runs.
Scope: engine, cli, ui, skills, docs

## Business
Today a command no Selective rule covers is handed back to the harness, so what runs in the end
depends on the harness's own approval. With the strict kind, the Selective rules are the whole
list of what may run, and any other command is refused straight away with a `[CHAD]` text for
the model.

Uses:
- a locked-down setup, where only a known set of commands may run;
- an agent nobody watches, such as `claude -p`, a scheduled job or CI: in CHAD mode a new
  command waits in the window until the hook's time limit runs out, while the strict kind refuses
  it at once and says why.

The strict kind answers only `deny` or runs the command itself, so it never needs `allow` and
works the same in every harness (CLAUDE.md: CHAD never answers `allow`).

## Implementation
One open choice: a fifth mode card, or Selective with a switch "Other commands: harness / deny",
like the "Deny list armed" switch. The switch keeps four cards and one meaning for the Selective
tick; the setting would be a user env var like the other switches (for example
`CHAD_SELECTIVE_STRICT`). The refusal text names the mode and tells the model not to retry and to
ask the user to add a rule or change the mode. `/chad-add-selective-command` has no harness
prompt to follow in the strict kind; adding the rule goes through the window or `chad`.

## Items
- TO DO - The owner decides: do it or not; a fifth mode or a switch on Selective
