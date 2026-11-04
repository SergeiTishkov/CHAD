# 0007 An audit log of every decision and answers written for the model

Source: the owner, 2026-10-06
Scope: engine, docs

## Business
The person can see later what was decided, by whom and why. The agent reads CHAD's refusals,
so each one says what happened and what to do next, and none invites a workaround.

## Implementation
`chad/audit.py`: `audit.log`, append-only, one line per decision, never fatal; the README says
it grows without limit. `chad/messages.py`: every message starts with `[CHAD]`.

## Items
- DONE - Audit log
- DONE - Messages to the model
- DONE - README: what audit.log keeps
