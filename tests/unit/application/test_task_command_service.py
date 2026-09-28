"""Unit tests for the TaskCommandService facade: every boundary is fake."""

from __future__ import annotations

import plistlib
from pathlib import Path
from uuid import UUID

import pytest
from tests.conftest import make_job
from tests.fakes import OK_PROCESS, FakeTaskWorld

from task_scheduler.application.diagnostic_models import DiagnosticSource
from task_scheduler.application.history_models import HistoryEventKind, HistoryOutcome
from task_scheduler.application.job_service import (
    JobNotFoundError,
    canonical_logging_for,
    managed_label,
)
from task_scheduler.application.log_service import JobLogs, LogStream
from task_scheduler.application.task_command_service import InstallResult
from task_scheduler.domain import JobDefinition
from task_scheduler.platform.macos import (
    LAUNCHCTL_PATH,
    CandidateSource,
    InterpreterCandidate,
    LaunchAgentBackend,
    LaunchAgentStatus,
    PlistCodec,
    ProcessResult,
    PythonDetectionResult,
)
from task_scheduler.platform.macos.run_wrapper import stderr_log_path, stdout_log_path

OTHER_ID = UUID("87654321-4321-4321-4321-432143214321")

def _canonical(job: JobDefinition) -> JobDefinition:
    """The plist form reinstall regenerates: managed logging canonicalized by label."""
    return job.model_copy(update={"logging": canonical_logging_for(job.label)})

class ScriptedStatusBackend:
    """Test-local backend wrapper with a scripted ``status`` loaded flag: returns the fixed *loaded*
    value (recording every label); every other call is delegated to the wrapped backend."""

    def __init__(self, inner: LaunchAgentBackend, *, loaded: bool | None) -> None:
        self._inner = inner
        self.loaded = loaded
        self.status_labels: list[str] = []

    def status(self, label: str) -> LaunchAgentStatus:
        self.status_labels.append(label)
        return LaunchAgentStatus(loaded=self.loaded, process=ProcessResult(exit_code=None))

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

class TestInspectDiscovered:
    def test_path_outside_root_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        outside = tmp_path / "outside.plist"
        outside.write_bytes(plistlib.dumps({"Label": "com.example.outside"}))
        with pytest.raises(ValueError):
            world.services.inspect_discovered(outside)

