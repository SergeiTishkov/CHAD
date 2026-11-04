# 0000 The specification: what CHAD does, written before the code

Source: the owner, 2026-10-06
Scope: docs

## Business
CHAD decides which shell commands an AI coding agent runs, from a desktop app. The behaviour
had to be agreed before the code: the policy, the approval flow, how the hook, the dispatcher
and the window talk, and how CHAD is installed. Code and tests are written against this one
document; where the two disagree, one of them is a bug.

## Implementation
`docs/SPEC.md`, version 1: purpose, terms, architecture and wire protocol, the Claude Code hook
contract, modes and switches, command analysis, the policy and its decision order, control
requests, approval, the UI, dispatcher lifecycle, audit log, messages to the model, CLI,
installation, skills, tests. Later commits that change behaviour change the spec with it.

## Items
- DONE - Write docs/SPEC.md
- DONE - Describe how CHAD's answers combine with Claude Code's permission settings
