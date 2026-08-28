"""Managed job catalog: persisted source of truth for application jobs.

The catalog stores one schema-versioned JSON file per managed job under
``~/Library/Application Support/macOS Task Scheduler for Humans/jobs`` (or an
injected root). The launchd plist is a derived deployment artifact, never
the application database (spec lines 1307-1326).
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from task_scheduler.domain import JobDefinition
from task_scheduler.storage import JsonJobRepository

__all__ = [
    "JobConflictError",
    "JobNotFoundError",
    "JobService",
    "default_job_catalog_root",
]


def default_job_catalog_root() -> Path:
    """Return the default managed-job catalog directory for this user."""
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "macOS Task Scheduler for Humans"
        / "jobs"
    )


class JobNotFoundError(Exception):
    """Raised when no managed job matches the requested label."""

    def __init__(self, label: str) -> None:
        self.label = label
        super().__init__(f"no managed job with label {label!r}")


class JobConflictError(Exception):
    """Raised when importing a job whose id is already managed."""

    def __init__(self, label: str, path: Path) -> None:
        self.label = label
        self.path = path
        super().__init__(f"a managed job already exists for label {label!r} ({path})")


class JobService:
    """Catalog of managed jobs, keyed by job id and resolved by label."""

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        repository: JsonJobRepository | None = None,
    ) -> None:
        self._root = Path(root) if root is not None else default_job_catalog_root()
        self._repository = repository if repository is not None else JsonJobRepository()

    @property
    def root(self) -> Path:
        """The catalog directory this service reads and writes (and only it)."""
        return self._root

    def list_jobs(self) -> list[JobDefinition]:
        """Return every managed job, sorted by label.

        A missing root yields an empty list. Only direct-child ``*.json``
        files are considered.
        """
        if not self._root.is_dir():
            return []
        jobs = [
            self._repository.load(path)
            for path in self._root.iterdir()
            if path.name.endswith(".json") and path.is_file()
        ]
        return sorted(jobs, key=lambda job: job.label)

    def find(self, label: str) -> JobDefinition | None:
        """Return the managed job for ``label``, or ``None`` when absent."""
        for job in self.list_jobs():
            if job.label == label:
                return job
        return None

    def resolve(self, label: str) -> JobDefinition:
        """Return the managed job for ``label``; raise :class:`JobNotFoundError`."""
        job = self.find(label)
        if job is None:
            raise JobNotFoundError(label)
        return job

    def import_job(self, job: JobDefinition) -> Path:
        """Persist ``job`` into the catalog; create-only, never overwrite."""
        path = self._path_for(job.id)
        if path.exists():
            raise JobConflictError(label=job.label, path=path)
        self._repository.save(job, path, create_parent=True)
        return path

    def remove(self, job_id: UUID) -> bool:
        """Remove the catalog record for ``job_id``.

        Idempotent: returns ``True`` when a record was removed and ``False``
        when nothing was present.
        """
        path = self._path_for(job_id)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True

    def _path_for(self, job_id: UUID) -> Path:
        return self._root / f"{job_id}.json"
