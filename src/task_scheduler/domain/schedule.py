"""Schedule domain model: one execution time on one or more weekdays."""

from __future__ import annotations

from datetime import time as Time
from enum import StrEnum

from pydantic import BaseModel, field_serializer, field_validator


class Weekday(StrEnum):
    """Weekday names as used in JSON representations."""

    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class Schedule(BaseModel):
    """One execution time applied to a set of selected weekdays."""

    time: Time
    weekdays: set[Weekday]

    @field_validator("time", mode="before")
    @classmethod
    def _coerce_time(cls, value: object) -> Time:
        if isinstance(value, Time):
            if value.second or value.microsecond:
                raise ValueError("schedule times support minute precision only (HH:MM)")
            return value
        if isinstance(value, str):
            return cls._parse_time_string(value)
        raise ValueError("schedule time must be a time object or an 'HH:MM' string")

    @classmethod
    def _parse_time_string(cls, value: str) -> Time:
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

    @field_validator("weekdays")
    @classmethod
    def _require_weekdays(cls, value: set[Weekday]) -> set[Weekday]:
        if not value:
            raise ValueError("at least one weekday is required")
        return value

    @field_serializer("time")
    def _serialize_time(self, value: Time) -> str:
        return value.strftime("%H:%M")

    @field_serializer("weekdays")
    def _serialize_weekdays(self, value: set[Weekday]) -> list[str]:
        return sorted(weekday.value for weekday in value)
