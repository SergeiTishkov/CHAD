# 0012 Skills that teach the agent how to work with CHAD

Source: the owner, 2026-10-06
Scope: skills

## Business
The agent has to read CHAD's answers correctly, open the policy window when asked, and run the
Selective capture flow only when the person invokes it.

## Implementation
`skills/chad` (modes, the deny list, CHAD's answers), `skills/chad-allow-deny-list` (opens the
policy window), `skills/chad-add-selective-command` (user-invoked only).

## Items
- DONE - Three skills ported to Claude Code
