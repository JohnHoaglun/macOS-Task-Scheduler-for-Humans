"""Tests for the LaunchAgent plist encoder."""

from __future__ import annotations

import plistlib
from datetime import time as Time
from pathlib import Path
from uuid import UUID

import pytest

from task_scheduler.domain import (
    CalendarSchedule,
    IntervalSchedule,
    JobDefinition,
    PythonCommand,
    Weekday,
)
from task_scheduler.platform.macos import PlistCodec

GOLDEN_DIR = Path(__file__).resolve().parents[2] / "golden"


def _python_job(**overrides: object) -> JobDefinition:
    values: dict[str, object] = {
        "schema_version": 2,
        "id": UUID("9f8a6c0e-1111-4222-8333-444455556666"),
        "name": "Python Monday",
        "label": "io.github.macos-task-scheduler.user.python-monday",
        "enabled": True,
        "command": PythonCommand(
            interpreter=Path("/Users/example/project/.venv/bin/python"),
            script=Path("/Users/example/project/report.py"),
            arguments=["--mode", "daily"],
        ),
        "schedule": CalendarSchedule(times=[Time(7, 30)], weekdays={Weekday.MONDAY}),
    }
    values.update(overrides)
    return JobDefinition.model_validate(values)


class TestEncodeDict:
    def test_python_job_core_keys(self) -> None:
        result = PlistCodec().encode_dict(_python_job())
        assert result["Label"] == "io.github.macos-task-scheduler.user.python-monday"
        assert result["ProgramArguments"] == [
            "/Users/example/project/.venv/bin/python",
            "/Users/example/project/report.py",
            "--mode",
            "daily",
        ]
        assert result["StartCalendarInterval"] == [
            {"Weekday": 1, "Hour": 7, "Minute": 30}
        ]
        assert "Disabled" not in result
        assert "WorkingDirectory" not in result
        assert "EnvironmentVariables" not in result
        assert "StandardOutPath" not in result
        assert "StandardErrorPath" not in result

    def test_optional_fields_emitted_when_set(self) -> None:
        job = _python_job(
            working_directory=Path("/Users/example/project"),
            environment={"variables": {"FOO": "bar"}},
            logging={"stdout_path": "/Users/example/logs/out.log"},
        )
        result = PlistCodec().encode_dict(job)
        assert result["WorkingDirectory"] == "/Users/example/project"
        assert result["EnvironmentVariables"] == {"FOO": "bar"}
        assert result["StandardOutPath"] == "/Users/example/logs/out.log"

    def test_disabled_job_emits_disabled_key(self) -> None:
        result = PlistCodec().encode_dict(_python_job(enabled=False))
        assert result["Disabled"] is True

    def test_calendar_entries_sorted_by_launchd_weekday(self) -> None:
        job = _python_job(
            schedule={
                "kind": "calendar",
                "times": ["07:30"],
                "weekdays": ["wednesday", "monday", "friday"],
            }
        )
        entries = PlistCodec().encode_dict(job)["StartCalendarInterval"]
        weekdays = [entry["Weekday"] for entry in entries]
        assert weekdays == [1, 3, 5]

    def test_multiple_times_grouped_by_time_then_weekday(self) -> None:
        job = _python_job(
            schedule={
                "kind": "calendar",
                "times": ["17:30", "07:30"],
                "weekdays": ["monday", "sunday"],
            }
        )
        entries = PlistCodec().encode_dict(job)["StartCalendarInterval"]
        assert entries == [
            {"Weekday": 0, "Hour": 7, "Minute": 30},
            {"Weekday": 1, "Hour": 7, "Minute": 30},
            {"Weekday": 0, "Hour": 17, "Minute": 30},
            {"Weekday": 1, "Hour": 17, "Minute": 30},
        ]

    def test_run_at_load_emitted_when_set(self) -> None:
        job = _python_job(
            schedule={
                "kind": "calendar",
                "times": ["07:30"],
                "weekdays": ["monday"],
                "run_at_load": True,
            }
        )
        result = PlistCodec().encode_dict(job)
        assert result["RunAtLoad"] is True

    def test_run_at_load_absent_by_default(self) -> None:
        result = PlistCodec().encode_dict(_python_job())
        assert "RunAtLoad" not in result

    def test_interval_schedule_uses_start_interval(self) -> None:
        job = _python_job(schedule=IntervalSchedule(seconds=1800))
        result = PlistCodec().encode_dict(job)
        assert result["StartInterval"] == 1800
        assert "StartCalendarInterval" not in result

    def test_interval_schedule_with_run_at_load(self) -> None:
        job = _python_job(schedule=IntervalSchedule(seconds=3600, run_at_load=True))
        result = PlistCodec().encode_dict(job)
        assert result["StartInterval"] == 3600
        assert result["RunAtLoad"] is True

    def test_shell_command_program_arguments(self) -> None:
        job = _python_job(
            command={
                "type": "shell",
                "executable": "/bin/zsh",
                "arguments": ["/Users/example/scripts/backup.sh"],
            }
        )
        assert PlistCodec().encode_dict(job)["ProgramArguments"] == [
            "/bin/zsh",
            "/Users/example/scripts/backup.sh",
        ]


class TestEncodeBytes:
    def test_round_trips_through_plistlib(self) -> None:
        codec = PlistCodec()
        job = _python_job()
        decoded = plistlib.loads(codec.encode_bytes(job))
        assert decoded == codec.encode_dict(job)

    def test_uses_xml_format(self) -> None:
        encoded = PlistCodec().encode_bytes(_python_job())
        assert encoded.startswith(b"<?xml")

    @pytest.mark.parametrize(
        "name",
        [
            "python_monday",
            "python_weekdays",
            "shell_mwf",
            "executable_weekend",
        ],
    )
    def test_golden_plist_bytes(self, name: str) -> None:
        import json

        payload = json.loads((GOLDEN_DIR / f"{name}.json").read_text())
        job = JobDefinition.model_validate(payload)
        expected = (GOLDEN_DIR / f"{name}.plist").read_bytes()
        assert PlistCodec().encode_bytes(job) == expected
