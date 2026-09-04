"""JSON persistence for managed job definitions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from task_scheduler.domain import SUPPORTED_SCHEMA_VERSION, JobDefinition


def _migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """Rewrite a v1 payload into the v2 shape (calendar variant)."""
    schedule = data.get("schedule")
    if isinstance(schedule, dict) and "time" in schedule:
        data["schedule"] = {
            "kind": "calendar",
            "times": [schedule["time"]],
            "weekdays": schedule.get("weekdays", []),
            "run_at_load": False,
        }
    data["schema_version"] = SUPPORTED_SCHEMA_VERSION
    return data


def _migrate_if_v1(text: str) -> dict[str, Any] | None:
    """Return a v2-ready dict when *text* is a v1 payload, else None."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        return None
    return _migrate_v1_to_v2(data)


class JsonJobRepository:
    """Read and write schema-versioned, human-readable job JSON files."""

    def load(self, path: Path) -> JobDefinition:
        """Load and validate a job definition from *path*, migrating v1 files."""
        text = path.read_text(encoding="utf-8")
        migrated = _migrate_if_v1(text)
        if migrated is not None:
            return JobDefinition.model_validate(migrated)
        return JobDefinition.model_validate_json(text)

    def save(self, job: JobDefinition, path: Path, create_parent: bool = False) -> None:
        """Write *job* as pretty-printed UTF-8 JSON to *path*."""
        if create_parent:
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._render(job) + "\n", encoding="utf-8")

    @staticmethod
    def _render(job: JobDefinition) -> str:
        return job.model_dump_json(indent=2, exclude_none=True)
