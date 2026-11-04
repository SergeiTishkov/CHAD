# 0030 Output of Windows programs is readable in the result

Source: the owner, 2026-11-02: review of 0019
Scope: engine

## Business
Why this is in POTENTIAL (the owner, 2026-11-02): the bug was seen in another agent harness, not
in Claude Code. The check below shows Claude Code's own Bash tool gives the same replacement
characters as CHAD, so under Claude Code CHAD changes nothing. The owner watches whether it
matters in practice, in Claude Code or when CHAD serves another harness, before anything is
decided.

The executor decodes all output as UTF-8. Many Windows programs write in the console's OEM
code page or the ANSI code page (cp866 and cp1251 on a Russian system): `ipconfig`, `ping`,
`net`, `cmd /c dir` with non-ASCII names. Their non-ASCII text reaches the agent as
replacement characters.

Checked 2026-11-02 on the owner's machine (ACP 1251, OEM code page 866), a folder with
`тест-файл.txt`, through `executor.run`:
- Bash: `cmd //c dir //b` and `cmd //c echo привет` → replacement characters; `ls` and
  `echo привет` → readable.
- PowerShell: `cmd /c dir /b`, `cmd /c echo привет`, `Get-ChildItem`, `Write-Output` → all
  readable: CHAD's script sets `[Console]::OutputEncoding` to UTF-8, and programs it starts
  write UTF-8 too.
- Claude Code's own Bash tool, the same two `cmd` commands → the same replacement characters.
  So CHAD shows what Claude Code shows; it is not a difference 0019 brought in.
- System messages are in English on this machine (`net help`), so only non-ASCII names and
  text are affected.

## Implementation
To work out: run the command with the UTF-8 code page where the shell allows it, or decode
bytes that are not valid UTF-8 with the console's code page. Test with a program that prints
non-ASCII text in the OEM code page.

## Items
- TO DO - Work out the plan and write it here as the next items
