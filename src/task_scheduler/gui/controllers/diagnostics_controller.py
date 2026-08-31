"""Diagnostics controller bridging the Test action to TaskCommandService.

Qt-free: all validation, gating, and busy-state logic lives here so it can
be tested without an event loop. The :class:`~task_scheduler.gui.controllers.
diagnostics_worker.DiagnosticsWorker` QObject performs the accepted direct
test on a worker thread and marshals an immutable :class:`TestOutcome`. Log
reads and environment comparisons are fast, read-only operations and are
served synchronously.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from task_scheduler.application import TaskCommandService
from task_scheduler.application.log_service import JobLogs
from task_scheduler.application.test_service import DirectTestResult
from task_scheduler.domain import JobDefinition
from task_scheduler.platform.macos import EnvironmentDifference

__all__ = [
    "DiagnosticsController",
    "EnvironmentOutcome",
    "LogsOutcome",
    "RequestVerdict",
    "TestOutcome",
]


class RequestVerdict(StrEnum):
    """Why a direct-test request was accepted or refused (synchronously)."""

    ACCEPTED = "accepted"
    BUSY = "busy"
    INVALID_JOB = "invalid job"


@dataclass(frozen=True, slots=True)
class TestOutcome:
    """Immutable result of a direct test, marshaled to the main thread.

    ``label`` identifies the job the outcome belongs to so the UI can
    discard stale results after the selection changed. ``result`` is the
    service's structured result; ``error`` is the failure reason for
    exceptions.
    """

    label: str
    result: DirectTestResult | None
    error: str | None

    @property
    def is_success(self) -> bool:
        """True when the test completed and the process exited 0."""
        if self.error is not None or self.result is None:
            return False
        return self.result.process.exit_code == 0


@dataclass(frozen=True, slots=True)
class LogsOutcome:
    """Immutable result of a persisted-log read."""

    label: str
    logs: JobLogs | None
    error: str | None


@dataclass(frozen=True, slots=True)
class EnvironmentOutcome:
    """Immutable result of an environment comparison."""

    label: str
    difference: EnvironmentDifference | None
    error: str | None


class DiagnosticsController:
    """Validates and queues exactly one direct-test request at a time.

    ``environment`` is a snapshot of the GUI process environment (from
    ``gui_environment``) used for the presentation-safe comparison; it is
    copied here so a later mutation of the snapshot never changes what was
    compared.
    """

    def __init__(
        self, services: TaskCommandService, environment: Mapping[str, str]
    ) -> None:
        self._services = services
        self._environment: dict[str, str] = dict(environment)
        self._current: JobDefinition | None = None
        self._busy = False

    @property
    def busy(self) -> bool:
        """True while a direct-test request is accepted and not yet finished."""
        return self._busy

    @property
    def environment(self) -> Mapping[str, str]:
        """The GUI process environment snapshot used for comparisons."""
        return self._environment

    def request_test(self, job: JobDefinition) -> RequestVerdict:
        """Validate *job* and accept it into the single test slot.

        Returns :data:`RequestVerdict.ACCEPTED` when the request is queued
        for the worker; the verdict otherwise says why it was refused.
        """
        if self._busy:
            return RequestVerdict.BUSY
        if self._invalid(job):
            return RequestVerdict.INVALID_JOB
        self._current = job
        self._busy = True
        return RequestVerdict.ACCEPTED

    def execute(self) -> TestOutcome:
        """Run the accepted direct test and marshal the outcome.

        Safe to call from a worker thread: every service failure is caught
        and converted to an error outcome, so the outcome is always produced
        and the busy state is always cleared by the worker's ``finish()``.
        """
        assert self._current is not None
        job = self._current
        try:
            result = self._services.test_job(job)
        except Exception as exc:
            return TestOutcome(label=job.label, result=None, error=str(exc))
        return TestOutcome(label=job.label, result=result, error=None)

    def finish(self) -> None:
        """Clear the busy state; called by the worker after ``execute()``."""
        self._busy = False
        self._current = None

    def read_logs(self, job: JobDefinition) -> LogsOutcome:
        """Read the job's configured persisted logs (synchronous, read-only)."""
        try:
            logs = self._services.read_logs_for(job)
        except Exception as exc:
            return LogsOutcome(label=job.label, logs=None, error=str(exc))
        return LogsOutcome(label=job.label, logs=logs, error=None)

    def compare_environment(self, job: JobDefinition) -> EnvironmentOutcome:
        """Compare the GUI process environment with the job's scheduled
        environment (synchronous, pure)."""
        try:
            difference = self._services.compare_environment(job, self._environment)
        except Exception as exc:
            return EnvironmentOutcome(label=job.label, difference=None, error=str(exc))
        return EnvironmentOutcome(label=job.label, difference=difference, error=None)

    def _invalid(self, job: JobDefinition) -> bool:
        try:
            self._services.validate_job(job)
        except Exception:
            return True
        return False
