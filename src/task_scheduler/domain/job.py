"""The core job definition model."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from task_scheduler.domain.command import Command
from task_scheduler.domain.environment import EnvironmentConfig
from task_scheduler.domain.errors import UnsupportedSchemaVersionError
from task_scheduler.domain.logging_config import LoggingConfig
from task_scheduler.domain.schedule import Schedule

SUPPORTED_SCHEMA_VERSION = 1

_NAME_MAX_LENGTH = 120
_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class JobDefinition(BaseModel):
    """One scheduled task; the application's source of truth."""

    schema_version: int
    id: UUID
    name: str
    label: str
    enabled: bool = True
    command: Command
    schedule: Schedule
    environment: EnvironmentConfig = Field(default_factory=EnvironmentConfig)
    working_directory: Path | None = None
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @field_validator("schema_version")
    @classmethod
    def _check_schema_version(cls, value: int) -> int:
        if value != SUPPORTED_SCHEMA_VERSION:
            raise UnsupportedSchemaVersionError(value, SUPPORTED_SCHEMA_VERSION)
        return value

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        if len(value) > _NAME_MAX_LENGTH:
            raise ValueError(f"name must be at most {_NAME_MAX_LENGTH} characters")
        return value

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: str) -> str:
        if not value:
            raise ValueError("label must not be empty")
        if any(char.isspace() for char in value):
            raise ValueError("label must not contain whitespace")
        if not _LABEL_PATTERN.fullmatch(value):
            raise ValueError(
                "label must start with a letter or number and contain only "
                "letters, numbers, '.', '-', and '_'"
            )
        return value

    @field_validator("working_directory")
    @classmethod
    def _validate_working_directory(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError(f"working_directory must be absolute, got {value!r}")
        return value
