"""Managed job catalog: persisted source of truth for application jobs.

The catalog stores one schema-versioned JSON file per managed job under
``~/Library/Application Support/macOS Task Scheduler for Humans/jobs`` (or an
injected root). The launchd plist is a derived deployment artifact, never
the application database (spec lines 1307-1326).
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID, uuid4

from task_scheduler.domain import (
    SUPPORTED_SCHEMA_VERSION,
    Command,
    EnvironmentConfig,
    JobDefinition,
    LoggingConfig,
    PythonCommand,
    Schedule,
)
from task_scheduler.storage import JsonJobRepository

__all__ = [
    "MANAGED_LABEL_PREFIX",
    "JobConflictError",
    "JobNotFoundError",
    "JobService",
    "default_job_catalog_root",
    "default_job_logs_root",
    "managed_label",
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


MANAGED_LABEL_PREFIX = "io.github.macos-task-scheduler.user."


def default_job_logs_root() -> Path:
    """Return the default per-user directory for job stdout/stderr logs."""
    return Path.home() / "Library" / "Logs" / "macOS Task Scheduler for Humans"


def managed_label(name: str, job_id: UUID) -> str:
    """Return the launchd label for the managed job *name* identified by *job_id*."""
    return f"{MANAGED_LABEL_PREFIX}{_slug(name)}-{job_id.hex[:8]}"


def _slug(name: str) -> str:
    """Return a lowercase hyphen-separated identifier derived from *name*."""
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "task"


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

    def new_managed_job(
        self,
        name: str,
        command: Command,
        schedule: Schedule,
        *,
        job_id: UUID | None = None,
    ) -> JobDefinition:
        """Build the :class:`JobDefinition` for a new managed job; nothing is persisted.

        The caller persists the result through :meth:`save`; no files or
        directories are created here.
        """
        id = job_id if job_id is not None else uuid4()
        return JobDefinition(
            schema_version=SUPPORTED_SCHEMA_VERSION,
            id=id,
            name=name,
            label=managed_label(name, id),
            enabled=True,
            command=command,
            schedule=schedule,
            environment=EnvironmentConfig(),
            working_directory=command.script.parent
            if isinstance(command, PythonCommand)
            else None,
            logging=LoggingConfig(
                stdout_path=default_job_logs_root() / id.hex / "stdout.log",
                stderr_path=default_job_logs_root() / id.hex / "stderr.log",
            ),
        )

    def import_job(self, job: JobDefinition) -> Path:
        """Persist ``job`` into the catalog; create-only, never overwrite."""
        path = self._path_for(job.id)
        if path.exists():
            raise JobConflictError(label=job.label, path=path)
        self._repository.save(job, path, create_parent=True)
        return path

    def save(self, job: JobDefinition) -> Path:
        """Persist ``job`` into the catalog, overwriting its own record.

        Overwriting the same immutable id is the normal update path. A
        different managed job already claiming ``job.label`` raises
        :class:`JobConflictError`.
        """
        owner = self.find(job.label)
        if owner is not None and owner.id != job.id:
            raise JobConflictError(label=job.label, path=self._path_for(owner.id))
        path = self._path_for(job.id)
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
