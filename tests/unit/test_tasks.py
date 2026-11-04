"""tasks/: the list of work, one Markdown file per task, the folder its stage (the owner,
2026-11-02; the format is tasks/README.md)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import tasks as tasks_tool  # noqa: E402

TASKS = ROOT / "tasks"
STAGES = ("0-potential", "1-triage", "2-to-do", "3-done", "4-cancelled")
NAME = re.compile(r"^(\d{4})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
MARK = re.compile(r"^(?:- |### )(TO DO|DONE) - \S")
# a line that means to be a mark but is spelled another way
MARK_LIKE = re.compile(r"^(?:- |### )(?:to[ -]?do|done)\b", re.IGNORECASE)


def _tickets():
    for stage in STAGES:
        # git keeps no empty folder: an emptied stage is absent in a clone
        if (TASKS / stage).is_dir():
            for path in sorted((TASKS / stage).iterdir()):
                yield stage, path


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_no_folder_but_the_five_stages() -> None:
    assert {p.name for p in TASKS.iterdir() if p.is_dir()} <= set(STAGES)


def test_a_task_is_a_numbered_markdown_file_with_a_number_of_its_own() -> None:
    seen: dict[str, str] = {}
    for stage, path in _tickets():
        match = NAME.match(path.name)
        assert match, f"{stage}/{path.name}: expected NNNN-a-few-words.md"
        number = match.group(1)
        assert number not in seen, f"{number} is both {seen[number]} and {stage}/{path.name}"
        seen[number] = f"{stage}/{path.name}"
        assert _lines(path)[0].startswith(f"# {number} "), (
            f"{seen[number]}: the title starts with '# {number} '"
        )


def test_the_business_comes_first() -> None:
    for stage, path in _tickets():
        headings = [line for line in _lines(path) if line.startswith("## ")]
        assert headings and headings[0] == "## Business", (
            f"{stage}/{path.name}: first section is '## Business'"
        )


def test_every_task_names_its_scope() -> None:
    for stage, path in _tickets():
        lines = _lines(path)
        scopes = [line for line in lines if line.startswith("Scope:")]
        where = f"{stage}/{path.name}"
        assert len(scopes) == 1, f"{where}: one 'Scope: <scope>, <scope>' line"
        assert lines.index(scopes[0]) < lines.index("## Business"), (
            f"{where}: Scope comes before ## Business"
        )
        errors = tasks_tool.scope_errors(scopes[0][len("Scope:") :])
        assert not errors, f"{where}: " + "; ".join(errors)


def test_a_scope_is_one_or_more_from_the_list() -> None:
    assert tasks_tool.scope_errors(" engine, docs") == []
    assert tasks_tool.scope_errors("") and tasks_tool.scope_errors(" , ")
    assert tasks_tool.scope_errors("misc")
    assert tasks_tool.scope_errors("engine, engine")


def test_marks_are_spelled_one_way_and_agree_with_the_stage() -> None:
    for stage, path in _tickets():
        marks = []
        for number, line in enumerate(_lines(path), 1):
            if MARK_LIKE.match(line):
                match = MARK.match(line)
                assert match, (
                    f"{stage}/{path.name}:{number}: write '- TO DO - <what>' or '- DONE - <what>'"
                )
                marks.append(match.group(1))
        assert marks, f"{stage}/{path.name}: no items"
        if stage == "4-cancelled":
            continue  # left as it stood when the owner cancelled it
        if stage == "3-done":
            assert "TO DO" not in marks, f"{path.name}: a TO DO left in a DONE task"
        else:
            assert "TO DO" in marks, (
                f"{stage}/{path.name}: nothing left to do, so it belongs in 3-done"
            )


def test_a_cancelled_task_says_who_cancelled_it_when_and_why() -> None:
    """Work decided against keeps its file, in 4-cancelled, with the decision on a
    'Cancelled:' line under 'Source:'."""
    for path in sorted((TASKS / "4-cancelled").glob("*.md")):
        lines = _lines(path)
        cancelled = [line for line in lines if line.startswith("Cancelled: ")]
        assert len(cancelled) == 1, (
            f"4-cancelled/{path.name}: one 'Cancelled: <who, when>: <why>' line"
        )
        assert lines.index(cancelled[0]) < lines.index("## Business"), (
            f"4-cancelled/{path.name}: Cancelled comes before ## Business"
        )


def test_a_new_task_takes_the_next_number_and_passes_the_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for stage in STAGES:
        (tmp_path / stage).mkdir()
    (tmp_path / "3-done" / "0007-old-work.md").write_text("# 0007 Old work\n", encoding="utf-8")
    monkeypatch.setattr(tasks_tool, "TASKS", tmp_path)
    assert tasks_tool.next_number() == "0008"
    path = tasks_tool.new("to-do", "a-fix", "A fix", "the owner", "Why.", "engine,docs")
    assert path.name == "0008-a-fix.md" and path.parent.name == "2-to-do"
    lines = _lines(path)
    assert lines[0] == "# 0008 A fix"
    assert "Scope: engine, docs" in lines
    assert [line for line in lines if line.startswith("## ")][0] == "## Business"
    last = MARK.match(lines[-1])
    assert last and last.group(1) == "TO DO"
    assert tasks_tool.find(["fix"]) == [path]


def test_a_new_task_goes_into_a_stage_git_did_not_keep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks_tool, "TASKS", tmp_path)
    path = tasks_tool.new("triage", "an-idea", "An idea", "the agent", "Why.", "engine")
    assert path.parent == tmp_path / "1-triage" and path.is_file()
    path = tasks_tool.new("potential", "a-question", "A question", "the owner", "Why.", "ui")
    assert path.parent == tmp_path / "0-potential" and path.name.startswith("0001-")


def test_a_new_task_needs_a_scope_from_the_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for stage in STAGES:
        (tmp_path / stage).mkdir()
    monkeypatch.setattr(tasks_tool, "TASKS", tmp_path)
    with pytest.raises(SystemExit):
        tasks_tool.new("to-do", "a-fix", "A fix", "the owner", "Why.", "misc")
    assert not list((tmp_path / "2-to-do").iterdir())


def test_a_deleted_task_keeps_its_number(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A task that needed no commit is deleted (tasks/README.md); git history still knows its
    number, and the next task does not take it again."""

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    for stage in STAGES:
        (tmp_path / stage).mkdir()
    (tmp_path / "3-done" / "0007-old-work.md").write_text("# 0007 Old work\n", encoding="utf-8")
    (tmp_path / "2-to-do" / "0008-no-commit-needed.md").write_text("# 0008 x\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "two tasks")
    git("rm", "-q", "2-to-do/0008-no-commit-needed.md")
    git("commit", "-q", "-m", "drop the task that needed no commit")
    monkeypatch.setattr(tasks_tool, "TASKS", tmp_path)
    assert tasks_tool.next_number() == "0009"
