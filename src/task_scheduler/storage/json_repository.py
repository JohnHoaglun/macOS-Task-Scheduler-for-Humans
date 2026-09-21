"""JSON persistence for managed job definitions."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
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
        return self.load_text(path.read_text(encoding="utf-8"))

    def load_text(self, text: str) -> JobDefinition:
        """Parse and validate job JSON *text*, migrating v1 payloads to v2."""
        migrated = _migrate_if_v1(text)
        if migrated is not None:
            return JobDefinition.model_validate(migrated)
        return JobDefinition.model_validate_json(text)

    def save(self, job: JobDefinition, path: Path, create_parent: bool = False) -> None:
        """Durably replace *path* with *job* atomically."""
        self._write(job, path, create_parent, exclusive=False)

    def save_new(self, job: JobDefinition, path: Path, create_parent: bool = False) -> None:
        """Durably create *path* for *job*, raising ``FileExistsError`` if it exists."""
        self._write(job, path, create_parent, exclusive=True)

    def _write(
        self,
        job: JobDefinition,
        path: Path,
        create_parent: bool,
        *,
        exclusive: bool,
    ) -> None:
        if create_parent:
            path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write((self._render(job) + "\n").encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            if exclusive:
                os.link(tmp, path)
            else:
                os.replace(tmp, path)
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()

    @staticmethod
    def _render(job: JobDefinition) -> str:
        return job.model_dump_json(indent=2, exclude_none=True)
