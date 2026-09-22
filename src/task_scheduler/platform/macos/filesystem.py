"""Filesystem abstraction for the LaunchAgent store (Increment 6).

The store never opens files directly: every filesystem operation goes through
:class:`LaunchAgentFilesystem` so unit tests can substitute a fake and never
touch the real ``~/Library/LaunchAgents``.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import stat
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

    def replace_verified(self, source: Path, destination: Path, expected: SourceSnapshot) -> None:
        """Replace ``destination`` with ``source`` after a best-effort re-check.

        The destination is re-read and compared to ``expected`` immediately
        before the atomic publish. This guards against drift the caller has not
        observed, but it is *not* a compare-and-swap: a writer that modifies the
        destination between the check and the publish is not excluded, because
        no advisory lock is held. Raises :class:`SourceChangedError` when the
        check fails or the destination is inaccessible.
        """

    def remove_verified(self, path: Path, expected: SourceSnapshot) -> None:
        """Remove ``path`` after a best-effort re-check against ``expected``.

        As with :meth:`replace_verified`, the file is re-read and compared to
        ``expected`` immediately before removal, but the check-and-remove is not
        atomic against non-cooperating writers. Raises :class:`SourceChangedError`
        when the check fails or the file is inaccessible.
        """


class LocalFilesystem:
    """Production :class:`LaunchAgentFilesystem` built on :mod:`pathlib`."""

    def read_plist_bytes(self, path: Path) -> bytes:
        if path.is_symlink():
            raise ValueError(f"refusing to read a symlinked plist file: {path}")
        return path.read_bytes()

    def list_plist_files(self, root: Path) -> list[Path]:
        return sorted(
            entry
            for entry in root.iterdir()
            if entry.name.endswith(".plist") and entry.is_file() and not entry.is_symlink()
        )

    def create_root(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)

    def create_exclusive(self, destination: Path, payload: bytes) -> None:
        temporary = self._write_private_file(destination.parent, payload)
        try:
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
        temporary = self._write_private_file(destination.parent, source.read_bytes())
        try:
            os.replace(temporary, destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def _write_private_file(self, directory: Path, payload: bytes) -> Path:
        """Create an unpredictable ``0600`` temp file in ``directory``.

        The file is opened with ``O_CREAT | O_EXCL`` (and ``O_NOFOLLOW`` where
        available) so an attacker-precreated symlink or file at the path cannot
        be followed or overwritten; it is verified to be a regular file, then
        fully written and ``fsync``ed before its path is returned for publish.
        On any failure the owned temp file is removed.
        """
        name = f".{os.getpid()}.{secrets.token_hex(8)}.tmp"
        temporary = directory / name
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(temporary, flags, 0o600)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise OSError(f"refusing to write through non-regular file: {temporary}")
            view = memoryview(payload)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            temporary.unlink(missing_ok=True)
            raise
        os.close(fd)
        return temporary

    def read_snapshot(self, path: Path) -> SourceSnapshot:
        """Descriptor-coherent snapshot: bytes, hash, and identity come from one
        open file descriptor, so a path swapped between stat and read cannot
        mix identity and payload from different files. Symlinks and non-regular
        files raise :class:`ValueError`; a missing path raises
        :class:`FileNotFoundError`.
        """
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(path, flags)
        except FileNotFoundError:
            raise
        except OSError as exc:
            # ``O_NOFOLLOW`` turns a pre-existing symlink into ELOOP; surface it
            # as the established non-regular-file error callers already catch.
            raise ValueError(f"path is not a regular non-symlink file: {path}") from exc
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise ValueError(f"path is not a regular non-symlink file: {path}")
            payload = self._read_all(fd)
        finally:
            os.close(fd)
        return SourceSnapshot(
            payload=payload,
            sha256=hashlib.sha256(payload).hexdigest(),
            st_dev=st.st_dev,
            st_ino=st.st_ino,
            st_size=st.st_size,
        )

    @staticmethod
    def _read_all(fd: int) -> bytes:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)

    def replace_verified(self, source: Path, destination: Path, expected: SourceSnapshot) -> None:
        """Best-effort re-check against ``expected``, then an atomic publish.

        Not a compare-and-swap: the destination is re-read and compared
        immediately before :meth:`replace`, but no lock is held, so a concurrent
        writer is not excluded (see the protocol docstring).
        """
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
            raise SourceChangedError(f"destination {destination} changed from expected snapshot")
        self.replace(source, destination)

    def remove_verified(self, path: Path, expected: SourceSnapshot) -> None:
        """Best-effort re-check against ``expected``, then remove.

        The file is re-read and compared immediately before removal, but the
        check-and-remove is not atomic against non-cooperating writers (see the
        protocol docstring).
        """
        try:
            current = self.read_snapshot(path)
        except (FileNotFoundError, ValueError) as exc:
            raise SourceChangedError(f"{path} not found or inaccessible") from exc
        if (
            current.sha256 != expected.sha256
            or current.st_dev != expected.st_dev
            or current.st_ino != expected.st_ino
        ):
            raise SourceChangedError(f"{path} changed from expected snapshot")
        self.remove_file(path)
