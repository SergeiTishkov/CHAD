# 0043 One commit of history before publishing

Source: the owner, 2026-11-05: "Историю сожми."
Scope: tasks, rules

## Business
Before the repository goes public, its history is one commit, so the public history shows the
finished state and none of the steps that led to it.

## Implementation
Back up the full history as a git bundle outside the repository, then make an orphan commit of
the current tree and let it replace `main`. The task files stop citing commit hashes that the
public history does not have: the `Commits:` lines of 0000-0019 go, `tasks/README.md` says the
history was squashed, 0039 no longer names a commit.

## Items
- DONE - Full history kept in C:\repos\_secondary\CHAD-history-before-squash-2026-11-05.bundle
  (outside the repository, verified with `git bundle verify`)
- DONE - Commit hashes removed from the task files; tasks/README.md says the history was squashed
- DONE - `main` is one orphan commit of the tree as of task 0042
