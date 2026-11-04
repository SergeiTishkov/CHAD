from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from chad import audit, messages, paths
from chad.audit import Decision
from chad.executor import CapturedOutput, ExecutionResult


def test_line_format() -> None:
    moment = datetime(2026, 10, 6, 21, 4, 11, tzinfo=timezone(timedelta(hours=4)))
    line = audit.format_line(
        Decision.ALLOW_FOREVER, "Bash", "s1", "C:/x", "git status\r\ngit log", "n", moment
    )
    assert line == (
        "2026-10-06 21:04:11 +04:00 | allowForever | Bash | session=s1 | cwd=C:/x"
        " | cmd=git status\\ngit log | note=n"
    )


def test_missing_fields_and_no_note() -> None:
    line = audit.format_line(Decision.ERROR, None, None, None, None)
    assert line.endswith("| error | - | session=- | cwd=- | cmd=")


def test_record_appends(isolated_home: Path) -> None:
    paths.ensure_root()
    audit.record(Decision.ALLOW_ONCE, "Bash", "s", "c", "ls")
    audit.record(Decision.EXPIRED, "Bash", "s", "c", "ls")
    lines = paths.audit_log_file().read_text(encoding="utf-8").splitlines()
    assert [line.split(" | ")[1] for line in lines] == ["allowOnce", "expired"]


def test_record_never_raises(tmp_path: Path) -> None:
    audit.record(Decision.ERROR, "Bash", "s", "c", "x", path=tmp_path / "missing" / "audit.log")


def test_hook_outputs() -> None:
    assert messages.NO_DECISION == {}
    assert not hasattr(messages, "allow")
    out = messages.deny(messages.expired())["hookSpecificOutput"]
    assert out == {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": messages.expired(),
    }


def test_every_model_message_is_prefixed() -> None:
    texts = [
        messages.rejected_by_user(None),
        messages.rejected_by_user("use the other branch"),
        messages.denied_by_rule("rm -rf", "rm -rf x"),
        messages.expired(),
        messages.shut_down(),
        messages.WINDOW_OPENED,
        messages.WINDOW_NOT_OPENED,
        messages.NOT_SELECTIVE,
        messages.NOTHING_CAPTURED,
        reason_of(messages.execution_failed("why")),
        reason_of(messages.execution_budget_expired()),
        reason_of(messages.executed(result(stdout=b"out"), 100_000)),
        messages.outside_selective([("git push", "no Selective rule matches it")], None, None),
        messages.outside_selective([("git push", "why")], "git", ["git status"], 1),
        messages.rules_found(("git",), ["git status"], 0, 1, 1, 1, False),
        messages.rules_found(("git",), [], 0, 0, 1, 1, False),
        messages.checked("git status", ["git status: covered by exact: git status"], True),
        messages.checked("make", ["make: no Selective rule matches it"], False),
        messages.error(messages.LOOKUP_OFF),
    ]
    assert all(t.startswith("[CHAD] ") for t in texts)
    assert "No reason was given." in texts[0]
    assert "The user's reason: use the other branch" in texts[1]


def captured(data: bytes, limit: int = 100_000) -> CapturedOutput:
    """What the executor keeps of a stream: all of it under the limit, else its two ends."""
    if len(data) <= limit:
        return CapturedOutput(data, b"", len(data), limit)
    half = limit // 2
    return CapturedOutput(data[: limit - half], data[-half:], len(data), limit)


def result(
    exit_code: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
    timed_out: bool = False,
    note: str | None = None,
    left_running: bool = False,
) -> ExecutionResult:
    return ExecutionResult(
        exit_code=exit_code,
        stdout=captured(stdout),
        stderr=captured(stderr),
        timed_out=timed_out,
        duration_seconds=1.0,
        time_limit_seconds=60.0,
        execution_note=note,
        left_running=left_running,
    )


def reason_of(output: dict) -> str:
    hook = output["hookSpecificOutput"]
    assert hook["permissionDecision"] == "deny"
    return hook["permissionDecisionReason"]


def test_an_executed_command_is_a_deny_with_its_result() -> None:
    text = reason_of(messages.executed(result(3, b"built 2 files\n", b"warning: x\n"), 100_000))
    assert text.startswith("[CHAD] COMMAND EXECUTED. Exit code: 3.")
    assert 'marks this call "denied" intentionally' in text
    assert "Do not retry it" in text
    assert "--- stdout ---\nbuilt 2 files\n" in text
    assert "--- stderr ---\nwarning: x\n" in text
    assert "omitted" not in text


def test_empty_streams_say_so() -> None:
    text = reason_of(messages.executed(result(), 100_000))
    assert "--- stdout ---\n(empty)" in text and "--- stderr ---\n(empty)" in text


def test_a_timed_out_command_says_its_output_is_partial() -> None:
    text = reason_of(messages.executed(result(-1, b"step 1\n", timed_out=True), 100_000))
    assert text.startswith("[CHAD] COMMAND TIMED OUT after 60 seconds. Exit code: -1.")
    assert "the output is partial" in text
    assert "step 1" in text


def test_an_incomplete_result_warns_that_the_command_may_have_run() -> None:
    text = reason_of(messages.executed(result(-1, note="the pipe broke"), 100_000))
    assert text.startswith("[CHAD] COMMAND RESULT INCOMPLETE.")
    assert "Its effects may have occurred; do not retry it" in text
    assert "the pipe broke" in text


def test_large_output_keeps_both_ends_within_the_budget() -> None:
    stdout = b"FIRST" + b"x" * 50_000 + b"LAST"
    text = reason_of(messages.executed(result(0, stdout, b"E" * 10_000), 4_000))
    assert "FIRST" in text and "LAST" in text
    assert "bytes omitted by CHAD" in text
    assert "output bytes were omitted to stay within the 4000-byte limit" in text
    assert len(text.encode()) < 6_000


def test_could_not_run_names_the_cause() -> None:
    text = reason_of(messages.execution_failed("The working folder does not exist: C:/gone."))
    assert text.startswith("[CHAD] CHAD COULD NOT RUN THE COMMAND. It did not run.")
    assert "The working folder does not exist: C:/gone." in text
    assert "Do not try again by yourself" in text


def test_a_process_left_running_is_named_in_the_heading() -> None:
    text = reason_of(messages.executed(result(0, b"server up\n", left_running=True), 100_000))
    assert text.startswith(
        "[CHAD] COMMAND EXECUTED. Exit code: 0. A PROCESS IT STARTED IS STILL RUNNING."
    )
    assert "its work is not finished" in text
    assert "did not stop it" in text
    assert "Do not rerun the command" in text
    assert "server up" in text
