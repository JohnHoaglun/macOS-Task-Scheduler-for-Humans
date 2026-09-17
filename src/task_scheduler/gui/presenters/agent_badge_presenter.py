"""Pure filter-dimension presenter for agent rows (no Qt dependency)."""

from __future__ import annotations

from dataclasses import dataclass

from task_scheduler.application.task_command_service import ListingKind, TaskListing
from task_scheduler.domain import JobDefinition
from task_scheduler.gui.presenters.agent_presenter import classify, enabled_state


@dataclass(frozen=True, slots=True)
class AgentDimensions:
    """State of one agent row across five filterable dimensions."""

    state: str
    installed: str
    enabled: str
    loaded: str
    command: str


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
    enabled = enabled_state(listing)
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


__all__ = [
    "AgentDimensions",
    "dimensions",
]
