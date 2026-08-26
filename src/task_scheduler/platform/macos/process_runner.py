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

    ``exit_code`` is None when the process never started; then
    ``launch_failure`` describes why.
    """

    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    duration: timedelta = timedelta()
    launch_failure: ProcessLaunchFailure | None = None


class ProcessRunner(Protocol):
    """Port for process execution; implemented by SubprocessRunner and fakes."""

    def run(self, spec: CommandSpec) -> ProcessResult:
        """Execute *spec* and return its result; never raises for launch errors."""


class SubprocessRunner:
    """Production runner backed by the standard library.

    No timeout is applied (by design for this increment). The monotonic
    clock is injectable for deterministic duration tests.
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock if clock is not None else time.monotonic

    def run(self, spec: CommandSpec) -> ProcessResult:
        started = self._clock()
        try:
            completed = subprocess.run(
                spec.argv,
                capture_output=True,
                text=True,
                env=dict(spec.environment),
                cwd=spec.working_directory,
                check=False,
            )
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

    def _failure(
        self, kind: LaunchFailureKind, message: str, seconds: float
    ) -> ProcessResult:
        return ProcessResult(
            exit_code=None,
            duration=timedelta(seconds=seconds),
            launch_failure=ProcessLaunchFailure(kind=kind, message=message),
        )
