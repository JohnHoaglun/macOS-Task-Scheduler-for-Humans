"""LaunchAgent plist encoder: JobDefinition to launchd plist representation.

When the codec is configured with a *run wrapper* path, ``ProgramArguments``
executes the wrapper around the job command. ``StandardOutPath`` /
``StandardErrorPath`` point at the job's own local log files
(``<job-logs>/jobs/<label>/stdout.log`` / ``stderr.log``); the wrapper writes
the START/STOP run record to the sibling ``run.log``. All job logs live under
one per-job folder on local disk, so launchd never has to open a network
(SMB/NFS) volume path, which it cannot do (the run would abort with exit 78).
"""

from __future__ import annotations

import plistlib
from pathlib import Path

from task_scheduler.domain import CalendarSchedule, IntervalSchedule, JobDefinition
from task_scheduler.domain.command import command_argv
from task_scheduler.platform.macos.plist_models import (
    WEEKDAY_TO_LAUNCHD,
    ExternalEditField,
)
from task_scheduler.platform.macos.run_wrapper import stderr_log_path, stdout_log_path


def _program_arguments(job: JobDefinition, wrapper_path: str | None = None) -> list[str]:
    argv = command_argv(job.command)
    if wrapper_path is None:
        return argv
    # The wrapper only needs the label: it writes the run record itself, and
    # launchd (via StandardOutPath/StandardErrorPath, set below) carries the
    # command's stdout/stderr to the job's own stdout.log/stderr.log.
    return [wrapper_path, "--label", job.label, "--", *argv]


def _encode_schedule(job: JobDefinition) -> dict[str, object]:
    """Encode a single schedule key from a job.

    When *job* has a calendar schedule return ``{"StartCalendarInterval": ...}``.
    When *job* has an interval schedule return ``{"StartInterval": ...}``.
    Never emit ``RunAtLoad`` here (the caller manages that key separately).
    """
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
        return {"StartCalendarInterval": entries}
    assert isinstance(schedule, IntervalSchedule)
    return {"StartInterval": schedule.seconds}


def _schedule_keys(job: JobDefinition) -> dict[str, object]:
    keys = _encode_schedule(job)
    if job.schedule.run_at_load:
        keys["RunAtLoad"] = True
    return keys


class PlistCodec:
    """Encode a validated JobDefinition into launchd LaunchAgent plists.

    With a *wrapper_path* (the deployed run wrapper), the plist runs the
    wrapper around the job command and points ``StandardOutPath`` /
    ``StandardErrorPath`` at the job's local ``stdout.log`` / ``stderr.log``
    (the wrapper records runs in the sibling ``run.log``), so launchd never
    has to open a network-volume log file. Without a wrapper the legacy
    behavior holds: the raw command and the job's configured log paths go
    into the plist.
    """

    def __init__(self, wrapper_path: str | Path | None = None) -> None:
        self._wrapper = str(wrapper_path) if wrapper_path is not None else None

    @property
    def wrapper(self) -> str | None:
        """The configured run wrapper path, or ``None`` for raw encoding."""
        return self._wrapper

    def encode_dict(self, job: JobDefinition) -> dict[str, object]:
        """Return the launchd plist dictionary for *job*."""
        result: dict[str, object] = {
            "Label": job.label,
            "ProgramArguments": _program_arguments(job, self._wrapper),
        }
        result.update(_schedule_keys(job))
        if job.working_directory is not None:
            result["WorkingDirectory"] = str(job.working_directory)
        if job.environment.variables:
            result["EnvironmentVariables"] = dict(job.environment.variables)
        if self._wrapper is not None:
            # launchd pipes the command's streams to the job's own local log
            # files; the wrapper records START/STOP in the sibling run.log.
            result["StandardOutPath"] = str(stdout_log_path(job.label))
            result["StandardErrorPath"] = str(stderr_log_path(job.label))
        else:
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


def merge_external_edit(
    original: dict[str, object],
    job: JobDefinition,
    *,
    dirty: frozenset[ExternalEditField],
    wrapper_path: str | None = None,
) -> dict[str, object]:
    """Merge *dirty* fields from *job* into a copy of *original*.

    Starts from a shallow copy of *original*. For each field in *dirty*,
    applies the job-encoded value (removes the key when the job value is
    absent/empty). Non-dirty keys and ``Label`` are never touched. When
    *wrapper_path* is given, a dirty ``ProgramArguments`` is re-encoded in
    the wrapper form.

    Returns a new dict; *original* is never mutated.
    """
    merged = dict(original)
    for field in dirty:
        if field is ExternalEditField.PROGRAM_ARGUMENTS:
            argv = _program_arguments(job, wrapper_path)
            if argv:
                merged["ProgramArguments"] = argv
            else:
                merged.pop("ProgramArguments", None)

        elif field is ExternalEditField.SCHEDULE:
            merged.pop("StartCalendarInterval", None)
            merged.pop("StartInterval", None)
            schedule_keys = _encode_schedule(job)
            merged.update(schedule_keys)

        elif field is ExternalEditField.RUN_AT_LOAD:
            if job.schedule.run_at_load:
                merged["RunAtLoad"] = True
            else:
                merged.pop("RunAtLoad", None)

        elif field is ExternalEditField.WORKING_DIRECTORY:
            if job.working_directory is not None:
                merged["WorkingDirectory"] = str(job.working_directory)
            else:
                merged.pop("WorkingDirectory", None)

        elif field is ExternalEditField.ENVIRONMENT_VARIABLES:
            if job.environment.variables:
                merged["EnvironmentVariables"] = dict(job.environment.variables)
            else:
                merged.pop("EnvironmentVariables", None)

        elif field is ExternalEditField.STDOUT_PATH:
            if job.logging.stdout_path is not None:
                merged["StandardOutPath"] = str(job.logging.stdout_path)
            else:
                merged.pop("StandardOutPath", None)

        elif field is ExternalEditField.STDERR_PATH:
            if job.logging.stderr_path is not None:
                merged["StandardErrorPath"] = str(job.logging.stderr_path)
            else:
                merged.pop("StandardErrorPath", None)

        elif field is ExternalEditField.ENABLED:
            if not job.enabled:
                merged["Disabled"] = True
            else:
                merged.pop("Disabled", None)

    return merged
