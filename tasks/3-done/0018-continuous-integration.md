# 0018 Lint and tests on every push

Source: the owner, 2026-10-06
Scope: ci

## Business
Every push and pull request is checked the same way on Windows, where CHAD runs: ruff, the
Python tests, the UI typecheck and the Playwright tests.

## Implementation
`.github/workflows/ci.yml` on `windows-latest` with uv and Node 22; the window stays hidden
(`CHAD_UI_HIDDEN=1`).

## Items
- DONE - GitHub Actions workflow
