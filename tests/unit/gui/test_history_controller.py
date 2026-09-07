"""Tests for the history controller (Qt-free)."""

from __future__ import annotations

from task_scheduler.application.job_service import JobNotFoundError
from task_scheduler.gui.controllers.history_controller import (
    HistoryController,
)


class FakeService:
    """Duck-typed TaskCommandService.history() for testing."""

    def __init__(self, events=(), error=None) -> None:
        self.events = events
        self.error = error

    def history(self, label: str, *, limit: int = 50):
        from task_scheduler.application.history_models import HistoryReadResult
        if self.error is not None:
            return HistoryReadResult(events=(), error=self.error)
        return HistoryReadResult(events=self.events)

class FakeFailingService:
    def history(self, label: str, *, limit: int = 50):
        raise JobNotFoundError("com.example.missing")

class TestHistoryController:

    def test_job_not_found_error_produces_error_outcome(self):
        svc = FakeFailingService()
        ctrl = HistoryController(svc)
        outcome = ctrl.history_for("com.example.missing")
        assert outcome.label == "com.example.missing"
        assert outcome.events == ()
        assert outcome.error == "no managed job with label 'com.example.missing'"

    def test_service_error_passthrough(self):
        svc = FakeService(error="execution history unavailable")
        ctrl = HistoryController(svc)
        outcome = ctrl.history_for("com.example.job")
        assert outcome.error == "execution history unavailable"
        assert outcome.events == ()
        assert outcome.label == "com.example.job"
