"""Execution-history models: event kinds, outcomes, events, and the repository port.

These models carry metadata only — never stdout/stderr, environment values,
or raw launchctl output. The application layer sees only HistoryEvent and
HistoryReadResult; the storage adapter implements HistoryRepository.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class HistoryEventKind(StrEnum):
    """What kind of application-observed event was recorded."""

    DIRECT_TEST = "direct_test"
    MANUAL_RUN = "manual_run"
    STATUS_OBSERVATION = "status_observation"
    DIAGNOSTIC_RESULT = "diagnostic_result"


class HistoryOutcome(StrEnum):
    """Outcome of a recorded event."""

    SUCCESS = "success"
    FAILURE = "failure"
    OBSERVED = "observed"


@dataclass(frozen=True, slots=True)
class HistoryEvent:
    """One application-observed execution-history event (metadata only)."""

    created_at: datetime
    job_id: UUID
    label: str
    kind: HistoryEventKind
    outcome: HistoryOutcome
    exit_code: int | None = None
    duration_seconds: float | None = None
    loaded: bool | None = None
    diagnostic_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HistoryReadResult:
    """Result of a bounded history read: events newest first, or a safe error."""

    events: tuple[HistoryEvent, ...] = ()
    error: str | None = None


class HistoryRepository(Protocol):
    """Port for the append-only execution-history store."""

    def append(self, event: HistoryEvent) -> None:
        """Record an event. Best-effort: never raises."""

    def read(self, job_id: UUID, *, limit: int) -> HistoryReadResult:
        """Read the most recent events for one job, newest first.

        Storage failures become a safe ``error`` result, never an exception.
        """


HISTORY_UNAVAILABLE = "execution history unavailable"
