"""Read-only log file reader for job stdout/stderr (Increment 8).

A narrow, never-raising adapter so the application layer (and the tests
behind it) never touch log files directly. Production reads are capped at
the final ``LOG_TAIL_BYTES`` (256 KiB); no following or log management
happens here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

LOG_TAIL_BYTES = 256 * 1024

__all__ = ["LOG_TAIL_BYTES", "LocalLogReader", "LogReadResult", "LogReader"]


class LogReadResult(BaseModel):
    """Outcome of one log file read.

    Exactly one of ``content`` or ``error`` is set: ``content`` when the
    file was read (possibly empty), ``error`` when it was not. When the
    file exceeds ``LOG_TAIL_BYTES`` only its final ``LOG_TAIL_BYTES`` bytes
    are returned, with ``truncated`` set and ``total_bytes`` holding the
    full file size.
    """

    content: str | None = None
    error: str | None = None
    truncated: bool = False
    total_bytes: int | None = None


class LogReader(Protocol):
    """Port for log file reads; implemented by LocalLogReader and fakes."""

    def read(self, path: Path) -> LogReadResult:
        """Return the content of *path*, capped at its final 256 KiB; never raises."""


class LocalLogReader:
    """Production :class:`LogReader` built on :mod:`pathlib`."""

    def read(self, path: Path) -> LogReadResult:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return LogReadResult(error=f"log file not found: {path}")
        except OSError as exc:
            return LogReadResult(error=f"could not read log file {path}: {exc}")
        if size <= LOG_TAIL_BYTES:
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                return LogReadResult(error=f"could not read log file {path}: {exc}")
            return LogReadResult(content=content, total_bytes=size, truncated=False)
        try:
            with path.open("rb") as handle:
                handle.seek(size - LOG_TAIL_BYTES)
                tail = handle.read()
        except OSError as exc:
            return LogReadResult(error=f"could not read log file {path}: {exc}")
        newline = tail.find(b"\n")
        if newline != -1:
            tail = tail[newline + 1 :]
        return LogReadResult(
            content=tail.decode("utf-8", errors="replace"),
            truncated=True,
            total_bytes=size,
        )
