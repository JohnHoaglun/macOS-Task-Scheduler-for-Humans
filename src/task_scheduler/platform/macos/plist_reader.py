"""LaunchAgent plist reader: parse existing plists into ParsedLaunchAgent.

This is intentionally not a universal launchd parser. It understands the
behavior the Crawl domain model represents and reports everything else:
unsupported keys are surfaced, and malformed input yields an invalid
result instead of an exception.
"""

from __future__ import annotations

import plistlib
import re
from datetime import time as Time
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from task_scheduler.domain import (
    MIN_INTERVAL_SECONDS,
    SUPPORTED_SCHEMA_VERSION,
    CalendarSchedule,
    Command,
    EnvironmentConfig,
    ExecutableCommand,
    IntervalSchedule,
    JobDefinition,
    LoggingConfig,
    PythonCommand,
    Schedule,
    ShellCommand,
    Weekday,
)
from task_scheduler.platform.macos.plist_models import (
    LAUNCHD_TO_WEEKDAY,
    SUPPORTED_KEYS,
    ParsedLaunchAgent,
    ParseSupport,
)

_PYTHON_VERSION_RE = re.compile(r"^python3\.\d+$")
_SHELL_EXECUTABLES = frozenset({"/bin/sh", "/bin/bash", "/bin/zsh"})


class _FatalParse(Exception):
    """Internal: a type mismatch that prevents meaningful interpretation."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def parse_bytes(data: bytes) -> ParsedLaunchAgent:
    """Parse plist *data* without ever raising for malformed input."""
    raw, error = _decode(data)
    if raw is None:
        return ParsedLaunchAgent(
            status=ParseSupport.INVALID, raw={}, warnings=[error or "malformed plist"]
        )
    return _interpret(raw)


def parse_path(path: Path) -> ParsedLaunchAgent:
    """Parse the plist file at *path* without mutating it."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        return ParsedLaunchAgent(
            status=ParseSupport.INVALID, raw={}, warnings=[f"could not read {path}: {exc}"]
        )
    return parse_bytes(data)


def _decode(data: bytes) -> tuple[dict[str, object] | None, str | None]:
    try:
        decoded = plistlib.loads(data)
    except Exception as exc:
        return None, f"malformed plist: {exc}"
    if not isinstance(decoded, dict):
        return None, "top-level plist is not a dictionary"
    return decoded, None


def _interpret(raw: dict[str, object]) -> ParsedLaunchAgent:
    unsupported_keys = sorted(set(raw) - SUPPORTED_KEYS)
    checked = _fatal_check(raw)
    if isinstance(checked, str):
        return _invalid(raw, unsupported_keys, [checked])
    label, args = checked
    try:
        job, warnings, partial = _build_job(raw, label, args, unsupported_keys)
    except _FatalParse as exc:
        return _invalid(raw, unsupported_keys, [exc.message])
    status = ParseSupport.PARTIALLY_SUPPORTED if partial else ParseSupport.SUPPORTED
    return ParsedLaunchAgent(
        status=status,
        job=job,
        raw=raw,
        unsupported_keys=unsupported_keys,
        warnings=warnings,
    )


def _invalid(
    raw: dict[str, object], unsupported_keys: list[str], warnings: list[str]
) -> ParsedLaunchAgent:
    return ParsedLaunchAgent(
        status=ParseSupport.INVALID,
        raw=raw,
        unsupported_keys=unsupported_keys,
        warnings=warnings,
    )


def _fatal_check(raw: dict[str, object]) -> str | tuple[str, list[str]]:
    """Return (label, program arguments) when usable, else a fatal message."""
    label = raw.get("Label")
    if not isinstance(label, str) or not label:
        return "missing or invalid Label"
    args = raw.get("ProgramArguments")
    if not isinstance(args, list) or not args or not all(
        isinstance(arg, str) and arg for arg in args
    ):
        return "unusable ProgramArguments"
    return label, args


def _build_job(
    raw: dict[str, object],
    label: str,
    args: list[str],
    unsupported_keys: list[str],
) -> tuple[JobDefinition | None, list[str], bool]:
    """Build a JobDefinition from *raw* where possible.

    Returns (job, warnings, partial). ``job`` is None whenever any part of
    the configuration cannot be represented without inventing or losing
    data; the raw dictionary in the result always retains everything.
    """
    warnings: list[str] = []
    partial = bool(unsupported_keys)

    command = _classify_command(args, warnings)
    schedule = _parse_schedule(raw, warnings)
    if command is None or schedule is None:
        return None, warnings, True

    working_directory = _parse_working_directory(raw, warnings)
    environment = _parse_environment(raw)
    stdout_path = _parse_log_path(raw, "StandardOutPath", warnings)
    stderr_path = _parse_log_path(raw, "StandardErrorPath", warnings)
    enabled = _parse_disabled(raw)

    unrepresentable_value = (
        "WorkingDirectory" in raw and working_directory is None
    ) or ("StandardOutPath" in raw and stdout_path is None) or (
        "StandardErrorPath" in raw and stderr_path is None
    )
    if unrepresentable_value:
        return None, warnings, True

    try:
        job = JobDefinition(
            schema_version=SUPPORTED_SCHEMA_VERSION,
            id=uuid4(),
            name=label,
            label=label,
            enabled=enabled,
            command=command,
            schedule=schedule,
            environment=environment,
            working_directory=working_directory,
            logging=LoggingConfig(stdout_path=stdout_path, stderr_path=stderr_path),
        )
    except ValidationError:
        warnings.append("field values not representable in the domain model")
        return None, warnings, True
    return job, warnings, partial


