"""Filesystem abstraction for the LaunchAgent store (Increment 6).

The store never opens files directly: every filesystem operation goes through
:class:`LaunchAgentFilesystem` so unit tests can substitute a fake and never
touch the real ``~/Library/LaunchAgents``.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class SourceChangedError(ValueError):
    """Destination content or identity diverged from the expected snapshot."""


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """Immutable fingerprint for a file on disk."""

    payload: bytes
    sha256: str
    st_dev: int
    st_ino: int
    st_size: int


class LaunchAgentFilesystem(Protocol):
    """Narrow filesystem interface used by the LaunchAgent store."""

    def read_plist_bytes(self, path: Path) -> bytes:
        """Return the raw bytes of a plist file."""

    def list_plist_files(self, root: Path) -> list[Path]:
        """Return direct-child ``*.plist`` regular files under ``root``, sorted."""

    def create_root(self, root: Path) -> None:
        """Create ``root`` (and parents) if missing; no error when it exists."""

    def create_exclusive(self, destination: Path, payload: bytes) -> None:
        """Atomically create ``destination`` with ``payload``.

        Raises :class:`FileExistsError` when the destination already exists; the
        destination is never overwritten.
        """

    def remove_file(self, path: Path) -> bool:
        """Remove ``path``. Return ``True`` when removed, ``False`` when absent."""

    def replace(self, source: Path, destination: Path) -> None:
        """Atomically replace ``destination``'s contents with a copy of ``source``.

        ``source`` is left in place. Unlike :meth:`create_exclusive` this is an
        explicit overwrite: the caller staged ``source`` and decided to
        activate it, so the destination is replaced, never created only.
        """

    def read_snapshot(self, path: Path) -> SourceSnapshot:
        """Return an immutable snapshot (bytes + hash + inode identity)."""

    def replace_verified(
        self, source: Path, destination: Path, expected: SourceSnapshot
    ) -> None:
        """Atomically replace ``destination`` with ``source`` only when
        ``destination`` still matches ``expected``.
        """


class LocalFilesystem:
    """Production :class:`LaunchAgentFilesystem` built on :mod:`pathlib`."""

    def read_plist_bytes(self, path: Path) -> bytes:
        return path.read_bytes()

    def list_plist_files(self, root: Path) -> list[Path]:
        return sorted(
            entry
            for entry in root.iterdir()
            if entry.name.endswith(".plist") and entry.is_file()
        )

    def create_root(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)

    def create_exclusive(self, destination: Path, payload: bytes) -> None:
        temporary = destination.with_name(
            f"{destination.name}.{os.getpid()}.tmp"
        )
        try:
            temporary.write_bytes(payload)
            os.link(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def remove_file(self, path: Path) -> bool:
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True

    def replace(self, source: Path, destination: Path) -> None:
        temporary = destination.with_name(
            f"{destination.name}.{os.getpid()}.tmp"
        )
        try:
            temporary.write_bytes(source.read_bytes())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def read_snapshot(self, path: Path) -> SourceSnapshot:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"path is not a regular non-symlink file: {path}")
        payload = path.read_bytes()
        stat = path.stat()
        return SourceSnapshot(
            payload=payload,
            sha256=hashlib.sha256(payload).hexdigest(),
            st_dev=stat.st_dev,
            st_ino=stat.st_ino,
            st_size=stat.st_size,
        )

    def replace_verified(
        self, source: Path, destination: Path, expected: SourceSnapshot
    ) -> None:
        try:
            current = self.read_snapshot(destination)
        except (FileNotFoundError, ValueError) as exc:
            raise SourceChangedError(
                f"destination {destination} not found or inaccessible"
            ) from exc
        if (
            current.sha256 != expected.sha256
            or current.st_dev != expected.st_dev
            or current.st_ino != expected.st_ino
        ):
            raise SourceChangedError(
                f"destination {destination} changed from expected snapshot"
            )
        self.replace(source, destination)
