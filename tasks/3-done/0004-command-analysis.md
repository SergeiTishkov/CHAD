# 0004 A command line read statement by statement, in bash and PowerShell

Source: the owner, 2026-10-06
Scope: engine, docs

## Business
`git add . && git commit -m x` runs without asking only if every statement is allowed, so a
chain has to be split exactly as the shell splits it. Anything whose effect cannot be read from
the text (command substitution, file redirection, `eval`, `Invoke-Expression`) must never be
allowed by a rule. Claude Code writes commit messages as a quoted here-document inside `$(cat
...)`; that idiom is literal text and should not block the commit.

## Implementation
`chad/analysis.py` splits at the top level only, keeps quoted text and groups intact, strips
comments from the normalized form and lists blocking constructs per statement. Fd duplication
and redirection to the null device are not file writes.

Fixes after review: a quoted here-document ends at the first delimiter line, as bash does (the
check had matched up to a later delimiter, so commands between the two were read as message
text). Each closing bracket ends only the group it opened; in bash `{` opens a group only where
a command starts; in PowerShell `( )` runs the pipeline inside it and is a blocking construct.

## Items
- DONE - Statements, normalized text, blocking constructs, the heredoc idiom
- DONE - A quoted heredoc ends at the first delimiter line
- DONE - Brackets close only their own group; PowerShell ( ) blocks
