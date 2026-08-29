"""Unit tests for the TaskCommandService facade (Increment 8).

Every boundary is fake: a temporary catalog, a temporary LaunchAgents root,
and scripted process results. No test touches the real home directory or
invokes the real launchctl.
"""

from __future__ import annotations

import plistlib
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
from tests.conftest import make_job
from tests.fakes import FakeTaskWorld

from task_scheduler.application import JobConflictError, JobNotFoundError
from task_scheduler.domain import (
    EnvironmentConfig,
    LoggingConfig,
    UnsupportedSchemaVersionError,
)
from task_scheduler.domain.command import command_argv
from task_scheduler.platform.macos import (
    LAUNCHCTL_PATH,
    LaunchAgentStatus,
    LaunchctlAction,
    ParseSupport,
    ProcessLaunchFailure,
    ProcessResult,
)

OTHER_ID = UUID("87654321-4321-4321-4321-432143214321")


def job_file(tmp_path: Path, job) -> Path:
    path = tmp_path / "job.json"
    path.write_text(job.model_dump_json(exclude_none=True), encoding="utf-8")
    return path


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
        by_name = {agent.path.name: agent for agent in agents}
        assert set(by_name) == {
            f"{managed.label}.plist",
            f"{external.label}.plist",
            "com.example.broken.plist",
        }
        assert by_name[f"{managed.label}.plist"].managed is True
        assert by_name[f"{managed.label}.plist"].parsed.status is ParseSupport.SUPPORTED
        assert by_name[f"{managed.label}.plist"].parsed.job is not None
        assert by_name[f"{external.label}.plist"].managed is False
        assert by_name["com.example.broken.plist"].managed is False
        assert by_name["com.example.broken.plist"].parsed.status is ParseSupport.INVALID


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
