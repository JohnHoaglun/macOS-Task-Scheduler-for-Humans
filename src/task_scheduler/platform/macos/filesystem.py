"""Filesystem abstraction for the LaunchAgent store (Increment 6).

The store never opens files directly: every filesystem operation goes through
:class:`LaunchAgentFilesystem` so unit tests can substitute a fake and never
touch the real ``~/Library/LaunchAgents``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


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
