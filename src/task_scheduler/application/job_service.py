"""Managed job catalog: persisted source of truth for application jobs.

The catalog stores one schema-versioned JSON file per managed job under
``~/Library/Application Support/macOS Task Scheduler for Humans/jobs`` (or an
injected root). The launchd plist is a derived deployment artifact, never
the application database (spec lines 1307-1326).
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
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
from task_scheduler.storage.json_repository import JsonJobRepository

__all__ = [
    "MANAGED_LABEL_PREFIX",
    "CatalogDiagnostic",
    "JobConflictError",
    "JobNotFoundError",
    "JobService",
    "default_job_catalog_root",
    "default_job_logs_root",
    "derive_log_paths",
    "managed_label",
]


def default_job_catalog_root() -> Path:
    """Return the default managed-job catalog directory for this user."""
    return (
        Path.home() / "Library" / "Application Support" / "macOS Task Scheduler for Humans" / "jobs"
    )


MANAGED_LABEL_PREFIX = "io.github.macos-task-scheduler.user."


def default_job_logs_root() -> Path:
    """Return the default per-user directory for job stdout/stderr logs."""
    return Path.home() / "Library" / "Logs" / "macOS Task Scheduler for Humans"


def derive_log_paths(name: str, log_directory: str) -> tuple[str, str]:
    """Derive the ``(stdout_path, stderr_path)`` pair for *name* in *log_directory*.

    Filenames are ``<name>.stdout.log`` / ``<name>.stderr.log`` (a blank name
    falls back to ``task``). A blank directory disables both streams and
    returns two empty strings.
    """
    directory = log_directory.strip()
    if not directory:
        return ("", "")
    task = name.strip() or "task"
    base = Path(directory)
    return (str(base / f"{task}.stdout.log"), str(base / f"{task}.stderr.log"))


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


@dataclass(frozen=True, slots=True)
class CatalogDiagnostic:
    """A catalog file that failed to load during a scan, with a short reason."""

    path: Path
    message: str


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
        files are considered; a file that fails to load is skipped and
        reported by :meth:`catalog_diagnostics`.
        """
        return self._scan()[0]

    def catalog_diagnostics(self) -> list[CatalogDiagnostic]:
        """Return the catalog files that failed to load, from a fresh scan.

        Each call re-scans the catalog (no caching). A missing root and a
        fully valid catalog both yield an empty list.
        """
        return self._scan()[1]

    def _scan(self) -> tuple[list[JobDefinition], list[CatalogDiagnostic]]:
        """Scan the catalog root; files that fail to load become diagnostics."""
        if not self._root.is_dir():
            return [], []
        jobs: list[JobDefinition] = []
        diagnostics: list[CatalogDiagnostic] = []
        for path in self._root.iterdir():
            if not path.name.endswith(".json") or not path.is_file():
                continue
            try:
                jobs.append(self._repository.load(path))
            except (OSError, ValueError) as exc:
                diagnostics.append(
                    CatalogDiagnostic(path=path, message=f"{type(exc).__name__}: {exc}")
                )
        diagnostics.sort(key=lambda diagnostic: diagnostic.path)
        return sorted(jobs, key=lambda job: job.label), diagnostics

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

    def transfer_conflicts(self, job: JobDefinition) -> tuple[Path | None, Path | None]:
        """Report import conflicts for ``job`` without writing.

        Returns ``(id_conflict_path, label_conflict_path)``. ``id_conflict_path``
        is the catalog file that already holds ``job.id`` (when it exists);
        ``label_conflict_path`` is the file of a different managed job that
        already claims ``job.label`` (when present). Either may be ``None``.
        """
        owner = self.find(job.label)
        label_conflict = (
            self._path_for(owner.id) if owner is not None and owner.id != job.id else None
        )
        id_path = self._path_for(job.id)
        id_conflict = id_path if id_path.exists() else None
        return id_conflict, label_conflict

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
        stdout_path, stderr_path = derive_log_paths(name, str(default_job_logs_root()))
        return JobDefinition(
            schema_version=SUPPORTED_SCHEMA_VERSION,
            id=id,
            name=name,
            label=managed_label(name, id),
            enabled=True,
            command=command,
            schedule=schedule,
            environment=EnvironmentConfig(),
            working_directory=command.script.parent if isinstance(command, PythonCommand) else None,
            logging=LoggingConfig(
                stdout_path=Path(stdout_path),
                stderr_path=Path(stderr_path),
            ),
        )

    def import_job(self, job: JobDefinition) -> Path:
        """Persist ``job`` into the catalog; create-only, never overwrite.

        Raises :class:`JobConflictError` when the job id is already managed
        (the destination file exists) or when a different managed job already
        claims ``job.label``.
        """
        with self._catalog_lock():
            owner = self.find(job.label)
            if owner is not None and owner.id != job.id:
                raise JobConflictError(label=job.label, path=self._path_for(owner.id))
            path = self._path_for(job.id)
            try:
                self._repository.save_new(job, path, create_parent=True)
            except FileExistsError as exc:
                raise JobConflictError(label=job.label, path=path) from exc
        return path

    def save(self, job: JobDefinition) -> Path:
        """Persist ``job`` into the catalog, overwriting its own record.

        Overwriting the same immutable id is the normal update path. A
        different managed job already claiming ``job.label`` raises
        :class:`JobConflictError`.
        """
        with self._catalog_lock():
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

    @contextlib.contextmanager
    def _catalog_lock(self) -> Iterator[None]:
        """Serialize catalog create-only imports on this catalog root."""
        self._root.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._root / ".catalog.lock", os.O_CREAT | os.O_RDWR, 0o600)
        locked = False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            locked = True
            yield
        finally:
            if locked:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
