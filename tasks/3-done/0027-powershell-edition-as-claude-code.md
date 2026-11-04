# 0027 PowerShell calls run in the PowerShell Claude Code would use

Source: the owner, 2026-11-02: review of 0019
Scope: engine

## Business
0019's executor always runs Windows PowerShell 5.1 (`powershell.exe`) on Windows. If Claude
Code's PowerShell tool uses PowerShell 7 (`pwsh`) when it is installed, commands written for 7
(`&&`, `||`, `??`, `?.`) fail with a parser error when CHAD runs them.

## Implementation
First check which edition Claude Code's PowerShell tool runs and how it chooses. Then choose the
same way in `executor._powershell_executable`, with a config override if Claude Code has one.

## Items
- DONE - Find out which PowerShell Claude Code uses, and write it here. Claude Code 2.1.312,
  strings in its binary: the PowerShell tool runs "PowerShell 7 when installed, including
  Microsoft Store installs, else Windows PowerShell 5.1"; the model's prompt has two variants,
  "PowerShell 7+ (pwsh)" with `&&`, `||`, `?:`, `??`, `?.` available, and 5.1 without them. No
  setting to choose the edition was found. On the owner's machine (2026-11-02) pwsh is not
  installed, so Claude Code and CHAD both run 5.1 there; the mismatch appears where pwsh is
  installed. CHAD's analysis already splits `&&` and `||` into statements and blocks `( )`, so
  rules are not affected, only the run.
- DONE - Use the same edition: `pwsh` on the PATH of the call's environment (0026), then
  `%ProgramFiles%\PowerShell\7\pwsh.exe`, then `%LOCALAPPDATA%\Microsoft\WindowsApps\pwsh.exe`,
  else `powershell.exe`; the same for background calls (0024). SPEC §6.3
- DONE - Unit tests of the lookup with fake installs in a temp folder (PATH first, install
  folder, Store, 5.1 on PATH and in System32, none at all, PATH whatever its case)
- DONE - Integration tests: the edition that runs is 7 when pwsh is installed, else 5; with
  pwsh, `&&` and `??` work
- Not checked: running under PowerShell 7. pwsh is not installed on the owner's machine and the
  repository has no remote, so CI has not run; the two integration tests and the PowerShell
  tests of 0019, 0024 and 0025 cover it where pwsh is installed (GitHub's Windows runners have
  it). Of those, the background pipeline (0024) and the CLIXML cleaning are the ones written
  against 5.1 output.
