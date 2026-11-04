# 0048 setup-uv pinned to a release that exists

Source: the agent, 2026-11-05, fixing what 0047 delivered: the first CI run after it stopped at
"Set up job" with "Unable to resolve action `astral-sh/setup-uv@v10`, unable to find version
`v10`". setup-uv publishes exact release tags (v10.3.3) and no moving major tag, unlike
actions/checkout and actions/setup-node, whose v7 tags exist.
Scope: ci

## Business
CI has to start at all before it can say anything about the code.

## Implementation
`ci.yml` names `astral-sh/setup-uv@v10.3.3`, the latest release.

## Items
- DONE - `ci.yml` uses `astral-sh/setup-uv@v10.3.3`
