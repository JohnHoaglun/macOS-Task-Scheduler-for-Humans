"""Presenters that format execution-history events.

Every function is pure: it maps a HistoryEvent to display strings.
"""

from __future__ import annotations

from task_scheduler.application.history_models import (
    HistoryEvent,
    HistoryEventKind,
)
from task_scheduler.application.history_models import (
    HistoryOutcome as HistoryOutcomeEnum,
)

__all__ = [
    "HISTORY_DISCLOSURE",
    "HISTORY_EMPTY",
    "HISTORY_NOT_APPLICABLE",
    "format_event_details",
    "format_event_kind",
    "format_event_outcome",
    "format_event_time",
]

HISTORY_DISCLOSURE = (
    "Records only what this application observed (tests, manual runs, "
    "status checks). It does not prove launchd ran the task on schedule."
)

HISTORY_EMPTY = "No execution history recorded for this task."

HISTORY_NOT_APPLICABLE = "Execution history is only recorded for managed tasks."


def format_event_time(event: HistoryEvent) -> str:
    """Local time string for the event's timestamp."""
    return event.created_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def format_event_kind(kind: HistoryEventKind) -> str:
    """Human-readable kind label."""
    return {
        HistoryEventKind.DIRECT_TEST: "Direct test",
        HistoryEventKind.MANUAL_RUN: "Manual run",
        HistoryEventKind.STATUS_OBSERVATION: "Status check",
        HistoryEventKind.DIAGNOSTIC_RESULT: "Diagnostics",
    }[kind]


def format_event_outcome(outcome: HistoryOutcomeEnum) -> str:
    """Human-readable outcome label."""
    return {
        HistoryOutcomeEnum.SUCCESS: "Succeeded",
        HistoryOutcomeEnum.FAILURE: "Failed",
        HistoryOutcomeEnum.OBSERVED: "Observed",
    }[outcome]


def format_event_details(event: HistoryEvent) -> str:
    """Joined detail parts: exit code, duration, loaded state, diagnostic codes.

    Parts are joined with `` · `` (space-middot-space). Each part appears
    only when applicable. No parts yields ``""``.
    """
    parts: list[str] = []

    if event.exit_code is not None:
        parts.append(f"exit code {event.exit_code}")

    if event.duration_seconds is not None:
        parts.append(f"{event.duration_seconds:.3f}s")

    if event.kind == HistoryEventKind.STATUS_OBSERVATION:
        if event.loaded is True:
            parts.append("loaded")
        elif event.loaded is False:
            parts.append("not loaded")
        else:
            parts.append("load state unknown")

    if event.diagnostic_codes:
        parts.append(f"codes: {', '.join(event.diagnostic_codes)}")

    return " \u00b7 ".join(parts)
