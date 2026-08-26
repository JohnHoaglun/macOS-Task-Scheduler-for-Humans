"""Tests for the schedule model."""

import json
from datetime import time

import pytest
from pydantic import ValidationError

from task_scheduler.domain import Schedule, Weekday

ALL_WEEKDAYS = set(Weekday)
MON_FRI = {Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY}
MWF = {Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.FRIDAY}


@pytest.mark.parametrize(
    ("text", "expected"),
    [("00:00", time(0, 0)), ("07:30", time(7, 30)), ("23:59", time(23, 59))],
)
def test_valid_times(text: str, expected: time) -> None:
    schedule = Schedule(time=text, weekdays={Weekday.MONDAY})
    assert schedule.time == expected


@pytest.mark.parametrize("text", ["24:00", "23:60", "12", "12:60", "abc", "07:30:00", "", "07-30"])
def test_invalid_times_rejected(text: str) -> None:
    with pytest.raises(ValidationError):
        Schedule(time=text, weekdays={Weekday.MONDAY})


def test_time_with_seconds_rejected() -> None:
    with pytest.raises(ValidationError):
        Schedule(time=time(7, 30, 15), weekdays={Weekday.MONDAY})


def test_time_object_accepted() -> None:
    schedule = Schedule(time=time(7, 30), weekdays={Weekday.MONDAY})
    assert schedule.time == time(7, 30)


def test_non_string_non_time_rejected() -> None:
    with pytest.raises(ValidationError):
        Schedule(time=123, weekdays={Weekday.MONDAY})


def test_non_numeric_time_string_rejected() -> None:
    with pytest.raises(ValidationError):
        Schedule(time="ab:cd", weekdays={Weekday.MONDAY})


@pytest.mark.parametrize("weekdays", [{Weekday.MONDAY}, MON_FRI, MWF, ALL_WEEKDAYS])
def test_weekday_selections_accepted(weekdays: set[Weekday]) -> None:
    schedule = Schedule(time="07:30", weekdays=weekdays)
    assert schedule.weekdays == weekdays


def test_zero_weekdays_rejected() -> None:
    with pytest.raises(ValidationError):
        Schedule(time="07:30", weekdays=set())


def test_schedule_json_round_trip() -> None:
    schedule = Schedule(time="07:30", weekdays=MWF)
    data = schedule.model_validate_json(schedule.model_dump_json())
    assert data == schedule
    assert '"time": "07:30"' in schedule.model_dump_json(indent=2)


def test_weekdays_serialize_sorted() -> None:
    schedule = Schedule(time="07:30", weekdays={Weekday.FRIDAY, Weekday.MONDAY})
    data = json.loads(schedule.model_dump_json())
    assert data["weekdays"] == ["friday", "monday"]
