"""Unit tests for the TaskCommandService facade (Increment 8).

Every boundary is fake: a temporary catalog, a temporary LaunchAgents root,
and scripted process results. No test touches the real home directory or
invokes the real launchctl.
"""

from __future__ import annotations

import plistlib
from pathlib import Path
from uuid import UUID

import pytest
from tests.conftest import make_job
from tests.fakes import OK_PROCESS, FakeTaskWorld

from task_scheduler.application.diagnostic_models import DiagnosticSource
from task_scheduler.application.job_service import (
    default_job_logs_root,
    managed_label,
)
from task_scheduler.application.log_service import JobLogs, LogStream
from task_scheduler.domain import (
    JobDefinition,
)
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

OTHER_ID = UUID("87654321-4321-4321-4321-432143214321")


class ScriptedStatusBackend:
    """Test-local backend wrapper with a scripted ``status`` loaded flag.

    ``status`` returns the fixed *loaded* value (recording every label it was
    asked for); every other call is delegated to the wrapped backend.
    """

    def __init__(self, inner: LaunchAgentBackend, *, loaded: bool | None) -> None:
        self._inner = inner
        self.loaded = loaded
        self.status_labels: list[str] = []

    def status(self, label: str) -> LaunchAgentStatus:
        self.status_labels.append(label)
        return LaunchAgentStatus(loaded=self.loaded, process=ProcessResult(exit_code=None))

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


def broken_job(job: JobDefinition) -> JobDefinition:
    """A job whose label fails validation, bypassing the model's checks."""
    data = job.model_dump()
    data["label"] = "bad label"
    return JobDefinition.model_construct(**data)


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
        assert result.plist_path.read_bytes() == PlistCodec().encode_bytes(updated)
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
        assert result.plist_path.read_bytes() == PlistCodec().encode_bytes(job)
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
        assert [spec.argv[1] for spec in world.launch_runner.specs] == [
            "bootout",
            "bootstrap",
        ]


class TestUninstall:
    @pytest.mark.parametrize(
        ("launch", "loaded", "removed"),
        [
            (OK_PROCESS, None, True),
            (ProcessResult(exit_code=1, stderr="bootout failed"), False, True),
            (ProcessResult(exit_code=1, stderr="bootout failed"), True, False),
            (ProcessResult(exit_code=1, stderr="bootout failed"), None, False),
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
        [
            ({"Label": "com.example.new", "ProgramArguments": ["/bin/echo"]}, "cannot add"),
            ({"ProgramArguments": ["/bin/echo"]}, "must contain a valid launchd label"),
        ],
    )
    def test_label_less_session_rejected(
        self, tmp_path: Path, replacement: dict[str, object], match: str
    ) -> None:
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


class TestJobBasedFacade:
    @staticmethod
    def _venv_project(tmp_path: Path) -> tuple[Path, Path]:
        project = tmp_path / "project"
        venv_python = project / ".venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        venv_python.chmod(0o755)
        script = project / "main.py"
        script.write_text("print('ok')\n", encoding="utf-8")
        return venv_python, script


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
        assert job.logging.stdout_path == default_job_logs_root() / "Daily Backup.stdout.log"
        assert job.logging.stderr_path == default_job_logs_root() / "Daily Backup.stderr.log"
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
        assert [d.code for d in diagnostics] == [
            "log_path_unreadable",
            "log_path_unreadable",
        ]
        assert "stdout" in diagnostics[0].description
        assert "stderr" in diagnostics[1].description
        clean = JobLogs(
            stdout=LogStream(name="stdout", path=None, content="ok"),
            stderr=LogStream(name="stderr", path=None),
        )
        assert world.services.log_diagnostics_for(job, clean) == ()
