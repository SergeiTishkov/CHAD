# 0037 A tested step is committed without waiting for a manual check

Source: the owner, 2026-11-02
Scope: rules

## Business
The global rule "do not commit unless asked" made the agent wait for someone to try each step
by hand before committing. In this repository, a step whose tests pass is committed at once. A
fix found afterwards is a new commit, never an amend.

## Implementation
`CLAUDE.md`, "Commits": the rule, stated as overriding the global one for this repository.

## Items
- DONE - CLAUDE.md. The owner, 2026-11-02: the agent commits and keeps git itself; the
  project is vibe coded, and code checks are the agent's. "Made when it is done" was already there; the override was not.
