# 0005 Allow rules that generalise: exact, word patterns, regex, Selective first

Source: the owner, 2026-10-06
Scope: engine

## Business
Approving `git commit -m "fix typo"` the person can store `git commit -m *`: anything after
`-m`, no other git verb. The list should not fill with narrow rules a wider one already covers.
Selective rules (the curated set for Selective mode) are kept apart from ordinary ones. A
broken file must not allow anything by accident.

## Implementation
`chad/patterns.py`: word-wildcard patterns with subsumption, matching memoized per call.
`chad/allowlist.py`: exact, pattern and regex rules in two tiers, Selective ahead; a new
pattern prunes what it makes redundant within its tier; live reload. A malformed file, an
unknown rule kind included, allows nothing and is reported.

## Items
- DONE - Word-wildcard patterns with subsumption
- DONE - Allow list in two tiers with pruning and live reload
- DONE - Matching memoized per call, not for the life of the process
- DONE - An unknown rule kind makes the list malformed instead of being dropped silently
