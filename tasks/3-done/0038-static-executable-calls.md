# 0038 Calls to a program by its path can be approved and remembered

Source: the owner, 2026-11-02
Scope: engine, docs

## Business
In PowerShell, every `&` call operator is a blocking construct, so
`& "C:\Tools\build.exe" --release` asks every time and can never become a rule. Wanted: a call whose target is a literal path or name (`& "C:\x\tool.exe" args`,
`& .\run.cmd`) can be approved and remembered, and a remembered `.exe` or `.cmd` call is
allowed when it comes again. A call whose target is computed (`& $tool`, `& (Get-Command x)`,
a script block) stays blocking.

## Implementation
`analysis.py`: `&` followed by a quoted or bare literal word is not blocking; a target with a
variable, subexpression or script block still is. Check that remembered rules for `tool.exe`
and `tool.cmd` calls match on the next call, in both shells, and fix what does not. SPEC §5.3.

## Items
- DONE - Reproduce what fails today for .exe and .cmd calls, and write it here
  Checked 2026-11-03 (analysis plus an exact rule stored and matched again). Only the `&` call
  operator fails: `& "C:\Tools\build.exe" --release`, `& .\run.cmd` and
  `& 'C:\Program Files\Git\bin\git.exe' status` are blocking, so they ask every time and
  cannot be stored. Without `&` the same calls are not blocking and a stored rule matches them
  again: PowerShell `C:\Tools\build.exe --release`, `.\run.cmd test`; bash
  `/c/Tools/build.exe --release`, `./run.cmd test`, `"C:\Program Files\x\tool.exe" a`. A path
  with a space needs `&` in PowerShell, so programs under Program Files are the case that
  matters. The deny list already sees through the call: `git.exe` in a quoted path counts as
  `git`.
- DONE - Static & targets not blocking, dynamic ones blocking; tests
- DONE - Integration test: a `.cmd` and an `.exe` called with `&` are allowed forever with a
  wildcard and run again without asking; `& $env:ComSpec` is still asked about
- DONE - SPEC
