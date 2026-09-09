"""Reusable test fakes for process execution, time, and the filesystem."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from task_scheduler.application import (
    JobService,
    LogService,
    TaskCommandService,
)
from task_scheduler.application.test_service import DirectTestService
from task_scheduler.domain import JobDefinition
from task_scheduler.platform.macos import (
    CommandSpec,
    DetectionContext,
    LaunchAgentBackend,
    LaunchAgentStore,
    PlistCodec,
    ProcessResult,
    PythonDetectionRoots,
)
from task_scheduler.platform.macos.diagnostic_probes import (
    ArchitectureFinding,
    DiagnosticProbes,
    ProtectedPathFinding,
)
from task_scheduler.storage import (
    ExecutionHistoryRepository,
    JsonJobRepository,
)


class FakeClock:
    """Deterministic monotonic clock.

    Each call returns the current time and then advances by ``step``, so a
    two-sample measurement (start/stop) spans exactly one step.
    """

    def __init__(self, start: float = 1000.0, step: float = 0.0) -> None:
        self._now = start
        self._step = step
        self.calls = 0

    def __call__(self) -> float:
        result = self._now
        self.calls += 1
        self._now += self._step
        return result

    def advance(self, seconds: float) -> None:
        self._now += seconds


class FakeProcessRunner:
    """Scripted ProcessRunner: records every spec, returns scripted results.

    Pass a single ``result`` to get the legacy sticky behavior, or an ordered
    ``results`` queue that is popped one result per call and then repeats its
    last entry (so multi-command lifecycles stay scripted but never run dry).
    """

    def __init__(
        self,
        result: ProcessResult | None = None,
        *,
        results: list[ProcessResult] | None = None,
    ) -> None:
        if result is None and not results:
            raise ValueError("provide a result or a non-empty results queue")
        self._queue: list[ProcessResult] = list(results) if results else []
        self._sticky = result if result is not None else self._queue[-1]
        self.specs: list[CommandSpec] = []

    def run(self, spec: CommandSpec) -> ProcessResult:
        self.specs.append(spec)
        if self._queue:
            return self._queue.pop(0)
        return self._sticky


class FakeFilesystem:
    """In-memory LaunchAgentFilesystem for store tests.

    ``files`` maps a destination filename to its existing bytes; ``create_error``,
    when set, is raised by :meth:`create_exclusive` instead of creating. All
    calls are recorded so tests can assert exactly what the store did.
    """

    def __init__(
        self,
        files: dict[str, bytes] | None = None,
        *,
        create_error: Exception | None = None,
    ) -> None:
        self._files: dict[str, bytes] = dict(files or {})
        self._create_error = create_error
        self.reads: list[str] = []
        self.listings: list[str] = []
        self.roots_created: list[str] = []
        self.created: list[str] = []
        self.removed: list[str] = []
        self.replaced: list[str] = []

    def read_plist_bytes(self, path: Path) -> bytes:
        self.reads.append(path.name)
        if path.name not in self._files:
            raise FileNotFoundError(path.name)
        return self._files[path.name]

    def list_plist_files(self, root: Path) -> list[Path]:
        self.listings.append(root.name)
        return sorted(Path(root) / name for name in self._files if name.endswith(".plist"))

    def create_root(self, root: Path) -> None:
        self.roots_created.append(root.name)

    def create_exclusive(self, destination: Path, payload: bytes) -> None:
        if destination.name in self._files:
            raise FileExistsError(destination.name)
        if self._create_error is not None:
            raise self._create_error
        self._files[destination.name] = payload
        self.created.append(destination.name)

    def remove_file(self, path: Path) -> bool:
        self.removed.append(path.name)
        if path.name in self._files:
            del self._files[path.name]
            return True
        return False

    def replace(self, source: Path, destination: Path) -> None:
        if source.name not in self._files:
            raise FileNotFoundError(source.name)
        self._files[destination.name] = self._files[source.name]
        self.replaced.append(destination.name)


OK_PROCESS = ProcessResult(exit_code=0)


class FakeFinderRevealer:
    """Recording FinderRevealer: records revealed paths, returns a canned result.

    ``result`` is ``None`` (success) by default; set a string to simulate a
    Finder reveal failure.
    """

    def __init__(self, result: str | None = None) -> None:
        self.result = result
        self.revealed: list[Path] = []

    def reveal(self, path: Path) -> str | None:
        self.revealed.append(path)
        return self.result


class FakeTaskWorld:
    """A fully faked TaskCommandService environment rooted at temp paths.

    The catalog and LaunchAgents store live under *tmp_path* and every
    launchctl / direct-test invocation is scripted, so no test touches the
    real home directory or invokes the real launchctl.
    """

    def __init__(
        self,
        tmp_path: Path,
        *,
        launch: ProcessResult | None = None,
        launches: list[ProcessResult] | None = None,
        test: ProcessResult | None = None,
        probes: DiagnosticProbes | None = None,
    ) -> None:
        self.catalog_root = tmp_path / "catalog"
        self.la_root = tmp_path / "launchagents"
        self.history_root = tmp_path / "history"
        self.history_root.mkdir(parents=True, exist_ok=True)
        self.store = LaunchAgentStore(self.la_root)
        self.jobs = JobService(self.catalog_root)
        if launches is not None:
            self.launch_runner = FakeProcessRunner(results=launches)
        else:
            self.launch_runner = FakeProcessRunner(result=launch or OK_PROCESS)
        self.test_runner = FakeProcessRunner(result=test or OK_PROCESS)
        self.backend = LaunchAgentBackend(self.store, self.launch_runner, uid=1000)
        self.history_repo = ExecutionHistoryRepository(
            self.history_root / "history.sqlite3"
        )
        self.finder_revealer = FakeFinderRevealer()
        self.services = TaskCommandService(
            repository=JsonJobRepository(),
            jobs=self.jobs,
            store=self.store,
            backend=self.backend,
            codec=PlistCodec(),
            test=DirectTestService(self.test_runner),
            logs=LogService(),
            probes=probes,
            history=self.history_repo,
            finder=self.finder_revealer,
        )

    def manage(self, job: JobDefinition) -> None:
        """Seed both the catalog record and the managed plist for *job*."""
        self.jobs.import_job(job)
        self.store.write(job)


class FakeDiagnosticProbes(DiagnosticProbes):
    """Injectable probe stub that returns canned findings.

    Records every call (inputs and kwargs) so tests can assert what was probed.
    """

    def __init__(
        self,
        protected_findings: tuple[ProtectedPathFinding, ...] = (),
        architecture_finding: ArchitectureFinding | None = None,
    ) -> None:
        self.protected_findings = protected_findings
        self.architecture_finding = architecture_finding
        self.protected_calls: list[tuple[Sequence[Path], dict[str, object]]] = []
        self.architecture_calls: list[tuple[Path, dict[str, object]]] = []

    def probe_protected_paths(
        self,
        paths: Sequence[Path],
        *,
        home: Path | None = None,
    ) -> tuple[ProtectedPathFinding, ...]:
        self.protected_calls.append((paths, {"home": home}))
        return self.protected_findings

    def probe_executable_architecture(
        self,
        executable: Path,
        *,
        machine: str | None = None,
    ) -> ArchitectureFinding | None:
        self.architecture_calls.append((executable, {"machine": machine}))
        return self.architecture_finding


class FakePythonDetectorFilesystem:
    """Dict-backed ``PythonDetectorFilesystem`` for deterministic detector tests."""

    def __init__(
        self,
        files: dict[Path, str],
        executable: set[Path],
        dirs: set[Path] | None = None,
        unreadable: set[Path] | None = None,
    ) -> None:
        self.files = files
        self.executable = executable
        self.dirs = dirs or set()
        self.unreadable = unreadable or set()

    def exists(self, path: Path) -> bool:
        return path in self.files or path in self.dirs or path in self.unreadable

    def is_file(self, path: Path) -> bool:
        return path in self.files

    def is_dir(self, path: Path) -> bool:
        return path in self.dirs

    def is_executable(self, path: Path) -> bool:
        return path in self.executable

    def read_text(self, path: Path) -> str | None:
        if path in self.unreadable:
            return None
        return self.files.get(path)


EMPTY_DETECTION_ROOTS = PythonDetectionRoots(pyenv=(), conda=(), homebrew=())


def detect_context(
    script: Path,
    filesystem: FakePythonDetectorFilesystem,
    roots: PythonDetectionRoots,
) -> DetectionContext:
    """A ``DetectionContext`` for exercising one detector in isolation (no PATH hits)."""
    return DetectionContext(
        script=script,
        current_interpreter=script.parent / "missing-interpreter",
        path_lookup=lambda _name: None,
        filesystem=filesystem,
        roots=roots,
    )
