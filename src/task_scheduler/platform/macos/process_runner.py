"""Process execution port: the only code allowed to call subprocess.

Direct task tests (and, later, launchctl) must go through a
`ProcessRunner`; no other layer may invoke `subprocess` directly.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field


class LaunchFailureKind(StrEnum):
    """Machine-readable classification of a process that never started."""

    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"
    OS_ERROR = "os_error"


class ProcessLaunchFailure(BaseModel):
    """Why a process could not be started."""

    kind: LaunchFailureKind
    message: str


class ProcessTimeout(BaseModel):
    """Why a running process was killed because it hit its deadline."""

    deadline: float
    message: str


class CommandSpec(BaseModel):
    """One process invocation with an explicit, complete environment.

    ``environment`` is the exact mapping passed to the child (it does not
    inherit the parent's environment), mirroring launchd semantics.
    """

    argv: list[str]
    environment: dict[str, str] = Field(default_factory=dict)
    working_directory: Path | None = None


class ProcessResult(BaseModel):
    """Outcome of one process invocation.

    ``exit_code`` is None when the process never started (then
    ``launch_failure`` describes why) or when it was killed because it
    reached its deadline (then ``timed_out`` describes it and
    ``stdout``/``stderr`` may hold partial output). The three terminal
    states — successful/nonzero exit, launch failure, timeout — are
    mutually exclusive.
    """

    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    duration: timedelta = timedelta()
    launch_failure: ProcessLaunchFailure | None = None
    timed_out: ProcessTimeout | None = None


class ProcessRunner(Protocol):
    """Port for process execution; implemented by SubprocessRunner and fakes."""

    def run(self, spec: CommandSpec, *, timeout: float | None = None) -> ProcessResult:
        """Execute *spec* and return its result; never raises for launch errors
        or for a deadline being hit. With *timeout* (seconds) the child is
        killed and the result is marked ``timed_out`` when it elapses."""


class SubprocessRunner:
    """Production runner backed by the standard library.

    Captured output is decoded as explicit UTF-8 (invalid byte sequences are
    replaced, never raised). An optional per-call timeout (seconds) kills the
    child and produces a ``timed_out`` result. The monotonic clock is
    injectable for deterministic duration tests.
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock if clock is not None else time.monotonic

    def run(self, spec: CommandSpec, *, timeout: float | None = None) -> ProcessResult:
        started = self._clock()
        try:
            completed = subprocess.run(
                spec.argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=dict(spec.environment),
                cwd=spec.working_directory,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            assert timeout is not None  # only raised when a deadline was given
            return self._timed_out(exc, timeout, self._clock() - started)
        except FileNotFoundError as exc:
            return self._failure(LaunchFailureKind.NOT_FOUND, str(exc), self._clock() - started)
        except PermissionError as exc:
            return self._failure(
                LaunchFailureKind.PERMISSION_DENIED, str(exc), self._clock() - started
            )
        except OSError as exc:
            return self._failure(LaunchFailureKind.OS_ERROR, str(exc), self._clock() - started)
        return ProcessResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration=timedelta(seconds=self._clock() - started),
        )

    def _failure(self, kind: LaunchFailureKind, message: str, seconds: float) -> ProcessResult:
        return ProcessResult(
            exit_code=None,
            duration=timedelta(seconds=seconds),
            launch_failure=ProcessLaunchFailure(kind=kind, message=message),
        )

    def _timed_out(
        self, exc: subprocess.TimeoutExpired, deadline: float, seconds: float
    ) -> ProcessResult:
        return ProcessResult(
            exit_code=None,
            stdout=self._decode(exc.stdout),
            stderr=self._decode(exc.stderr),
            duration=timedelta(seconds=seconds),
            timed_out=ProcessTimeout(deadline=deadline, message=str(exc)),
        )

    @staticmethod
    def _decode(data: bytes | str | None) -> str:
        """Decode partial captured output; bytes use UTF-8 with replacement."""
        if data is None:
            return ""
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return data
