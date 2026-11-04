# 0008 An approval queue and rules built from word choices

Source: the owner, 2026-10-06
Scope: engine

## Business
Several agents can wait at once, and each gets its own answer in order. While approving, the
person turns "this one command" into "this shape of command" by marking each word kept,
wildcard or dropped; a rule that would not allow its own statement is refused. In Selective
mode the latest handed-back call is remembered so it can be added to the list afterwards.

## Implementation
`chad/approvals.py`: a FIFO queue of futures, rule building from per-word choices.
`chad/captures.py`: the latest Selective-mode call per session, kept ten minutes.

## Items
- DONE - Approval queue
- DONE - Rule building from word choices
- DONE - Captures for add-selective
