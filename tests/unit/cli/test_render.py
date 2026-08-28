"""Unit tests for CLI render helpers not exercised by the CLI tests."""

from __future__ import annotations

from task_scheduler.cli import render
from task_scheduler.platform.macos import LaunchAgentStatus, ProcessResult


def test_format_status_unknown() -> None:
    status = LaunchAgentStatus(loaded=None, process=ProcessResult(exit_code=None))
    assert render.format_status(status) == (
        "launchd status unknown (launchctl could not be queried)"
    )
