# 0006 A deny list that outranks every yes

Source: the owner, 2026-10-06
Scope: engine

## Business
Some commands must be refused whatever else says yes, and rewording must not get around it:
`rm -rf` should also catch `rm build -rf` and `bash -c "rm -rf /"`.

## Implementation
`chad/denylist.py`: a rule matches when all its words appear anywhere in a statement. Quotes,
parentheses and braces separate words; a path-qualified program also counts as its bare name.
Live reload; a broken file keeps the built-in rules and is left alone.

## Items
- DONE - Word-presence deny rules with live reload and built-in defaults
