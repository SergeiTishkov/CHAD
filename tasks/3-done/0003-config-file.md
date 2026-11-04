# 0003 config.yaml: timeouts and UI launch

Source: the owner, 2026-10-06
Scope: engine

## Business
The approval budget must end before Claude Code gives up on the hook, so the person always gets
CHAD's answer rather than a timed-out hook. Running without the tray window has to be possible.

## Implementation
`config.yaml` in the data root: `hookTimeoutSeconds` (3600, equal to the hook registration),
`safetyMarginSeconds` (30), `launchUi`, `uiCommand`. A broken file falls back to the defaults.

## Items
- DONE - config.yaml with defaults and a commented template
