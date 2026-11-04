from __future__ import annotations

from pathlib import Path

from chad import atomic


def test_writes_and_replaces_without_leftovers(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "file.yaml"
    atomic.write_text(target, "one\n")
    atomic.write_text(target, "two\n")
    assert target.read_text(encoding="utf-8") == "two\n"
    assert [p.name for p in target.parent.iterdir()] == ["file.yaml"]
