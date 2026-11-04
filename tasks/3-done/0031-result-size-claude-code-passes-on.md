# 0031 The result fits what Claude Code passes to the model

Source: the owner, 2026-11-02: review of 0019
Scope: engine, docs

## Business
CHAD returns up to 100000 bytes of output inside `permissionDecisionReason`. Whether Claude
Code passes a reason that long to the model whole, or cuts it, was not checked. If it cuts, the
agent loses the end of the output, where errors usually are, without being told.

## Implementation
Measure with a real `claude -p` run (the opt-in suite, 0015) what reaches the model for reasons
of growing size. Set the `maxOutputBytes` default below that limit and record it in the SPEC.

## Items
- DONE - Measure the limit and write it here
  Measured 2026-11-02 with a test hook (not CHAD) through `claude -p --settings`, model haiku,
  Claude Code 2.1.220 (the CLI on PATH) and 2.1.312 (the VS Code extension's binary): a deny
  reason of 126015 characters in 3002 lines reached the model whole, first and last line
  included. No cut up to that size; larger sizes were not tried. The 2.1.312 binary holds
  limits of 2000 characters and 20 lines for `permissionDecisionReason`, but that code returns
  the text unchanged for hooks from the user's own Claude Code files, which is where CHAD is.
  Claude Code's own Bash and PowerShell tools pass 30000 characters of output inline by
  default (`bashOutputMaxChars`, 4000-128000) and save the rest to a file.
- DONE - Default and SPEC to match: 30000, the owner chose "as is best" (2026-11-02)
