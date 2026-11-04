# 0014 The tray app: approval and policy windows

Source: the owner, 2026-10-06
Scope: ui, docs

## Business
The person sees every waiting command in one window, one at a time, edits the rule word by
word with a live preview, and cannot approve by an accidental click. A second view switches the
mode and the deny list and edits both lists. The tray icon shows the mode by colour.

## Implementation
Electron main process subscribes to the dispatcher and reconnects when it restarts, raises the
window when attention is requested; the renderer gets a sandboxed preload bridge only. The
approval view has an arming delay and a two-step deny. The UI is started without
`ELECTRON_RUN_AS_NODE`, which VS Code sets for its children. Playwright tests run the real
dispatcher, hooks and app with the window off screen; screenshots for the README are rendered
on request (`CHAD_SCREENSHOTS=1`).

## Items
- DONE - Start the UI without ELECTRON_RUN_AS_NODE
- DONE - Tray app with dispatcher subscription, window and tray menu
- DONE - Approval and policy views
- DONE - Playwright end-to-end tests
- DONE - Screenshots of both windows in the README
