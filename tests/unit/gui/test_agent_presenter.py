"""Tests for the discovery presenter formatting (pure Python, no Qt)."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_job
from task_scheduler.application.task_command_service import ListingKind, TaskListing
from task_scheduler.domain import (
    CalendarSchedule,
    EnvironmentConfig,
    IntervalSchedule,
    JobDefinition,
    Weekday,
)
from task_scheduler.gui.presenters.agent_presenter import (
    AgentClassification,
    classify,
    format_command,
    format_enabled,
    format_environment,
    format_label,
    format_lifecycle_state,
    format_name,
    format_raw_plist,
    format_schedule,
    format_state,
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


def _discovered(
    parsed: ParsedLaunchAgent,
    *,
    managed: bool = False,
    job: JobDefinition | None = None,
) -> TaskListing:
    return TaskListing(
        kind=ListingKind.DISCOVERED,
        path=AGENT_PATH,
        parsed=parsed,
        job=job,
        managed=managed,
    )


def _saved(job: JobDefinition) -> TaskListing:
    return TaskListing(kind=ListingKind.SAVED, path=None, parsed=None, job=job, managed=True)


class TestClassify:
    def test_saved_row_is_managed(self) -> None:
        assert classify(_saved(make_job())) is AgentClassification.MANAGED

    def test_supported_and_managed(self) -> None:
        assert classify(_discovered(_parsed(), managed=True)) is AgentClassification.MANAGED

    def test_supported_and_unmanaged(self) -> None:
        assert classify(_discovered(_parsed())) is AgentClassification.EXTERNAL

    def test_invalid_wins_over_managed(self) -> None:
        parsed = _parsed(status=ParseSupport.INVALID, raw={})
        assert classify(_discovered(parsed, managed=True)) is AgentClassification.INVALID

    def test_missing_parse_is_invalid(self) -> None:
        listing = TaskListing(
            kind=ListingKind.DISCOVERED, path=AGENT_PATH, parsed=None, job=None, managed=False
        )
        assert classify(listing) is AgentClassification.INVALID


class TestFormatName:
    def test_with_job(self) -> None:
        job = make_job()
        listing = _discovered(_parsed(job=job), managed=True)
        assert format_name(listing) == job.name

    def test_without_job_uses_path_stem(self) -> None:
        listing = _discovered(
            _parsed(status=ParseSupport.INVALID, raw={}),
        )
        assert format_name(listing) == "com.example"

    def test_saved_uses_job_name(self) -> None:
        job = make_job()
        assert format_name(_saved(job)) == job.name

    def test_no_job_and_no_path(self) -> None:
        listing = TaskListing(
            kind=ListingKind.DISCOVERED, path=None, parsed=None, job=None, managed=False
        )
        assert format_name(listing) == "—"


class TestFormatLabel:
    def test_with_job(self) -> None:
        listing = _discovered(_parsed(job=make_job()), managed=True)
        assert format_label(listing) == "io.github.macos-task-scheduler.user.daily-backup"

    def test_catalog_job_used_when_parse_has_none(self) -> None:
        job = make_job()
        listing = _discovered(
            _parsed(status=ParseSupport.INVALID, raw={}), job=job
        )
        assert format_label(listing) == job.label

    def test_raw_only(self) -> None:
        listing = _discovered(
            _parsed(status=ParseSupport.INVALID, raw={"Label": "com.example.x"})
        )
        assert format_label(listing) == "com.example.x"

    def test_empty_raw(self) -> None:
        listing = _discovered(_parsed(status=ParseSupport.INVALID, raw={}))
        assert format_label(listing) == "—"

    def test_saved_uses_job_label(self) -> None:
        job = make_job()
        assert format_label(_saved(job)) == job.label

    def test_no_parse_no_job(self) -> None:
        listing = TaskListing(
            kind=ListingKind.DISCOVERED, path=None, parsed=None, job=None, managed=False
        )
        assert format_label(listing) == "—"


class TestFormatCommand:
    def test_with_job(self) -> None:
        listing = _discovered(_parsed(job=make_job()), managed=True)
        assert format_command(listing) == (
            "/Users/example/project/.venv/bin/python /Users/example/project/main.py "
            "--mode daily"
        )

    def test_raw_program_arguments_list(self) -> None:
        listing = _discovered(
            _parsed(
                status=ParseSupport.INVALID,
                raw={"ProgramArguments": ["/bin/zsh", "/Users/example/scripts/x.sh"]},
            )
        )
        assert format_command(listing) == "/bin/zsh /Users/example/scripts/x.sh"

    def test_raw_program_arguments_not_a_list(self) -> None:
        listing = _discovered(
            _parsed(status=ParseSupport.INVALID, raw={"ProgramArguments": "/bin/zsh"})
        )
        assert format_command(listing) == "—"

    def test_raw_missing(self) -> None:
        listing = _discovered(_parsed(status=ParseSupport.INVALID, raw={}))
        assert format_command(listing) == "—"

    def test_saved_uses_job_argv(self) -> None:
        job = make_job()
        assert format_command(_saved(job)) == (
            "/Users/example/project/.venv/bin/python /Users/example/project/main.py "
            "--mode daily"
        )


class TestFormatSchedule:
    def test_multiple_weekdays(self) -> None:
        job = make_job(
            schedule=CalendarSchedule(
                times=["09:15"],
                weekdays={Weekday.FRIDAY, Weekday.MONDAY, Weekday.SUNDAY},
            )
        )
        listing = _discovered(_parsed(job=job), managed=True)
        assert format_schedule(listing) == "at 09:15:00 on Friday, Monday, Sunday"

    def test_single_weekday(self) -> None:
        listing = _discovered(_parsed(job=make_job()), managed=True)
        assert format_schedule(listing) == "at 07:30:00 on Monday"

    def test_multiple_times(self) -> None:
        job = make_job(
            schedule=CalendarSchedule(
                times=["17:30", "07:30"], weekdays={Weekday.MONDAY}
            )
        )
        listing = _discovered(_parsed(job=job), managed=True)
        assert format_schedule(listing) == "at 07:30:00 and 17:30:00 on Monday"

    def test_run_at_load_suffix(self) -> None:
        job = make_job(
            schedule=CalendarSchedule(
                times=["07:30"], weekdays={Weekday.MONDAY}, run_at_load=True
            )
        )
        listing = _discovered(_parsed(job=job), managed=True)
        assert format_schedule(listing) == "at 07:30:00 on Monday + at login"

    def test_interval(self) -> None:
        job = make_job(schedule=IntervalSchedule(seconds=1800))
        listing = _discovered(_parsed(job=job), managed=True)
        assert format_schedule(listing) == "Every 30 minutes"

    def test_interval_with_run_at_load(self) -> None:
        job = make_job(schedule=IntervalSchedule(seconds=3600, run_at_load=True))
        listing = _discovered(_parsed(job=job), managed=True)
        assert format_schedule(listing) == "Every hour + at login"

    def test_without_job(self) -> None:
        listing = _discovered(_parsed(status=ParseSupport.INVALID, raw={}))
        assert format_schedule(listing) == "—"


class TestFormatState:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (ParseSupport.SUPPORTED, "supported"),
            (ParseSupport.PARTIALLY_SUPPORTED, "partially supported"),
            (ParseSupport.INVALID, "invalid"),
        ],
    )
    def test_discovered_statuses(self, status: ParseSupport, expected: str) -> None:
        assert format_state(_discovered(_parsed(status=status))) == expected

    def test_saved(self) -> None:
        assert format_state(_saved(make_job())) == "Saved, not installed"

    def test_installed_configured_enabled(self) -> None:
        job = make_job()
        assert (
            format_state(_discovered(_parsed(job=job), managed=True, job=job))
            == "Installed, configured enabled"
        )

    def test_installed_configured_disabled(self) -> None:
        job = make_job(enabled=False)
        assert (
            format_state(_discovered(_parsed(job=job), managed=True, job=job))
            == "Installed, configured disabled"
        )

    def test_external_row_ignores_parsed_job(self) -> None:
        job = make_job()
        listing = _discovered(_parsed(job=job), managed=False)
        assert format_state(listing) == "supported"

    def test_missing_parse(self) -> None:
        listing = TaskListing(
            kind=ListingKind.DISCOVERED, path=AGENT_PATH, parsed=None, job=None, managed=False
        )
        assert format_state(listing) == "—"


class TestFormatLifecycleState:
    @pytest.mark.parametrize(
        ("enabled", "loaded", "expected"),
        [
            (True, True, "Installed, configured enabled (loaded)"),
            (True, False, "Installed, configured enabled (not loaded)"),
            (False, True, "Installed, configured disabled (loaded)"),
            (False, False, "Installed, configured disabled (not loaded)"),
        ],
    )
    def test_full_states(self, enabled: bool, loaded: bool, expected: str) -> None:
        assert format_lifecycle_state(enabled, loaded) == expected

    def test_unknown_when_configured_missing(self) -> None:
        assert format_lifecycle_state(None, True) == "Status unknown"

    def test_unknown_when_runtime_missing(self) -> None:
        assert format_lifecycle_state(True, None) == "Status unknown"

    def test_unknown_when_both_missing(self) -> None:
        assert format_lifecycle_state(None, None) == "Status unknown"


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
        listing = _discovered(_parsed(job=make_job(enabled=True)), managed=True)
        assert format_enabled(listing) == "enabled"

    def test_disabled(self) -> None:
        listing = _discovered(_parsed(job=make_job(enabled=False)), managed=True)
        assert format_enabled(listing) == "disabled"

    def test_without_job(self) -> None:
        listing = _discovered(_parsed(status=ParseSupport.INVALID, raw={}))
        assert format_enabled(listing) == "—"

    def test_saved_uses_job_enabled(self) -> None:
        assert format_enabled(_saved(make_job(enabled=False))) == "disabled"


class TestFormatEnvironment:
    def test_with_variables(self) -> None:
        job = make_job(
            environment=EnvironmentConfig(variables={"FOO": "bar", "PATH": "/usr/bin"})
        )
        listing = _discovered(_parsed(job=job), managed=True)
        assert format_environment(listing) == "FOO=bar, PATH=/usr/bin"

    def test_empty_mapping(self) -> None:
        listing = _discovered(_parsed(job=make_job()), managed=True)
        assert format_environment(listing) == "none configured"

    def test_without_job(self) -> None:
        listing = _discovered(_parsed(status=ParseSupport.INVALID, raw={}))
        assert format_environment(listing) == "—"

    def test_saved_uses_job_environment(self) -> None:
        job = make_job(environment=EnvironmentConfig(variables={"A": "b"}))
        assert format_environment(_saved(job)) == "A=b"


class TestFormatWorkingDirectory:
    def test_set(self) -> None:
        job = make_job(working_directory=Path("/Users/example/project"))
        listing = _discovered(_parsed(job=job), managed=True)
        assert format_working_directory(listing) == "/Users/example/project"

    def test_not_set(self) -> None:
        listing = _discovered(_parsed(job=make_job()), managed=True)
        assert format_working_directory(listing) == "not set"

    def test_without_job(self) -> None:
        listing = _discovered(_parsed(status=ParseSupport.INVALID, raw={}))
        assert format_working_directory(listing) == "—"


class TestFormatWarnings:
    def test_warnings_only(self) -> None:
        listing = _discovered(
            _parsed(
                status=ParseSupport.PARTIALLY_SUPPORTED,
                warnings=["no calendar schedule found"],
            )
        )
        assert format_warnings(listing) == "no calendar schedule found"

    def test_unsupported_keys_only(self) -> None:
        listing = _discovered(
            _parsed(
                status=ParseSupport.PARTIALLY_SUPPORTED,
                unsupported_keys=["a", "b"],
            )
        )
        assert format_warnings(listing) == "unsupported keys: a, b"

    def test_both(self) -> None:
        listing = _discovered(
            _parsed(
                status=ParseSupport.PARTIALLY_SUPPORTED,
                warnings=["distinct execution times"],
                unsupported_keys=["a", "b"],
            )
        )
        assert format_warnings(listing) == (
            "distinct execution times\nunsupported keys: a, b"
        )

    def test_neither(self) -> None:
        assert format_warnings(_discovered(_parsed())) == "none"

    def test_saved_reports_none(self) -> None:
        assert format_warnings(_saved(make_job())) == "none"


class TestFormatRawPlist:
    def test_non_empty_raw(self) -> None:
        listing = _discovered(
            _parsed(status=ParseSupport.INVALID, raw={"Label": "com.example.x"})
        )
        text = format_raw_plist(listing)
        assert "<plist" in text
        assert "com.example.x" in text

    def test_empty_raw(self) -> None:
        listing = _discovered(_parsed(status=ParseSupport.INVALID, raw={}))
        assert format_raw_plist(listing) == "(no raw data)"

    def test_saved_reports_no_deployed_plist(self) -> None:
        assert format_raw_plist(_saved(make_job())) == (
            "(no deployed plist — saved in the task catalog)"
        )
