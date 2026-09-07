"""Tests for the history presenter (pure functions)."""

from __future__ import annotations

from datetime import UTC, datetime

from task_scheduler.application.history_models import (
    HistoryEvent,
    HistoryEventKind,
    HistoryOutcome,
)
from task_scheduler.gui.presenters.history_presenter import (
    HISTORY_DISCLOSURE,
    HISTORY_EMPTY,
    HISTORY_NOT_APPLICABLE,
    format_event_details,
    format_event_kind,
    format_event_outcome,
    format_event_time,
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


class TestConstants:
    def test_disclosure_text(self):
        assert HISTORY_DISCLOSURE == (
            "Records only what this application observed (tests, manual runs, "
            "status checks). It does not prove launchd ran the task on schedule."
        )

    def test_empty_text(self):
        assert HISTORY_EMPTY == "No execution history recorded for this task."

    def test_not_applicable_text(self):
        assert HISTORY_NOT_APPLICABLE == (
            "Execution history is only recorded for managed tasks."
        )


class TestFormatEventTime:
    def test_formats_local_time(self):
        event = _event()
        # datetime is in UTC, astimezone() converts to local
        result = format_event_time(event)
        # Assert it matches the expected format YYYY-MM-DD HH:MM:SS
        assert len(result) == 19
        assert result[4] == "-"
        assert result[7] == "-"
        assert result[10] == " "
        assert result[13] == ":"
        assert result[16] == ":"

    def test_uses_local_timezone(self):
        # UTC midnight should render as local time, not as "UTC"
        event = _event(
            created_at=datetime(2025, 1, 15, 0, 0, 0, tzinfo=UTC)
        )
        result = format_event_time(event)
        # Should NOT contain "UTC" or "GMT" in the time string
        assert "UTC" not in result
        assert "GMT" not in result


class TestFormatEventKind:
    def test_all_kinds_mapped(self):
        assert format_event_kind(HistoryEventKind.DIRECT_TEST) == "Direct test"
        assert format_event_kind(HistoryEventKind.MANUAL_RUN) == "Manual run"
        assert format_event_kind(HistoryEventKind.STATUS_OBSERVATION) == "Status check"
        assert format_event_kind(HistoryEventKind.DIAGNOSTIC_RESULT) == "Diagnostics"


class TestFormatEventOutcome:
    def test_all_outcomes_mapped(self):
        assert format_event_outcome(HistoryOutcome.SUCCESS) == "Succeeded"
        assert format_event_outcome(HistoryOutcome.FAILURE) == "Failed"
        assert format_event_outcome(HistoryOutcome.OBSERVED) == "Observed"


class TestFormatEventDetails:
    def test_all_fields_present_status_observation(self):
        event = _event(
            kind=HistoryEventKind.STATUS_OBSERVATION,
            exit_code=0,
            duration_seconds=0.500,
            loaded=True,
            diagnostic_codes=("code_a", "code_b"),
        )
        result = format_event_details(event)
        parts = result.split(" \u00b7 ")
        assert "exit code 0" in parts
        assert "0.500s" in parts
        assert "loaded" in parts
        assert "codes: code_a, code_b" in parts

    def test_exit_code_only(self):
        event = _event(exit_code=1, duration_seconds=None, loaded=None, diagnostic_codes=())
        result = format_event_details(event)
        assert result == "exit code 1"

    def test_duration_only(self):
        event = _event(exit_code=None, duration_seconds=1.250, loaded=None, diagnostic_codes=())
        result = format_event_details(event)
        assert result == "1.250s"

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

    def test_non_status_kind_never_shows_loaded(self):
        event = _event(
            kind=HistoryEventKind.DIRECT_TEST,
            loaded=True,
        )
        result = format_event_details(event)
        assert "loaded" not in result
        assert "not loaded" not in result
        assert "load state unknown" not in result

    def test_diagnostic_codes_comma_joined(self):
        event = _event(
            diagnostic_codes=("err_one", "err_two", "err_three"),
        )
        result = format_event_details(event)
        assert "codes: err_one, err_two, err_three" in result

    def test_no_parts_returns_empty_string(self):
        event = _event(exit_code=None, duration_seconds=None, loaded=None, diagnostic_codes=())
        result = format_event_details(event)
        assert result == ""

    def test_exit_and_duration(self):
        event = _event(exit_code=0, duration_seconds=2.000, loaded=None, diagnostic_codes=())
        result = format_event_details(event)
        assert "exit code 0" in result
        assert "2.000s" in result
