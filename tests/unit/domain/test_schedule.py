"""Tests for the schedule model: calendar and interval variants."""

import json
from datetime import datetime, time

import pytest
from pydantic import TypeAdapter, ValidationError

from task_scheduler.domain import (
    MIN_INTERVAL_SECONDS,
    CalendarSchedule,
    IntervalSchedule,
    Schedule,
    Weekday,
    human_interval,
    upcoming_occurrences,
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


# Weekday anchors (verified against the 2026 calendar):
# 2026-08-26 Wed, 2026-08-30 Sun, 2026-08-31 Mon, 2026-09-02 Wed,
# 2026-09-04 Fri, 2026-09-05 Sat, 2026-09-06 Sun, 2026-09-07 Mon,
# 2026-09-09 Wed, 2026-09-14 Mon, 2026-09-16 Wed, 2026-09-21 Mon


class TestUpcomingOccurrences:
    MONDAY_0730 = CalendarSchedule(times=["07:30"], weekdays={Weekday.MONDAY})

    def test_same_day_before_time(self) -> None:
        """A configured time later the same day is the first occurrence."""
        now = datetime(2026, 8, 31, 7, 0)  # Monday 07:00
        result = upcoming_occurrences(self.MONDAY_0730, now=now, count=5)
        assert result == [
            datetime(2026, 8, 31, 7, 30),
            datetime(2026, 9, 7, 7, 30),
            datetime(2026, 9, 14, 7, 30),
            datetime(2026, 9, 21, 7, 30),
            datetime(2026, 9, 28, 7, 30),
        ]

    def test_exact_boundary_includes_now(self) -> None:
        """An occurrence exactly at now is included."""
        now = datetime(2026, 8, 31, 7, 30)  # Monday 07:30
        result = upcoming_occurrences(self.MONDAY_0730, now=now, count=2)
        assert result == [now, datetime(2026, 9, 7, 7, 30)]

    def test_same_day_after_time_skips_today(self) -> None:
        """Once past the configured time, the next configured weekday wins."""
        now = datetime(2026, 8, 31, 7, 31)  # Monday 07:31
        assert upcoming_occurrences(self.MONDAY_0730, now=now, count=1) == [
            datetime(2026, 9, 7, 7, 30)
        ]

    def test_friday_to_saturday_rollover(self) -> None:
        schedule = CalendarSchedule(times=["09:00"], weekdays={Weekday.SATURDAY})
        now = datetime(2026, 9, 4, 8, 0)  # Friday
        assert upcoming_occurrences(schedule, now=now, count=1) == [
            datetime(2026, 9, 5, 9, 0)
        ]

    def test_sunday_to_monday_rollover(self) -> None:
        schedule = CalendarSchedule(times=["00:30"], weekdays={Weekday.MONDAY})
        now = datetime(2026, 9, 6, 23, 0)  # Sunday 23:00
        assert upcoming_occurrences(schedule, now=now, count=1) == [
            datetime(2026, 9, 7, 0, 30)
        ]

    def test_multi_time_chronological_ordering(self) -> None:
        schedule = CalendarSchedule(
            times=["17:30", "07:30"], weekdays={Weekday.MONDAY, Weekday.WEDNESDAY}
        )
        now = datetime(2026, 9, 7, 8, 0)  # Monday 08:00, past the 07:30 run
        result = upcoming_occurrences(schedule, now=now, count=5)
        assert result == [
            datetime(2026, 9, 7, 17, 30),
            datetime(2026, 9, 9, 7, 30),
            datetime(2026, 9, 9, 17, 30),
            datetime(2026, 9, 14, 7, 30),
            datetime(2026, 9, 14, 17, 30),
        ]

    def test_requested_count(self) -> None:
        now = datetime(2026, 8, 31, 12, 0)  # Monday, past the 07:30 run
        assert len(upcoming_occurrences(self.MONDAY_0730, now=now, count=1)) == 1
        assert len(upcoming_occurrences(self.MONDAY_0730, now=now, count=10)) == 10

    def test_run_at_load_adds_no_dated_occurrence(self) -> None:
        schedule = CalendarSchedule(
            times=["07:30"], weekdays={Weekday.MONDAY}, run_at_load=True
        )
        now = datetime(2026, 8, 31, 7, 0)
        assert upcoming_occurrences(schedule, now=now, count=5) == upcoming_occurrences(
            self.MONDAY_0730, now=now, count=5
        )

    def test_occurrences_are_naive_local_datetimes(self) -> None:
        now = datetime(2026, 8, 31, 7, 0)
        result = upcoming_occurrences(self.MONDAY_0730, now=now, count=3)
        assert all(occurrence.tzinfo is None for occurrence in result)
        assert all(occurrence.time() == time(7, 30) for occurrence in result)

    @pytest.mark.parametrize("count", [0, -3])
    def test_invalid_count_rejected(self, count: int) -> None:
        with pytest.raises(ValueError):
            upcoming_occurrences(self.MONDAY_0730, now=datetime(2026, 8, 31, 12, 0), count=count)
