"""Domain models for the task scheduler."""

from task_scheduler.domain.command import (
    Command,
    ExecutableCommand,
    PythonCommand,
    ShellCommand,
    command_argv,
)
from task_scheduler.domain.environment import EnvironmentConfig
from task_scheduler.domain.errors import UnsupportedSchemaVersionError
from task_scheduler.domain.job import SUPPORTED_SCHEMA_VERSION, JobDefinition
from task_scheduler.domain.logging_config import LoggingConfig
from task_scheduler.domain.schedule import (
    MIN_INTERVAL_SECONDS,
    CalendarSchedule,
    IntervalSchedule,
    Schedule,
    Weekday,
    human_interval,
    upcoming_occurrences,
)

__all__ = [
    "CalendarSchedule",
    "Command",
    "EnvironmentConfig",
    "ExecutableCommand",
    "IntervalSchedule",
    "JobDefinition",
    "LoggingConfig",
    "MIN_INTERVAL_SECONDS",
    "PythonCommand",
    "SUPPORTED_SCHEMA_VERSION",
    "Schedule",
    "ShellCommand",
    "UnsupportedSchemaVersionError",
    "Weekday",
    "command_argv",
    "human_interval",
    "upcoming_occurrences",
]
