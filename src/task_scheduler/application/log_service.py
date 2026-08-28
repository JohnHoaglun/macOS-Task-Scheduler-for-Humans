"""Job log access: read the stdout/stderr files a managed job configured.

:class:`LogService` never raises for file problems: each stream reports its
own state (unconfigured, read content, or a read error) so the CLI can
render a clear per-stream message and the GUI can show the same.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from task_scheduler.domain import JobDefinition
from task_scheduler.platform.macos.log_reader import (
    LocalLogReader,
    LogReader,
    LogReadResult,
)

__all__ = ["JobLogs", "LogService", "LogStream"]


class LogStream(BaseModel):
    """One log stream of a job.

    ``path`` is None when the job configured no capture path for this
    stream. Otherwise exactly one of ``content`` (file read, possibly
    empty) or ``error`` (missing/unreadable) is set.
    """

    name: str
    path: Path | None
    content: str | None = None
    error: str | None = None


class JobLogs(BaseModel):
    """The stdout and stderr streams of one job."""

    stdout: LogStream
    stderr: LogStream


class LogService:
    """Read the configured log files of a job without ever mutating them."""

    def __init__(self, reader: LogReader | None = None) -> None:
        self._reader = reader if reader is not None else LocalLogReader()

    def read(self, job: JobDefinition) -> JobLogs:
        """Return both streams of ``job``; never raises for file problems."""
        return JobLogs(
            stdout=self._read_stream("stdout", job.logging.stdout_path),
            stderr=self._read_stream("stderr", job.logging.stderr_path),
        )

    def _read_stream(self, name: str, path: Path | None) -> LogStream:
        if path is None:
            return LogStream(name=name, path=None)
        result: LogReadResult = self._reader.read(path)
        return LogStream(
            name=name, path=path, content=result.content, error=result.error
        )
