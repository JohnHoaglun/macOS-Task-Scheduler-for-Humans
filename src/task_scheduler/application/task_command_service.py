"""TaskCommandService: the shared application facade for CLI (and GUI).

Every ``mactask`` command maps to exactly one method here; the Typer CLI
and the future PySide6 GUI both call this service rather than the platform
adapters (spec lines 230-248, 1089, 2542-2550). The facade owns
orchestration (catalog + storage + launchctl + direct testing + logs) and
returns structured results, never presentation text.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from task_scheduler.application.job_service import JobService
from task_scheduler.application.log_service import JobLogs, LogService
from task_scheduler.application.test_service import DirectTestResult, DirectTestService
from task_scheduler.domain import Command, JobDefinition, PythonCommand, Schedule
from task_scheduler.platform.macos import (
    EnvironmentDifference,
    LaunchAgentBackend,
    LaunchAgentStatus,
    LaunchAgentStore,
    LaunchctlResult,
    ParsedLaunchAgent,
    PlistCodec,
    ProcessResult,
    PythonDetectionResult,
    compare_environments,
    parse_path,
    validate_label,
)
from task_scheduler.platform.macos import (
    detect_python as platform_detect_python,
)
from task_scheduler.storage import JsonJobRepository

__all__ = [
    "DiscoveredInspectReport",
    "InspectReport",
    "InstallPhase",
    "InstallResult",
    "ListingKind",
    "TaskCommandService",
    "TaskListing",
    "UninstallResult",
]


class ListingKind(StrEnum):
    """Where a listed task lives: a deployed plist or the catalog only."""

    SAVED = "saved"
    DISCOVERED = "discovered"


@dataclass(frozen=True, slots=True)
class TaskListing:
    """One task row: a discovered LaunchAgent or a catalog-only saved job.

    Discovered rows carry the plist path and its parse. Saved rows have no
    deployed plist (path/parsed are ``None``) and expose only the canonical
    managed job from the catalog.
    """

    kind: ListingKind
    path: Path | None
    parsed: ParsedLaunchAgent | None
    job: JobDefinition | None
    managed: bool


@dataclass(frozen=True, slots=True)
class DiscoveredInspectReport:
    """A discovered LaunchAgent: its plist parse, managed flag, launchd status."""

    path: Path
    parsed: ParsedLaunchAgent
    managed: bool
    status: LaunchAgentStatus | None


@dataclass(frozen=True, slots=True)
class InspectReport:
    """A managed job: its definition, its plist parse, its launchd status."""

    job: JobDefinition
    plist_path: Path
    plist: ParsedLaunchAgent
    status: LaunchAgentStatus


@dataclass(frozen=True, slots=True)
class InstallPhase:
    """The outcome of one launchctl phase of an install/reinstall transaction."""

    name: str
    process: ProcessResult


@dataclass(frozen=True, slots=True)
class InstallResult:
    """Outcome of an install or reinstall transaction.

    ``process`` is the primary (final) result. ``phases`` records every
    launchctl phase attempted, in order; ``completed_phases`` marks the
    phases that finished successfully; ``retained_artifacts`` lists staged
    or backup plists kept for diagnosis when a later phase fails — the
    transaction never claims a rollback.
    """

    job: JobDefinition
    plist_path: Path
    process: ProcessResult
    phases: tuple[InstallPhase, ...] = ()
    completed_phases: tuple[str, ...] = ()
    retained_artifacts: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class UninstallResult:
    """Outcome of uninstalling a job by label."""

    label: str
    process: ProcessResult
    catalog_removed: bool


class TaskCommandService:
    """Application facade backing every CLI/GUI task command."""

    def __init__(
        self,
        *,
        repository: JsonJobRepository,
        jobs: JobService,
        store: LaunchAgentStore,
        backend: LaunchAgentBackend,
        codec: PlistCodec,
        test: DirectTestService,
        logs: LogService,
    ) -> None:
        self._repository = repository
        self._jobs = jobs
        self._store = store
        self._backend = backend
        self._codec = codec
        self._test = test
        self._logs = logs

    # -- discovery ---------------------------------------------------------

    def list_agents(self) -> list[TaskListing]:
        """List user LaunchAgents plus catalog-only saved jobs, in that order.

        Discovered rows keep discovery order; saved rows (catalog jobs with
        no deployed plist) follow, sorted by label. Managed rows carry the
        canonical catalog job.
        """
        catalog = {job.label: job for job in self._jobs.list_jobs()}
        listings: list[TaskListing] = []
        discovered_labels: set[str] = set()
        for agent in self._store.discover():
            parsed = agent.parsed
            parsed_job = parsed.job
            label = parsed_job.label if parsed_job is not None else None
            if label is not None:
                discovered_labels.add(label)
            job = catalog.get(label) if label is not None and label in catalog else None
            listings.append(
                TaskListing(
                    kind=ListingKind.DISCOVERED,
                    path=agent.path,
                    parsed=parsed,
                    job=job,
                    managed=job is not None,
                )
            )
        for job in sorted(catalog.values(), key=lambda job: job.label):
            if job.label not in discovered_labels:
                listings.append(
                    TaskListing(
                        kind=ListingKind.SAVED,
                        path=None,
                        parsed=None,
                        job=job,
                        managed=True,
                    )
                )
        return listings

    def inspect(self, label: str) -> InspectReport:
        """Return the managed job's definition, plist parse, and launchd status."""
        job = self._jobs.resolve(label)
        plist_path = self._store.destination_for(label)
        return InspectReport(
            job=job,
            plist_path=plist_path,
            plist=parse_path(plist_path),
            status=self._backend.status(label),
        )

    def inspect_discovered(self, path: Path) -> DiscoveredInspectReport:
        """Inspect a discovered plist (read-only, any parse status).

        Raises ValueError when *path* is outside the store root.
        """
        root = self._store.root
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"path is outside the LaunchAgent root: {path}")
        parsed = parse_path(path)
        job = parsed.job
        managed = False
        status = None
        if job is not None:
            managed = self._jobs.find(job.label) is not None
            status = self._backend.status(job.label)
        return DiscoveredInspectReport(
            path=path, parsed=parsed, managed=managed, status=status
        )

    # -- JSON file commands --------------------------------------------------

    def validate_json(self, path: Path) -> JobDefinition:
        """Load and validate a job JSON file; raise on any problem."""
        return self._repository.load(path)

    def generate_plist(self, path: Path) -> str:
        """Load, validate, and return the XML plist text for a job file."""
        job = self._repository.load(path)
        return self._codec.encode_bytes(job).decode("utf-8")

    def install_json(self, path: Path) -> InstallResult:
        """Install a job from a JSON file (validated, then installed)."""
        return self.install(self._repository.load(path))

    def install(self, job: JobDefinition) -> InstallResult:
        """Install a job: import it into the catalog, write the plist, bootstrap.

        The import is skipped when this same job id is already saved in the
        catalog (installing a saved, not-installed job). ``FileExistsError``
        when the plist already exists — an installed job is re-applied with
        ``reinstall`` instead. A failed bootstrap retains the catalog record
        and the plist for diagnosis — no rollback is claimed.
        """
        job = self.validate_job(job)
        existing = self._jobs.find(job.label)
        if existing is None or existing.id != job.id:
            self._jobs.import_job(job)
        result = self._backend.install(job)
        return self._install_result(
            job,
            result.process,
            [InstallPhase("bootstrap", result.process)],
            ["bootstrap"] if result.process.exit_code == 0 else [],
            [],
        )

    def reinstall(self, label: str) -> InstallResult:
        """Reinstall the managed job for *label*.

        Transaction: stage the freshly generated plist as a unique sibling,
        boot the label out, preserve the deployed plist as a unique backup
        sibling, activate the staged plist, bootstrap. On a failed bootout
        the staged sibling is retained; on a failed bootstrap the backup
        sibling is retained. A successful reinstall removes the backup and
        retains nothing. The primary result is always the last phase's.
        """
        job = self._jobs.resolve(label)
        phases: list[InstallPhase] = []
        completed: list[str] = []
        retained: list[Path] = []

        staged = self._store.stage_plist(label, self._codec.encode_bytes(job))
        retained.append(staged)

        bootout = self._backend.bootout(label)
        phases.append(InstallPhase("bootout", bootout.process))
        if bootout.process.exit_code != 0:
            return self._install_result(
                job, bootout.process, phases, completed, retained
            )
        completed.append("bootout")

        backup = self._store.backup_plist(label)
        if backup is not None:
            retained.append(backup)
        self._store.activate_staged(label, staged)
        retained.remove(staged)

        bootstrap = self._backend.bootstrap(label)
        phases.append(InstallPhase("bootstrap", bootstrap.process))
        if bootstrap.process.exit_code != 0:
            return self._install_result(
                job, bootstrap.process, phases, completed, retained
            )
        completed.append("bootstrap")
        if backup is not None:
            self._store.remove_sibling(backup)
        return self._install_result(job, bootstrap.process, phases, completed, [])

    def _install_result(
        self,
        job: JobDefinition,
        process: ProcessResult,
        phases: list[InstallPhase],
        completed: list[str],
        retained: list[Path],
    ) -> InstallResult:
        return InstallResult(
            job=job,
            plist_path=self._store.destination_for(job.label),
            process=process,
            phases=tuple(phases),
            completed_phases=tuple(completed),
            retained_artifacts=tuple(retained),
        )

    # -- editor (in-memory, non-deploying) ---

    def new_managed_job(
        self,
        name: str,
        command: Command,
        schedule: Schedule,
        *,
        job_id: UUID | None = None,
    ) -> JobDefinition:
        """Builds the in-memory managed job; nothing is persisted; see
        JobService.new_managed_job for label policy and defaults.
        """
        return self._jobs.new_managed_job(name, command, schedule, job_id=job_id)

    def validate_job(self, job: JobDefinition) -> JobDefinition:
        """Re-validates the given job through the model (catches cross-field
        and schema drift), returning the validated instance.
        """
        return JobDefinition.model_validate(job.model_dump())

    def generate_plist_for(self, job: JobDefinition) -> str:
        """Returns the XML plist text for the job after re-validation; no file
        is written.
        """
        validated = self.validate_job(job)
        return self._codec.encode_bytes(validated).decode("utf-8")

    def save_managed_job(self, job: JobDefinition) -> Path:
        """Persists to the catalog only (no plist write, no launchctl, no log
        directories); raises JobConflictError when another job id claims the
        label.
        """
        return self._jobs.save(self.validate_job(job))

    def detect_python(self, script: Path) -> PythonDetectionResult:
        """Finds candidate interpreters and a working-directory recommendation
        for a selected script.
        """
        return platform_detect_python(script)

    def resolve_managed_job(self, label: str) -> JobDefinition:
        """Returns the managed job for label; raises JobNotFoundError when absent."""
        return self._jobs.resolve(label)

    # -- lifecycle -----------------------------------------------------------

    def _require_managed(self, label: str) -> JobDefinition:
        """Validate *label* and resolve it through the catalog (managed-only)."""
        validate_label(label)
        return self._jobs.resolve(label)

    def uninstall(self, label: str) -> UninstallResult:
        """Boot the managed job out and remove its catalog record on success."""
        job = self._require_managed(label)
        result = self._backend.uninstall(label)
        catalog_removed = False
        if result.process.exit_code == 0:
            catalog_removed = self._jobs.remove(job.id)
        return UninstallResult(
            label=label, process=result.process, catalog_removed=catalog_removed
        )

    def enable(self, label: str) -> LaunchctlResult:
        """Re-enable a managed job (launchctl enable)."""
        self._require_managed(label)
        return self._backend.enable(label)

    def disable(self, label: str) -> LaunchctlResult:
        """Disable a managed job (launchctl disable)."""
        self._require_managed(label)
        return self._backend.disable(label)

    def status(self, label: str) -> LaunchAgentStatus:
        """Report whether the managed job is loaded in launchd."""
        self._require_managed(label)
        return self._backend.status(label)

    def run_now(self, label: str) -> LaunchctlResult:
        """Ask launchd to run the managed job now (kickstart -k)."""
        self._require_managed(label)
        return self._backend.trigger(label)

    # -- testing and logs -----------------------------------------------------

    def test(self, label: str) -> DirectTestResult:
        """Run the managed job's command directly (Mode A), with diagnostics."""
        return self.test_job(self._jobs.resolve(label))

    def test_job(
        self,
        job: JobDefinition,
        *,
        detection: PythonDetectionResult | None = None,
    ) -> DirectTestResult:
        """Run the given job's command directly (Mode A), with diagnostics.

        Works for validated, unsaved drafts as well as saved jobs. Python
        commands without an explicit *detection* get their candidate
        interpreters detected first, so interpreter-mismatch diagnostics are
        available. Never mutates the job or writes logs.
        """
        validated = self.validate_job(job)
        if detection is None and isinstance(validated.command, PythonCommand):
            detection = self.detect_python(validated.command.script)
        return self._test.run(validated, detection=detection)

    def compare_environment(
        self,
        job: JobDefinition,
        terminal_environment: Mapping[str, str],
    ) -> EnvironmentDifference:
        """Compare a supplied terminal environment with the job's scheduled
        environment variables. Read-only; the platform comparison stays pure.
        """
        validated = self.validate_job(job)
        return compare_environments(
            terminal_environment, validated.environment.variables
        )

    def read_logs(self, label: str) -> JobLogs:
        """Read the managed job's configured stdout/stderr files."""
        return self.read_logs_for(self._jobs.resolve(label))

    def read_logs_for(self, job: JobDefinition) -> JobLogs:
        """Read the given job's configured stdout/stderr files (read-only).

        Works for validated, unsaved drafts as well as saved jobs.
        """
        return self._logs.read(self.validate_job(job))
