"""Tests for the history presenter (pure functions)."""

from __future__ import annotations

from datetime import UTC, datetime

from task_scheduler.application.history_models import (
    HistoryEvent,
    HistoryEventKind,
    HistoryOutcome,
)
from task_scheduler.gui.presenters.history_presenter import (
    format_event_details,
)


def _event(**overrides) -> HistoryEvent:
    kwargs = {
        "created_at": datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC),
        "job_id": "00000000-0000-4000-8000-000000000001",
        "label": "com.example.job",
        "kind": HistoryEventKind.DIRECT_TEST,
        "outcome": HistoryOutcome.SUCCESS,
        "exit_code": 0,
        "duration_seconds": 1.250,
        "loaded": None,
        "diagnostic_codes": (),
    }
    kwargs.update(overrides)
    # Ensure job_id is UUID
    from uuid import UUID
    if isinstance(kwargs["job_id"], str):
        kwargs["job_id"] = UUID(kwargs["job_id"])
    return HistoryEvent(**kwargs)

class TestFormatEventDetails:

    def test_loaded_true(self):
        event = _event(kind=HistoryEventKind.STATUS_OBSERVATION, loaded=True)
        result = format_event_details(event)
        assert "loaded" in result

    def test_loaded_false(self):
        event = _event(kind=HistoryEventKind.STATUS_OBSERVATION, loaded=False)
        result = format_event_details(event)
        assert "not loaded" in result

    def test_load_state_unknown(self):
        event = _event(kind=HistoryEventKind.STATUS_OBSERVATION, loaded=None)
        result = format_event_details(event)
        assert "load state unknown" in result

    def test_diagnostic_codes_comma_joined(self):
        event = _event(
            diagnostic_codes=("err_one", "err_two", "err_three"),
        )
        result = format_event_details(event)
        assert "codes: err_one, err_two, err_three" in result
