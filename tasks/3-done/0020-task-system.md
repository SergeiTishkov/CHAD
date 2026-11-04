# 0020 A list of work in tasks/, and every commit names its task

Source: the owner, 2026-11-02: copy the task system of Work IDE, with its documentation
Scope: tasks, rules, docs, ci

## Business
The owner tracks work on CHAD the way Work IDE does: one file per task, the folder its stage,
and every commit names the task it belongs to. The history so far is written down as done
tasks, so the list starts complete, and what is left to do is in the same place.

## Implementation
Copied from Work IDE and adapted: `tasks/README.md` (format, stages, scopes for CHAD's areas),
`tools/tasks.py` (`next`, `find`, `new`, `log`), `.githooks/commit-msg`,
`tests/unit/test_tasks.py`, `tests/integration/test_commit_hook.py` (the check that the hook is
on is skipped in CI, where no commits are made), the `task` skill in `.claude/skills/task/`,
and the "Tasks" and "Commits" sections of `CLAUDE.md`. Every task names its scope from the
start. Ruff now checks `tools/` as well, locally and in CI.

## Items
- DONE - tasks/README.md, tools/tasks.py, the commit hook, their tests, the task skill
- DONE - CLAUDE.md "Tasks" and "Commits"; README "Development"; ruff on tools/ in CI
- DONE - Tasks 0000-0019 written from the git history
- DONE - Turn the hook on in this clone and commit with it
