"""Unit tests for CLI render helpers not exercised by the CLI tests."""

from __future__ import annotations

from pathlib import Path

from task_scheduler.application.log_service import LogStream
from task_scheduler.cli import render
from task_scheduler.domain import CalendarSchedule, IntervalSchedule
from task_scheduler.platform.macos import LaunchAgentStatus, ProcessResult
from task_scheduler.platform.macos.log_reader import LOG_TAIL_BYTES


def test_format_status_unknown() -> None:
    status = LaunchAgentStatus(loaded=None, process=ProcessResult(exit_code=None))
    assert render.format_status(status) == "launchd status unknown (launchctl could not be queried)"


def test_format_schedule_interval() -> None:
    assert render.format_schedule(IntervalSchedule(seconds=1800)) == "Every 30 minutes"


def test_format_schedule_run_at_load() -> None:
    schedule = CalendarSchedule(times=["07:30"], weekdays={"monday"}, run_at_load=True)
    assert render.format_schedule(schedule) == "07:30 on monday + at login"


def test_format_stream_truncation_marker_after_heading() -> None:
    stream = LogStream(
        name="stdout",
        path=Path("/logs/out.log"),
        content="line",
        truncated=True,
        total_bytes=LOG_TAIL_BYTES * 3,
    )
    assert render.format_stream(stream) == (
        "=== stdout ===\n"
        "(truncated: showing the last 256 KiB of 786432 bytes)\n"
        "line"
    )


def test_format_stream_no_marker_when_not_truncated() -> None:
    stream = LogStream(
        name="stdout",
        path=Path("/logs/out.log"),
        content="line",
        truncated=False,
        total_bytes=10,
    )
    assert render.format_stream(stream) == "=== stdout ===\nline"


def test_format_stream_error_branch_has_no_marker() -> None:
    stream = LogStream(
        name="stderr",
        path=Path("/logs/err.log"),
        error="could not read log file /logs/err.log: denied",
        truncated=True,
        total_bytes=999,
    )
    assert (
        render.format_stream(stream)
        == "=== stderr ===\ncould not read log file /logs/err.log: denied"
    )
