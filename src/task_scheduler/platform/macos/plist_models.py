"""Shared launchd plist representation types and constants.

This module is the single source for launchd-specific representation
details shared by the plist encoder and the plist reader: weekday
numbering, the set of keys the Crawl model understands, and the parse
result types.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from task_scheduler.domain import JobDefinition, Weekday

# launchd weekday numbering: Sunday=0 ... Saturday=6 (see launchd.plist(5)).
WEEKDAY_TO_LAUNCHD: dict[Weekday, int] = {
    Weekday.SUNDAY: 0,
    Weekday.MONDAY: 1,
    Weekday.TUESDAY: 2,
    Weekday.WEDNESDAY: 3,
    Weekday.THURSDAY: 4,
    Weekday.FRIDAY: 5,
    Weekday.SATURDAY: 6,
}

LAUNCHD_TO_WEEKDAY: dict[int, Weekday] = {
    value: weekday for weekday, value in WEEKDAY_TO_LAUNCHD.items()
}

# Keys the Crawl domain model can represent. Any other key in an external
# plist marks the file partially_supported rather than invalid.
SUPPORTED_KEYS: frozenset[str] = frozenset(
    {
        "Label",
        "ProgramArguments",
        "StartCalendarInterval",
        "WorkingDirectory",
        "EnvironmentVariables",
        "StandardOutPath",
        "StandardErrorPath",
        "Disabled",
    }
)


class ParseSupport(StrEnum):
    """How well a parsed plist maps onto the Crawl domain model."""

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    INVALID = "invalid"


class ParsedLaunchAgent(BaseModel):
    """Result of parsing an existing LaunchAgent plist.

    ``raw`` always preserves the decoded plist dictionary whenever the
    plist itself decoded successfully, so no external configuration is
    ever silently lost.
    """

    status: ParseSupport
    job: JobDefinition | None = None
    raw: dict[str, object] = Field(default_factory=dict)
    unsupported_keys: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
