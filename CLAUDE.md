# CHAD - notes for working on this repository

- **CHAD never answers `allow`** (the owner, 2026-11-02: a requirement of the project, not a
  design choice to revisit). It has two answers. `deny`: the reason says the command was refused
  and why, carries the output of the run CHAD did itself, or says CHAD failed and why. Skip (no
  decision, `{}`): CHAD hands the call back and the harness decides; this is for Off mode and,
  in Selective mode, a command no Selective rule covers. No mode, fix or feature may return
  `allow` or ask Claude Code to run a command CHAD approved; a feature that seems to need it is
  designed another way. The reason is the name: Cross Harness Allow/Deny gives many agent
  harnesses one behaviour by the simplest means there is. Every harness with a pre-command hook
  can refuse a call with a text for the model, or leave it alone; what an `allow` leads to
  differs from harness to harness.
- `docs/SPEC.md` is the contract. Change the spec in the same commit as behaviour that departs
  from it.
- Python: `uv sync`, then `uv run ruff format src tests tools`, `uv run ruff check src tests tools`,
  `uv run pytest`. UI: `cd ui && npm run typecheck && npm test`.
- Integration tests are preferred over unit tests. They run the real hook client
  (`python -m chad.hook`) and dispatcher as processes; see `tests/integration/harness.py`.
- Never install CHAD into the real user setup while developing: no `chad install` without
  `--claude-dir`/`--bin-dir` pointing at temporary folders, no writes to the real
  `~/.claude/settings.json`, `HKCU\Environment` or the Run key. Tests set `CHAD_ISOLATED=1`,
  which also makes the installer refuse the real folders.
- A hook registered in the session you are working in would intercept your own commands. Use
  `claude -p --settings <temp file>` for manual end-to-end checks.
- VS Code sets `ELECTRON_RUN_AS_NODE=1` for child processes; anything that launches Electron
  must drop it (`chad.uilaunch.ui_environment`, `ui/tests/fixtures.ts`).
- Policy lives only in the dispatcher (`chad.policy.Engine`). The hook client and the UI hold no
  rules; the UI's rule preview (`ui/src/renderer/rules.ts`) mirrors `chad/approvals.py` and the
  backend re-validates.

## Tasks

Work is tracked in `tasks/` (the owner, 2026-11-02): **every change is a task, every commit
names its task**, a one-line fix included. The format is `tasks/README.md`; the procedure is the
`task` skill (`.claude/skills/task/SKILL.md`), used before the first edit of any change and
before every commit.

- Find the task first: `python tools/tasks.py find <words>`. Work the owner asked for that has
  no task gets one in `tasks/2-to-do/`; an idea of the agent's own goes to `tasks/1-triage/` and
  waits for the owner; a question the owner will check in practice goes to `tasks/0-potential/`.
  A fix to what a done task delivered is a new task that names the old one.
- Every commit carries a `Task: NNNN` line and changes that task's file in the same commit: the
  items it finishes marked DONE, the work it does added as items, the file moved to
  `tasks/3-done/` with its last item. A task in `0-potential/`, `1-triage/` or `4-cancelled/`
  covers no work outside `tasks/`.
- The one kind of commit with no task: one that changes task files only. A change to the task
  system itself (`tasks/README.md`, the hook, its tests, `tools/tasks.py`) has a task.
- `.githooks/commit-msg` refuses a commit that breaks this
  (`git config core.hooksPath .githooks`, once per clone). Never `--no-verify`.

## Commits

The agent runs git and commits by itself, on `main`, without being asked and without waiting
for anyone to try the change by hand (the owner, 2026-11-02: the project is 100% vibe coded,
and all code checks are done by AI).
This overrides a global "commit only when asked" rule for this repository. A fix found later
is a new commit, never an amend.

One commit per finished, self-contained piece of work, made when it is done. When several pieces
end up in one commit anyway, its message lists **every** change of behaviour it carries, not
only the latest one: the history is read to find when and why a behaviour changed.
