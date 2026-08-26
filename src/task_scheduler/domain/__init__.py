"""Domain models for the task scheduler."""

from task_scheduler.domain.command import (
    Command,
    ExecutableCommand,
    PythonCommand,
    ShellCommand,
)
from task_scheduler.domain.environment import EnvironmentConfig
from task_scheduler.domain.errors import UnsupportedSchemaVersionError
from task_scheduler.domain.job import SUPPORTED_SCHEMA_VERSION, JobDefinition
from task_scheduler.domain.logging_config import LoggingConfig
from task_scheduler.domain.schedule import Schedule, Weekday

__all__ = [
    "Command",
    "EnvironmentConfig",
    "ExecutableCommand",
    "JobDefinition",
    "LoggingConfig",
    "PythonCommand",
    "SUPPORTED_SCHEMA_VERSION",
    "Schedule",
    "ShellCommand",
    "UnsupportedSchemaVersionError",
    "Weekday",
]
