"""LaunchAgent plist encoder: JobDefinition to launchd plist representation."""

from __future__ import annotations

import plistlib

from task_scheduler.domain import JobDefinition, PythonCommand
from task_scheduler.platform.macos.plist_models import WEEKDAY_TO_LAUNCHD


def _program_arguments(job: JobDefinition) -> list[str]:
    command = job.command
    if isinstance(command, PythonCommand):
        return [str(command.interpreter), str(command.script), *command.arguments]
    return [str(command.executable), *command.arguments]


def _calendar_interval(job: JobDefinition) -> list[dict[str, int]]:
    schedule = job.schedule
    ordered = sorted(schedule.weekdays, key=lambda weekday: WEEKDAY_TO_LAUNCHD[weekday])
    return [
        {
            "Weekday": WEEKDAY_TO_LAUNCHD[weekday],
            "Hour": schedule.time.hour,
            "Minute": schedule.time.minute,
        }
        for weekday in ordered
    ]


class PlistCodec:
    """Encode a validated JobDefinition into launchd LaunchAgent plists."""

    def encode_dict(self, job: JobDefinition) -> dict[str, object]:
        """Return the launchd plist dictionary for *job*."""
        result: dict[str, object] = {
            "Label": job.label,
            "ProgramArguments": _program_arguments(job),
            "StartCalendarInterval": _calendar_interval(job),
        }
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
