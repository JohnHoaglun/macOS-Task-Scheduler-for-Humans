"""Lifecycle controller bridging the Lifecycle menu to TaskCommandService.

Qt-free: all validation, gating, and busy-state logic lives here so it can
be tested without an event loop. The :class:`~task_scheduler.gui.controllers.
lifecycle_worker.LifecycleWorker` QObject performs the accepted request on
a worker thread and marshals an immutable :class:`LifecycleOutcome`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from task_scheduler.application import ExternalEditResult
from task_scheduler.application.diagnostic_models import Diagnostic
from task_scheduler.application.job_service import JobNotFoundError
from task_scheduler.application.task_command_service import (
    InstallResult,
    ListingKind,
    TaskCommandService,
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
    "usable_external_label",
]


def usable_external_label(listing: TaskListing) -> str | None:
    """The decoded plist's non-empty ``Label`` value, or ``None``.

    Mirrors the service's usable-label check so GUI gating matches what the
    external control operations accept.
    """
    if listing.parsed is None:
        return None
    label = listing.parsed.raw.get("Label")
    if isinstance(label, str) and label:
        return label
    return None


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
    """An accepted lifecycle request: the action and its target.

    Managed requests carry the catalog *label* and *job*; external requests
    carry the source plist *source_path* (label/job may be ``None``).
    """

    action: LifecycleAction
    label: str | None = None
    job: JobDefinition | None = None
    source_path: Path | None = None


@dataclass(frozen=True, slots=True)
class LifecycleOutcome:
    """Immutable result of a lifecycle action, marshaled to the main thread.

    ``result`` is the service's structured result (or ``None`` when no process
    ran); ``error`` is the human-readable failure reason for exceptions;
    ``diagnostics`` carries the LIFECYCLE-group findings (empty on failure).
    External actions carry their ``external_result`` instead of ``result``.
    """

    action: LifecycleAction
    label: str | None
    result: LifecycleResult | None
    error: str | None
    diagnostics: tuple[Diagnostic, ...] = ()
    external_result: ExternalEditResult | None = None

    @property
    def is_success(self) -> bool:
        """True when the operation completed and its process exited 0.

        A structured result with a nonzero (or missing) exit code is a
        failure even though no exception was raised. External outcomes
        succeed when no launchctl phase failed (quarantine carries no
        process).
        """
        if self.error is not None:
            return False
        if self.external_result is not None:
            process = self.external_result.process
            return process is None or process.exit_code == 0
        if self.result is None:
            return False
        return self.result.process.exit_code == 0


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
        """Universal gating per the state matrix: a saved managed row offers
        Install/Disable/Enable; an installed managed row offers the existing
        five; external rows offer Disable always, Enable and Run Now when a
        usable label exists (Run Now only when loaded is True)."""
        if listing is None:
            return frozenset()
        if not listing.managed:
            return self._external_actions(listing)
        if listing.job is None:
            return frozenset()
        if listing.kind is ListingKind.SAVED:
            return frozenset(
                {
                    LifecycleAction.INSTALL,
                    LifecycleAction.DISABLE,
                    LifecycleAction.ENABLE,
                }
            )
        return frozenset(
            {
                LifecycleAction.REINSTALL,
                LifecycleAction.UNINSTALL,
                LifecycleAction.ENABLE,
                LifecycleAction.DISABLE,
                LifecycleAction.RUN_NOW,
            }
        )

    @staticmethod
    def _external_actions(listing: TaskListing) -> frozenset[LifecycleAction]:
        """Lifecycle actions for an external (unmanaged) row per the state matrix."""
        actions = {LifecycleAction.DISABLE}
        label = usable_external_label(listing)
        if label is not None:
            actions.add(LifecycleAction.ENABLE)
            if listing.loaded is True:
                actions.add(LifecycleAction.RUN_NOW)
        return frozenset(actions)

    def enabled_remove_action(self, listing: TaskListing | None) -> bool:
        """Whether the File menu's Remove action is available for *listing*."""
        return listing is not None

    def request(self, action: LifecycleAction, listing: TaskListing | None) -> RequestVerdict:
        """Validate *action* for *listing*; accept it into the single slot.

        Returns :data:`RequestVerdict.ACCEPTED` when the request is queued
        for the worker; the verdict otherwise says why it was refused.
        """
        if self._busy:
            return RequestVerdict.BUSY
        if listing is None:
            return RequestVerdict.NOT_MANAGED
        if action not in self.enabled_actions(listing):
            return RequestVerdict.NOT_ALLOWED
        if listing.managed:
            if listing.job is None:
                return RequestVerdict.NOT_MANAGED
            self._current = LifecycleRequest(
                action=action, label=listing.job.label, job=listing.job
            )
        else:
            if listing.path is None:
                return RequestVerdict.NOT_MANAGED
            self._current = LifecycleRequest(
                action=action,
                label=usable_external_label(listing),
                source_path=listing.path,
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
        if request.source_path is not None:
            return self._execute_external(request)
        label = request.label
        if label is None:
            return LifecycleOutcome(
                action=request.action,
                label=None,
                result=None,
                error="the request has no usable label",
            )
        try:
            result = self._execute_action(request)
            diagnostics = self._services.lifecycle_diagnostics(label, request.action.value, result)
        except Exception as exc:
            return LifecycleOutcome(action=request.action, label=label, result=None, error=str(exc))
        return LifecycleOutcome(
            action=request.action,
            label=label,
            result=result,
            error=None,
            diagnostics=diagnostics,
        )

    def _execute_external(self, request: LifecycleRequest) -> LifecycleOutcome:
        """Route an external request to the matching service control method."""
        assert request.source_path is not None
        path = request.source_path
        try:
            if request.action is LifecycleAction.DISABLE:
                external = self._services.disable_external(path)
            elif request.action is LifecycleAction.ENABLE:
                external = self._services.enable_external(path)
            else:
                external = self._services.run_now_external(path)
        except Exception as exc:
            return LifecycleOutcome(
                action=request.action, label=request.label, result=None, error=str(exc)
            )
        return LifecycleOutcome(
            action=request.action,
            label=external.label,
            result=None,
            error=None,
            external_result=external,
        )

    def finish(self) -> None:
        """Clear the busy state; called by the worker after ``execute()``."""
        self._busy = False
        self._current = None

    def _execute_action(self, request: LifecycleRequest) -> LifecycleResult:
        job = request.job
        label = request.label
        if job is None or label is None:
            raise ValueError("the request is missing the managed job")
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

    # -- catalog removal -----------------------------------------------------

    def request_remove_saved(self, label: str) -> Path | None:
        """Request remove for a saved managed job identified by *label*."""
        try:
            return self._services.remove_saved_job(label)
        except (ValueError, JobNotFoundError):
            return None
