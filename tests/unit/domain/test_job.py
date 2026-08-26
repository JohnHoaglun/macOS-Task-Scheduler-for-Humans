"""Tests for the JobDefinition model."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from task_scheduler.domain import (
    JobDefinition,
    LoggingConfig,
    PythonCommand,
    Schedule,
    UnsupportedSchemaVersionError,
    Weekday,
)
from tests.conftest import FIXED_JOB_ID, make_job

VALID_LABELS = [
    "io.github.macos-task-scheduler.user.daily-backup",
    "A_b-c.1",
    "com.example.job",
]

INVALID_LABELS = ["", "has space", "bad/label", "-lead", ".lead", "tab\there"]


@pytest.mark.parametrize("label", VALID_LABELS)
def test_valid_labels_accepted(label: str) -> None:
    assert make_job(label=label).label == label


@pytest.mark.parametrize("label", INVALID_LABELS)
def test_invalid_labels_rejected(label: str) -> None:
    with pytest.raises(ValidationError):
        make_job(label=label)


def test_blank_name_rejected() -> None:
    with pytest.raises(ValidationError):
        make_job(name="   ")


def test_whitespace_name_normalized() -> None:
    assert make_job(name="  Daily Backup  ").name == "Daily Backup"


def test_overlong_name_rejected() -> None:
    with pytest.raises(ValidationError):
        make_job(name="x" * 121)


def test_max_length_name_accepted() -> None:
    assert make_job(name="x" * 120).name == "x" * 120


def test_uuid_round_trip() -> None:
    job = make_job()
    assert job.id == FIXED_JOB_ID
    again = job.model_validate_json(job.model_dump_json())
    assert again.id == FIXED_JOB_ID


def test_enabled_true_false_preserved() -> None:
    assert make_job(enabled=True).enabled is True
    assert make_job(enabled=False).enabled is False


def test_schema_version_one_accepted() -> None:
    assert make_job().schema_version == 1


@pytest.mark.parametrize("version", [0, 2, 99])
def test_unsupported_schema_versions_rejected(version: int) -> None:
    with pytest.raises(UnsupportedSchemaVersionError):
        make_job(schema_version=version)


def test_schema_version_required() -> None:
    kwargs = make_job().model_dump(mode="json")
    kwargs.pop("schema_version")
    with pytest.raises(ValidationError):
        JobDefinition.model_validate(kwargs)


@pytest.mark.parametrize("path", [Path("/Users/example/project"), Path("/Volumes/data")])
def test_absolute_working_directory_accepted(path: Path) -> None:
    assert make_job(working_directory=path).working_directory == path


def test_relative_working_directory_rejected() -> None:
    with pytest.raises(ValidationError):
        make_job(working_directory=Path("relative/project"))


def test_absolute_log_paths_accepted() -> None:
    logging = LoggingConfig(
        stdout_path="/Users/example/logs/task.stdout.log",
        stderr_path="/Users/example/logs/task.stderr.log",
    )
    job = make_job(logging=logging)
    assert job.logging.stdout_path == Path("/Users/example/logs/task.stdout.log")
    assert job.logging.stderr_path == Path("/Users/example/logs/task.stderr.log")


@pytest.mark.parametrize(
    "kwargs",
    [{"stdout_path": "relative/stdout.log"}, {"stderr_path": "relative/stderr.log"}],
)
def test_relative_log_paths_rejected(kwargs: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        make_job(logging=LoggingConfig(**kwargs))


def test_environment_defaults_empty() -> None:
    assert make_job().environment.variables == {}


def test_command_and_schedule_embedded() -> None:
    job = make_job()
    assert isinstance(job.command, PythonCommand)
    assert isinstance(job.schedule, Schedule)
    assert job.schedule.weekdays == {Weekday.MONDAY}
