"""Unit tests for LaunchAgentStore (Increment 6).

Every test runs against a temporary root or an in-memory fake: no test
touches the real ``~/Library/LaunchAgents``, ``/Library``, or launchctl.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fakes import FakeFilesystem

from task_scheduler.platform.macos import (
    LaunchAgentStore,
)


class TestRemove:

    def test_remove_missing_root_is_false(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        assert store.remove("x") is False
        assert not (tmp_path / "agents").exists()

class TestStaging:

    def test_stage_exhaustion_raises(self, tmp_path: Path) -> None:
        filesystem = FakeFilesystem(create_error=FileExistsError("taken"))
        store = LaunchAgentStore(tmp_path / "agents", filesystem=filesystem)

        with pytest.raises(RuntimeError, match="unique staged sibling"):
            store.stage_plist("x", b"x")

    def test_backup_missing_deployed_returns_none(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        assert store.backup_plist("never-there") is None

    def test_backup_exhaustion_raises(self, tmp_path: Path) -> None:
        filesystem = FakeFilesystem(
            files={"x.plist": b"old"}, create_error=FileExistsError("taken")
        )
        store = LaunchAgentStore(tmp_path / "agents", filesystem=filesystem)

        with pytest.raises(RuntimeError, match="unique backup sibling"):
            store.backup_plist("x")

    def test_remove_sibling_rejects_outside_root(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        (tmp_path / "outside.plist").write_bytes(b"x")

        with pytest.raises(ValueError, match="outside the LaunchAgent root"):
            store.remove_sibling(tmp_path / "outside.plist")

        assert (tmp_path / "outside.plist").is_file()
