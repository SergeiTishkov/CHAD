# 0033 Non-ASCII commands run as written

Source: the owner, 2026-11-02
Scope: engine

## Business
A command with non-ASCII text must reach the shell as written. Cursor has been seen sending
its hook payload with UTF-8 bytes read in the ANSI code page and encoded again, so an em dash
arrives as `â€”`. A repair for that would turn such text back before the policy, the audit log
and the executor see it, and only when the reversal is exact.

Here the hook client reads stdin as bytes and decodes UTF-8, and only Claude Code's
payload is handled (a Cursor client is a possible extension in the README). Whether Claude
Code's payload ever arrives garbled was not checked.

## Implementation
The repair: if the text encoded in the ANSI code page (cp1252 and the system code page) decodes
as valid UTF-8 and differs, use the decoded text; otherwise keep the text. It runs once, in the
hook client or at the start of `Engine.hook`. Tests: an em dash, Cyrillic, text that only looks
garbled and must stay as it is.

## Items
- DONE - Integration test: a command with an em dash and Cyrillic through the hook, run in Bash and in PowerShell, reaches the shell and the audit log unchanged
  Checked 2026-11-02: Claude Code 2.1.312 writes the hook payload as raw UTF-8 (`echo "тест — ок"`
  recorded byte for byte by a test hook). The test sends the payload the same way.
Not done: the exact-reversal repair. Claude Code's payload is not garbled, and the hook client
decodes it as strict UTF-8, so bytes in another code page fail loudly rather than run garbled.
The repair would only change text that legitimately reads like `â€”`. It belongs to a Cursor
client, if one is written; README, "Adapters for the other harnesses", records it.