def _classify_command(args: list[str], warnings: list[str]) -> Command | None:
    head = args[0]
    if _is_python(head):
        if len(args) >= 2 and Path(args[1]).is_absolute():
            return PythonCommand(
                interpreter=Path(head), script=Path(args[1]), arguments=args[2:]
            )
        warnings.append("python command without a usable absolute script path")
        return None
    if head in _SHELL_EXECUTABLES:
        return ShellCommand(executable=Path(head), arguments=args[1:])
    if Path(head).is_absolute():
        return ExecutableCommand(executable=Path(head), arguments=args[1:])
    warnings.append(f"program path is not absolute: {head!r}")
    return None


def _is_python(head: str) -> bool:
    path = Path(head)
    if not path.is_absolute():
        return False
    return path.name in ("python", "python3") or _PYTHON_VERSION_RE.fullmatch(path.name) is not None


def _parse_schedule(raw: dict[str, object], warnings: list[str]) -> Schedule | None:
    calendar = raw.get("StartCalendarInterval")
    interval = raw.get("StartInterval")
    run_at_load = _parse_run_at_load(raw)
    if calendar is not None and interval is not None:
        warnings.append(
            "schedule has both StartCalendarInterval and StartInterval; "
            "the conflict cannot be represented"
        )
        return None
    if calendar is not None:
        return _parse_calendar(calendar, warnings, run_at_load)
    if interval is not None:
        return _parse_interval(interval, warnings, run_at_load)
    if run_at_load:
        warnings.append("RunAtLoad is set but no StartCalendarInterval or StartInterval schedule")
    else:
        warnings.append("no schedule found")
    return None


def _parse_run_at_load(raw: dict[str, object]) -> bool:
    value = raw.get("RunAtLoad")
    if value is None:
        return False
    if not isinstance(value, bool):
        raise _FatalParse("RunAtLoad must be a boolean")
    return value


def _parse_calendar(
    value: object, warnings: list[str], run_at_load: bool
) -> Schedule | None:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(entry, dict) for entry in value)
    ):
        raise _FatalParse("StartCalendarInterval must be a non-empty list of dictionaries")

    times: set[tuple[int, int]] = set()
    weekdays: set[Weekday] = set()
    for entry in value:
        hour = _entry_int(entry, "Hour")
        minute = _entry_int(entry, "Minute")
        if not 0 <= hour <= 23:
            raise _FatalParse(f"malformed calendar schedule: Hour out of range: {hour}")
        if not 0 <= minute <= 59:
            raise _FatalParse(f"malformed calendar schedule: Minute out of range: {minute}")
        weekday = _entry_int(entry, "Weekday")
        if weekday not in LAUNCHD_TO_WEEKDAY:
            raise _FatalParse(f"malformed calendar schedule: invalid Weekday: {weekday}")
        weekdays.add(LAUNCHD_TO_WEEKDAY[weekday])
        times.add((hour, minute))
    return CalendarSchedule(
        times=[Time(hour, minute) for hour, minute in sorted(times)],
        weekdays=weekdays,
        run_at_load=run_at_load,
    )


def _parse_interval(value: object, warnings: list[str], run_at_load: bool) -> Schedule | None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _FatalParse("StartInterval must be an integer")
    if value < MIN_INTERVAL_SECONDS:
        warnings.append(
            f"StartInterval of {value} is below the {MIN_INTERVAL_SECONDS}-second domain minimum"
        )
        return None
    return IntervalSchedule(seconds=value, run_at_load=run_at_load)


def _entry_int(entry: dict[object, object], key: str) -> int:
    value = entry.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise _FatalParse(f"malformed calendar schedule: {key} must be an integer")
    return value


def _parse_working_directory(raw: dict[str, object], warnings: list[str]) -> Path | None:
    value = raw.get("WorkingDirectory")
    if value is None:
        return None
    if not isinstance(value, str):
        raise _FatalParse("WorkingDirectory must be a string")
    path = Path(value)
    if not path.is_absolute():
        warnings.append(f"WorkingDirectory is not absolute: {value!r}")
        return None
    return path


def _parse_environment(raw: dict[str, object]) -> EnvironmentConfig:
    value = raw.get("EnvironmentVariables")
    if value is None:
        return EnvironmentConfig()
    if not isinstance(value, dict):
        raise _FatalParse("EnvironmentVariables must be a string-to-string mapping")
    variables: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise _FatalParse("EnvironmentVariables must be a string-to-string mapping")
        variables[key] = item
    return EnvironmentConfig(variables=variables)


def _parse_log_path(raw: dict[str, object], key: str, warnings: list[str]) -> Path | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _FatalParse(f"{key} must be a string")
    path = Path(value)
    if not path.is_absolute():
        warnings.append(f"{key} is not absolute: {value!r}")
        return None
    return path


def _parse_disabled(raw: dict[str, object]) -> bool:
    value = raw.get("Disabled")
    if value is None:
        return True
    if not isinstance(value, bool):
        raise _FatalParse("Disabled must be a boolean")
    return not value
