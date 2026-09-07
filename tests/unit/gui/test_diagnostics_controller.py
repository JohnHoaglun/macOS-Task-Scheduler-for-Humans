"""Tests for the diagnostics controller (pure Python, no Qt)."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest
from tests.fakes import FakeTaskWorld

from conftest import make_job
from task_scheduler.domain import JobDefinition
from task_scheduler.domain.command import ShellCommand
from task_scheduler.gui.controllers.diagnostics_controller import (
    DiagnosticsController,
)
from task_scheduler.platform.macos import ProcessResult

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
