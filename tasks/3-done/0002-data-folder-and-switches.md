# 0002 A data folder and mode switches that every shell sees at once

Source: the owner, 2026-10-06
Scope: engine, ui

## Business
The person switches CHAD's mode from the window, the CLI or by asking the agent, and the next
command must obey it with nothing restarted. Claude Code copied its environment when it
started, so a switch kept in the process environment would not reach it. Tests must never read or
write the person's real switches.

## Implementation
Switches are user environment variables (`HKCU\Environment` on Windows), read on every hook
call. `CHAD_ISOLATED=1` swaps them for `user-environment.json` in the data root. The data root
is `CHAD_HOME`, by default `%LOCALAPPDATA%\CHAD` or `$XDG_STATE_HOME/chad`; the UI mirrors the
same default. Files are written atomically. `CHAD_HOME` is read from the registry on Windows
only, since elsewhere the lookup recursed.

## Items
- DONE - Data paths and atomic writes
- DONE - Switches in the user environment, isolated mode for tests
- DONE - CHAD_HOME from the registry on Windows only
- DONE - The UI uses the same data folder default, XDG_STATE_HOME included
