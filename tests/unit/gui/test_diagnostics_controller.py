"""Tests for the diagnostics controller (pure Python, no Qt)."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest

from conftest import make_job
from task_scheduler.application.test_service import DirectTestResult
from task_scheduler.domain import EnvironmentConfig, JobDefinition, LoggingConfig
from task_scheduler.domain.command import ShellCommand
from task_scheduler.gui.controllers.diagnostics_controller import (
    DiagnosticsController,
    RequestVerdict,
)
from task_scheduler.platform.macos import ProcessResult
from tests.fakes import FakeTaskWorld

JOB_LABEL = "io.github.macos-task-scheduler.user.daily-backup"


def _shell_job() -> JobDefinition:
    return make_job(
        command=ShellCommand(executable=Path("/bin/zsh"), arguments=["-c", "true"])
    )


def _broken(job: JobDefinition) -> JobDefinition:
    """A job whose label fails validation, bypassing the model's checks."""
    data = job.model_dump()
    data["label"] = "bad label"
    return JobDefinition.model_construct(**data)


class TestRequestTest:
    def test_accepts_valid_job(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        controller = DiagnosticsController(world.services, {})
        assert controller.request_test(_shell_job()) is RequestVerdict.ACCEPTED
        assert controller.busy

    def test_refuses_second_request_while_busy(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        controller = DiagnosticsController(world.services, {})
        assert controller.request_test(_shell_job()) is RequestVerdict.ACCEPTED
        assert controller.request_test(_shell_job()) is RequestVerdict.BUSY

    def test_refuses_invalid_job(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        controller = DiagnosticsController(world.services, {})
        assert controller.request_test(_broken(_shell_job())) is RequestVerdict.INVALID_JOB
        assert not controller.busy

    def test_finish_clears_busy(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        controller = DiagnosticsController(world.services, {})
        controller.request_test(_shell_job())
        controller.execute()
        controller.finish()
        assert not controller.busy


class TestExecute:
    def test_execute_returns_direct_test_result(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(
            tmp_path, test=ProcessResult(exit_code=0, stdout="test-out")
        )
        job = _shell_job()
        controller = DiagnosticsController(world.services, {})
        controller.request_test(job)
        outcome = controller.execute()
        assert outcome.label == JOB_LABEL
        assert outcome.error is None
        assert outcome.is_success
        assert isinstance(outcome.result, DirectTestResult)
        assert outcome.result.process.stdout == "test-out"

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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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
    def test_read_logs_returns_job_logs(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        out = tmp_path / "out.log"
        out.write_text("job stdout\n")
        job = make_job(logging=LoggingConfig(stdout_path=out, stderr_path=None))
        controller = DiagnosticsController(world.services, {})
        outcome = controller.read_logs(job)
        assert outcome.error is None
        assert outcome.logs is not None
        assert outcome.logs.stdout.content == "job stdout\n"
        assert outcome.logs.stderr.path is None

    def test_read_logs_unconfigured_has_no_paths(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        controller = DiagnosticsController(world.services, {})
        outcome = controller.read_logs(_shell_job())
        assert outcome.error is None
        assert outcome.logs is not None
        assert outcome.logs.stdout.path is None
        assert outcome.logs.stderr.path is None

    def test_read_logs_invalid_job_is_error(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        controller = DiagnosticsController(world.services, {})
        outcome = controller.read_logs(_broken(_shell_job()))
        assert outcome.logs is None
        assert outcome.error is not None


class TestCompareEnvironment:
    def test_compare_uses_gui_environment_snapshot(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job(
            environment=EnvironmentConfig(variables={"JOB_ONLY": "2", "PATH": "/job"})
        )
        controller = DiagnosticsController(
            world.services, {"TERM_ONLY": "1", "PATH": "/term"}
        )
        outcome = controller.compare_environment(job)
        assert outcome.error is None
        assert outcome.difference is not None
        assert outcome.difference.terminal_only == {"TERM_ONLY": "1"}
        assert outcome.difference.scheduled_only == {"JOB_ONLY": "2"}
        assert outcome.difference.different == {"PATH": ("/term", "/job")}

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
