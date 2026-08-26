"""JSON persistence for managed job definitions."""

from __future__ import annotations

from pathlib import Path

from task_scheduler.domain import JobDefinition


class JsonJobRepository:
    """Read and write schema-versioned, human-readable job JSON files."""

    def load(self, path: Path) -> JobDefinition:
        """Load and validate a job definition from *path*."""
        text = path.read_text(encoding="utf-8")
        return JobDefinition.model_validate_json(text)

    def save(self, job: JobDefinition, path: Path, create_parent: bool = False) -> None:
        """Write *job* as pretty-printed UTF-8 JSON to *path*."""
        if create_parent:
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._render(job) + "\n", encoding="utf-8")

    @staticmethod
    def _render(job: JobDefinition) -> str:
        return job.model_dump_json(indent=2, exclude_none=True)
