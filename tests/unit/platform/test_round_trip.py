"""Round-trip tests: JobDefinition -> plist bytes -> parsed result.

Domain semantics must survive the round trip. IDs are excluded because
external plists do not encode job UUIDs; the reader assigns fresh ones.
"""

from __future__ import annotations

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
from task_scheduler.domain.command import command_argv
from task_scheduler.platform.macos import ParseSupport, PlistCodec, parse_bytes
from task_scheduler.platform.macos.run_wrapper import spool_err_path, spool_out_path

WRAPPER = (
    "/Users/example/Library/Application Support/"
    "macOS Task Scheduler for Humans/bin/run_wrapper.py"
)


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


class TestWrappedRoundTrip:
    """The run-wrapper plist form: wrapped argv + local spool log keys."""

    def test_wrapped_encode_round_trips_to_same_job(self) -> None:
        codec = PlistCodec(wrapper_path=WRAPPER)
        for original in _jobs():
            parsed = parse_bytes(codec.encode_bytes(original))
            assert parsed.status is ParseSupport.SUPPORTED
            assert parsed.job is not None
            _assert_round_trip(original, parsed.job)

    def test_wrapped_argv_carries_command_and_user_log_path(self) -> None:
        job = _jobs()[1]  # has a configured stdout log path
        args = PlistCodec(wrapper_path=WRAPPER).encode_dict(job)["ProgramArguments"]
        assert args[0] == WRAPPER
        assert args[1:3] == ["--label", job.label]
        assert args[args.index("--") + 1:] == command_argv(job.command)
        assert str(job.logging.stdout_path) in args  # handed to the wrapper

    def test_wrapped_plist_points_launchd_logs_at_local_spool(self) -> None:
        job = _jobs()[1]
        payload = PlistCodec(wrapper_path=WRAPPER).encode_dict(job)
        assert payload["StandardOutPath"] == str(spool_out_path(job.label))
        assert payload["StandardErrorPath"] == str(spool_err_path(job.label))
        # the user's configured path must not appear as a launchd log key
        configured = str(job.logging.stdout_path)
        assert configured not in (payload["StandardOutPath"], payload["StandardErrorPath"])

    def test_job_without_logging_keeps_no_user_paths(self) -> None:
        job = _jobs()[0]  # no LoggingConfig paths
        codec = PlistCodec(wrapper_path=WRAPPER)
        payload = codec.encode_dict(job)
        assert "StandardOutPath" in payload  # spool keys still serve launchd
        assert "StandardErrorPath" in payload
        parsed = parse_bytes(codec.encode_bytes(job))
        assert parsed.status is ParseSupport.SUPPORTED
        assert parsed.job is not None
        # the spool must not leak back into the job as user configuration
        assert parsed.job.logging.stdout_path is None
        assert parsed.job.logging.stderr_path is None

    def test_unwrapped_encode_keeps_legacy_behavior(self) -> None:
        job = _jobs()[1]
        payload = PlistCodec().encode_dict(job)
        assert payload["ProgramArguments"] == command_argv(job.command)
        assert payload["StandardOutPath"] == str(job.logging.stdout_path)
        assert "StandardErrorPath" not in payload

    def test_merge_external_edit_wraps_program_arguments(self) -> None:
        from task_scheduler.platform.macos.plist_codec import merge_external_edit
        from task_scheduler.platform.macos.plist_models import ExternalEditField

        job = _jobs()[0]
        original = {"Label": job.label, "ProgramArguments": ["/bin/zsh", "old.sh"]}
        merged = merge_external_edit(
            original,
            job,
            dirty=frozenset({ExternalEditField.PROGRAM_ARGUMENTS}),
            wrapper_path=WRAPPER,
        )
        argv = merged["ProgramArguments"]
        assert argv[0] == WRAPPER
        assert argv[argv.index("--") + 1:] == command_argv(job.command)
        assert original["ProgramArguments"] == ["/bin/zsh", "old.sh"]
