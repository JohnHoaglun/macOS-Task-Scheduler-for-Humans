"""Unit tests for LocalFilesystem (Increment 8 — direct-edit primitives)."""

from __future__ import annotations

from pathlib import Path

import pytest

from task_scheduler.platform.macos import (
    LocalFilesystem,
    SourceChangedError,
    SourceSnapshot,
)


class TestLocalFilesystemReplaceVerified:
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
