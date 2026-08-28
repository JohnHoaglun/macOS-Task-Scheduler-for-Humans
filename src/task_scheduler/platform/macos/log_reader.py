"""Read-only log file reader for job stdout/stderr (Increment 8).

A narrow, never-raising adapter so the application layer (and the tests
behind it) never touch log files directly. Production reads are plain full
reads; no tailing, following, or log management happens here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

__all__ = ["LocalLogReader", "LogReadResult", "LogReader"]


class LogReadResult(BaseModel):
    """Outcome of one log file read.

    Exactly one of ``content`` or ``error`` is set: ``content`` when the
    file was read (possibly empty), ``error`` when it was not.
    """

    content: str | None = None
    error: str | None = None


class LogReader(Protocol):
    """Port for log file reads; implemented by LocalLogReader and fakes."""

    def read(self, path: Path) -> LogReadResult:
        """Return the full content of *path*; never raises."""


class LocalLogReader:
    """Production :class:`LogReader` built on :mod:`pathlib`."""

    def read(self, path: Path) -> LogReadResult:
        try:
            return LogReadResult(content=path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return LogReadResult(error=f"log file not found: {path}")
        except (OSError, UnicodeDecodeError) as exc:
            return LogReadResult(error=f"could not read log file {path}: {exc}")
