"""Unit tests for LaunchAgentStore (Increment 6).

Every test runs against a temporary root or an in-memory fake: no test
touches the real ``~/Library/LaunchAgents``, ``/Library``, or launchctl.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fakes import FakeFilesystem

from task_scheduler.platform.macos import LaunchAgentStore, SourceSnapshot


class TestRemove:
    def test_remove_missing_root_is_false(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        assert store.remove("x") is False
        assert not (tmp_path / "agents").exists()


class TestExternal:
    @pytest.mark.parametrize(
        "method",
        [
            "read_external",
            "stage_external",
            "activate_external",
        ],
    )
    def test_external_rejects_outside_root(self, tmp_path: Path, method: str) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        outside = tmp_path / "outside.plist"
        outside.write_bytes(b"data")
        kwargs: dict = {}
        if method == "read_external":
            fn = store.read_external
        elif method == "stage_external":
            fn = lambda p, payload=None: store.stage_external(p, payload)  # noqa: E731
            kwargs = {"payload": b"new"}
        else:
            staged = tmp_path / "staged.plist"
            staged.write_bytes(b"staged")
            fn = (  # noqa: E731,E501
                lambda s=staged, d=outside: store.activate_external(
                    s, d, SourceSnapshot(payload=b"", sha256="", st_dev=0, st_ino=0, st_size=0)
                )
            )
            kwargs = {}
        with pytest.raises(ValueError, match="outside the LaunchAgent root"):
            fn(outside, **kwargs)


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


class TestExternalEdgeCases:
    def test_stage_external_exhaustion_raises(self, tmp_path: Path) -> None:
        filesystem = FakeFilesystem(create_error=FileExistsError("taken"))
        store = LaunchAgentStore(tmp_path / "agents", filesystem=filesystem)
        with pytest.raises(RuntimeError, match="unique staged sibling"):
            store.stage_external(tmp_path / "agents" / "x.plist", b"new")

    def test_activate_external_rejects_outside_destination(self, tmp_path: Path) -> None:
        filesystem = FakeFilesystem(files={"x.plist": b"old", "x.plist.staged.1": b"new"})
        store = LaunchAgentStore(tmp_path / "agents", filesystem=filesystem)
        snapshot = filesystem.read_snapshot(tmp_path / "agents" / "x.plist")
        with pytest.raises(ValueError, match="outside the LaunchAgent root"):
            store.activate_external(
                tmp_path / "agents" / "x.plist.staged.1",
                tmp_path / "outside.plist",
                snapshot,
            )
        assert "x.plist" not in filesystem.replaced
