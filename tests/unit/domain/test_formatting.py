"""Tests for the shared CLI/GUI formatting helpers."""

from pathlib import Path

from task_scheduler.domain.command import (
    ExecutableCommand,
    PythonCommand,
    ShellCommand,
)
from task_scheduler.domain.formatting import (
    format_command_argv,
    format_schedule_text,
    format_truncation_marker,
    quote_argv,
)
from task_scheduler.domain.schedule import (
    CalendarSchedule,
    IntervalSchedule,
    Weekday,
)


class TestQuoteArgv:
    def test_plain_args_unchanged(self) -> None:
        assert quote_argv(["launchctl", "list"]) == "launchctl list"

    def test_args_with_spaces_are_quoted(self) -> None:
        assert quote_argv(["/usr/local/bin/my tool", "-a"]) == "'/usr/local/bin/my tool' -a"

    def test_args_with_shell_metacharacters_are_quoted(self) -> None:
        assert quote_argv(["echo", "a;rm -rf /"]) == "echo 'a;rm -rf /'"

    def test_empty_argv_renders_empty_string(self) -> None:
        assert quote_argv([]) == ""

    def test_empty_arg_is_quoted(self) -> None:
        assert quote_argv([""]) == "''"

    def test_accepts_any_iterable(self) -> None:
        assert quote_argv(iter(["a", "b"])) == "a b"


class TestFormatCommandArgv:
    def test_python_command(self) -> None:
        command = PythonCommand(
            interpreter=Path("/usr/bin/python3"),
            script=Path("/tmp/run job.py"),
            arguments=["--flag"],
        )
        assert format_command_argv(command) == "/usr/bin/python3 '/tmp/run job.py' --flag"

    def test_shell_command(self) -> None:
        command = ShellCommand(executable=Path("/bin/zsh"), arguments=["-lc", "echo hi && there"])
        assert format_command_argv(command) == "/bin/zsh -lc 'echo hi && there'"

    def test_executable_command(self) -> None:
        command = ExecutableCommand(
            executable=Path("/usr/bin/sw_vers"), arguments=["-productVersion"]
        )
        assert format_command_argv(command) == "/usr/bin/sw_vers -productVersion"


class TestFormatScheduleText:
    def test_interval(self) -> None:
        assert format_schedule_text(IntervalSchedule(seconds=1800)) == "Every 30 minutes"

    def test_calendar_single_time_single_weekday(self) -> None:
        schedule = CalendarSchedule(times=["07:30"], weekdays={Weekday.MONDAY})
        assert format_schedule_text(schedule) == "07:30 on monday"

    def test_calendar_multiple_times_oxford_comma(self) -> None:
        schedule = CalendarSchedule(
            times=["07:30", "12:00", "18:45"],
            weekdays={Weekday.MONDAY, Weekday.WEDNESDAY},
        )
        assert format_schedule_text(schedule) == "07:30, 12:00 and 18:45 on monday, wednesday"

    def test_weekdays_sorted_canonically(self) -> None:
        schedule = CalendarSchedule(
            times=["09:00"], weekdays={Weekday.FRIDAY, Weekday.MONDAY, Weekday.WEDNESDAY}
        )
        assert format_schedule_text(schedule) == "09:00 on friday, monday, wednesday"

    def test_run_at_load_suffix(self) -> None:
        schedule = CalendarSchedule(times=["07:30"], weekdays={Weekday.MONDAY}, run_at_load=True)
        assert format_schedule_text(schedule) == "07:30 on monday + at login"

    def test_interval_run_at_load(self) -> None:
        schedule = IntervalSchedule(seconds=3600, run_at_load=True)
        assert format_schedule_text(schedule) == "Every hour + at login"

    def test_times_rendered_at_minute_precision_only(self) -> None:
        schedule = CalendarSchedule(times=["23:05"], weekdays={Weekday.SATURDAY})
        assert format_schedule_text(schedule) == "23:05 on saturday"


class TestFormatTruncationMarker:
    def test_marker_shows_tail_and_total(self) -> None:
        assert format_truncation_marker(1_048_576, 256 * 1024) == (
            "(truncated: showing the last 256 KiB of 1048576 bytes)"
        )

    def test_marker_scales_with_tail_size(self) -> None:
        assert format_truncation_marker(512 * 1024, 64 * 1024) == (
            "(truncated: showing the last 64 KiB of 524288 bytes)"
        )
