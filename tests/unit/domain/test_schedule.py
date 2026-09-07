"""Tests for the schedule model: calendar and interval variants."""

from datetime import datetime, time

import pytest
from pydantic import ValidationError

from task_scheduler.domain import (
    CalendarSchedule,
    IntervalSchedule,
    Weekday,
    human_interval,
    upcoming_interval_occurrences,
    upcoming_occurrences,
)

ALL_WEEKDAYS = set(Weekday)
MON_FRI = {Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY}
MWF = {Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.FRIDAY}

class TestCalendarTimes:

    def test_time_with_seconds_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalendarSchedule(times=[time(7, 30, 15)], weekdays={Weekday.MONDAY})

    def test_non_string_non_time_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalendarSchedule(times=[123], weekdays={Weekday.MONDAY})

    def test_non_list_times_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalendarSchedule(times="07:30", weekdays={Weekday.MONDAY})

    def test_zero_times_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalendarSchedule(times=[], weekdays={Weekday.MONDAY})

class TestUnionAndRendering:

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

    @pytest.mark.parametrize("count", [0, -3])
    def test_invalid_count_rejected(self, count: int) -> None:
        with pytest.raises(ValueError):
            upcoming_occurrences(self.MONDAY_0730, now=datetime(2026, 8, 31, 12, 0), count=count)

class TestUpcomingIntervalOccurrences:
    NINETY_SECONDS = IntervalSchedule(seconds=90)

    @pytest.mark.parametrize("count", [0, -1])
    def test_invalid_count_rejected(self, count: int) -> None:
        with pytest.raises(ValueError):
            upcoming_interval_occurrences(
                self.NINETY_SECONDS, now=datetime(2026, 9, 5, 12, 0), count=count
            )

    def test_calendar_schedule_rejected(self) -> None:
        with pytest.raises(ValueError):
            upcoming_interval_occurrences(
                CalendarSchedule(times=["07:30"], weekdays={Weekday.MONDAY}),
                now=datetime(2026, 9, 5, 12, 0),
                count=5,
            )
