"""Presenters that format task rows for the discovery UI."""

from __future__ import annotations

import plistlib
from datetime import datetime
from enum import StrEnum

from task_scheduler.application.task_command_service import (
    ListingKind,
    TaskListing,
)
from task_scheduler.domain import (
    CalendarSchedule,
    IntervalSchedule,
    JobDefinition,
    command_argv,
    human_interval,
    upcoming_occurrences,
)
from task_scheduler.platform.macos import (
    LaunchAgentStatus,
    ParseSupport,
)

__all__ = [
    "AgentClassification",
    "PREVIEW_COUNT",
    "PREVIEW_DISCLOSURE",
    "PREVIEW_DISABLED_HEADING",
    "PREVIEW_HEADING",
    "PREVIEW_INCOMPLETE",
    "PREVIEW_UNAVAILABLE",
    "classify",
    "format_command",
    "format_enabled",
    "format_environment",
    "format_label",
    "format_name",
    "format_raw_plist",
    "format_schedule",
    "format_upcoming_heading",
    "format_upcoming_occurrences",
    "format_upcoming_occurrences_for",
    "format_lifecycle_state",
    "format_state",
    "format_status",
    "format_warnings",
    "format_working_directory",
]

PREVIEW_COUNT = 5
PREVIEW_DISCLOSURE = (
    "Estimated upcoming schedule occurrences — application-derived schedule "
    "preview, not launchd's internal queue"
)
PREVIEW_HEADING = "Next scheduled times"
PREVIEW_DISABLED_HEADING = "Next scheduled times (configured disabled)"
PREVIEW_INCOMPLETE = "Complete the schedule to preview occurrences."
PREVIEW_UNAVAILABLE = "No schedule available to preview."
PREVIEW_NO_INTERVAL = "Interval schedules have no dated occurrences to preview."
PREVIEW_LINE_FORMAT = "%a %b %d %H:%M"


class AgentClassification(StrEnum):
    """How a discovered agent is presented in the UI."""

    MANAGED = "Managed"
    EXTERNAL = "External"
    INVALID = "Invalid"


def _job_of(listing: TaskListing) -> JobDefinition | None:
    """The job to display: the deployed parse first, then the catalog job."""
    parsed = listing.parsed
    if parsed is not None and parsed.job is not None:
        return parsed.job
    return listing.job


def classify(listing: TaskListing) -> AgentClassification:
    """Classify a task row; an invalid parse always wins over the managed flag."""
    if listing.kind is ListingKind.SAVED:
        return AgentClassification.MANAGED
    parsed = listing.parsed
    if parsed is None or parsed.status is ParseSupport.INVALID:
        return AgentClassification.INVALID
    return AgentClassification.MANAGED if listing.managed else AgentClassification.EXTERNAL


def format_name(listing: TaskListing) -> str:
    """Display name: the job name when available, else the plist file stem."""
    job = _job_of(listing)
    if job is not None:
        return job.name
    if listing.path is not None:
        return listing.path.stem
    return "—"


def format_label(listing: TaskListing) -> str:
    """The launchd label, falling back to the raw plist's Label key."""
    job = _job_of(listing)
    if job is not None:
        return job.label
    parsed = listing.parsed
    if parsed is not None:
        return str(parsed.raw.get("Label", "—"))
    return "—"


def format_command(listing: TaskListing) -> str:
    """Command text: the job's argv, else the raw ProgramArguments list."""
    job = _job_of(listing)
    if job is not None:
        return " ".join(command_argv(job.command))
    parsed = listing.parsed
    if parsed is not None:
        raw_args = parsed.raw.get("ProgramArguments")
        if isinstance(raw_args, list) and all(isinstance(item, str) for item in raw_args):
            return " ".join(map(str, raw_args))
    return "—"


def format_schedule(listing: TaskListing) -> str:
    """The schedule as 'at HH:MM:SS on Weekday, ...', or a dash when unparseable."""
    job = _job_of(listing)
    if job is None:
        return "—"
    schedule = job.schedule
    if isinstance(schedule, IntervalSchedule):
        text = human_interval(schedule.seconds)
    else:
        parts = [f"{time:%H:%M:%S}" for time in schedule.times]
        times = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + f" and {parts[-1]}"
        weekdays = ", ".join(weekday.value.title() for weekday in sorted(schedule.weekdays))
        text = f"at {times} on {weekdays}"
    if schedule.run_at_load:
        text += " + at login"
    return text


