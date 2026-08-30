"""Unit tests for the TaskCommandService facade (Increment 8).

Every boundary is fake: a temporary catalog, a temporary LaunchAgents root,
and scripted process results. No test touches the real home directory or
invokes the real launchctl.
"""

from __future__ import annotations

import plistlib
import sys
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
from tests.conftest import make_job
from tests.fakes import FakeTaskWorld

from task_scheduler.application import JobConflictError, JobNotFoundError, ListingKind
from task_scheduler.application.job_service import (
    default_job_logs_root,
    managed_label,
)
from task_scheduler.domain import (
    EnvironmentConfig,
    JobDefinition,
    LoggingConfig,
    UnsupportedSchemaVersionError,
)
from task_scheduler.domain.command import command_argv
from task_scheduler.platform.macos import (
    LAUNCHCTL_PATH,
    CandidateSource,
    LaunchAgentStatus,
    LaunchctlAction,
    ParseSupport,
    PlistCodec,
    ProcessLaunchFailure,
    ProcessResult,
)

OTHER_ID = UUID("87654321-4321-4321-4321-432143214321")


def job_file(tmp_path: Path, job) -> Path:
    path = tmp_path / "job.json"
    path.write_text(job.model_dump_json(exclude_none=True), encoding="utf-8")
    return path


def broken_job(job: JobDefinition) -> JobDefinition:
    """A job whose label fails validation, bypassing the model's checks."""
    data = job.model_dump()
    data["label"] = "bad label"
    return JobDefinition.model_construct(**data)


