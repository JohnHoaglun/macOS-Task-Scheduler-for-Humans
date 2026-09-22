"""Pure display formatting shared by the CLI and the GUI.

These helpers turn domain values into canonical text. They import no Qt and
depend only on the domain model, so the CLI (``cli.render``) and the GUI
(``gui.presenters.agent_presenter``, the import preview, and the table search
haystack) all render byte-identical command and schedule strings.
"""

from __future__ import annotations

import shlex
from collections.abc import Iterable

from task_scheduler.domain.command import Command, command_argv
from task_scheduler.domain.schedule import (
    IntervalSchedule,
    Schedule,
    human_interval,
)

__all__ = [
    "format_command_argv",
    "format_schedule_text",
    "format_truncation_marker",
    "quote_argv",
]


def quote_argv(args: Iterable[str]) -> str:
    """Join argv elements shell-quoted with :func:`shlex.quote`."""
    return " ".join(shlex.quote(arg) for arg in args)


def format_command_argv(command: Command) -> str:
    """Render a command's argv shell-quoted, identical across CLI and GUI."""
    return quote_argv(command_argv(command))


def format_schedule_text(schedule: Schedule) -> str:
    """Render a schedule with minute-precision times.

    The domain forbids seconds in schedule times, so the canonical form is
    ``%H:%M`` (e.g. ``07:30 on monday, wednesday``); the same string is used
    by the CLI, the GUI table, and the import preview.
    """
    if isinstance(schedule, IntervalSchedule):
        text = human_interval(schedule.seconds)
    else:
        weekdays = ", ".join(weekday.value for weekday in sorted(schedule.weekdays))
        parts = [f"{time:%H:%M}" for time in schedule.times]
        times = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + f" and {parts[-1]}"
        text = f"{times} on {weekdays}"
    if schedule.run_at_load:
        text += " + at login"
    return text


def format_truncation_marker(total_bytes: int, tail_bytes: int) -> str:
    """Render the log-tail truncation marker, identical across CLI and GUI."""
    return f"(truncated: showing the last {tail_bytes // 1024} KiB of {total_bytes} bytes)"
