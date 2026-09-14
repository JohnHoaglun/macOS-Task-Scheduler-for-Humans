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
    enabled_state,
    format_enabled,
    format_lifecycle_state,
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

    def test_run_at_login_only_shown_from_raw(self) -> None:
        parsed = _parsed(
            status=ParseSupport.PARTIALLY_SUPPORTED,
            raw={"Label": "com.example.autostart", "RunAtLoad": True},
        )
        assert format_schedule(_discovered(parsed)) == "at login"

    def test_unscheduled_shown_from_raw(self) -> None:
        parsed = _parsed(
            status=ParseSupport.PARTIALLY_SUPPORTED,
            raw={"Label": "com.example.onservice"},
        )
        assert format_schedule(_discovered(parsed)) == "not scheduled"

    def test_invalid_parse_remains_dash(self) -> None:
        assert format_schedule(_discovered(_parsed(status=ParseSupport.INVALID))) == "—"


class TestEnabledState:
    def test_parsed_job_flag_wins_over_raw(self) -> None:
        job = make_job()  # enabled=True, while raw says disabled
        parsed = _parsed(job=job, raw={"Disabled": True})
        assert enabled_state(_discovered(parsed, job=job)) == "enabled"

    def test_catalog_job_fallback(self) -> None:
        assert enabled_state(_saved(make_job(enabled=False))) == "disabled"

    def test_raw_disabled_key(self) -> None:
        parsed = _parsed(
            status=ParseSupport.PARTIALLY_SUPPORTED,
            raw={"Label": "com.example.x", "Disabled": True},
        )
        assert enabled_state(_discovered(parsed)) == "disabled"

    def test_absent_disabled_key_defaults_enabled(self) -> None:
        parsed = _parsed(
            status=ParseSupport.PARTIALLY_SUPPORTED,
            raw={"Label": "com.example.x", "RunAtLoad": True},
        )
        assert enabled_state(_discovered(parsed)) == "enabled"

    def test_invalid_status_is_unknown(self) -> None:
        parsed = _parsed(status=ParseSupport.INVALID, raw={"Disabled": True})
        assert enabled_state(_discovered(parsed)) == "unknown"

    def test_missing_parse_is_unknown(self) -> None:
        listing = TaskListing(
            kind=ListingKind.DISCOVERED, path=AGENT_PATH, parsed=None, job=None, managed=False
        )
        assert enabled_state(listing) == "unknown"


class TestFormatState:
    def test_missing_parse_is_unknown(self) -> None:
        listing = TaskListing(
            kind=ListingKind.DISCOVERED, path=AGENT_PATH, parsed=None, job=None, managed=False
        )
        assert format_state(listing) == "unknown"

    def test_external_row_uses_raw_disabled_key(self) -> None:
        parsed = _parsed(
            status=ParseSupport.PARTIALLY_SUPPORTED,
            raw={"Label": "com.example.x", "Disabled": True},
        )
        assert format_state(_discovered(parsed)) == "disabled"

    def test_external_invalid(self) -> None:
        parsed = _parsed(status=ParseSupport.INVALID, raw={"Label": "com.example.x"})
        assert format_state(_discovered(parsed)) == "invalid"

    def test_saved_not_installed(self) -> None:
        assert format_state(_saved(make_job())) == "Saved, not installed"

    def test_managed_configured_disabled(self) -> None:
        job = make_job(enabled=False)
        listing = _discovered(_parsed(job=job), managed=True, job=job)
        assert format_state(listing) == "Installed, configured disabled"


class TestFormatLifecycleState:
    def test_configured_enabled_loaded(self) -> None:
        assert format_lifecycle_state("enabled", True) == "Installed, configured enabled (loaded)"

    def test_configured_disabled_not_loaded(self) -> None:
        text = format_lifecycle_state("disabled", False)
        assert text == "Installed, configured disabled (not loaded)"

    def test_unknown_enabled(self) -> None:
        assert format_lifecycle_state("unknown", True) == "Status unknown"

    def test_unknown_loaded(self) -> None:
        assert format_lifecycle_state("enabled", None) == "Status unknown"


class TestFormatEnabled:
    def test_external_disabled_key(self) -> None:
        parsed = _parsed(
            status=ParseSupport.PARTIALLY_SUPPORTED,
            raw={"Label": "com.example.x", "Disabled": True},
        )
        assert format_enabled(_discovered(parsed)) == "disabled"


class TestPreviewWording:
    """Increment 15: the next-run preview wording is pinned by the spec."""

    def test_format_upcoming_heading_disabled(self) -> None:
        job = make_job(enabled=False)
        assert format_upcoming_heading(_saved(job)) == PREVIEW_DISABLED_HEADING
