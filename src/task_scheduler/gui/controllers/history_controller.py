"""History controller bridging the History panel to TaskCommandService.

Qt-free: all validation, gating, and error handling lives here so it can be
tested without an event loop. Mirrors the synchronous fast-read pattern of
DiagnosticsController.read_logs — no worker thread.
"""

from __future__ import annotations

from dataclasses import dataclass

from task_scheduler.application import TaskCommandService
from task_scheduler.application.history_models import HistoryEvent
from task_scheduler.application.job_service import JobNotFoundError

__all__ = ["HistoryController", "HistoryOutcome"]


@dataclass(frozen=True, slots=True)
class HistoryOutcome:
    """Immutable result of a history query for one task label.

    ``events`` carries the recorded events (newest first); ``error`` carries
    the human-readable failure reason (JobNotFoundError or service error).
    """

    label: str
    events: tuple[HistoryEvent, ...] = ()
    error: str | None = None


class HistoryController:
    """Validates and queries execution history for a single label."""

    def __init__(self, services: TaskCommandService) -> None:
        self._services = services

    def history_for(self, label: str) -> HistoryOutcome:
        """Return the most recent history events for *label* (up to 50)."""
        try:
            result = self._services.history(label)
        except JobNotFoundError as exc:
            return HistoryOutcome(label=label, events=(), error=str(exc))
        if result.error is not None:
            return HistoryOutcome(label=label, events=(), error=result.error)
        return HistoryOutcome(label=label, events=result.events, error=None)
