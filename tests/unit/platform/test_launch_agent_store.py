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
