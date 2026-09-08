"""Managed-JSON transfer: strict, identity-preserving catalog transfer.

Distinct from increment 21's external-plist import (which regenerates the
UUID), managed-JSON transfer round-trips a job to/from a JSON file while
preserving the immutable UUID and label. The transfer is a closed schema:
unknown fields at any accepted level are rejected before any write, and legacy
v1 payloads are normalized to canonical v2. Export and import are catalog-only
— nothing is deployed (spec §63).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from task_scheduler.domain import SUPPORTED_SCHEMA_VERSION, JobDefinition
from task_scheduler.storage.json_repository import JsonJobRepository

__all__ = [
    "ManagedJsonImportPreview",
    "StrictJsonDecodeError",
    "strict_decode_job_json",
]


class StrictJsonDecodeError(ValueError):
    """Raised when strict managed-JSON transfer decoding rejects a payload."""


_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "id",
        "name",
        "label",
        "enabled",
        "command",
        "schedule",
        "environment",
        "working_directory",
        "logging",
    }
)
_COMMAND_FIELDS_BY_TYPE = {
    "python": frozenset({"type", "interpreter", "script", "arguments"}),
    "shell": frozenset({"type", "executable", "arguments"}),
    "executable": frozenset({"type", "executable", "arguments"}),
}
_SCHEDULE_FIELDS_V2_BY_KIND = {
    "calendar": frozenset({"kind", "times", "weekdays", "run_at_load"}),
    "interval": frozenset({"kind", "seconds", "run_at_load"}),
}
_SCHEDULE_FIELDS_V1 = frozenset({"time", "weekdays"})
_ENVIRONMENT_FIELDS = frozenset({"variables"})
_LOGGING_FIELDS = frozenset({"stdout_path", "stderr_path"})


@dataclass(frozen=True, slots=True)
class ManagedJsonImportPreview:
    """Read-only preview of importing a managed JSON file (identity-preserving).

    ``candidate`` is the canonical v2 job with its immutable UUID preserved.
    ``id_conflict_path`` is the catalog file that already holds the candidate's
    UUID (when present); ``label_conflict_path`` is the file of a different
    managed job that already claims the candidate's label (when present).
    ``can_import`` is True only when both conflict paths are ``None``.
    """

    source_path: Path
    candidate: JobDefinition
    normalized_schema_version: int
    id_conflict_path: Path | None
    label_conflict_path: Path | None
    can_import: bool


def strict_decode_job_json(text: str) -> JobDefinition:
    """Strictly decode managed-job JSON *text* into a canonical v2 job.

    Rejects malformed JSON, a non-object top level, any unknown field at an
    accepted level, and any schema version other than 1 or the supported
    version. Legacy v1 payloads are migrated to v2. Raises
    :class:`StrictJsonDecodeError` (a ``ValueError``) on any problem.
    """
    data = _parse_object(text)
    _reject_unknown(data, _TOP_LEVEL_FIELDS, "top level")
    _check_command(data)
    _check_environment(data)
    _check_logging(data)
    version = data.get("schema_version")
    if version == 1:
        _check_schedule_v1(data)
    elif version == SUPPORTED_SCHEMA_VERSION:
        _check_schedule_v2(data)
    else:
        raise StrictJsonDecodeError(
            f"unsupported schema version {version!r}; managed-JSON transfer "
            f"accepts versions 1 and {SUPPORTED_SCHEMA_VERSION}"
        )
    try:
        return JsonJobRepository().load_text(text)
    except ValidationError as exc:
        raise StrictJsonDecodeError(_format_validation_error(exc)) from None


def _parse_object(text: str) -> dict[str, Any]:
    """Parse *text* as a JSON object or raise :class:`StrictJsonDecodeError`."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StrictJsonDecodeError(
            f"malformed JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})"
        ) from None
    if not isinstance(data, dict):
        raise StrictJsonDecodeError("top-level JSON value must be an object")
    return data


def _reject_unknown(
    mapping: dict[str, Any], allowed: frozenset[str], where: str
) -> None:
    """Raise when *mapping* contains any key outside *allowed*."""
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise StrictJsonDecodeError(
            f"unknown field(s) in {where}: {', '.join(unknown)}"
        )


def _check_command(data: dict[str, Any]) -> None:
    command = data.get("command")
    if not isinstance(command, dict):
        return
    command_type = command.get("type")
    allowed = (
        _COMMAND_FIELDS_BY_TYPE.get(command_type)
        if isinstance(command_type, str)
        else None
    )
    if allowed is not None:
        _reject_unknown(command, allowed, f"command (type={command_type!r})")


def _check_environment(data: dict[str, Any]) -> None:
    environment = data.get("environment")
    if isinstance(environment, dict):
        _reject_unknown(environment, _ENVIRONMENT_FIELDS, "environment")


def _check_logging(data: dict[str, Any]) -> None:
    logging = data.get("logging")
    if isinstance(logging, dict):
        _reject_unknown(logging, _LOGGING_FIELDS, "logging")


def _check_schedule_v1(data: dict[str, Any]) -> None:
    schedule = data.get("schedule")
    if isinstance(schedule, dict):
        _reject_unknown(schedule, _SCHEDULE_FIELDS_V1, "schedule")


def _check_schedule_v2(data: dict[str, Any]) -> None:
    schedule = data.get("schedule")
    if isinstance(schedule, dict):
        kind = schedule.get("kind")
        allowed = (
            _SCHEDULE_FIELDS_V2_BY_KIND.get(kind)
            if isinstance(kind, str)
            else None
        )
        if allowed is not None:
            _reject_unknown(schedule, allowed, f"schedule (kind={kind!r})")


def _format_validation_error(exc: ValidationError) -> str:
    problems: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        message = str(error["msg"])
        if message.startswith("Value error, "):
            message = message[len("Value error, "):]
        problems.append(f"{location}: {message}")
    return "invalid job definition: " + "; ".join(problems)
