"""Tests for the diagnostics worker (QObject, offscreen)."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest

from conftest import make_job
from task_scheduler.application.test_service import DirectTestResult
from task_scheduler.domain import JobDefinition
from task_scheduler.domain.command import ShellCommand
from task_scheduler.gui.controllers.diagnostics_controller import (
    DiagnosticsController,
    RequestVerdict,
    TestOutcome,
)
from task_scheduler.gui.controllers.diagnostics_worker import DiagnosticsWorker
from tests.fakes import FakeTaskWorld

JOB_LABEL = "io.github.macos-task-scheduler.user.daily-backup"


def _shell_job() -> JobDefinition:
    return make_job(
        command=ShellCommand(executable=Path("/bin/zsh"), arguments=["-c", "true"])
    )


class TestDiagnosticsWorker:
    def test_run_emits_success_outcome_and_restores_busy(
        self, tmp_path: Path
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        job = _shell_job()
        controller = DiagnosticsController(world.services, {})
        worker = DiagnosticsWorker(controller)
        assert controller.request_test(job) is RequestVerdict.ACCEPTED
        outcomes: list[TestOutcome] = []
        worker.finished.connect(lambda outcome: outcomes.append(outcome))
        worker.run()
        assert not controller.busy
        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome.label == JOB_LABEL
        assert outcome.error is None
        assert outcome.is_success
        assert isinstance(outcome.result, DirectTestResult)

    def test_run_emits_error_outcome_and_restores_busy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        job = _shell_job()
        controller = DiagnosticsController(world.services, {})

        def boom(target: JobDefinition, *, detection: object = None) -> NoReturn:
            raise RuntimeError("boom")

        monkeypatch.setattr(world.services, "test_job", boom)
        worker = DiagnosticsWorker(controller)
        assert controller.request_test(job) is RequestVerdict.ACCEPTED
        outcomes: list[TestOutcome] = []
        worker.finished.connect(lambda outcome: outcomes.append(outcome))
        worker.run()
        assert not controller.busy
        assert len(outcomes) == 1
        assert outcomes[0].error == "boom"
        assert outcomes[0].result is None
