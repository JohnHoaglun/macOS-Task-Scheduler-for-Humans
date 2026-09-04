"""LaunchAgent plist encoder: JobDefinition to launchd plist representation."""

from __future__ import annotations

import plistlib

from task_scheduler.domain import CalendarSchedule, JobDefinition
from task_scheduler.domain.command import command_argv
from task_scheduler.platform.macos.plist_models import WEEKDAY_TO_LAUNCHD


def _program_arguments(job: JobDefinition) -> list[str]:
    return command_argv(job.command)


def _schedule_keys(job: JobDefinition) -> dict[str, object]:
    schedule = job.schedule
    if isinstance(schedule, CalendarSchedule):
        ordered = sorted(schedule.weekdays, key=lambda weekday: WEEKDAY_TO_LAUNCHD[weekday])
        entries = [
            {
                "Weekday": WEEKDAY_TO_LAUNCHD[weekday],
                "Hour": time.hour,
                "Minute": time.minute,
            }
            for time in schedule.times
            for weekday in ordered
        ]
        keys: dict[str, object] = {"StartCalendarInterval": entries}
    else:
        keys = {"StartInterval": schedule.seconds}
    if schedule.run_at_load:
        keys["RunAtLoad"] = True
    return keys


class PlistCodec:
    """Encode a validated JobDefinition into launchd LaunchAgent plists."""

    def encode_dict(self, job: JobDefinition) -> dict[str, object]:
        """Return the launchd plist dictionary for *job*."""
        result: dict[str, object] = {
            "Label": job.label,
            "ProgramArguments": _program_arguments(job),
        }
        result.update(_schedule_keys(job))
        if job.working_directory is not None:
            result["WorkingDirectory"] = str(job.working_directory)
        if job.environment.variables:
            result["EnvironmentVariables"] = dict(job.environment.variables)
        if job.logging.stdout_path is not None:
            result["StandardOutPath"] = str(job.logging.stdout_path)
        if job.logging.stderr_path is not None:
            result["StandardErrorPath"] = str(job.logging.stderr_path)
        if not job.enabled:
            result["Disabled"] = True
        return result

    def encode_bytes(self, job: JobDefinition) -> bytes:
        """Return the XML plist encoding of *job* (human inspectable)."""
        return plistlib.dumps(self.encode_dict(job), fmt=plistlib.FMT_XML)
