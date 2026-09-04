"""Tests for JSON (de)serialization of job definitions."""

import json

import pytest
from pydantic import ValidationError

from task_scheduler.domain import (
    EnvironmentConfig,
    JobDefinition,
    LoggingConfig,
    ShellCommand,
    UnsupportedSchemaVersionError,
    Weekday,
)
from tests.conftest import make_job


def test_serialize_is_pretty_json() -> None:
    text = make_job().model_dump_json(indent=2)
    data = json.loads(text)
    assert data["schema_version"] == 2
    assert data["schedule"]["kind"] == "calendar"
    assert data["schedule"]["times"] == ["07:30"]
    assert data["schedule"]["run_at_load"] is False
    assert '"name": "Daily Backup"' in text


def test_semantic_round_trip() -> None:
    job = make_job()
    assert job.model_validate_json(job.model_dump_json()) == job


def test_full_field_round_trip() -> None:
    job = make_job(
        enabled=False,
        command=ShellCommand(
            executable="/bin/zsh", arguments=["/Users/example/scripts/backup.sh"]
        ),
        environment=EnvironmentConfig(variables={"FOO": "bar", "PATH": "/usr/bin"}),
        working_directory="/Users/example/project",
        logging=LoggingConfig(
            stdout_path="/Users/example/logs/out.log",
            stderr_path="/Users/example/logs/err.log",
        ),
    )
    again = job.model_validate_json(job.model_dump_json())
    assert again == job
    assert again.enabled is False
    assert again.environment.variables == {"FOO": "bar", "PATH": "/usr/bin"}
    assert str(again.working_directory) == "/Users/example/project"


def test_weekdays_round_trip_order_independent() -> None:
    job = make_job(
        schedule={
            "kind": "calendar",
            "times": ["07:30"],
            "weekdays": ["friday", "monday"],
        }
    )
    again = job.model_validate_json(job.model_dump_json())
    assert again.schedule.weekdays == {Weekday.FRIDAY, Weekday.MONDAY}


def test_unsupported_schema_rejected_on_deserialize() -> None:
    text = make_job().model_dump_json()
    bad = json.loads(text)
    bad["schema_version"] = 3
    with pytest.raises(UnsupportedSchemaVersionError):
        JobDefinition.model_validate_json(json.dumps(bad))


@pytest.mark.parametrize("text", ["not json", "{", '"job"', "null"])
def test_malformed_json_produces_clear_failure(text: str) -> None:
    with pytest.raises(ValidationError):
        JobDefinition.model_validate_json(text)


def test_json_key_order_is_stable() -> None:
    job = make_job()
    first = json.loads(job.model_dump_json(exclude_none=True))
    second = json.loads(job.model_dump_json(exclude_none=True))
    assert list(first) == list(second) == [
        "schema_version",
        "id",
        "name",
        "label",
        "enabled",
        "command",
        "schedule",
        "environment",
        "logging",
    ]
