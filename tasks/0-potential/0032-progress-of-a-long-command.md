# 0032 The person sees that a long command is running

Source: the owner, 2026-11-02: review of 0019
Scope: engine, ui

## Business
When Claude Code runs a command itself, its output appears as it comes. When CHAD runs it,
Claude Code shows a hook that is running and nothing else until the command ends, up to 30
minutes. The person cannot tell a long build from a command that hangs, and cannot stop only
that command.

## Why this is in POTENTIAL
The owner, 2026-11-02: not for now. CHAD is a cross-harness tool and does not follow one
harness's features; waiting several minutes for a command is acceptable.

## Implementation
To work out: the tray window lists running commands with elapsed time and the latest output
lines, and can stop one; or a per-command log file in the data root.

## Items
- TO DO - Work out the plan and write it here as the next items
