"""Tests for the discovery presenter formatting (pure Python, no Qt)."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_job
from task_scheduler.application.task_command_service import AgentListing
from task_scheduler.domain import EnvironmentConfig, Schedule, Weekday
from task_scheduler.gui.presenters.agent_presenter import (
    AgentClassification,
    classify,
    format_command,
    format_enabled,
    format_environment,
    format_label,
    format_name,
    format_parsed_support,
    format_raw_plist,
    format_schedule,
    format_status,
    format_warnings,
    format_working_directory,
)
from task_scheduler.platform.macos import (
    LaunchAgentStatus,
    ParsedLaunchAgent,
    ParseSupport,
    ProcessResult,
)

AGENT_PATH = Path("/Users/example/Library/LaunchAgents/com.example.plist")


def _parsed(**overrides: object) -> ParsedLaunchAgent:
    kwargs: dict[str, object] = {"status": ParseSupport.SUPPORTED}
    kwargs.update(overrides)
    return ParsedLaunchAgent(**kwargs)  # type: ignore[arg-type]


class TestClassify:
    def test_supported_and_managed(self) -> None:
        assert classify(_parsed(), managed=True) is AgentClassification.MANAGED

    def test_supported_and_unmanaged(self) -> None:
        assert classify(_parsed(), managed=False) is AgentClassification.EXTERNAL

    def test_invalid_wins_over_managed(self) -> None:
        parsed = _parsed(status=ParseSupport.INVALID, raw={})
        assert classify(parsed, managed=True) is AgentClassification.INVALID


class TestFormatName:
    def test_with_job(self) -> None:
        job = make_job()
        agent = AgentListing(path=AGENT_PATH, parsed=_parsed(job=job), managed=True)
        assert format_name(agent) == job.name

    def test_without_job_uses_path_stem(self) -> None:
        agent = AgentListing(
            path=AGENT_PATH,
            parsed=_parsed(status=ParseSupport.INVALID, raw={}),
            managed=False,
        )
        assert format_name(agent) == "com.example"


class TestFormatLabel:
    def test_with_job(self) -> None:
        parsed = _parsed(job=make_job())
        assert format_label(parsed) == "io.github.macos-task-scheduler.user.daily-backup"

    def test_raw_only(self) -> None:
        parsed = _parsed(status=ParseSupport.INVALID, raw={"Label": "com.example.x"})
        assert format_label(parsed) == "com.example.x"

    def test_empty_raw(self) -> None:
        parsed = _parsed(status=ParseSupport.INVALID, raw={})
        assert format_label(parsed) == "—"


class TestFormatCommand:
    def test_with_job(self) -> None:
        parsed = _parsed(job=make_job())
        assert format_command(parsed) == (
            "/Users/example/project/.venv/bin/python /Users/example/project/main.py "
            "--mode daily"
        )

    def test_raw_program_arguments_list(self) -> None:
        parsed = _parsed(
            status=ParseSupport.INVALID,
            raw={"ProgramArguments": ["/bin/zsh", "/Users/example/scripts/x.sh"]},
        )
        assert format_command(parsed) == "/bin/zsh /Users/example/scripts/x.sh"

    def test_raw_program_arguments_not_a_list(self) -> None:
        parsed = _parsed(status=ParseSupport.INVALID, raw={"ProgramArguments": "/bin/zsh"})
        assert format_command(parsed) == "—"

    def test_raw_missing(self) -> None:
        parsed = _parsed(status=ParseSupport.INVALID, raw={})
        assert format_command(parsed) == "—"


class TestFormatSchedule:
    def test_multiple_weekdays(self) -> None:
        job = make_job(
            schedule=Schedule(
                time="09:15",
                weekdays={Weekday.FRIDAY, Weekday.MONDAY, Weekday.SUNDAY},
            )
        )
        parsed = _parsed(job=job)
        assert format_schedule(parsed) == "at 09:15:00 on Friday, Monday, Sunday"

    def test_single_weekday(self) -> None:
        parsed = _parsed(job=make_job())
        assert format_schedule(parsed) == "at 07:30:00 on Monday"

    def test_without_job(self) -> None:
        parsed = _parsed(status=ParseSupport.INVALID, raw={})
        assert format_schedule(parsed) == "—"


class TestFormatParsedSupport:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (ParseSupport.SUPPORTED, "supported"),
            (ParseSupport.PARTIALLY_SUPPORTED, "partially supported"),
            (ParseSupport.INVALID, "invalid"),
        ],
    )
    def test_all_statuses(self, status: ParseSupport, expected: str) -> None:
        parsed = _parsed(status=status)
        assert format_parsed_support(parsed) == expected


class TestFormatStatus:
    def test_none(self) -> None:
        assert format_status(None) == "unknown"

    def test_loaded(self) -> None:
        status = LaunchAgentStatus(loaded=True, process=ProcessResult(exit_code=0))
        assert format_status(status) == "loaded"

    def test_not_loaded(self) -> None:
        status = LaunchAgentStatus(loaded=False, process=ProcessResult(exit_code=1))
        assert format_status(status) == "not loaded"


class TestFormatEnabled:
    def test_enabled(self) -> None:
        parsed = _parsed(job=make_job(enabled=True))
        assert format_enabled(parsed) == "enabled"

    def test_disabled(self) -> None:
        parsed = _parsed(job=make_job(enabled=False))
        assert format_enabled(parsed) == "disabled"

    def test_without_job(self) -> None:
        parsed = _parsed(status=ParseSupport.INVALID, raw={})
        assert format_enabled(parsed) == "—"


class TestFormatEnvironment:
    def test_with_variables(self) -> None:
        job = make_job(
            environment=EnvironmentConfig(variables={"FOO": "bar", "PATH": "/usr/bin"})
        )
        parsed = _parsed(job=job)
        assert format_environment(parsed) == "FOO=bar, PATH=/usr/bin"

    def test_empty_mapping(self) -> None:
        parsed = _parsed(job=make_job())
        assert format_environment(parsed) == "none configured"

    def test_without_job(self) -> None:
        parsed = _parsed(status=ParseSupport.INVALID, raw={})
        assert format_environment(parsed) == "—"


class TestFormatWorkingDirectory:
    def test_set(self) -> None:
        job = make_job(working_directory=Path("/Users/example/project"))
        parsed = _parsed(job=job)
        assert format_working_directory(parsed) == "/Users/example/project"

    def test_not_set(self) -> None:
        parsed = _parsed(job=make_job())
        assert format_working_directory(parsed) == "not set"

    def test_without_job(self) -> None:
        parsed = _parsed(status=ParseSupport.INVALID, raw={})
        assert format_working_directory(parsed) == "—"


class TestFormatWarnings:
    def test_warnings_only(self) -> None:
        parsed = _parsed(
            status=ParseSupport.PARTIALLY_SUPPORTED,
            warnings=["no calendar schedule found"],
        )
        assert format_warnings(parsed) == "no calendar schedule found"

    def test_unsupported_keys_only(self) -> None:
        parsed = _parsed(status=ParseSupport.PARTIALLY_SUPPORTED, unsupported_keys=["a", "b"])
        assert format_warnings(parsed) == "unsupported keys: a, b"

    def test_both(self) -> None:
        parsed = _parsed(
            status=ParseSupport.PARTIALLY_SUPPORTED,
            warnings=["distinct execution times"],
            unsupported_keys=["a", "b"],
        )
        assert format_warnings(parsed) == (
            "distinct execution times\nunsupported keys: a, b"
        )

    def test_neither(self) -> None:
        parsed = _parsed()
        assert format_warnings(parsed) == "none"


class TestFormatRawPlist:
    def test_non_empty_raw(self) -> None:
        parsed = _parsed(status=ParseSupport.INVALID, raw={"Label": "com.example.x"})
        text = format_raw_plist(parsed)
        assert "<plist" in text
        assert "com.example.x" in text

    def test_empty_raw(self) -> None:
        parsed = _parsed(status=ParseSupport.INVALID, raw={})
        assert format_raw_plist(parsed) == "(no raw data)"