class TestReinstall:
    def test_success_replaces_plist_and_retains_nothing(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)
        updated = job.model_copy(update={"name": "Renamed Backup"})
        world.jobs.save(updated)
        result = world.services.reinstall(job.label)
        assert result.process.exit_code == 0
        assert [phase.name for phase in result.phases] == ["bootout", "bootstrap"]
        assert result.completed_phases == ("bootout", "bootstrap")
        assert result.retained_artifacts == ()
        assert result.plist_path.read_bytes() == PlistCodec().encode_bytes(_canonical(updated))
        assert [path.name for path in world.la_root.iterdir()] == [f"{job.label}.plist"]
        assert world.launch_runner.specs[0].argv == [
            LAUNCHCTL_PATH,
            "bootout",
            f"gui/1000/{job.label}",
        ]
        assert world.launch_runner.specs[1].argv == [
            LAUNCHCTL_PATH,
            "bootstrap",
            "gui/1000",
            str(result.plist_path),
        ]
        assert world.jobs.find(job.label) is not None

    def test_failed_bootout_loaded_removes_staged_and_aborts(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path, launch=ProcessResult(exit_code=1, stderr="bootout failed"))
        backend = ScriptedStatusBackend(world.backend, loaded=True)
        world.services._backend = backend
        job = make_job()
        world.manage(job)
        result = world.services.reinstall(job.label)
        assert result.process.exit_code == 1
        assert result.process.stderr == "bootout failed"
        assert [phase.name for phase in result.phases] == ["bootout"]
        assert result.completed_phases == ()
        assert result.retained_artifacts == ()
        assert not (world.la_root / f"{job.label}.plist.staged.1").exists()
        assert result.plist_path.read_bytes() == PlistCodec().encode_bytes(job)
        assert [spec.argv[1] for spec in world.launch_runner.specs] == ["bootout"]
        assert world.jobs.find(job.label) is not None
        assert backend.status_labels == [job.label]

    def test_failed_bootout_not_loaded_continues_transaction(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(
            tmp_path,
            launches=[
                ProcessResult(exit_code=1, stderr="bootout failed"),
                OK_PROCESS,
            ],
        )
        backend = ScriptedStatusBackend(world.backend, loaded=False)
        world.services._backend = backend
        job = make_job()
        world.manage(job)
        result = world.services.reinstall(job.label)
        assert result.process.exit_code == 0
        assert [phase.name for phase in result.phases] == ["bootout", "bootstrap"]
        assert result.phases[0].process.exit_code == 1
        assert result.phases[0].process.stderr == "bootout failed"
        assert result.completed_phases == ("bootout", "bootstrap")
        assert result.retained_artifacts == ()
        assert result.plist_path.read_bytes() == PlistCodec().encode_bytes(_canonical(job))
        assert [path.name for path in world.la_root.iterdir()] == [f"{job.label}.plist"]
        assert [spec.argv[1] for spec in world.launch_runner.specs] == ["bootout", "bootstrap"]
        assert backend.status_labels == [job.label]

    def test_failed_bootstrap_retains_backup_sibling(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(
            tmp_path,
            launches=[
                OK_PROCESS,
                ProcessResult(exit_code=1, stderr="bootstrap failed"),
            ],
        )
        job = make_job()
        world.manage(job)
        result = world.services.reinstall(job.label)
        assert result.process.exit_code == 1
        assert result.process.stderr == "bootstrap failed"
        assert [phase.name for phase in result.phases] == ["bootout", "bootstrap"]
        assert result.completed_phases == ("bootout",)
        assert len(result.retained_artifacts) == 1
        backup = result.retained_artifacts[0]
        assert backup.name == f"{job.label}.plist.backup.1"
        assert backup.is_file()
        assert backup.read_bytes() == PlistCodec().encode_bytes(job)
        assert [spec.argv[1] for spec in world.launch_runner.specs] == ["bootout", "bootstrap"]

class TestUninstall:
    @pytest.mark.parametrize(
        ("launch", "loaded", "removed"),
        [
            (OK_PROCESS, None, True),
            (ProcessResult(exit_code=1, stderr="bootout failed"), False, True),
            (ProcessResult(exit_code=1, stderr="bootout failed"), True, False),
        ],
    )
    def test_uninstall_matrix(
        self,
        tmp_path: Path,
        launch: ProcessResult,
        loaded: bool | None,
        removed: bool,
    ) -> None:
        world = FakeTaskWorld(tmp_path, launch=launch)
        backend = ScriptedStatusBackend(world.backend, loaded=loaded)
        world.services._backend = backend
        job = make_job()
        world.manage(job)
        result = world.services.uninstall(job.label)
        assert result.process is launch
        assert result.process.exit_code == launch.exit_code
        assert result.catalog_removed is removed
        assert (world.la_root / f"{job.label}.plist").exists() == (not removed)
        assert (world.jobs.find(job.label) is not None) == (not removed)
        assert (backend.status_labels == [job.label]) == (launch.exit_code != 0)

class TestCommitRawExternalEditLabelInvariants:
    @pytest.mark.parametrize(
        ("replacement", "match"),
        [ ({"Label": "com.example.new", "ProgramArguments": ["/bin/echo"]}, "cannot add"), ],
    )
    def test_label_less_session_rejected(
        self, tmp_path: Path, replacement: dict[str, object], match: str) -> None:
        world = FakeTaskWorld(tmp_path)
        world.la_root.mkdir(parents=True)
        plist_path = world.la_root / "external.plist"
        plist_path.write_bytes(plistlib.dumps({"ProgramArguments": ["/bin/sleep"]}))
        session = world.services.open_external_edit_session(plist_path)
        assert session.label is None
        with pytest.raises(ValueError, match=match):
            world.services.commit_raw_external_edit(
                session, plistlib.dumps(replacement).decode("utf-8")
            )
        assert plist_path.read_bytes() == plistlib.dumps({"ProgramArguments": ["/bin/sleep"]})

class TestEditorFacade:
    def test_new_managed_job_builds_in_memory_job_without_persisting(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        base = make_job()
        job = world.services.new_managed_job(
            "Daily Backup", base.command, base.schedule, job_id=OTHER_ID
        )
        assert job.id == OTHER_ID
        assert job.name == "Daily Backup"
        assert job.label == managed_label("Daily Backup", OTHER_ID)
        assert job.enabled is True
        assert job.logging.stdout_path == stdout_log_path(job.label)
        assert job.logging.stderr_path == stderr_log_path(job.label)
        assert not world.catalog_root.exists()
        assert world.jobs.find(job.label) is None
        assert not world.la_root.exists()
        assert world.launch_runner.specs == []
        assert world.test_runner.specs == []

class TestDiagnosticsFacade:
    def test_diagnostic_report_for_includes_logs_and_python_groups(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        script = Path("/Users/example/project/main.py")
        detection = PythonDetectionResult(
            script=script,
            candidates=[
                InterpreterCandidate(path=Path("/opt/other/python"), source=CandidateSource.VENV)
            ],
        )
        logs = JobLogs(
            stdout=LogStream(name="stdout", path=Path("/tmp/out.log"), error="gone"),
            stderr=LogStream(name="stderr", path=None),
        )
        report = world.services.diagnostic_report_for(job, detection=detection, logs=logs)
        assert [group.source for group in report.groups] == [
            DiagnosticSource.PREFLIGHT,
            DiagnosticSource.LOGS,
            DiagnosticSource.PYTHON_ENVIRONMENT,
        ]
        assert [d.code for d in report.all] == [
            "executable_missing",
            "script_missing",
            "log_path_unreadable",
            "interpreter_mismatch",
        ]

    def test_log_diagnostics_for(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        logs = JobLogs(
            stdout=LogStream(name="stdout", path=Path("/tmp/a.log"), error="gone"),
            stderr=LogStream(name="stderr", path=Path("/tmp/b.log"), error="gone"),
        )
        diagnostics = world.services.log_diagnostics_for(job, logs)
        assert [d.code for d in diagnostics] == ["log_path_unreadable", "log_path_unreadable"]
        assert "stdout" in diagnostics[0].description
        assert "stderr" in diagnostics[1].description
        clean = JobLogs(
            stdout=LogStream(name="stdout", path=None, content="ok"),
            stderr=LogStream(name="stderr", path=None),
        )
        assert world.services.log_diagnostics_for(job, clean) == ()

class TestLaunchdTestFacade:
    def test_requires_configured_service(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)
        with pytest.raises(ValueError, match="not configured"):
            world.services.test_via_launchd(job.label)

    def test_unknown_label_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path, launchd_exit_code=0)
        with pytest.raises(JobNotFoundError):
            world.services.test_via_launchd("com.example.missing")

    def test_passes_and_records_success_event(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path, launchd_exit_code=0)
        job = make_job()
        world.manage(job)
        result = world.services.test_via_launchd(job.label)
        assert result.passed and result.run is not None and result.run.exit_code == 0
        events = world.history_repo.read(job.id, limit=10).events
        assert len(events) == 1
        assert events[0].kind == HistoryEventKind.LAUNCHD_TEST
        assert events[0].outcome == HistoryOutcome.SUCCESS
        assert events[0].exit_code == 0

    def test_failed_run_records_failure_event(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path, launchd_exit_code=3)
        job = make_job()
        world.manage(job)
        result = world.services.test_via_launchd(job.label)
        assert not result.passed and result.run is not None and result.run.exit_code == 3
        events = world.history_repo.read(job.id, limit=10).events
        assert len(events) == 1
        assert events[0].kind == HistoryEventKind.LAUNCHD_TEST
        assert events[0].outcome == HistoryOutcome.FAILURE
        assert events[0].exit_code == 3

EXTERNAL_PLIST_PAYLOAD = {
    "Label": "com.example.external",
    "ProgramArguments": ["/bin/echo", "hi"],
    "StartCalendarInterval": [{"Hour": 9, "Minute": 0, "Weekday": 1}],
}

def _external_plist(tmp_path: Path) -> Path:
    path = tmp_path / "external.plist"
    path.write_bytes(plistlib.dumps(EXTERNAL_PLIST_PAYLOAD))
    return path

class TestExternalImportDrift:
    def test_unreadable_source_at_preview_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        with pytest.raises(ValueError, match="could not read"):
            world.services.preview_external_plist(tmp_path / "missing.plist")

    def test_unreadable_source_at_commit_rejects_import(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        path = _external_plist(tmp_path)
        preview = world.services.preview_external_plist(path)
        path.unlink()
        with pytest.raises(ValueError, match="could not read"):
            world.services.import_external_plist(preview, acknowledge_partial=False)
        assert world.jobs.list_jobs() == []


class TestMigrateManagedPlists:
    def test_no_jobs_returns_empty_summary(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        result = world.services.migrate_managed_plists()
        assert result == (
            result.__class__(checked=0, up_to_date=0, migrated=0, skipped_running=0, missing=0)
        )
        assert world.launch_runner.specs == []

    def test_up_to_date_plist_is_left_alone(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)
        (world.la_root / f"{job.label}.plist").write_bytes(
            PlistCodec().encode_bytes(_canonical(job))
        )
        result = world.services.migrate_managed_plists()
        assert result.checked == 1
        assert result.up_to_date == 1
        assert result.migrated == 0
        assert result.errors == ()
        assert world.launch_runner.specs == []

    def test_stale_plist_is_reinstalled(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)
        result = world.services.migrate_managed_plists()
        assert result.checked == 1
        assert result.migrated == 1
        assert result.up_to_date == 0
        assert result.errors == ()
        assert (world.la_root / f"{job.label}.plist").read_bytes() == PlistCodec().encode_bytes(
            _canonical(job)
        )
        assert [spec.argv[1] for spec in world.launch_runner.specs] == [
            "print",
            "bootout",
            "bootstrap",
        ]

    def test_stale_running_plist_is_skipped(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(
            tmp_path, launch=ProcessResult(exit_code=0, stdout="\tstate = running\n")
        )
        job = make_job()
        world.manage(job)
        result = world.services.migrate_managed_plists()
        assert result.checked == 1
        assert result.skipped_running == 1
        assert result.migrated == 0
        assert result.errors == ()
        assert (world.la_root / f"{job.label}.plist").read_bytes() == PlistCodec().encode_bytes(job)
        assert [spec.argv[1] for spec in world.launch_runner.specs] == ["print"]

    def test_missing_plist_is_counted_without_reinstall(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)
        (world.la_root / f"{job.label}.plist").unlink()
        result = world.services.migrate_managed_plists()
        assert result.checked == 1
        assert result.missing == 1
        assert result.migrated == 0
        assert result.errors == ()
        assert not (world.la_root / f"{job.label}.plist").exists()
        assert world.launch_runner.specs == []

    def test_unreadable_plist_is_recorded(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)
        destination = world.la_root / f"{job.label}.plist"
        destination.unlink()
        destination.mkdir()
        result = world.services.migrate_managed_plists()
        assert result.checked == 1
        assert result.missing == 0
        assert result.migrated == 0
        assert len(result.errors) == 1
        assert result.errors[0][0] == job.label
        assert "could not read plist" in result.errors[0][1]

    def test_reinstall_failure_is_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)

        def _boom(_label: str) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(world.services, "reinstall", _boom)
        result = world.services.migrate_managed_plists()
        assert result.migrated == 0
        assert len(result.errors) == 1
        assert result.errors[0][0] == job.label
        assert "reinstall raised" in result.errors[0][1]

    def test_reinstall_incomplete_is_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)
        incomplete = InstallResult(
            job=job,
            plist_path=world.la_root / f"{job.label}.plist",
            process=ProcessResult(exit_code=1),
            completed_phases=("bootout",),
        )
        monkeypatch.setattr(world.services, "reinstall", lambda _label: incomplete)
        result = world.services.migrate_managed_plists()
        assert result.migrated == 0
        assert len(result.errors) == 1
        assert result.errors[0][0] == job.label
        assert "reinstall incomplete" in result.errors[0][1]


class TestIsRunning:
    def test_matches_running_state(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path, launch=ProcessResult(exit_code=0, stdout="state = running"))
        assert world.services._is_running(make_job().label) is True

    def test_idle_state_does_not_match(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(
            tmp_path, launch=ProcessResult(exit_code=0, stdout="state = not running")
        )
        assert world.services._is_running(make_job().label) is False
