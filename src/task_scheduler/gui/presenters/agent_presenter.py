"""Presenters that format parsed LaunchAgents for the discovery UI."""

from __future__ import annotations

import plistlib
from enum import StrEnum

from task_scheduler.application.task_command_service import AgentListing
from task_scheduler.domain import command_argv
from task_scheduler.platform.macos import (
    LaunchAgentStatus,
    ParsedLaunchAgent,
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
    "format_parsed_support",
    "format_raw_plist",
    "format_schedule",
    "format_status",
    "format_warnings",
    "format_working_directory",
]


class AgentClassification(StrEnum):
    """How a discovered agent is presented in the UI."""

    MANAGED = "Managed"
    EXTERNAL = "External"
    INVALID = "Invalid"


def classify(parsed: ParsedLaunchAgent, managed: bool) -> AgentClassification:
    """Classify an agent; an invalid parse always wins over the managed flag."""
    if parsed.status is ParseSupport.INVALID:
        return AgentClassification.INVALID
    if managed:
        return AgentClassification.MANAGED
    return AgentClassification.EXTERNAL


def format_name(agent: AgentListing) -> str:
    """Display name: the job name when parsed, otherwise the plist file stem."""
    job = agent.parsed.job
    if job is not None:
        return job.name
    return agent.path.stem


def format_label(parsed: ParsedLaunchAgent) -> str:
    """The launchd label, falling back to the raw plist's Label key."""
    job = parsed.job
    if job is not None:
        return job.label
    return str(parsed.raw.get("Label", "—"))


def format_command(parsed: ParsedLaunchAgent) -> str:
    """Command text: the parsed job's argv, else the raw ProgramArguments list."""
    job = parsed.job
    if job is not None:
        return " ".join(command_argv(job.command))
    raw_args = parsed.raw.get("ProgramArguments")
    if isinstance(raw_args, list) and all(isinstance(item, str) for item in raw_args):
        return " ".join(map(str, raw_args))
    return "—"


def format_schedule(parsed: ParsedLaunchAgent) -> str:
    """The schedule as 'at HH:MM on Weekday, ...', or a dash when unparseable."""
    job = parsed.job
    if job is not None:
        return f"at {job.schedule.time} on " + ", ".join(
            weekday.value.title() for weekday in sorted(job.schedule.weekdays)
        )
    return "—"


def format_parsed_support(parsed: ParsedLaunchAgent) -> str:
    """The parse support level in words: supported, partially, or invalid."""
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


def format_enabled(parsed: ParsedLaunchAgent) -> str:
    """The job's enabled state, or a dash when the job was not parsed."""
    job = parsed.job
    if job is None:
        return "—"
    return "enabled" if job.enabled else "disabled"


def format_environment(parsed: ParsedLaunchAgent) -> str:
    """The configured environment variables as 'KEY=VALUE' pairs."""
    job = parsed.job
    if job is None:
        return "—"
    pairs = ", ".join(f"{key}={value}" for key, value in job.environment.variables.items())
    return pairs or "none configured"


def format_working_directory(parsed: ParsedLaunchAgent) -> str:
    """The configured working directory, or 'not set' / a dash."""
    job = parsed.job
    if job is None:
        return "—"
    return str(job.working_directory) if job.working_directory else "not set"


def format_warnings(parsed: ParsedLaunchAgent) -> str:
    """All warnings plus a summary line for unsupported keys."""
    lines = list(parsed.warnings)
    if parsed.unsupported_keys:
        lines.append("unsupported keys: " + ", ".join(parsed.unsupported_keys))
    return "\n".join(lines) if lines else "none"


def format_raw_plist(parsed: ParsedLaunchAgent) -> str:
    """The raw plist re-serialized as XML, or a placeholder when absent."""
    if not parsed.raw:
        return "(no raw data)"
    return plistlib.dumps(parsed.raw, fmt=plistlib.FMT_XML).decode()
