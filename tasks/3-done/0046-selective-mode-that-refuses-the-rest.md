# 0046 Selective mode that refuses everything else

Source: the owner, 2026-11-05, looking at the four mode cards: Selective could come in two
kinds, "the rest goes to the harness" (today's) and "the rest is denied". The first is the case
the owner had: the harness's own approval broke, and the commands marked Selective kept working
through CHAD while everything else stayed with the harness. The second is a restricted setup:
a fixed set of commands is allowed and nothing else runs. The same day the owner set the shape:
two checkboxes in the window, and a refusal that can list the allowed commands so the agent can
pick one of them.
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

With the list in the refusal, the agent does not have to guess: it sees which commands it may
run and rewrites its call to fit one of them. The strict kind answers only `deny` or runs the
command itself, so it never needs `allow` and works the same in every harness (CLAUDE.md: CHAD
never answers `allow`).

## Implementation
The window, under "Deny list armed", while Selective is the chosen mode:
- checkbox 1, "Refuse other commands": off - they go to the harness's own approval (today);
  on - CHAD refuses them.
- checkbox 2, shown only while checkbox 1 is on, "Show the agent the Selective rules": in the
  refusal, and through the two requests below. Off - the refusal says CHAD keeps its rules to
  itself, and the requests are refused.

Both are stored as user env vars like the other switches, settable from `chad` too, and are
ignored in every mode but Selective. The deny list still comes first.

The refusal names the mode and says: do not retry the same command; use one of the commands
below, or ask the user to add a rule or change the mode. With checkbox 2 on, it lists the
Selective rules (exact, pattern, regex) and how to read them, as the matcher works: `*` stands
for one or more whole words, never for a redirection; each statement of a chain must match a
rule on its own; command substitution, `eval` and the like never match. The list is the short
one described below, with the total when more rules are left out.

`/chad-add-selective-command` has no harness prompt to follow in the strict kind; adding the
rule goes through the window or `chad`.

### Asking CHAD instead of reading the whole list
The owner, the same day: with thousands of Selective rules the refusal cannot carry them all.
It carries a short list, and the agent asks CHAD for the rest through a skill. The channel is a
control request (SPEC §7): a marker command the hook catches before any rule, answered with a
`deny` text, so it works in the strict kind and in any harness, and nothing runs.
- `#chad:find-rules <words>`: the Selective rules that contain those words, in pages of 50
  (`findRulesPageSize` in config.yaml). The answer says "rules 1-50 of 3000", that a narrower
  search is the better next step, and how to ask for the next page
  (`#chad:find-rules --page 2 <words>`). Rules matching more of the words come first, then the
  list's own order.
- `#chad:check <command>`: whether that command would run now, which rule covers each statement,
  or which statement no rule covers and why (a redirection, `$(...)`, no rule). The real matcher
  answers, so the agent does not have to guess how `*` and chains are read.

The short list in the refusal is the Selective rules for the same program as the refused
command (`git push --force` → the `git ...` rules), up to about 20. The refusal also names the
two requests. A skill describes them for harnesses that load skills; the refusal text alone is
enough for the others.

## Items
- DONE - Switches `CHAD_SELECTIVE_REFUSE` and `CHAD_SELECTIVE_LIST_RULES`, ignored outside
  Selective mode; the Selective description follows the first (window, `chad status`)
- DONE - Selective mode with refuse on: an uncovered command is refused with
  `[CHAD] Refused: no Selective rule covers this command.`, each uncovered statement and why; not
  captured; audited `refusedOutsideSelective`; the deny list still first
- DONE - With list on: up to 20 Selective rules for the program of the first uncovered statement,
  the total when there are more, how the rules read, and the two requests; with it off, the
  rules stay hidden
- DONE - `#chad:find-rules [--page N] <words>`: ranked search, pages of `findRulesPageSize` (50),
  next-page command and the advice to narrow; audited `rulesLookup`
- DONE - `#chad:check <command>`: statement by statement - deny-list rule, blocking construct,
  covering rule, or no rule; audited `rulesLookup`
- DONE - Both requests answer only in Selective with both switches on, otherwise an error to ask
  the user; they reach the dispatcher in Off mode too and get their own refusal when it is down
- DONE - Window: the two checkboxes under "Deny list armed", shown by mode and by checkbox 1;
  UI actions `setSelectiveRefuse` and `setSelectiveList`
- DONE - CLI `chad selective refuse|list on|off`; `chad status` prints a Selective line
- DONE - Skill `chad-selective-rules`; the `chad` skill lists the new answers and switches
- DONE - README (feature, switches, env vars, config, skills, CLI, a section with a screenshot
  and a sample refusal) and SPEC §4, §6.3, §6.4, §7.3, §7.4, §9.2, §9.3, §11, §12, §13, §15, §16
- DONE - Tests: unit (lookup, engine, switches, config, hook client, messages), integration
  through real processes, Playwright for the checkboxes; screenshot docs/images/selective.png
