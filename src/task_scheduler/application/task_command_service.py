"""TaskCommandService: the shared application facade for CLI (and GUI).

Every ``mactask`` command maps to exactly one method here; the Typer CLI
and the future PySide6 GUI both call this service rather than the platform
adapters (spec lines 230-248, 1089, 2542-2550). The facade owns
orchestration (catalog + storage + launchctl + direct testing + logs) and
returns structured results, never presentation text.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from task_scheduler.application.job_service import JobService
from task_scheduler.application.log_service import JobLogs, LogService
from task_scheduler.application.test_service import DirectTestResult, DirectTestService
from task_scheduler.domain import Command, JobDefinition, Schedule
from task_scheduler.platform.macos import (
    DiscoveredLaunchAgent,
    LaunchAgentBackend,
    LaunchAgentStatus,
    LaunchAgentStore,
    LaunchctlResult,
    ParsedLaunchAgent,
    PlistCodec,
    ProcessResult,
    PythonDetectionResult,
    parse_path,
    validate_label,
)
from task_scheduler.platform.macos import (
    detect_python as platform_detect_python,
)
from task_scheduler.storage import JsonJobRepository

__all__ = [
    "AgentListing",
    "DiscoveredInspectReport",
    "InspectReport",
    "InstallResult",
    "TaskCommandService",
    "UninstallResult",
]


@dataclass(frozen=True, slots=True)
class AgentListing:
    """One discovered LaunchAgent, flagged when application-managed."""

    path: Path
    parsed: ParsedLaunchAgent
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
class InstallResult:
    """Outcome of installing a job from a JSON file."""

    job: JobDefinition
    plist_path: Path
    process: ProcessResult


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

    def list_agents(self) -> list[AgentListing]:
        """Discover user LaunchAgents, flagging the application-managed ones."""
        managed = {job.label for job in self._jobs.list_jobs()}
        return [
            AgentListing(
                path=agent.path,
                parsed=agent.parsed,
                managed=self._is_managed(agent, managed),
            )
            for agent in self._store.discover()
        ]

    @staticmethod
    def _is_managed(agent: DiscoveredLaunchAgent, managed: set[str]) -> bool:
        job = agent.parsed.job
        return job is not None and job.label in managed

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
        """Install a job from JSON: catalog import, then write + bootstrap.

        Create-only: ``JobConflictError`` when the catalog id already
        exists, ``FileExistsError`` when the plist already exists. A failed
        bootstrap retains the catalog record and the plist for diagnosis.
        """
        job = self._repository.load(path)
        self._jobs.import_job(job)
        result = self._backend.install(job)
        return InstallResult(
            job=job,
            plist_path=self._store.destination_for(job.label),
            process=result.process,
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

    def uninstall(self, label: str) -> UninstallResult:
        """Boot the job out and remove its catalog record only on success."""
        validate_label(label)
        job = self._jobs.find(label)
        result = self._backend.uninstall(label)
        catalog_removed = False
        if result.process.exit_code == 0 and job is not None:
            catalog_removed = self._jobs.remove(job.id)
        return UninstallResult(
            label=label, process=result.process, catalog_removed=catalog_removed
        )

    def enable(self, label: str) -> LaunchctlResult:
        """Re-enable a managed job (launchctl enable)."""
        validate_label(label)
        return self._backend.enable(label)

    def disable(self, label: str) -> LaunchctlResult:
        """Disable a managed job (launchctl disable)."""
        validate_label(label)
        return self._backend.disable(label)

    def status(self, label: str) -> LaunchAgentStatus:
        """Report whether the job is loaded in launchd."""
        validate_label(label)
        return self._backend.status(label)

    def run_now(self, label: str) -> LaunchctlResult:
        """Ask launchd to run the job now (kickstart -k)."""
        validate_label(label)
        return self._backend.trigger(label)

    # -- testing and logs -----------------------------------------------------

    def test(self, label: str) -> DirectTestResult:
        """Run the managed job's command directly (Mode A), with diagnostics."""
        job = self._jobs.resolve(label)
        return self._test.run(job)

    def read_logs(self, label: str) -> JobLogs:
        """Read the managed job's configured stdout/stderr files."""
        job = self._jobs.resolve(label)
        return self._logs.read(job)
