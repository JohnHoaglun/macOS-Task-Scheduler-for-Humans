"""Tests for the history controller (Qt-free)."""

from __future__ import annotations

from datetime import UTC
from uuid import UUID

from task_scheduler.application.history_models import HistoryEvent, HistoryEventKind, HistoryOutcome
from task_scheduler.application.job_service import JobNotFoundError
from task_scheduler.gui.controllers.history_controller import (
    HistoryController,
)


def _make_event(**overrides) -> HistoryEvent:
    from datetime import datetime
    kwargs = {
        "created_at": datetime(2025, 1, 15, 10, 30, 0, tzinfo=UTC),
        "job_id": UUID("00000000-0000-4000-8000-000000000001"),
        "label": "com.example.job",
        "kind": HistoryEventKind.DIRECT_TEST,
        "outcome": HistoryOutcome.SUCCESS,
        "exit_code": 0,
        "duration_seconds": 1.5,
        "loaded": None,
        "diagnostic_codes": (),
    }
    kwargs.update(overrides)
    return HistoryEvent(**kwargs)


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
    def test_happy_path_returns_events(self):
        events = (_make_event(), _make_event())
        svc = FakeService(events=events)
        ctrl = HistoryController(svc)
        outcome = ctrl.history_for("com.example.job")
        assert outcome.label == "com.example.job"
        assert outcome.error is None
        assert outcome.events == events

    def test_empty_events_returns_empty_tuple(self):
        svc = FakeService()
        ctrl = HistoryController(svc)
        outcome = ctrl.history_for("com.example.job")
        assert outcome.events == ()
        assert outcome.error is None

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
