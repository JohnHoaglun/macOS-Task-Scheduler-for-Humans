"""Unit tests for CLI render helpers not exercised by the CLI tests."""

from __future__ import annotations

from task_scheduler.cli import render
from task_scheduler.domain import CalendarSchedule, IntervalSchedule
from task_scheduler.platform.macos import LaunchAgentStatus, ProcessResult


def test_format_status_unknown() -> None:
    status = LaunchAgentStatus(loaded=None, process=ProcessResult(exit_code=None))
    assert render.format_status(status) == (
        "launchd status unknown (launchctl could not be queried)"
    )


def test_format_schedule_calendar() -> None:
    schedule = CalendarSchedule(
        times=["17:30", "07:30"], weekdays={"monday", "friday"}
    )
    assert render.format_schedule(schedule) == "07:30 and 17:30 on friday, monday"


def test_format_schedule_interval() -> None:
    assert render.format_schedule(IntervalSchedule(seconds=1800)) == "Every 30 minutes"


def test_format_schedule_run_at_load() -> None:
    schedule = CalendarSchedule(times=["07:30"], weekdays={"monday"}, run_at_load=True)
    assert render.format_schedule(schedule) == "07:30 on monday + at login"
