"""Unit tests for LocalFilesystem (Increment 6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from task_scheduler.platform.macos import LocalFilesystem


class TestReadAndList:
    def test_read_plist_bytes(self, tmp_path: Path) -> None:
        target = tmp_path / "a.plist"
        target.write_bytes(b"123")
        assert LocalFilesystem().read_plist_bytes(target) == b"123"

    def test_list_plist_files_sorted_and_filtered(self, tmp_path: Path) -> None:
        (tmp_path / "b.plist").write_bytes(b"")
        (tmp_path / "a.plist").write_bytes(b"")
        (tmp_path / "notes.txt").write_text("x")
        (tmp_path / "sub.plist").mkdir()
        (tmp_path / "broken.plist").symlink_to(tmp_path / "missing")

        names = [
            path.name for path in LocalFilesystem().list_plist_files(tmp_path)
        ]

        assert names == ["a.plist", "b.plist"]


class TestCreate:
    def test_create_root_nested_and_idempotent(self, tmp_path: Path) -> None:
        filesystem = LocalFilesystem()
        root = tmp_path / "x" / "y"

        filesystem.create_root(root)
        filesystem.create_root(root)

        assert root.is_dir()

    def test_create_exclusive_writes_payload_without_leftovers(
        self, tmp_path: Path
    ) -> None:
        destination = tmp_path / "d.plist"
        LocalFilesystem().create_exclusive(destination, b"payload")

        assert destination.read_bytes() == b"payload"
        assert [path.name for path in tmp_path.iterdir()] == ["d.plist"]

    def test_create_exclusive_refuses_existing_destination(
        self, tmp_path: Path
    ) -> None:
        destination = tmp_path / "d.plist"
        destination.write_bytes(b"old")

        with pytest.raises(FileExistsError):
            LocalFilesystem().create_exclusive(destination, b"new")

        assert destination.read_bytes() == b"old"
        assert [path.name for path in tmp_path.iterdir()] == ["d.plist"]


class TestReplace:
    def test_replace_overwrites_destination_and_keeps_source(self, tmp_path: Path) -> None:
        source = tmp_path / "s.plist"
        source.write_bytes(b"new")
        destination = tmp_path / "d.plist"
        destination.write_bytes(b"old")

        LocalFilesystem().replace(source, destination)

        assert destination.read_bytes() == b"new"
        assert source.read_bytes() == b"new"
        assert sorted(path.name for path in tmp_path.iterdir()) == ["d.plist", "s.plist"]

    def test_replace_into_missing_destination(self, tmp_path: Path) -> None:
        source = tmp_path / "s.plist"
        source.write_bytes(b"new")

        LocalFilesystem().replace(source, tmp_path / "d.plist")

        assert (tmp_path / "d.plist").read_bytes() == b"new"

    def test_replace_missing_source_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            LocalFilesystem().replace(tmp_path / "nope.plist", tmp_path / "d.plist")


class TestRemove:
    def test_remove_file_then_missing(self, tmp_path: Path) -> None:
        filesystem = LocalFilesystem()
        victim = tmp_path / "v.plist"
        victim.write_bytes(b"x")

        assert filesystem.remove_file(victim) is True
        assert filesystem.remove_file(victim) is False
