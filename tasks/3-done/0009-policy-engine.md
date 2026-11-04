# 0009 The policy engine: one decision order for every call

Source: the owner, 2026-10-06
Scope: engine, docs

## Business
Every shell call gets the same answer for the same state: control markers first (the window is
where CHAD gets switched back on), then Off, empty commands, the deny list, Selective, Allow
all, then rules or the approval queue. A decision re-checks the deny list and the mode before
anything is stored, so a rule cannot be added past a deny rule armed in the meantime.

## Implementation
`chad/policy.py` (`Engine`): hook decisions, the control requests `#chad:allow-deny-list` and
`#chad:add-selective-command`, and the UI actions, `addAllow`/`addDeny` and the selections
format documented in the spec. CHAD mode is listed first.

## Items
- DONE - Decision order, control requests, UI actions
- DONE - CHAD mode listed first
