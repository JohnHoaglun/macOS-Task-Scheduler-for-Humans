"""Unit tests for LaunchAgentStore (Increment 6).

Every test runs against a temporary root or an in-memory fake: no test
touches the real ``~/Library/LaunchAgents``, ``/Library``, or launchctl.
"""

from __future__ import annotations

import os
import plistlib
from pathlib import Path

import pytest

from task_scheduler.platform.macos import (
    LaunchAgentStore,
    ParseSupport,
    PlistCodec,
    default_launch_agents_root,
)
from tests.conftest import make_job
from tests.fakes import FakeFilesystem


class TestConstruction:
    def test_default_launch_agents_root(self) -> None:
        assert default_launch_agents_root() == (
            Path.home() / "Library" / "LaunchAgents"
        )

    def test_default_store_uses_default_root(self) -> None:
        assert LaunchAgentStore().root == default_launch_agents_root()

    def test_injected_root_filesystem_and_codec(self, tmp_path: Path) -> None:
        filesystem = FakeFilesystem()
        store = LaunchAgentStore(
            tmp_path / "agents", filesystem=filesystem, codec=PlistCodec()
        )
        assert store.root == tmp_path / "agents"
        store.write(make_job(label="x"))
        assert filesystem.roots_created == ["agents"]
        assert filesystem.created == ["x.plist"]


class TestWrite:
    def test_write_creates_root_and_writes_encoded_plist(
        self, tmp_path: Path
    ) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        job = make_job()
        destination = store.write(job)

        assert destination == tmp_path / "agents" / f"{job.label}.plist"
        assert destination.is_file()
        assert destination.read_bytes() == PlistCodec().encode_bytes(job)
        decoded = plistlib.loads(destination.read_bytes())
        assert decoded["Label"] == job.label
        assert decoded["ProgramArguments"] == [
            "/Users/example/project/.venv/bin/python",
            "/Users/example/project/main.py",
            "--mode",
            "daily",
        ]

    def test_write_into_preexisting_root(self, tmp_path: Path) -> None:
        root = tmp_path / "agents"
        root.mkdir()
        store = LaunchAgentStore(root)
        assert store.write(make_job()).is_file()

    def test_write_refuses_existing_destination(self, tmp_path: Path) -> None:
        root = tmp_path / "agents"
        root.mkdir()
        store = LaunchAgentStore(root)
        destination = root / "taken.plist"
        destination.write_bytes(b"OLD CONTENT")

        with pytest.raises(FileExistsError):
            store.write(make_job(label="taken"))

        assert destination.read_bytes() == b"OLD CONTENT"
        assert [path.name for path in root.iterdir()] == ["taken.plist"]

    def test_write_propagates_filesystem_error(self, tmp_path: Path) -> None:
        filesystem = FakeFilesystem(create_error=OSError("boom"))
        store = LaunchAgentStore(tmp_path / "agents", filesystem=filesystem)

        with pytest.raises(OSError, match="boom"):
            store.write(make_job(label="x"))

        assert filesystem.created == []

    @pytest.mark.parametrize("label", ["..", ".", "../escape", "a/b", os.sep])
    def test_remove_rejects_unsafe_labels(
        self, tmp_path: Path, label: str
    ) -> None:
        store = LaunchAgentStore(tmp_path / "agents")

        with pytest.raises(ValueError, match="Label must not be"):
            store.remove(label)

        assert not (tmp_path / "agents").exists()


