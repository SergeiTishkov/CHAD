# 0036 A command that writes to one fixed local file can be remembered

Source: the owner, 2026-11-02
Scope: engine, ui, docs

## Business
Any redirection to a file is a blocking construct, so `dotnet test *> red-run.log` asks every
time and can never become a rule. Wanted: such a redirect can be remembered when its
target is one literal path inside the working folder. A wildcard does not cover a redirect:
`dotnet test *` does not match `dotnet test > out.log`.

## Why it is blocking today
Checked 2026-11-02. A redirect is part of the statement's words (`echo hi > ~/.bashrc` is
`echo`, `hi`, `>`, `~/.bashrc`), and a pattern's `*` takes any words, so `echo *` matches it
(`Pattern.parse("echo *").matches(...)` is True). Without the block, every pattern rule for a
command that prints would also write any file the agent names, `~/.bashrc` included. The block
keeps redirects out of rules altogether. Written without spaces (`dotnet test>out.log`) the
redirect is not even a word of its own.

## Implementation
`analysis.py`: a redirect whose target is a literal relative path (no variables, globs or `..`)
inside `cwd` is not blocking, and is kept as part of the statement. A rule must name it
literally. Patterns do not let `*` absorb a redirection operator or its target. Every other
redirect stays blocking. SPEC §5.1 and §6.1.

## Items
- DONE - Literal local redirect targets are rememberable; tests for both shells
- DONE - A wildcard never matches a redirect; tests
- DONE - Redirect operators are words of their own, so `dotnet test>out.log` is ruled like
  `dotnet test > out.log`; the window's preview follows the same rule (`rules.ts`)
- DONE - SPEC
