from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from chad import paths

from . import harness
from .harness import finish_test


@pytest.fixture(autouse=True)
def stop_after(isolated_home: Path, tmp_path: Path) -> Iterator[Path]:
    """Every dispatcher a test starts, through a hook or directly, is gone when it ends."""
    paths.ensure_root()
    harness.WORK = tmp_path / "work"
    harness.WORK.mkdir()
    yield isolated_home
    finish_test()
