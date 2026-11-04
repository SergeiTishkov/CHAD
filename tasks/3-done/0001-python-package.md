# 0001 A Python package to build CHAD in

Source: the owner, 2026-10-06
Scope: other

## Business
The backend (hook client, dispatcher, CLI) needs one package that installs into a virtual
environment with one command and depends on as little as possible.

## Implementation
`pyproject.toml` for Python 3.12+, PyYAML as the only runtime dependency, pytest and ruff for
development, managed with uv; package metadata (license, keywords, classifiers).

## Items
- DONE - Package skeleton, uv lock, dev tools
- DONE - Package metadata
