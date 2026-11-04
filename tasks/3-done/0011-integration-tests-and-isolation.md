# 0011 Tests that run the real processes and never touch the real setup

Source: the owner, 2026-10-06
Scope: tests

## Business
The behaviour that matters happens between processes: Claude Code starting a hook, the hook
starting a dispatcher, two hooks starting at once. Those paths are tested with real processes.
A test run must never change the person's Claude Code settings, registry or switches.

## Implementation
`tests/integration/harness.py` runs the hook client and the dispatcher as processes and drives
approvals through the UI protocol: cold and concurrent starts, every decision path, control
markers, expiry, shutdown, live reload, withdrawal, fail-open. Every test gets its own
`CHAD_HOME` with `CHAD_ISOLATED=1` and a temporary `CLAUDE_CONFIG_DIR`; the registry
round-trip needs `CHAD_TEST_REGISTRY=1`; the isolated-mode guard also refuses the folder
`CLAUDE_CONFIG_DIR` names.

## Items
- DONE - Integration harness and hook-flow tests
- DONE - Test runs isolated from the real user environment
- DONE - Guard against CLAUDE_CONFIG_DIR pointing at the real folder
