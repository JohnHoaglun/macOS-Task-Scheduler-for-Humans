"""Schedule domain model: calendar (weekday + times) or interval execution."""

from __future__ import annotations

from datetime import datetime, timedelta
from datetime import time as Time
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_serializer, field_validator

MIN_INTERVAL_SECONDS = 60


class Weekday(StrEnum):
    """Weekday names as used in JSON representations."""

    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


def _parse_time_string(value: str) -> Time:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"schedule time must look like 'HH:MM', got {value!r}")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(f"schedule time must look like 'HH:MM', got {value!r}") from None
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(f"schedule time out of range (00:00-23:59), got {value!r}")
    return Time(hour, minute)


def _coerce_time(value: object) -> Time:
    if isinstance(value, Time):
        if value.second or value.microsecond:
            raise ValueError("schedule times support minute precision only (HH:MM)")
        return value
    if isinstance(value, str):
        return _parse_time_string(value)
    raise ValueError("schedule times must be time objects or 'HH:MM' strings")


def _require_weekdays(value: set[Weekday]) -> set[Weekday]:
    if not value:
        raise ValueError("at least one weekday is required")
    return value


def _serialize_times(value: list[Time]) -> list[str]:
    return [time.strftime("%H:%M") for time in value]


def _serialize_weekdays(value: set[Weekday]) -> list[str]:
    return sorted(weekday.value for weekday in value)


class CalendarSchedule(BaseModel):
    """One or more execution times applied to a set of selected weekdays."""

    kind: Literal["calendar"] = "calendar"
    times: list[Time]
    weekdays: set[Weekday]
    run_at_load: bool = False

    @field_validator("times", mode="before")
    @classmethod
    def _coerce_times(cls, value: object) -> list[Time]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("calendar schedule times must be a list of times")
        times = [_coerce_time(item) for item in value]
        if not times:
            raise ValueError("at least one time is required")
        return sorted(set(times))

    @field_validator("weekdays")
    @classmethod
    def _require_weekdays(cls, value: set[Weekday]) -> set[Weekday]:
        return _require_weekdays(value)

    @field_serializer("times")
    def _serialize_times(self, value: list[Time]) -> list[str]:
        return _serialize_times(value)

    @field_serializer("weekdays")
    def _serialize_weekdays(self, value: set[Weekday]) -> list[str]:
        return _serialize_weekdays(value)


class IntervalSchedule(BaseModel):
    """Repeated execution at a fixed interval, in whole seconds."""

    kind: Literal["interval"] = "interval"
    seconds: int
    run_at_load: bool = False

    @field_validator("seconds")
    @classmethod
    def _require_minimum_seconds(cls, value: int) -> int:
        if value < MIN_INTERVAL_SECONDS:
            raise ValueError(f"interval must be at least {MIN_INTERVAL_SECONDS} seconds")
        return value


def human_interval(seconds: int) -> str:
    """Render an interval in whole seconds as a human phrase, e.g. ``Every 30 minutes``."""
    if seconds % 86400 == 0:
        count, unit = seconds // 86400, "day"
    elif seconds % 3600 == 0:
        count, unit = seconds // 3600, "hour"
    elif seconds % 60 == 0:
        count, unit = seconds // 60, "minute"
    else:
        count, unit = seconds, "second"
    if count == 1:
        return f"Every {unit}"
    return f"Every {count} {unit}s"


_WEEKDAY_TO_PYTHON_INDEX = {
    Weekday.MONDAY: 0,
    Weekday.TUESDAY: 1,
    Weekday.WEDNESDAY: 2,
    Weekday.THURSDAY: 3,
    Weekday.FRIDAY: 4,
    Weekday.SATURDAY: 5,
    Weekday.SUNDAY: 6,
}


def upcoming_occurrences(
    schedule: CalendarSchedule, *, now: datetime, count: int
) -> list[datetime]:
    """The next *count* calendar occurrences at or after *now*, oldest first.

    Occurrences are naive local datetimes derived from the injected *now* —
    no clock, I/O, or timezone handling. An occurrence exactly at *now* is
    included. ``run_at_load`` is additive and never contributes a dated
    occurrence. Raises ``ValueError`` when *count* is less than 1.
    """
    if count < 1:
        raise ValueError("count must be at least 1")
    target_days = {_WEEKDAY_TO_PYTHON_INDEX[weekday] for weekday in schedule.weekdays}
    occurrences: list[datetime] = []
    day = now.date()
    while len(occurrences) < count:
        if day.weekday() in target_days:
            for scheduled_time in schedule.times:
                candidate = datetime.combine(day, scheduled_time)
                if candidate >= now:
                    occurrences.append(candidate)
                    if len(occurrences) >= count:
                        break
        day += timedelta(days=1)
    return occurrences


Schedule = Annotated[CalendarSchedule | IntervalSchedule, Field(discriminator="kind")]
