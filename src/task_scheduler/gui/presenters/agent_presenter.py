"""Presenters that format task rows for the discovery UI."""

from __future__ import annotations

import plistlib
from enum import StrEnum

from task_scheduler.application.task_command_service import (
    ListingKind,
    TaskListing,
)
from task_scheduler.domain import JobDefinition, command_argv
from task_scheduler.platform.macos import (
    LaunchAgentStatus,
    ParseSupport,
)

__all__ = [
    "AgentClassification",
    "classify",
    "format_command",
    "format_enabled",
    "format_environment",
    "format_label",
    "format_name",
    "format_raw_plist",
    "format_schedule",
    "format_state",
    "format_status",
    "format_warnings",
    "format_working_directory",
]


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
    """The schedule as 'at HH:MM on Weekday, ...', or a dash when unparseable."""
    job = _job_of(listing)
    if job is not None:
        return f"at {job.schedule.time} on " + ", ".join(
            weekday.value.title() for weekday in sorted(job.schedule.weekdays)
        )
    return "—"


def format_state(listing: TaskListing) -> str:
    """The row's state: the parse support level, or 'saved, not installed'."""
    if listing.kind is ListingKind.SAVED:
        return "saved, not installed"
    parsed = listing.parsed
    if parsed is None:
        return "—"
    return {
        ParseSupport.SUPPORTED: "supported",
        ParseSupport.PARTIALLY_SUPPORTED: "partially supported",
        ParseSupport.INVALID: "invalid",
    }[parsed.status]


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
