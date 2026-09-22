"""Unit tests for LocalFilesystem (Increment 8 — direct-edit primitives)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from task_scheduler.platform.macos import LocalFilesystem, SourceChangedError, SourceSnapshot


class TestLocalFilesystemReplaceVerified:
    def test_replace_verified_byte_drift(self, tmp_path: Path) -> None:
        fs = LocalFilesystem()
        dest = tmp_path / "dest.plist"
        dest.write_bytes(b"original")
        source = tmp_path / "source.plist"
        source.write_bytes(b"replacement")
        snap = fs.read_snapshot(dest)
        dest.write_bytes(b"mutated")
        with pytest.raises(SourceChangedError):
            fs.replace_verified(source, dest, snap)

    def test_replace_verified_missing_destination(self, tmp_path: Path) -> None:
        fs = LocalFilesystem()
        source = tmp_path / "source.plist"
        source.write_bytes(b"data")
        missing = tmp_path / "nope.plist"
        snap = SourceSnapshot(payload=b"x", sha256="abc123", st_dev=1, st_ino=2, st_size=1)
        with pytest.raises(SourceChangedError):
            fs.replace_verified(source, missing, snap)


class TestCreateExclusiveSecure:
    def test_0600_and_no_leftover_temp(self, tmp_path: Path) -> None:
        dest = tmp_path / "dest.plist"
        LocalFilesystem().create_exclusive(dest, b"payload")
        assert dest.read_bytes() == b"payload"
        assert stat.S_IMODE(dest.stat().st_mode) == 0o600
        assert [p.name for p in tmp_path.iterdir()] == ["dest.plist"]

    def test_refuses_preexisting_destination(self, tmp_path: Path) -> None:
        fs = LocalFilesystem()
        target = tmp_path / "target.plist"
        target.write_bytes(b"victim")
        (tmp_path / "link.plist").symlink_to(target)
        pre = tmp_path / "pre.plist"
        pre.write_bytes(b"existing")
        for victim in (tmp_path / "link.plist", pre):
            with pytest.raises(FileExistsError):
                fs.create_exclusive(victim, b"new")
        assert target.read_bytes() == b"victim" and pre.read_bytes() == b"existing"


class TestReadSnapshotDescriptorCoherent:
    def test_rejects_symlink_and_directory(self, tmp_path: Path) -> None:
        real = tmp_path / "real.plist"
        real.write_bytes(b"data")
        (tmp_path / "link.plist").symlink_to(real)
        fs = LocalFilesystem()
        with pytest.raises(ValueError, match="non-symlink"):
            fs.read_snapshot(tmp_path / "link.plist")
        with pytest.raises(ValueError, match="non-symlink"):
            fs.read_snapshot(tmp_path)

    def test_payload_and_identity_are_coherent(self, tmp_path: Path) -> None:
        dest = tmp_path / "dest.plist"
        dest.write_bytes(b"0123456789")
        snap = LocalFilesystem().read_snapshot(dest)
        assert snap.payload == b"0123456789" and snap.st_size == 10
        assert snap.st_ino == dest.stat().st_ino


class TestDiscoveryReadSymlinkContainment:
    def test_list_plist_files_skips_symlinked_entries(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        target = outside / "target.plist"
        target.write_bytes(b"outside")
        regular = tmp_path / "regular.plist"
        regular.write_bytes(b"inside")
        (tmp_path / "link.plist").symlink_to(target)
        (tmp_path / "broken.plist").symlink_to(outside / "gone.plist")
        assert LocalFilesystem().list_plist_files(tmp_path) == [regular]

    def test_read_plist_bytes_rejects_symlinks(self, tmp_path: Path) -> None:
        fs = LocalFilesystem()
        regular = tmp_path / "regular.plist"
        regular.write_bytes(b"inside")
        outside = tmp_path / "outside"
        outside.mkdir()
        target = outside / "target.plist"
        target.write_bytes(b"outside")
        (tmp_path / "link_in.plist").symlink_to(regular)
        (tmp_path / "link_out.plist").symlink_to(target)
        for link in (tmp_path / "link_in.plist", tmp_path / "link_out.plist"):
            with pytest.raises(ValueError, match="symlinked plist"):
                fs.read_plist_bytes(link)

    def test_read_plist_bytes_reads_regular_file(self, tmp_path: Path) -> None:
        regular = tmp_path / "regular.plist"
        regular.write_bytes(b"payload")
        assert LocalFilesystem().read_plist_bytes(regular) == b"payload"


def _raise_oserror(*_args: object, **_kwargs: object) -> None:
    raise OSError("injected failure")


class TestFilesystemFailureCleanup:
    def test_replace_cleans_temp_when_os_replace_fails(self, tmp_path: Path, monkeypatch) -> None:
        source = tmp_path / "s"
        source.write_bytes(b"x")
        monkeypatch.setattr(os, "replace", _raise_oserror)
        with pytest.raises(OSError):
            LocalFilesystem().replace(source, tmp_path / "d")
        assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]

    def test_create_refuses_non_regular_and_cleans_temp(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(os, "fstat", lambda _fd: tmp_path.stat())
        with pytest.raises(OSError, match="non-regular"):
            LocalFilesystem().create_exclusive(tmp_path / "x", b"p")
        assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
