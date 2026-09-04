"""Round-trip tests: JobDefinition -> plist bytes -> parsed result.

Domain semantics must survive the round trip. IDs are excluded because
external plists do not encode job UUIDs; the reader assigns fresh ones.
"""

from __future__ import annotations

import json
from datetime import time as Time
from pathlib import Path
from uuid import uuid4

from task_scheduler.domain import (
    CalendarSchedule,
    EnvironmentConfig,
    ExecutableCommand,
    IntervalSchedule,
    JobDefinition,
    LoggingConfig,
    PythonCommand,
    ShellCommand,
    Weekday,
)
from task_scheduler.platform.macos import ParseSupport, PlistCodec, parse_bytes


def _jobs() -> list[JobDefinition]:
    return [
        JobDefinition(
            schema_version=2,
            id=uuid4(),
            name="Python Monday",
            label="io.github.macos-task-scheduler.user.python-monday",
            enabled=True,
            command=PythonCommand(
                interpreter=Path("/Users/example/project/.venv/bin/python"),
                script=Path("/Users/example/project/report.py"),
                arguments=["--mode", "daily"],
            ),
            schedule=CalendarSchedule(times=[Time(7, 30)], weekdays={Weekday.MONDAY}),
        ),
        JobDefinition(
            schema_version=2,
            id=uuid4(),
            name="Python Weekdays",
            label="io.github.macos-task-scheduler.user.python-weekdays",
            enabled=True,
            command=PythonCommand(
                interpreter=Path("/Users/example/project/.venv/bin/python"),
                script=Path("/Users/example/project/report.py"),
            ),
            schedule=CalendarSchedule(
                times=[Time(7, 30)],
                weekdays={Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.FRIDAY},
            ),
            environment=EnvironmentConfig(variables={"FOO": "bar"}),
            working_directory=Path("/Users/example/project"),
            logging=LoggingConfig(stdout_path=Path("/Users/example/logs/out.log")),
        ),
        JobDefinition(
            schema_version=2,
            id=uuid4(),
            name="Shell MWF",
            label="io.github.macos-task-scheduler.user.shell-mwf",
            enabled=False,
            command=ShellCommand(
                executable=Path("/bin/zsh"),
                arguments=["/Users/example/scripts/backup.sh"],
            ),
            schedule=CalendarSchedule(
                times=[Time(9, 15)],
                weekdays={Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.FRIDAY},
            ),
            logging=LoggingConfig(stderr_path=Path("/Users/example/logs/err.log")),
        ),
        JobDefinition(
            schema_version=2,
            id=uuid4(),
            name="Executable Weekend",
            label="io.github.macos-task-scheduler.user.executable-weekend",
            enabled=True,
            command=ExecutableCommand(
                executable=Path("/opt/homebrew/bin/sync-tool"),
                arguments=["--sync"],
            ),
            schedule=CalendarSchedule(
                times=[Time(10, 0)], weekdays={Weekday.SATURDAY, Weekday.SUNDAY}
            ),
        ),
        JobDefinition(
            schema_version=2,
            id=uuid4(),
            name="Morning and Evening",
            label="io.github.macos-task-scheduler.user.two-times",
            enabled=True,
            command=ShellCommand(
                executable=Path("/bin/zsh"),
                arguments=["/Users/example/scripts/report.sh"],
            ),
            schedule=CalendarSchedule(
                times=[Time(17, 30), Time(7, 30)],
                weekdays={Weekday.MONDAY},
                run_at_load=True,
            ),
        ),
        JobDefinition(
            schema_version=2,
            id=uuid4(),
            name="Half Hourly",
            label="io.github.macos-task-scheduler.user.half-hourly",
            enabled=True,
            command=ShellCommand(
                executable=Path("/bin/zsh"),
                arguments=["/Users/example/scripts/heartbeat.sh"],
            ),
            schedule=IntervalSchedule(seconds=1800),
        ),
    ]


def _assert_round_trip(original: JobDefinition, parsed: JobDefinition) -> None:
    assert parsed.name == original.label
    assert parsed.label == original.label
    assert parsed.enabled == original.enabled
    assert parsed.command == original.command
    assert parsed.schedule == original.schedule
    assert parsed.environment.variables == original.environment.variables
    assert parsed.working_directory == original.working_directory
    assert parsed.logging == original.logging


def test_all_command_kinds_round_trip() -> None:
    codec = PlistCodec()
    for original in _jobs():
        parsed_result = parse_bytes(codec.encode_bytes(original))
        assert parsed_result.status is ParseSupport.SUPPORTED
        assert parsed_result.job is not None
        _assert_round_trip(original, parsed_result.job)


def test_golden_json_round_trips() -> None:
    golden_dir = Path(__file__).resolve().parents[2] / "golden"
    codec = PlistCodec()
    for stem in ("python_monday", "python_weekdays", "shell_mwf", "executable_weekend"):
        payload = json.loads((golden_dir / f"{stem}.json").read_text())
        original = JobDefinition.model_validate(payload)
        parsed_result = parse_bytes(codec.encode_bytes(original))
        assert parsed_result.status is ParseSupport.SUPPORTED, stem
        assert parsed_result.job is not None
        _assert_round_trip(original, parsed_result.job)
