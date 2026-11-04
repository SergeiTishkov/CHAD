# 0047 CI is green on a UTC runner

Source: the owner, 2026-11-05, after a GitHub mail "Run failed: CI - main": every CI run since
the first push failed. Its log (`gh run view --log-failed`): one test,
`test_audit_messages.py::test_line_format`, expected `21:04:11 +04:00` and got the same moment
in the runner's zone, UTC.
Scope: engine, ci

## Business
CI on GitHub is red on every push, so a real failure there would not stand out. The cause is in
CHAD, not in the runner: `audit._timestamp` moved a time that already had its zone into the
machine's zone. The audit log itself was right, because CHAD always passes no time and writes
the local one; only a caller that passes a time with its own zone got it moved.

## Implementation
`_timestamp` keeps the zone of a time that has one, and takes the local zone for the current
time and for a time without a zone. A test runs the same moment under a different local zone.

## Items
- DONE - `audit._timestamp` keeps the zone a given time carries
- DONE - Test: the line keeps `+04:00` whatever the local zone is
- DONE - The actions in `ci.yml` moved to their Node 24 versions (the runner warned that
  `actions/checkout@v4` and `astral-sh/setup-uv@v6` target the deprecated Node 20)
