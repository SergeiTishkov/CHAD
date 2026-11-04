# 0035 An allow rule can be edited where it stands

Source: the owner, 2026-11-02
Scope: ui, engine, docs

## Business
Today a stored rule can only be deleted, moved or switched to Selective. Changing one word
means deleting the rule and waiting for the command to come up again. Wanted: each
exact or pattern row can be edited as word pieces (retype a word, make it `*`, reorder, add,
remove) and saved in place.

## Implementation
A UI action (`editAllow`) that replaces a row and keeps its position and tier. The dispatcher
re-validates the rule as it does for `addAllow`, and pruning applies within the tier. The word
editor reuses the tiles of the approval view. SPEC §9.3.

## Items
- DONE - editAllow in the dispatcher with validation; tests
- DONE - Word-piece editor in the policy view; Playwright test
- DONE - SPEC
