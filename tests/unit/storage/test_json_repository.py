"""Tests for the JSON job repository."""

import json
from datetime import time as Time
from pathlib import Path

import pytest
from pydantic import ValidationError

from task_scheduler.domain import (
    CalendarSchedule,
    EnvironmentConfig,
    UnsupportedSchemaVersionError,
    Weekday,
)
from task_scheduler.storage import JsonJobRepository
from tests.conftest import make_job


def test_save_then_load_round_trip(tmp_path: Path) -> None:
    repo = JsonJobRepository()
    job = make_job()
    path = tmp_path / "daily-backup.json"
    repo.save(job, path)
    assert repo.load(path) == job


def test_saved_file_is_schema_v2_calendar(tmp_path: Path) -> None:
    repo = JsonJobRepository()
    path = tmp_path / "job.json"
    repo.save(make_job(), path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert data["schedule"]["kind"] == "calendar"
    assert data["schedule"]["times"] == ["07:30"]
    assert data["schedule"]["run_at_load"] is False


def test_load_migrates_v1_calendar_schedule(tmp_path: Path) -> None:
    path = tmp_path / "v1.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "12345678-1234-5678-1234-567812345678",
                "name": "Daily Backup",
                "label": "io.github.macos-task-scheduler.user.daily-backup",
                "enabled": True,
                "command": {
                    "type": "python",
                    "interpreter": "/Users/example/project/.venv/bin/python",
                    "script": "/Users/example/project/main.py",
                    "arguments": ["--mode", "daily"],
                },
                "schedule": {"time": "07:30", "weekdays": ["monday", "friday"]},
            }
        ),
        "utf-8",
    )
    job = JsonJobRepository().load(path)
    assert isinstance(job.schedule, CalendarSchedule)
    assert job.schedule.times == [Time(7, 30)]
    assert job.schedule.weekdays == {Weekday.MONDAY, Weekday.FRIDAY}
    assert job.schedule.run_at_load is False


def test_migrated_v1_job_round_trips_as_v2(tmp_path: Path) -> None:
    repo = JsonJobRepository()
    v1_path = tmp_path / "v1.json"
    payload = make_job().model_dump(mode="json")
    payload["schema_version"] = 1
    payload["schedule"] = {"time": "07:30", "weekdays": ["monday"]}
    v1_path.write_text(json.dumps(payload), "utf-8")
    job = repo.load(v1_path)
    out_path = tmp_path / "v2.json"
    repo.save(job, out_path)
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert data["schedule"]["kind"] == "calendar"


def test_load_rejects_broken_v1_schedule(tmp_path: Path) -> None:
    path = tmp_path / "broken-v1.json"
    path.write_text(
        '{"schema_version": 1, "id": "12345678-1234-5678-1234-567812345678", '
        '"name": "x", "label": "com.example.x", '
        '"command": {"type": "shell", "executable": "/bin/zsh", "arguments": []}, '
        '"schedule": {"weekdays": ["monday"]}}',
        "utf-8",
    )
    with pytest.raises(ValidationError):
        JsonJobRepository().load(path)


def test_saved_file_is_pretty_utf8_with_trailing_newline(tmp_path: Path) -> None:
    repo = JsonJobRepository()
    path = tmp_path / "job.json"
    repo.save(make_job(name="Caf\u00e9 Backup"), path)
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert '\n  "name": "Caf\u00e9 Backup"' in text


def test_save_requires_parent_directory_by_default(tmp_path: Path) -> None:
    repo = JsonJobRepository()
    with pytest.raises(FileNotFoundError):
        repo.save(make_job(), tmp_path / "missing" / "dir" / "job.json")


def test_save_creates_parent_when_requested(tmp_path: Path) -> None:
    repo = JsonJobRepository()
    path = tmp_path / "a" / "b" / "job.json"
    repo.save(make_job(), path, create_parent=True)
    assert repo.load(path).name == "Daily Backup"


def test_load_rejects_unsupported_schema(tmp_path: Path) -> None:
    path = tmp_path / "old.json"
    path.write_text('{"schema_version": 99, "id": "00000000-0000-0000-0000-000000000000"}', "utf-8")
    with pytest.raises(UnsupportedSchemaVersionError):
        JsonJobRepository().load(path)


def test_load_rejects_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{ not valid json", "utf-8")
    with pytest.raises(ValidationError):
        JsonJobRepository().load(path)


def test_environment_variables_round_trip(tmp_path: Path) -> None:
    repo = JsonJobRepository()
    job = make_job(environment=EnvironmentConfig(variables={"HOME": "/Users/example"}))
    path = tmp_path / "job.json"
    repo.save(job, path)
    assert repo.load(path).environment.variables == {"HOME": "/Users/example"}
