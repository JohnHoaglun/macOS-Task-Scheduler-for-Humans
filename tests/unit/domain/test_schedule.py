"""Tests for the schedule model: calendar and interval variants."""

import json
from datetime import time

import pytest
from pydantic import TypeAdapter, ValidationError

from task_scheduler.domain import (
    MIN_INTERVAL_SECONDS,
    CalendarSchedule,
    IntervalSchedule,
    Schedule,
    Weekday,
    human_interval,
)

ALL_WEEKDAYS = set(Weekday)
MON_FRI = {Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY}
MWF = {Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.FRIDAY}


class TestCalendarTimes:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [("00:00", time(0, 0)), ("07:30", time(7, 30)), ("23:59", time(23, 59))],
    )
    def test_valid_times(self, text: str, expected: time) -> None:
        schedule = CalendarSchedule(times=[text], weekdays={Weekday.MONDAY})
        assert schedule.times == [expected]

    @pytest.mark.parametrize(
        "text", ["24:00", "23:60", "12", "12:60", "abc", "ab:cd", "07:30:00", "", "07-30"]
    )
    def test_invalid_times_rejected(self, text: str) -> None:
        with pytest.raises(ValidationError):
            CalendarSchedule(times=[text], weekdays={Weekday.MONDAY})

    def test_time_with_seconds_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalendarSchedule(times=[time(7, 30, 15)], weekdays={Weekday.MONDAY})

    def test_time_objects_accepted(self) -> None:
        schedule = CalendarSchedule(times=[time(7, 30)], weekdays={Weekday.MONDAY})
        assert schedule.times == [time(7, 30)]

    def test_non_string_non_time_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalendarSchedule(times=[123], weekdays={Weekday.MONDAY})

    def test_non_list_times_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalendarSchedule(times="07:30", weekdays={Weekday.MONDAY})

    def test_zero_times_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalendarSchedule(times=[], weekdays={Weekday.MONDAY})

    def test_times_sorted_ascending_and_deduped(self) -> None:
        schedule = CalendarSchedule(
            times=["17:30", "07:30", "17:30", "11:00"], weekdays={Weekday.MONDAY}
        )
        assert schedule.times == [time(7, 30), time(11, 0), time(17, 30)]


class TestCalendarWeekdays:
    @pytest.mark.parametrize("weekdays", [{Weekday.MONDAY}, MON_FRI, MWF, ALL_WEEKDAYS])
    def test_weekday_selections_accepted(self, weekdays: set[Weekday]) -> None:
        schedule = CalendarSchedule(times=["07:30"], weekdays=weekdays)
        assert schedule.weekdays == weekdays

    def test_zero_weekdays_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalendarSchedule(times=["07:30"], weekdays=set())


class TestCalendarSerialization:
    def test_kind_defaults_to_calendar(self) -> None:
        assert CalendarSchedule(times=["07:30"], weekdays={Weekday.MONDAY}).kind == "calendar"

    def test_run_at_load_defaults_false(self) -> None:
        schedule = CalendarSchedule(times=["07:30"], weekdays={Weekday.MONDAY})
        assert schedule.run_at_load is False

    def test_json_round_trip(self) -> None:
        schedule = CalendarSchedule(times=["07:30", "17:30"], weekdays=MWF, run_at_load=True)
        data = CalendarSchedule.model_validate_json(schedule.model_dump_json())
        assert data == schedule
        assert '"kind": "calendar"' in schedule.model_dump_json(indent=2)

    def test_times_serialize_hhmm(self) -> None:
        schedule = CalendarSchedule(times=[time(7, 30)], weekdays={Weekday.MONDAY})
        data = json.loads(schedule.model_dump_json())
        assert data["times"] == ["07:30"]

    def test_weekdays_serialize_sorted(self) -> None:
        schedule = CalendarSchedule(
            times=["07:30"], weekdays={Weekday.FRIDAY, Weekday.MONDAY}
        )
        data = json.loads(schedule.model_dump_json())
        assert data["weekdays"] == ["friday", "monday"]


class TestInterval:
    def test_minimum_accepted(self) -> None:
        schedule = IntervalSchedule(seconds=MIN_INTERVAL_SECONDS)
        assert schedule.seconds == MIN_INTERVAL_SECONDS

    @pytest.mark.parametrize("seconds", [59, 0, -5])
    def test_below_minimum_rejected(self, seconds: int) -> None:
        with pytest.raises(ValidationError):
            IntervalSchedule(seconds=seconds)

    def test_kind_is_interval(self) -> None:
        assert IntervalSchedule(seconds=1800).kind == "interval"

    def test_run_at_load_defaults_false(self) -> None:
        assert IntervalSchedule(seconds=1800).run_at_load is False

    def test_json_round_trip(self) -> None:
        schedule = IntervalSchedule(seconds=3600, run_at_load=True)
        data = IntervalSchedule.model_validate_json(schedule.model_dump_json())
        assert data == schedule


class TestUnionAndRendering:
    def test_discriminated_union_validates_both_kinds(self) -> None:
        adapter = TypeAdapter(Schedule)
        calendar = adapter.validate_python(
            {"kind": "calendar", "times": ["07:30"], "weekdays": ["monday"]}
        )
        assert isinstance(calendar, CalendarSchedule)
        interval = adapter.validate_python({"kind": "interval", "seconds": 1800})
        assert isinstance(interval, IntervalSchedule)

    def test_unknown_kind_rejected(self) -> None:
        adapter = TypeAdapter(Schedule)
        with pytest.raises(ValidationError):
            adapter.validate_python({"kind": "weekly", "times": ["07:30"]})

    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (60, "Every minute"),
            (15, "Every 15 seconds"),
            (1800, "Every 30 minutes"),
            (3600, "Every hour"),
            (7200, "Every 2 hours"),
            (86400, "Every day"),
            (172800, "Every 2 days"),
        ],
    )
    def test_human_interval(self, seconds: int, expected: str) -> None:
        assert human_interval(seconds) == expected