class TestListAgents:
    def test_empty_root_lists_nothing(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        assert world.services.list_agents() == []

    def test_lists_managed_external_and_invalid_agents(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        managed = make_job()
        world.manage(managed)
        external = make_job(label="com.example.external", id=OTHER_ID)
        world.store.write(external)
        (world.la_root / "com.example.broken.plist").write_bytes(b"garbage")
        agents = world.services.list_agents()
        by_name = {
            agent.path.name: agent for agent in agents if agent.path is not None
        }
        assert set(by_name) == {
            f"{managed.label}.plist",
            f"{external.label}.plist",
            "com.example.broken.plist",
        }
        assert by_name[f"{managed.label}.plist"].kind is ListingKind.DISCOVERED
        assert by_name[f"{managed.label}.plist"].managed is True
        assert by_name[f"{managed.label}.plist"].job == managed
        assert by_name[f"{managed.label}.plist"].parsed.status is ParseSupport.SUPPORTED
        assert by_name[f"{managed.label}.plist"].parsed.job is not None
        assert by_name[f"{external.label}.plist"].managed is False
        assert by_name[f"{external.label}.plist"].job is None
        assert by_name["com.example.broken.plist"].managed is False
        assert by_name["com.example.broken.plist"].parsed.status is ParseSupport.INVALID

    def test_catalog_only_jobs_appear_as_saved_rows(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.jobs.import_job(job)
        agents = world.services.list_agents()
        assert len(agents) == 1
        listing = agents[0]
        assert listing.kind is ListingKind.SAVED
        assert listing.path is None
        assert listing.parsed is None
        assert listing.job == job
        assert listing.managed is True

    def test_saved_rows_follow_discovered_rows(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        deployed = make_job(label="io.github.macos-task-scheduler.user.aaa")
        world.manage(deployed)
        saved = make_job(id=OTHER_ID, label="io.github.macos-task-scheduler.user.bbb")
        world.jobs.import_job(saved)
        agents = world.services.list_agents()
        assert [agent.kind for agent in agents] == [
            ListingKind.DISCOVERED,
            ListingKind.SAVED,
        ]
        assert agents[1].job == saved

    def test_deployed_managed_job_is_not_listed_twice(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)
        agents = world.services.list_agents()
        assert [agent.kind for agent in agents] == [ListingKind.DISCOVERED]


class TestInspect:
    def test_managed_job_with_plist(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)
        report = world.services.inspect(job.label)
        assert report.job == job
        assert report.plist_path == world.store.destination_for(job.label)
        assert report.plist.status is ParseSupport.SUPPORTED
        assert report.status.loaded is True
        assert world.launch_runner.specs[0].argv == [
            LAUNCHCTL_PATH,
            "print",
            f"gui/1000/{job.label}",
        ]

    def test_managed_job_without_plist_reports_invalid(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.jobs.import_job(job)
        report = world.services.inspect(job.label)
        assert report.plist.status is ParseSupport.INVALID
        assert any("could not read" in warning for warning in report.plist.warnings)
        assert report.status.loaded is True

    def test_unknown_label_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        with pytest.raises(JobNotFoundError):
            world.services.inspect("missing.label")


class TestInspectDiscovered:
    def test_managed_agent_reports_managed_and_status(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)
        destination = world.store.destination_for(job.label)
        report = world.services.inspect_discovered(destination)
        assert report.path == destination
        assert report.managed is True
        assert report.parsed.status is ParseSupport.SUPPORTED
        assert report.parsed.job is not None
        assert report.status is not None
        assert isinstance(report.status, LaunchAgentStatus)
        assert report.status.loaded is True

    def test_external_agent_is_not_managed(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        external = make_job(label="com.example.external", id=OTHER_ID)
        world.store.write(external)
        destination = world.store.destination_for(external.label)
        report = world.services.inspect_discovered(destination)
        assert report.managed is False
        assert report.parsed.status is ParseSupport.SUPPORTED
        assert report.status is not None
        assert report.status.loaded is True

    def test_partially_supported_reports_job_and_status(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        payload = {
            "Label": "com.example.keepalive",
            "ProgramArguments": ["/bin/zsh", "/Users/example/scripts/x.sh"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
            "KeepAlive": True,
        }
        world.la_root.mkdir(parents=True, exist_ok=True)
        path = world.la_root / "com.example.keepalive.plist"
        path.write_bytes(plistlib.dumps(payload))
        report = world.services.inspect_discovered(path)
        assert report.parsed.status is ParseSupport.PARTIALLY_SUPPORTED
        assert report.parsed.job is not None
        assert report.parsed.unsupported_keys == ["KeepAlive"]
        assert report.managed is False
        assert report.status is not None
        assert report.status.loaded is True

    def test_invalid_plist_has_no_job_or_status(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        payload = {
            "Label": "com.example.broken",
            "ProgramArguments": "not-a-list",
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        }
        world.la_root.mkdir(parents=True, exist_ok=True)
        path = world.la_root / "com.example.broken.plist"
        path.write_bytes(plistlib.dumps(payload))
        report = world.services.inspect_discovered(path)
        assert report.parsed.status is ParseSupport.INVALID
        assert report.parsed.job is None
        assert report.managed is False
        assert report.status is None

    def test_path_outside_root_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        outside = tmp_path / "outside.plist"
        outside.write_bytes(plistlib.dumps({"Label": "com.example.outside"}))
        with pytest.raises(ValueError):
            world.services.inspect_discovered(outside)

    def test_inspect_discovered_is_read_only(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)
        plist_path = world.store.destination_for(job.label)
        catalog_path = world.catalog_root / f"{job.id}.json"
        plist_before = plist_path.read_bytes()
        catalog_before = catalog_path.read_bytes()
        world.services.inspect_discovered(plist_path)
        assert plist_path.read_bytes() == plist_before
        assert catalog_path.read_bytes() == catalog_before
        assert [spec.argv[1] for spec in world.launch_runner.specs] == ["print"]

    def test_status_passthrough_reflects_launch_result(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path, launch=ProcessResult(exit_code=5))
        job = make_job()
        world.manage(job)
        destination = world.store.destination_for(job.label)
        report = world.services.inspect_discovered(destination)
        assert report.status is not None
        assert report.status.loaded is False
        assert report.status.process.exit_code == 5


class TestJsonFileCommands:
    def test_validate_json_returns_job(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        assert world.services.validate_json(job_file(tmp_path, job)) == job

    def test_validate_json_invalid_files_raise(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValidationError):
            world.services.validate_json(bad)
        wrong = tmp_path / "wrong.json"
        wrong.write_text('{"schema_version": 99}', encoding="utf-8")
        with pytest.raises(UnsupportedSchemaVersionError):
            world.services.validate_json(wrong)

    def test_generate_plist_returns_xml_without_side_effects(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        xml = world.services.generate_plist(job_file(tmp_path, job))
        assert xml.startswith("<?xml")
        assert f"<string>{job.label}</string>" in xml
        assert not world.la_root.exists()
        assert not world.catalog_root.exists()


class TestInstall:
    def test_install_success(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        result = world.services.install_json(job_file(tmp_path, job))
        assert result.job == job
        assert result.plist_path == world.store.destination_for(job.label)
        assert result.process.exit_code == 0
        assert (world.catalog_root / f"{job.id}.json").is_file()
        assert result.plist_path.is_file()
        assert world.launch_runner.specs[0].argv == [
            LAUNCHCTL_PATH,
            "bootstrap",
            "gui/1000",
            str(result.plist_path),
        ]

    def test_install_conflict_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.jobs.import_job(job)
        with pytest.raises(JobConflictError):
            world.services.install_json(job_file(tmp_path, job))

    def test_install_existing_plist_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.store.write(job)
        with pytest.raises(FileExistsError):
            world.services.install_json(job_file(tmp_path, job))

    def test_failed_bootstrap_retains_artifacts(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(
            tmp_path, launch=ProcessResult(exit_code=1, stderr="bootstrap failed")
        )
        job = make_job()
        result = world.services.install_json(job_file(tmp_path, job))
        assert result.process.exit_code == 1
        assert (world.catalog_root / f"{job.id}.json").is_file()
        assert result.plist_path.is_file()
        assert world.jobs.find(job.label) is not None


class TestLifecycle:
    def test_uninstall_success_removes_plist_and_catalog(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)
        result = world.services.uninstall(job.label)
        assert result.process.exit_code == 0
        assert result.catalog_removed is True
        assert not (world.la_root / f"{job.label}.plist").exists()
        assert not (world.catalog_root / f"{job.id}.json").exists()
        assert world.launch_runner.specs[0].argv == [
            LAUNCHCTL_PATH,
            "bootout",
            f"gui/1000/{job.label}",
        ]

    def test_uninstall_failure_retains_plist_and_catalog(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(
            tmp_path, launch=ProcessResult(exit_code=1, stderr="bootout failed")
        )
        job = make_job()
        world.manage(job)
        result = world.services.uninstall(job.label)
        assert result.process.exit_code == 1
        assert result.catalog_removed is False
        assert (world.la_root / f"{job.label}.plist").is_file()
        assert (world.catalog_root / f"{job.id}.json").is_file()

    def test_uninstall_external_label_has_no_catalog_record(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        external = make_job(label="com.example.external", id=OTHER_ID)
        world.store.write(external)
        result = world.services.uninstall(external.label)
        assert result.catalog_removed is False
        assert not (world.la_root / f"{external.label}.plist").exists()

    def test_uninstall_invalid_label_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        with pytest.raises(ValueError):
            world.services.uninstall("../escape")

    def test_enable_and_disable(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        label = make_job().label
        enabled = world.services.enable(label)
        disabled = world.services.disable(label)
        assert enabled.action is LaunchctlAction.ENABLE
        assert enabled.process.exit_code == 0
        assert world.launch_runner.specs[0].argv[0] == LAUNCHCTL_PATH
        assert disabled.action is LaunchctlAction.DISABLE
        actions = [spec.argv[1] for spec in world.launch_runner.specs]
        assert actions == ["enable", "disable"]

    def test_status_loaded_unloaded_and_unknown(self, tmp_path: Path) -> None:
        label = make_job().label
        loaded = FakeTaskWorld(tmp_path).services.status(label)
        assert loaded.loaded is True
        unloaded = FakeTaskWorld(
            tmp_path, launch=ProcessResult(exit_code=5)
        ).services.status(label)
        assert unloaded.loaded is False
        unknown = FakeTaskWorld(
            tmp_path,
            launch=ProcessResult(
                exit_code=None,
                launch_failure=ProcessLaunchFailure(kind="not_found", message="gone"),
            ),
        ).services.status(label)
        assert unknown.loaded is None

    def test_run_now_uses_kickstart(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        label = make_job().label
        result = world.services.run_now(label)
        assert result.action is LaunchctlAction.TRIGGER
        assert world.launch_runner.specs[0].argv == [
            LAUNCHCTL_PATH,
            "kickstart",
            "-k",
            f"gui/1000/{label}",
        ]


class TestDirectTestAndLogs:
    def test_test_runs_command_with_job_environment(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(
            tmp_path,
            test=ProcessResult(
                exit_code=3, stdout="out-line", stderr="err-line",
                duration=timedelta(milliseconds=250),
            ),
        )
        job = make_job(
            environment=EnvironmentConfig(variables={"PYTHONUNBUFFERED": "1"})
        )
        world.jobs.import_job(job)
        result = world.services.test(job.label)
        assert result.process.exit_code == 3
        assert result.process.stdout == "out-line"
        assert world.test_runner.specs[0].argv == command_argv(job.command)
        assert world.test_runner.specs[0].environment == {"PYTHONUNBUFFERED": "1"}
        codes = {diagnostic.code for diagnostic in result.diagnostics}
        assert "executable_missing" in codes

    def test_test_unknown_label_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        with pytest.raises(JobNotFoundError):
            world.services.test("missing.label")

    def test_read_logs_unconfigured(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.jobs.import_job(job)
        logs = world.services.read_logs(job.label)
        assert logs.stdout.path is None
        assert logs.stderr.path is None

    def test_read_logs_reads_configured_files(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        out = tmp_path / "out.log"
        out.write_text("job stdout\n")
        job = make_job(logging=LoggingConfig(stdout_path=out, stderr_path=None))
        world.jobs.import_job(job)
        logs = world.services.read_logs(job.label)
        assert logs.stdout.content == "job stdout\n"
        assert logs.stderr.path is None


class TestEditorFacade:
    def test_new_managed_job_builds_in_memory_job_without_persisting(
        self, tmp_path: Path
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        base = make_job()
        job = world.services.new_managed_job(
            "Daily Backup", base.command, base.schedule, job_id=OTHER_ID
        )
        assert job.id == OTHER_ID
        assert job.name == "Daily Backup"
        assert job.label == managed_label("Daily Backup", OTHER_ID)
        assert job.enabled is True
        assert not world.catalog_root.exists()
        assert world.jobs.find(job.label) is None
        assert not world.la_root.exists()
        assert world.launch_runner.specs == []
        assert world.test_runner.specs == []

    def test_validate_job_returns_validated_job(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        assert world.services.validate_job(job).model_dump() == job.model_dump()

    def test_validate_job_revalidates_through_the_model(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        with pytest.raises(ValueError):
            world.services.validate_job(broken_job(make_job()))

    def test_generate_plist_for_matches_codec(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        text = world.services.generate_plist_for(job)
        assert text == PlistCodec().encode_bytes(job).decode("utf-8")
        assert text.startswith("<?xml")
        assert job.label in text

    def test_generate_plist_for_rejects_invalid_job(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        with pytest.raises(ValueError):
            world.services.generate_plist_for(broken_job(make_job()))

    def test_save_new_job_persists_catalog_only(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        path = world.services.save_managed_job(job)
        assert path == world.catalog_root / f"{job.id}.json"
        assert path.is_file()
        assert world.services.resolve_managed_job(job.label).id == job.id
        assert not world.store.destination_for(job.label).exists()
        assert world.launch_runner.specs == []
        assert not (default_job_logs_root() / job.id.hex).exists()

    def test_save_update_overwrites_own_record(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.services.save_managed_job(job)
        world.services.save_managed_job(job.model_copy(update={"name": "Renamed"}))
        assert list(world.catalog_root.glob("*.json")) == [
            world.catalog_root / f"{job.id}.json"
        ]
        assert world.services.resolve_managed_job(job.label).name == "Renamed"

    def test_save_conflict_keeps_original_record(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        path = world.services.save_managed_job(job)
        original = path.read_bytes()
        with pytest.raises(JobConflictError):
            world.services.save_managed_job(job.model_copy(update={"id": OTHER_ID}))
        assert path.read_bytes() == original
        assert not (world.catalog_root / f"{OTHER_ID}.json").exists()

    def test_save_invalid_job_writes_nothing(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        with pytest.raises(ValueError):
            world.services.save_managed_job(broken_job(make_job()))
        assert not world.catalog_root.exists()

    def test_detect_python_reports_candidates_for_script(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        script = tmp_path / "run.py"
        script.write_text("print('hello')\n", encoding="utf-8")
        venv_python = tmp_path / ".venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        venv_python.write_bytes(b"")
        venv_python.chmod(0o755)
        result = world.services.detect_python(script)
        assert result.script == script
        assert result.candidates
        current = [
            candidate
            for candidate in result.candidates
            if candidate.source is CandidateSource.CURRENT
        ]
        assert current and current[0].path == Path(sys.executable)

    def test_resolve_managed_job_returns_saved_job(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.services.save_managed_job(job)
        assert world.services.resolve_managed_job(job.label).id == job.id

    def test_resolve_unknown_label_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        with pytest.raises(JobNotFoundError):
            world.services.resolve_managed_job("missing.label")
