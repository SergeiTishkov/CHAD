# 0034 The policy window scrolls instead of being cut off

Source: the owner, 2026-11-02
Scope: ui

## Business
A policy window that grows with its lists can clip its content, so the lower rows cannot be
reached. The window must scroll instead.

## Implementation
Reproduce in a Playwright test with an allow list longer than the window; the lists scroll
inside a fixed-height window.

## Items
- DONE - Reproduce with a long list; make the view scroll; Playwright test
  The window was not cut off: the page itself scrolls. The Playwright test adds 40 rules,
  scrolls with the mouse wheel until the last row is in view and deletes it; with scrolling
  turned off in the stylesheet it fails.
- DONE - The UI tests ran their hook commands in the repository (`git commit`, `git push`) and
  still expected `allow`. They run in a folder of the test's data root now, and expect CHAD's
  deny with the output (`ranByChad`).
