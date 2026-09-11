"""Unit tests for LocalFilesystem (Increment 8 — direct-edit primitives)."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fakes import FakeFilesystem

from task_scheduler.platform.macos import (
    LocalFilesystem,
    SourceChangedError,
    SourceSnapshot,
)


class TestLocalFilesystemReadSnapshot:

    def test_read_snapshot_regular_file(self, tmp_path: Path) -> None:
        fs = LocalFilesystem()
        f = tmp_path / "test.plist"
        f.write_bytes(b"hello world")
        snap = fs.read_snapshot(f)
        assert snap.payload == b"hello world"
        assert snap.sha256 != ""
        assert snap.st_size == 11

    def test_read_snapshot_symlink_rejected(self, tmp_path: Path) -> None:
        fs = LocalFilesystem()
        target = tmp_path / "real.plist"
        target.write_bytes(b"target")
        link = tmp_path / "link.plist"
        link.symlink_to(target)
        with pytest.raises(ValueError, match="not a regular non-symlink file"):
            fs.read_snapshot(link)

    def test_read_snapshot_directory_rejected(self, tmp_path: Path) -> None:
        fs = LocalFilesystem()
        d = tmp_path / "adir"
        d.mkdir()
        with pytest.raises(ValueError, match="not a regular non-symlink file"):
            fs.read_snapshot(d)


class TestLocalFilesystemReplaceVerified:

    def test_replace_verified_success(self, tmp_path: Path) -> None:
        fs = LocalFilesystem()
        dest = tmp_path / "dest.plist"
        dest.write_bytes(b"original")
        source = tmp_path / "source.plist"
        source.write_bytes(b"replacement")
        snap = fs.read_snapshot(dest)
        fs.replace_verified(source, dest, snap)
        assert dest.read_bytes() == b"replacement"

    def test_replace_verified_byte_drift(self, tmp_path: Path) -> None:
        fs = LocalFilesystem()
        dest = tmp_path / "dest.plist"
        dest.write_bytes(b"original")
        source = tmp_path / "source.plist"
        source.write_bytes(b"replacement")
        snap = fs.read_snapshot(dest)
        # Mutate destination via a separate replace
        dest.write_bytes(b"mutated")
        with pytest.raises(SourceChangedError):
            fs.replace_verified(source, dest, snap)

    def test_replace_verified_missing_destination(self, tmp_path: Path) -> None:
        fs = LocalFilesystem()
        source = tmp_path / "source.plist"
        source.write_bytes(b"data")
        missing = tmp_path / "nope.plist"
        snap = SourceSnapshot(
            payload=b"x",
            sha256="abc123",
            st_dev=1,
            st_ino=2,
            st_size=1,
        )
        with pytest.raises(SourceChangedError):
            fs.replace_verified(source, missing, snap)


class TestFakeFilesystemSnapshot:

    def test_read_snapshot_identity_persists_across_replace(self, tmp_path: Path) -> None:
        fs = FakeFilesystem(files={"test.plist": b"v1"})
        snap1 = fs.read_snapshot(Path("/root/test.plist"))
        # Simulate a replace (bytes change, identity stays)
        fs._files["test.plist"] = b"v2"
        snap2 = fs.read_snapshot(Path("/root/test.plist"))
        assert snap1.st_ino == snap2.st_ino
        assert snap1.st_dev == snap2.st_dev
        assert snap1.sha256 != snap2.sha256

    def test_replace_verified_missing_source(self, tmp_path: Path) -> None:
        fs = FakeFilesystem(files={"dest.plist": b"data"})
        with pytest.raises(FileNotFoundError):
            fs.replace_verified(
                Path("/root/missing.plist"),
                Path("/root/dest.plist"),
                SourceSnapshot(
                    payload=b"data",
                    sha256="x",
                    st_dev=1,
                    st_ino=2,
                    st_size=4,
                ),
            )

    def test_replace_verified_missing_destination(self, tmp_path: Path) -> None:
        fs = FakeFilesystem(files={"source.plist": b"data"})
        with pytest.raises(SourceChangedError):
            fs.replace_verified(
                Path("/root/source.plist"),
                Path("/root/missing.plist"),
                SourceSnapshot(
                    payload=b"data",
                    sha256="x",
                    st_dev=1,
                    st_ino=2,
                    st_size=4,
                ),
            )

    def test_read_snapshot_symlink_rejected(self, tmp_path: Path) -> None:
        fs = FakeFilesystem(files={"real.plist": b"data"}, symlinks={"real.plist"})
        with pytest.raises(ValueError, match="not a regular non-symlink file"):
            fs.read_snapshot(Path("/root/real.plist"))

    def test_read_snapshot_directory_rejected(self, tmp_path: Path) -> None:
        fs = FakeFilesystem(files={"real.plist": b"data"}, directories={"real.plist"})
        with pytest.raises(ValueError, match="not a regular non-symlink file"):
            fs.read_snapshot(Path("/root/real.plist"))

    def test_replace_verified_identity_drift_refused(self, tmp_path: Path) -> None:
        fs = FakeFilesystem(files={"dest.plist": b"original", "source.plist": b"new"})
        snap = fs.read_snapshot(Path("/root/dest.plist"))
        # Corrupt the identity registry so the destination identity no longer matches
        fs._name_to_identity["dest.plist"] = (999, 999)
        with pytest.raises(SourceChangedError):
            fs.replace_verified(
                Path("/root/source.plist"),
                Path("/root/dest.plist"),
                snap,
            )
