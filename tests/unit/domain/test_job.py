"""Tests for the JobDefinition model."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.conftest import make_job

from task_scheduler.domain import (
    UnsupportedSchemaVersionError,
)

VALID_LABELS = [
    "io.github.macos-task-scheduler.user.daily-backup",
    "A_b-c.1",
    "com.example.job",
]

INVALID_LABELS = ["", "has space", "bad/label", "-lead", ".lead", "tab\there"]

@pytest.mark.parametrize("label", INVALID_LABELS)
def test_invalid_labels_rejected(label: str) -> None:
    with pytest.raises(ValidationError):
        make_job(label=label)

def test_blank_name_rejected() -> None:
    with pytest.raises(ValidationError):
        make_job(name="   ")

@pytest.mark.parametrize("version", [0, 1, 99])
def test_unsupported_schema_versions_rejected(version: int) -> None:
    with pytest.raises(UnsupportedSchemaVersionError):
        make_job(schema_version=version)

def test_relative_working_directory_rejected() -> None:
    with pytest.raises(ValidationError):
        make_job(working_directory=Path("relative/project"))

