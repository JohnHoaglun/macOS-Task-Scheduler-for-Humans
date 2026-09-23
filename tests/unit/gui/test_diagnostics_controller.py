"""Tests for the diagnostics controller (pure Python, no Qt)."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest
from tests.fakes import FakeTaskWorld

from conftest import make_job
from task_scheduler.domain import JobDefinition, LoggingConfig
from task_scheduler.domain.command import ShellCommand
from task_scheduler.gui.controllers.diagnostics_controller import (
    DiagnosticsController,
    RequestVerdict,
)
from task_scheduler.platform.macos import ProcessResult

JOB_LABEL = "io.github.macos-task-scheduler.user.daily-backup"


def _shell_job() -> JobDefinition:
    return make_job(command=ShellCommand(executable=Path("/bin/zsh"), arguments=["-c", "true"]))


def _broken(job: JobDefinition) -> JobDefinition:
    """A job whose label fails validation, bypassing the model's checks."""
    data = job.model_dump()
    data["label"] = "bad label"
    return JobDefinition.model_construct(**data)


class TestExecute:
    def test_nonzero_exit_code_is_not_success(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path, test=ProcessResult(exit_code=2))
        controller = DiagnosticsController(world.services, {})
        controller.request_test(_shell_job())
        outcome = controller.execute()
        assert outcome.error is None
        assert outcome.result is not None
        assert outcome.result.process.exit_code == 2
        assert not outcome.is_success

    def test_unexpected_error_becomes_error_outcome(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        world = FakeTaskWorld(tmp_path)

        def boom(job: JobDefinition, *, detection: object = None) -> NoReturn:
            raise RuntimeError("boom")

        monkeypatch.setattr(world.services, "test_job", boom)
        controller = DiagnosticsController(world.services, {})
        controller.request_test(_shell_job())
        outcome = controller.execute()
        assert outcome.error == "boom"
        assert outcome.result is None
        assert not outcome.is_success
        controller.finish()
        assert not controller.busy


class TestReadLogs:
    def test_read_logs_invalid_job_is_error(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        controller = DiagnosticsController(world.services, {})
        outcome = controller.read_logs(_broken(_shell_job()))
        assert outcome.logs is None
        assert outcome.error is not None
        assert outcome.diagnostics == ()


class TestCompareEnvironment:
    def test_snapshot_is_copied(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        env = {"A": "1"}
        controller = DiagnosticsController(world.services, env)
        env["A"] = "changed"
        assert controller.environment["A"] == "1"

    def test_compare_invalid_job_is_error(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        controller = DiagnosticsController(world.services, {})
        outcome = controller.compare_environment(_broken(_shell_job()))
        assert outcome.difference is None
        assert outcome.error is not None


def _logged_job(log_dir: Path, stdout_name: str = "daily-backup.stdout.log") -> JobDefinition:
    return make_job(
        name="daily-backup",
        command=ShellCommand(executable=Path("/bin/zsh"), arguments=["-c", "true"]),
        logging=LoggingConfig(stdout_path=log_dir / stdout_name, stderr_path=None),
    )


class TestSaveReport:
    def test_report_saved_beside_job_logs(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        world = FakeTaskWorld(tmp_path, test=ProcessResult(
            exit_code=0, stdout="hello", stderr="warn"))
        controller = DiagnosticsController(world.services, {})
        assert controller.request_test(_logged_job(log_dir)) is RequestVerdict.ACCEPTED
        outcome = controller.execute()
        assert outcome.saved_to is not None
        report = Path(outcome.saved_to)
        assert report == log_dir / "daily-backup.direct-test.log"
        text = report.read_text(encoding="utf-8")
        assert "exit code: 0" in text
        assert "hello" in text and "warn" in text

    def test_no_log_directory_means_no_save(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path, test=ProcessResult(exit_code=0))
        controller = DiagnosticsController(world.services, {})
        controller.request_test(_shell_job())
        assert controller.execute().saved_to is None

    def test_unwritable_report_path_is_not_fatal(self, tmp_path: Path) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("x", encoding="utf-8")
        world = FakeTaskWorld(tmp_path, test=ProcessResult(exit_code=0))
        controller = DiagnosticsController(world.services, {})
        controller.request_test(_logged_job(blocker))
        outcome = controller.execute()
        assert outcome.saved_to is None
        assert outcome.result is not None
