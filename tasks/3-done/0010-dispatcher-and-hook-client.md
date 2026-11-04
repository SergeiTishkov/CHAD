# 0010 A dispatcher that answers every hook, started on demand

Source: the owner, 2026-10-06
Scope: engine

## Business
Claude Code runs a short-lived hook for every shell call; the policy and the queue need one
long-running process shared by all sessions. If that process is not running, the first hook
starts it. If anything fails, the hook gives no decision and Claude Code asks as usual: CHAD
never leaves the agent stuck. A hook the person interrupts withdraws its question.

## Implementation
`chad/server.py`: newline-delimited JSON over TCP on 127.0.0.1 with a token, one request per
connection; `subscribe` streams state on every change and notices hand edits by polling.
`chad/dispatcher.py`: single instance per data root under a lock; `chad/uilaunch.py` supervises
the UI. `chad/hook.py`: starts a detached dispatcher under a launch lock when none answers,
relays the payload, always prints valid JSON. Unused members removed afterwards.

## Items
- DONE - TCP server, protocol client, file locks
- DONE - Dispatcher process and UI supervisor
- DONE - Hook client with cold start and fail-open
- DONE - Remove members nothing uses