class TestDestination:
    def test_destination_for_valid_label(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        assert store.destination_for("x") == tmp_path / "agents" / "x.plist"

    @pytest.mark.parametrize("label", ["..", ".", "a/b"])
    def test_destination_for_rejects_unsafe_labels(
        self, tmp_path: Path, label: str
    ) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        with pytest.raises(ValueError, match="Label must not be"):
            store.destination_for(label)


class TestRemove:
    def test_remove_existing_returns_true(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        store.write(make_job(label="gone"))

        assert store.remove("gone") is True
        assert not store.destination_for("gone").exists()

    def test_remove_missing_is_idempotent(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        assert store.remove("never-there") is False
        assert store.remove("never-there") is False

    def test_remove_missing_root_is_false(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        assert store.remove("x") is False
        assert not (tmp_path / "agents").exists()

    def test_remove_forwards_to_injected_filesystem(self, tmp_path: Path) -> None:
        filesystem = FakeFilesystem(files={"l.plist": b"data"})
        store = LaunchAgentStore(tmp_path / "agents", filesystem=filesystem)

        assert store.remove("l") is True
        assert store.remove("l") is False
        assert filesystem.removed == ["l.plist", "l.plist"]


class TestDiscover:
    def test_discover_missing_root_empty(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        assert store.discover() == []
        assert not (tmp_path / "agents").exists()

    def test_discover_sorted_and_classified(self, tmp_path: Path) -> None:
        root = tmp_path / "agents"
        store = LaunchAgentStore(root)
        store.write(make_job(label="b-job"))
        store.write(make_job(label="a-job"))
        (root / "c.plist").write_bytes(b"not a plist at all")
        (root / "d.plist").write_bytes(
            plistlib.dumps(
                {
                    "Label": "d-job",
                    "ProgramArguments": ["/bin/echo", "hi"],
                    "StartCalendarInterval": [
                        {"Hour": 7, "Minute": 30, "Weekday": 1}
                    ],
                    "KeepAlive": True,
                }
            )
        )
        (root / "notes.txt").write_text("ignore me")
        (root / "subdir.plist").mkdir()

        found = store.discover()

        assert [entry.path.name for entry in found] == [
            "a-job.plist",
            "b-job.plist",
            "c.plist",
            "d.plist",
        ]
        by_name = {entry.path.name: entry for entry in found}
        assert by_name["a-job.plist"].parsed.status is ParseSupport.SUPPORTED
        assert by_name["a-job.plist"].parsed.job is not None
        assert by_name["a-job.plist"].parsed.job.label == "a-job"
        assert by_name["c.plist"].parsed.status is ParseSupport.INVALID
        assert by_name["c.plist"].parsed.job is None
        assert by_name["d.plist"].parsed.status is ParseSupport.PARTIALLY_SUPPORTED
        assert "KeepAlive" in by_name["d.plist"].parsed.unsupported_keys

    def test_discover_never_mutates_files(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        store.write(make_job(label="one"))
        store.write(make_job(label="two"))
        before = {path.name: path.read_bytes() for path in store.root.iterdir()}

        store.discover()

        after = {path.name: path.read_bytes() for path in store.root.iterdir()}
        assert before == after

    def test_discover_uses_injected_filesystem(self, tmp_path: Path) -> None:
        root = tmp_path / "agents"
        root.mkdir()
        filesystem = FakeFilesystem(
            files={"x.plist": PlistCodec().encode_bytes(make_job(label="x"))}
        )
        store = LaunchAgentStore(root, filesystem=filesystem)

        found = store.discover()

        assert len(found) == 1
        assert found[0].path == root / "x.plist"
        assert found[0].parsed.status is ParseSupport.SUPPORTED
        assert filesystem.reads == ["x.plist"]

    def test_discover_missing_root_skips_filesystem(self, tmp_path: Path) -> None:
        filesystem = FakeFilesystem(files={"x.plist": b"y"})
        store = LaunchAgentStore(tmp_path / "agents", filesystem=filesystem)

        assert store.discover() == []
        assert filesystem.listings == []


class TestStaging:
    def test_stage_creates_unique_sibling_without_touching_deployed(
        self, tmp_path: Path
    ) -> None:
        store = LaunchAgentStore(tmp_path / "agents")

        staged = store.stage_plist("x", b"payload")

        assert staged == tmp_path / "agents" / "x.plist.staged.1"
        assert staged.read_bytes() == b"payload"
        assert not store.destination_for("x").exists()

    def test_stage_skips_taken_names(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")

        first = store.stage_plist("x", b"one")
        second = store.stage_plist("x", b"two")

        assert first.name == "x.plist.staged.1"
        assert second.name == "x.plist.staged.2"
        assert second.read_bytes() == b"two"

    def test_stage_rejects_unsafe_labels(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")

        with pytest.raises(ValueError, match="Label must not be"):
            store.stage_plist("../escape", b"x")

        assert not (tmp_path / "agents").exists()

    def test_stage_exhaustion_raises(self, tmp_path: Path) -> None:
        filesystem = FakeFilesystem(create_error=FileExistsError("taken"))
        store = LaunchAgentStore(tmp_path / "agents", filesystem=filesystem)

        with pytest.raises(RuntimeError, match="unique staged sibling"):
            store.stage_plist("x", b"x")

    def test_backup_preserves_deployed_bytes(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        store.write(make_job(label="x"))
        deployed_bytes = store.destination_for("x").read_bytes()

        backup = store.backup_plist("x")

        assert backup is not None
        assert backup.name == "x.plist.backup.1"
        assert backup.read_bytes() == deployed_bytes
        assert store.destination_for("x").read_bytes() == deployed_bytes

    def test_backup_missing_deployed_returns_none(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        assert store.backup_plist("never-there") is None

    def test_backup_skips_taken_names(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        store.write(make_job(label="x"))

        assert store.backup_plist("x").name == "x.plist.backup.1"
        assert store.backup_plist("x").name == "x.plist.backup.2"

    def test_backup_exhaustion_raises(self, tmp_path: Path) -> None:
        filesystem = FakeFilesystem(
            files={"x.plist": b"old"}, create_error=FileExistsError("taken")
        )
        store = LaunchAgentStore(tmp_path / "agents", filesystem=filesystem)

        with pytest.raises(RuntimeError, match="unique backup sibling"):
            store.backup_plist("x")

    def test_activate_replaces_deployed_and_removes_staged(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        store.write(make_job(label="x"))
        staged = store.stage_plist("x", b"new-payload")

        destination = store.activate_staged("x", staged)

        assert destination == store.destination_for("x")
        assert destination.read_bytes() == b"new-payload"
        assert not staged.exists()

    def test_activate_missing_staged_raises(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")

        with pytest.raises(FileNotFoundError):
            store.activate_staged("x", store.root / "x.plist.staged.9")

    def test_remove_sibling_removes_then_missing(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        sibling = store.stage_plist("x", b"p")

        assert store.remove_sibling(sibling) is True
        assert store.remove_sibling(sibling) is False

    def test_remove_sibling_rejects_outside_root(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        (tmp_path / "outside.plist").write_bytes(b"x")

        with pytest.raises(ValueError, match="outside the LaunchAgent root"):
            store.remove_sibling(tmp_path / "outside.plist")

        assert (tmp_path / "outside.plist").is_file()
