"""Tests for the discovery presenter formatting (pure Python, no Qt)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from conftest import make_job
from task_scheduler.application.task_command_service import ListingKind, TaskListing
from task_scheduler.domain import (
    IntervalSchedule,
    JobDefinition,
)
from task_scheduler.gui.presenters.agent_presenter import (
    PREVIEW_DISABLED_HEADING,
    format_command,
    format_label,
    format_name,
    format_schedule,
    format_state,
    format_upcoming_heading,
    format_upcoming_occurrences_for,
    format_warnings,
)
from task_scheduler.platform.macos import (
    ParsedLaunchAgent,
    ParseSupport,
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

class TestFormatName:

    def test_no_job_and_no_path(self) -> None:
        listing = TaskListing(
            kind=ListingKind.DISCOVERED, path=None, parsed=None, job=None, managed=False
        )
        assert format_name(listing) == "—"

class TestFormatLabel:

    def test_no_parse_no_job(self) -> None:
        listing = TaskListing(
            kind=ListingKind.DISCOVERED, path=None, parsed=None, job=None, managed=False
        )
        assert format_label(listing) == "—"

class TestFormatCommand:

    def test_raw_program_arguments_list(self) -> None:
        listing = _discovered(
            _parsed(
                status=ParseSupport.INVALID,
                raw={"ProgramArguments": ["/bin/zsh", "/Users/example/scripts/x.sh"]},
            )
        )
        assert format_command(listing) == "/bin/zsh /Users/example/scripts/x.sh"

class TestFormatSchedule:

    def test_interval_with_run_at_load(self) -> None:
        job = make_job(schedule=IntervalSchedule(seconds=3600, run_at_load=True))
        listing = _discovered(_parsed(job=job), managed=True)
        assert format_schedule(listing) == "Every hour + at login"

class TestFormatState:

    def test_missing_parse(self) -> None:
        listing = TaskListing(
            kind=ListingKind.DISCOVERED, path=AGENT_PATH, parsed=None, job=None, managed=False
        )
        assert format_state(listing) == "—"

class TestFormatWarnings:

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

class TestPreviewWording:
    """Increment 15: the next-run preview wording is pinned by the spec."""

    def test_format_upcoming_heading_disabled(self) -> None:
        job = make_job(enabled=False)
        assert format_upcoming_heading(_saved(job)) == PREVIEW_DISABLED_HEADING

    def test_interval_run_at_load_adds_no_line(self) -> None:
        base = make_job(schedule=IntervalSchedule(seconds=900))
        job = make_job(schedule=IntervalSchedule(seconds=900, run_at_load=True))
        now = datetime(2026, 9, 4, 12, 0, 0)
        assert (
            format_upcoming_occurrences_for(_saved(job), now=now)
            == format_upcoming_occurrences_for(_saved(base), now=now)
        )
