"""Lifecycle controller bridging the Lifecycle menu to TaskCommandService.

Qt-free: all validation, gating, and busy-state logic lives here so it can
be tested without an event loop. The :class:`~task_scheduler.gui.controllers.
lifecycle_worker.LifecycleWorker` QObject performs the accepted request on
a worker thread and marshals an immutable :class:`LifecycleOutcome`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from task_scheduler.application import TaskCommandService
from task_scheduler.application.task_command_service import (
    InstallResult,
    ListingKind,
    TaskListing,
    UninstallResult,
)
from task_scheduler.domain import JobDefinition
from task_scheduler.platform.macos import LaunchAgentStatus, LaunchctlResult

__all__ = [
    "LifecycleAction",
    "LifecycleController",
    "LifecycleOutcome",
    "LifecycleRequest",
    "LifecycleResult",
    "RequestVerdict",
]

LifecycleResult = InstallResult | LaunchctlResult | LaunchAgentStatus | UninstallResult


class LifecycleAction(StrEnum):
    """The six lifecycle operations the Lifecycle menu offers."""

    INSTALL = "install"
    REINSTALL = "reinstall"
    UNINSTALL = "uninstall"
    ENABLE = "enable"
    DISABLE = "disable"
    RUN_NOW = "run now"


class RequestVerdict(StrEnum):
    """Why a lifecycle request was accepted or refused (synchronously)."""

    ACCEPTED = "accepted"
    BUSY = "busy"
    NOT_MANAGED = "not managed"
    NOT_ALLOWED = "not allowed"


@dataclass(frozen=True, slots=True)
class LifecycleRequest:
    """An accepted lifecycle request: the action and its managed target."""

    action: LifecycleAction
    label: str
    job: JobDefinition


@dataclass(frozen=True, slots=True)
class LifecycleOutcome:
    """Immutable result of a lifecycle action, marshaled to the main thread.

    ``result`` is the service's structured result (or ``None`` on failure);
    ``error`` is the human-readable failure reason (or ``None`` on success).
    """

    action: LifecycleAction
    label: str
    result: LifecycleResult | None
    error: str | None


class LifecycleController:
    """Validates and queues exactly one managed lifecycle request at a time."""

    def __init__(self, services: TaskCommandService) -> None:
        self._services = services
        self._current: LifecycleRequest | None = None
        self._busy = False

    @property
    def busy(self) -> bool:
        """True while a request is accepted and not yet finished."""
        return self._busy

    def enabled_actions(self, listing: TaskListing | None) -> frozenset[LifecycleAction]:
        """Gating: a saved row offers Install only; an installed managed row
        offers the other five; anything else offers nothing."""
        if listing is None or not listing.managed or listing.job is None:
            return frozenset()
        if listing.kind is ListingKind.SAVED:
            return frozenset({LifecycleAction.INSTALL})
        return frozenset(
            {
                LifecycleAction.REINSTALL,
                LifecycleAction.UNINSTALL,
                LifecycleAction.ENABLE,
                LifecycleAction.DISABLE,
                LifecycleAction.RUN_NOW,
            }
        )

    def request(self, action: LifecycleAction, listing: TaskListing | None) -> RequestVerdict:
        """Validate *action* for *listing*; accept it into the single slot.

        Returns :data:`RequestVerdict.ACCEPTED` when the request is queued
        for the worker; the verdict otherwise says why it was refused.
        """
        if self._busy:
            return RequestVerdict.BUSY
        if listing is None or not listing.managed or listing.job is None:
            return RequestVerdict.NOT_MANAGED
        if action not in self.enabled_actions(listing):
            return RequestVerdict.NOT_ALLOWED
        self._current = LifecycleRequest(
            action=action, label=listing.job.label, job=listing.job
        )
        self._busy = True
        return RequestVerdict.ACCEPTED

    def execute(self) -> LifecycleOutcome:
        """Run the accepted request and marshal the outcome.

        Safe to call from a worker thread: every service failure is caught
        and converted to an error outcome, so the outcome is always produced
        and the busy state is always cleared by the worker's ``finish()``.
        """
        assert self._current is not None
        request = self._current
        try:
            result = self._execute_action(request)
        except Exception as exc:
            return LifecycleOutcome(
                action=request.action, label=request.label, result=None, error=str(exc)
            )
        return LifecycleOutcome(
            action=request.action, label=request.label, result=result, error=None
        )

    def finish(self) -> None:
        """Clear the busy state; called by the worker after ``execute()``."""
        self._busy = False
        self._current = None

    def _execute_action(self, request: LifecycleRequest) -> LifecycleResult:
        job = request.job
        label = request.label
        if request.action is LifecycleAction.INSTALL:
            return self._services.install(job)
        if request.action is LifecycleAction.REINSTALL:
            return self._services.reinstall(label)
        if request.action is LifecycleAction.UNINSTALL:
            return self._services.uninstall(label)
        if request.action is LifecycleAction.ENABLE:
            return self._services.enable(label)
        if request.action is LifecycleAction.DISABLE:
            return self._services.disable(label)
        return self._services.run_now(label)
