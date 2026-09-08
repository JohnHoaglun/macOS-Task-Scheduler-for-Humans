"""Pure badge presenter for agent rows (no Qt dependency)."""

from __future__ import annotations

from dataclasses import dataclass

from task_scheduler.application.task_command_service import ListingKind, TaskListing
from task_scheduler.domain import JobDefinition
from task_scheduler.gui.presenters.agent_presenter import classify


@dataclass(frozen=True, slots=True)
class BadgeDescriptor:
    """A single badge with text, accessible name, and optional tooltip."""

    text: str
    accessible_name: str
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class AgentDimensions:
    """State of one agent row across five filterable dimensions."""

    state: str
    installed: str
    enabled: str
    loaded: str
    command: str


@dataclass(frozen=True, slots=True)
class AgentBadgeSet:
    """All five badge descriptors for one agent row."""

    state: BadgeDescriptor
    installed: BadgeDescriptor
    enabled: BadgeDescriptor
    loaded: BadgeDescriptor
    command: BadgeDescriptor


def dimensions(listing: TaskListing) -> AgentDimensions:
    """Extract the five filterable dimensions from a listing."""
    state = classify(listing).value
    installed = "saved" if listing.kind is ListingKind.SAVED else "installed"
    parsed = listing.parsed
    job: JobDefinition | None = None
    if parsed is not None and parsed.job is not None:
        job = parsed.job
    elif listing.job is not None:
        job = listing.job
    enabled = "unknown" if job is None else ("enabled" if job.enabled else "disabled")
    loaded = (
        "loaded"
        if listing.loaded is True
        else ("not loaded" if listing.loaded is False else "unknown")
    )
    cmd_type: str = job.command.type if job is not None else "unknown"
    return AgentDimensions(
        state=state,
        installed=installed,
        enabled=enabled,
        loaded=loaded,
        command=cmd_type,
    )


def agent_badges(listing: TaskListing) -> AgentBadgeSet:
    """Build a BadgeSet for *listing* with human-friendly tooltips."""
    dims = dimensions(listing)

    state = BadgeDescriptor(
        text=dims.state,
        accessible_name=f"State: {dims.state}",
        tooltip=_state_tooltip(dims.state),
    )
    installed = BadgeDescriptor(
        text=dims.installed,
        accessible_name=f"Installed: {dims.installed}",
        tooltip=_installed_tooltip(dims.installed),
    )
    enabled = BadgeDescriptor(
        text=dims.enabled,
        accessible_name=f"Enabled: {dims.enabled}",
        tooltip=_enabled_tooltip(dims.enabled),
    )
    loaded = BadgeDescriptor(
        text=dims.loaded,
        accessible_name=f"Loaded: {dims.loaded}",
        tooltip=_loaded_tooltip(dims.loaded),
    )
    command = BadgeDescriptor(
        text=dims.command,
        accessible_name=f"Command: {dims.command}",
        tooltip=_command_tooltip(dims.command),
    )
    return AgentBadgeSet(
        state=state,
        installed=installed,
        enabled=enabled,
        loaded=loaded,
        command=command,
    )


def _state_tooltip(value: str) -> str | None:
    if value == "Managed":
        return "Managed by the task catalog"
    if value == "External":
        return "Third-party LaunchAgent, not managed by the catalog"
    return "Invalid or unrecognized agent"


def _installed_tooltip(value: str) -> str | None:
    if value == "saved":
        return "Job saved in the catalog but not deployed as a plist"
    return "Plist discovered in the LaunchAgents directory"


def _enabled_tooltip(value: str) -> str | None:
    if value == "enabled":
        return "Job is configured to run"
    if value == "disabled":
        return "Job is configured but disabled"
    return "Enabled state could not be determined"


def _loaded_tooltip(value: str) -> str | None:
    if value == "loaded":
        return "Job is currently loaded in launchd"
    if value == "not loaded":
        return "Job is installed but not loaded in launchd"
    return "Load status is unknown"


def _command_tooltip(value: str) -> str | None:
    if value == "python":
        return "Python script command"
    if value == "shell":
        return "Shell command"
    if value == "executable":
        return "Direct executable command"
    return "Command type could not be determined"


__all__ = [
    "AgentBadgeSet",
    "AgentDimensions",
    "BadgeDescriptor",
    "agent_badges",
    "dimensions",
]
