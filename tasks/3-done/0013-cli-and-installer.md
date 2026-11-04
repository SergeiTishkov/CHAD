# 0013 The chad CLI and a per-user installer

Source: the owner, 2026-10-06
Scope: cli

## Business
The person installs CHAD for their user with one command, removes it with another, and
controls it from any shell: status, mode, deny list, open the window, start and stop.

## Implementation
`chad/cli.py` and `chad/installer.py`: install sets `CHAD_HOME`, merges the hook into the
user's Claude Code settings with a backup, copies the skills, writes `chad` shims and registers
autostart (Windows only, and says so elsewhere). Isolated runs refuse the real folders.
Uninstall also clears the mode and deny switches. Mode names print as the CLI takes them
(`allow-all`), and a dispatcher that does not answer is an error line, not a traceback.

## Items
- DONE - CLI and installer
- DONE - Uninstall resets the switches
- DONE - Mode names as the CLI takes them; no traceback for a silent dispatcher
