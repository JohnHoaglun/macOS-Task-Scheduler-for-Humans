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
    SourceChangedError,
    SourceSnapshot,
)


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
            "backup_external",
            "activate_external",
        ],
    )
    def test_external_rejects_outside_root(
        self, tmp_path: Path, method: str
    ) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        outside = tmp_path / "outside.plist"
        outside.write_bytes(b"data")
        kwargs: dict = {}
        if method == "read_external":
            fn = store.read_external
        elif method == "stage_external":
            fn = lambda p, payload=None: store.stage_external(p, payload)  # noqa: E731
            kwargs = {"payload": b"new"}
        elif method == "backup_external":
            fn = store.backup_external
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

    def test_read_external(self, tmp_path: Path) -> None:
        plist = tmp_path / "agents" / "io.example.job.plist"
        plist.parent.mkdir(parents=True)
        plist.write_bytes(b"xml-data")
        store = LaunchAgentStore(tmp_path / "agents")
        snap = store.read_external(plist)
        assert snap.payload == b"xml-data"
        assert snap.sha256 != ""
        assert snap.st_size == 8

    def test_stage_external_creates_sibling(self, tmp_path: Path) -> None:
        plist = tmp_path / "agents" / "io.example.job.plist"
        plist.parent.mkdir(parents=True)
        plist.write_bytes(b"original")
        store = LaunchAgentStore(tmp_path / "agents")
        staged = store.stage_external(plist, b"new-payload")
        assert staged.name == "io.example.job.plist.staged.1"
        assert staged.read_bytes() == b"new-payload"

    def test_stage_external_uniqueness_on_collision(self, tmp_path: Path) -> None:
        plist = tmp_path / "agents" / "io.example.job.plist"
        plist.parent.mkdir(parents=True)
        plist.write_bytes(b"original")
        fs = FakeFilesystem(
            files={"io.example.job.plist.staged.1": b"old-staged"},
        )
        store = LaunchAgentStore(tmp_path / "agents", filesystem=fs)
        staged = store.stage_external(plist, b"new-payload")
        assert staged.name == "io.example.job.plist.staged.2"

    def test_backup_external_creates_sibling(self, tmp_path: Path) -> None:
        plist = tmp_path / "agents" / "io.example.job.plist"
        plist.parent.mkdir(parents=True)
        plist.write_bytes(b"original-content")
        store = LaunchAgentStore(tmp_path / "agents")
        backup = store.backup_external(plist)
        assert backup.name == "io.example.job.plist.backup.1"
        assert backup.read_bytes() == b"original-content"

    def test_backup_external_uniqueness_on_collision(self, tmp_path: Path) -> None:
        plist = tmp_path / "agents" / "io.example.job.plist"
        plist.parent.mkdir(parents=True)
        plist.write_bytes(b"original")
        fs = FakeFilesystem(
            files={
                "io.example.job.plist": b"original",
                "io.example.job.plist.backup.1": b"old-backup",
            },
        )
        store = LaunchAgentStore(tmp_path / "agents", filesystem=fs)
        backup = store.backup_external(plist)
        assert backup.name == "io.example.job.plist.backup.2"

    def test_activate_external_success(self, tmp_path: Path) -> None:
        dest = tmp_path / "agents" / "io.example.job.plist"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"original")
        staged = tmp_path / "agents" / "io.example.job.plist.staged.1"
        staged.write_bytes(b"staged-content")
        fs = FakeFilesystem(
            files={
                "io.example.job.plist": b"original",
                "io.example.job.plist.staged.1": b"staged-content",
            },
        )
        store = LaunchAgentStore(tmp_path / "agents", filesystem=fs)
        snap = store.read_external(dest)
        store.activate_external(staged, dest, snap)
        assert fs._files["io.example.job.plist"] == b"staged-content"

    def test_activate_external_source_change_refuses_byte_drift(self, tmp_path: Path) -> None:
        dest = tmp_path / "agents" / "io.example.job.plist"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"original")
        staged = tmp_path / "agents" / "io.example.job.plist.staged.1"
        staged.write_bytes(b"staged")
        fs = FakeFilesystem(
            files={
                "io.example.job.plist": b"original",
                "io.example.job.plist.staged.1": b"staged",
            },
        )
        store = LaunchAgentStore(tmp_path / "agents", filesystem=fs)
        snap = store.read_external(dest)
        # Mutate the dest bytes in the fake to simulate byte drift
        fs._files["io.example.job.plist"] = b"mutated-by-something-else"
        with pytest.raises(SourceChangedError):
            store.activate_external(staged, dest, snap)

    def test_activate_external_missing_staged(self, tmp_path: Path) -> None:
        dest = tmp_path / "agents" / "io.example.job.plist"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"original")
        staged = tmp_path / "agents" / "io.example.job.plist.staged.1"
        fs = FakeFilesystem(
            files={"io.example.job.plist": b"original"},
        )
        store = LaunchAgentStore(tmp_path / "agents", filesystem=fs)
        snap = store.read_external(dest)
        with pytest.raises(FileNotFoundError):
            store.activate_external(staged, dest, snap)


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

    def test_backup_external_exhaustion_raises(self, tmp_path: Path) -> None:
        filesystem = FakeFilesystem(
            files={"x.plist": b"old"}, create_error=FileExistsError("taken")
        )
        store = LaunchAgentStore(tmp_path / "agents", filesystem=filesystem)

        with pytest.raises(RuntimeError, match="unique backup sibling"):
            store.backup_external(tmp_path / "agents" / "x.plist")

    def test_backup_external_missing_file_backs_up_empty(self, tmp_path: Path) -> None:
        filesystem = FakeFilesystem()
        store = LaunchAgentStore(tmp_path / "agents", filesystem=filesystem)

        backup = store.backup_external(tmp_path / "agents" / "gone.plist")

        assert backup.name == "gone.plist.backup.1"
        assert filesystem._files[backup.name] == b""

    def test_activate_external_rejects_outside_destination(self, tmp_path: Path) -> None:
        filesystem = FakeFilesystem(
            files={"x.plist": b"old", "x.plist.staged.1": b"new"}
        )
        store = LaunchAgentStore(tmp_path / "agents", filesystem=filesystem)
        snapshot = filesystem.read_snapshot(tmp_path / "agents" / "x.plist")

        with pytest.raises(ValueError, match="outside the LaunchAgent root"):
            store.activate_external(
                tmp_path / "agents" / "x.plist.staged.1",
                tmp_path / "outside.plist",
                snapshot,
            )
        assert "x.plist" not in filesystem.replaced
