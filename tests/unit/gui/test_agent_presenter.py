"""Tests for the discovery presenter formatting (pure Python, no Qt)."""

from __future__ import annotations

from pathlib import Path

from conftest import make_job
from task_scheduler.application.task_command_service import ListingKind, TaskListing
from task_scheduler.domain import (
    IntervalSchedule,
    JobDefinition,
)
from task_scheduler.gui.presenters.agent_presenter import (
    PREVIEW_DISABLED_HEADING,
    format_schedule,
    format_state,
    format_upcoming_heading,
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


class TestPreviewWording:
    """Increment 15: the next-run preview wording is pinned by the spec."""

    def test_format_upcoming_heading_disabled(self) -> None:
        job = make_job(enabled=False)
        assert format_upcoming_heading(_saved(job)) == PREVIEW_DISABLED_HEADING