def format_upcoming_heading(listing: TaskListing) -> str:
    """The preview heading, with the configured-disabled label for disabled jobs."""
    job = _job_of(listing)
    if job is not None and not job.enabled:
        return PREVIEW_DISABLED_HEADING
    return PREVIEW_HEADING


def format_upcoming_occurrences(schedule: CalendarSchedule, *, now: datetime) -> str:
    """The next PREVIEW_COUNT occurrences as local-time lines, oldest first."""
    return "\n".join(
        occurrence.strftime(PREVIEW_LINE_FORMAT)
        for occurrence in upcoming_occurrences(schedule, now=now, count=PREVIEW_COUNT)
    )


def format_upcoming_occurrences_for(listing: TaskListing, *, now: datetime) -> str:
    """The preview lines for a listing, or the honest no-preview note."""
    job = _job_of(listing)
    if job is None:
        return PREVIEW_UNAVAILABLE
    schedule = job.schedule
    if isinstance(schedule, IntervalSchedule):
        return PREVIEW_NO_INTERVAL
    return format_upcoming_occurrences(schedule, now=now)


def format_state(listing: TaskListing) -> str:
    """The row's state: saved, installed-and-configured, or parse support level."""
    if listing.kind is ListingKind.SAVED:
        return "Saved, not installed"
    if listing.job is not None:
        return f"Installed, configured {'enabled' if listing.job.enabled else 'disabled'}"
    parsed = listing.parsed
    if parsed is None:
        return "—"
    return {
        ParseSupport.SUPPORTED: "supported",
        ParseSupport.PARTIALLY_SUPPORTED: "partially supported",
        ParseSupport.INVALID: "invalid",
    }[parsed.status]


def format_lifecycle_state(enabled: bool | None, loaded: bool | None) -> str:
    """The full installed state: configured plus loaded, or 'Status unknown'."""
    if enabled is None or loaded is None:
        return "Status unknown"
    configured = "enabled" if enabled else "disabled"
    runtime = "loaded" if loaded else "not loaded"
    return f"Installed, configured {configured} ({runtime})"


def format_status(status: LaunchAgentStatus | None) -> str:
    """launchd load state: unknown, loaded, or not loaded."""
    if status is None or status.loaded is None:
        return "unknown"
    return "loaded" if status.loaded else "not loaded"


def format_enabled(listing: TaskListing) -> str:
    """The job's enabled state, or a dash when the job was not parsed."""
    job = _job_of(listing)
    if job is None:
        return "—"
    return "enabled" if job.enabled else "disabled"


def format_environment(listing: TaskListing) -> str:
    """The configured environment variables as 'KEY=VALUE' pairs."""
    job = _job_of(listing)
    if job is None:
        return "—"
    pairs = ", ".join(f"{key}={value}" for key, value in job.environment.variables.items())
    return pairs or "none configured"


def format_working_directory(listing: TaskListing) -> str:
    """The configured working directory, or 'not set' / a dash."""
    job = _job_of(listing)
    if job is None:
        return "—"
    return str(job.working_directory) if job.working_directory else "not set"


def format_warnings(listing: TaskListing) -> str:
    """All warnings plus a summary line for unsupported keys."""
    parsed = listing.parsed
    if parsed is None:
        return "none"
    lines = list(parsed.warnings)
    if parsed.unsupported_keys:
        lines.append("unsupported keys: " + ", ".join(parsed.unsupported_keys))
    return "\n".join(lines) if lines else "none"


def format_raw_plist(listing: TaskListing) -> str:
    """The raw plist re-serialized as XML, or a placeholder when absent."""
    parsed = listing.parsed
    if parsed is None:
        return "(no deployed plist — saved in the task catalog)"
    if not parsed.raw:
        return "(no raw data)"
    return plistlib.dumps(parsed.raw, fmt=plistlib.FMT_XML).decode()
