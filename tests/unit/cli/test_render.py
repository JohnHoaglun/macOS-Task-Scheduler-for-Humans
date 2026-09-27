"""Unit tests for CLI render helpers not exercised by the CLI tests."""

from __future__ import annotations

from pathlib import Path

from task_scheduler.application.launchd_test_service import LaunchdTestResult
from task_scheduler.application.log_service import LogStream
from task_scheduler.cli import render
from task_scheduler.domain import CalendarSchedule, IntervalSchedule
from task_scheduler.platform.macos import (
    LaunchAgentStatus,
    LaunchctlAction,
    LaunchctlResult,
    ProcessResult,
    RunObservation,
)
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

def test_format_stream_no_path_shows_not_configured() -> None:
    stream = LogStream(name="stdout", path=None)
    assert render.format_stream(stream) == (
        "=== stdout ===\nnot configured (no stdout log path set)"
    )

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

def _launchd_result(
    *,
    passed: bool,
    reason: str,
    run: RunObservation | None = None,
    kickstart_exit: int = 0,
    kickstart_stderr: str = "",
) -> LaunchdTestResult:
    return LaunchdTestResult(
        label="com.example.job",
        kickstart=LaunchctlResult(
            action=LaunchctlAction.TRIGGER,
            process=ProcessResult(exit_code=kickstart_exit, stderr=kickstart_stderr),
        ),
        observed=run is not None,
        timed_out=False,
        run=run,
        passed=passed,
        reason=reason,
    )

def test_format_launchd_test_passed_with_run() -> None:
    run = RunObservation(
        run_id="run-1", exit_code=0, duration_seconds=1.0, status="ok", stopped_at="ts"
    )
    result = _launchd_result(passed=True, reason="run exited 0 in 1.0s (ok)", run=run)
    assert render.format_launchd_test(result) == (
        "launchd test passed for com.example.job\n"
        "reason: run exited 0 in 1.0s (ok)\n"
        "run run-1: exit 0 in 1.0s (ok)"
    )

def test_format_launchd_test_failed_no_run() -> None:
    result = _launchd_result( passed=False, reason="kickstart rejected (launchctl exit 1)" )
    assert render.format_launchd_test(result) == (
        "launchd test FAILED for com.example.job\n"
        "reason: kickstart rejected (launchctl exit 1)"
    )

def test_format_launchd_test_shows_kickstart_stderr() -> None:
    result = _launchd_result(
        passed=False,
        reason="kickstart rejected (launchctl exit 1)",
        kickstart_exit=1,
        kickstart_stderr="Boot-out failed: 111: Could not find service\n",
    )
    assert render.format_launchd_test(result) == (
        "launchd test FAILED for com.example.job\n"
        "reason: kickstart rejected (launchctl exit 1)\n"
        "kickstart stderr: Boot-out failed: 111: Could not find service"
    )
