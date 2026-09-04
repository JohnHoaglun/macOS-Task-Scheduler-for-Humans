"""Shared test fixtures."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from uuid import UUID

from task_scheduler.domain import (
    CalendarSchedule,
    EnvironmentConfig,
    JobDefinition,
    LoggingConfig,
    PythonCommand,
    Weekday,
)

FIXED_JOB_ID = UUID("12345678-1234-5678-1234-567812345678")


def make_job(**overrides: object) -> JobDefinition:
    """Build a valid job, applying *overrides* to the default fields."""
    kwargs: dict[str, object] = {
        "schema_version": 2,
        "id": FIXED_JOB_ID,
        "name": "Daily Backup",
        "label": "io.github.macos-task-scheduler.user.daily-backup",
        "enabled": True,
        "command": PythonCommand(
            interpreter="/Users/example/project/.venv/bin/python",
            script="/Users/example/project/main.py",
            arguments=["--mode", "daily"],
        ),
        "schedule": CalendarSchedule(times=["07:30"], weekdays={Weekday.MONDAY}),
        "environment": EnvironmentConfig(variables={}),
        "working_directory": None,
        "logging": LoggingConfig(stdout_path=None, stderr_path=None),
    }
    kwargs.update(overrides)
    return JobDefinition(**kwargs)  # type: ignore[arg-type]
