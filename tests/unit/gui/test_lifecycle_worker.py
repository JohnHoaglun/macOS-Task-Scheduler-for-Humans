"""Tests for the lifecycle worker (QObject, offscreen)."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn
from uuid import UUID

import pytest

from conftest import make_job
from task_scheduler.application.task_command_service import InstallResult, UninstallResult
from task_scheduler.gui.controllers.lifecycle_controller import (
    LifecycleAction,
    LifecycleController,
    LifecycleOutcome,
    RequestVerdict,
)
from task_scheduler.gui.controllers.lifecycle_worker import LifecycleWorker
from tests.fakes import FakeTaskWorld

EXTERNAL_ID = UUID("87654321-4321-4321-4321-432143214321")
SAVED_LABEL = "com.example.saved-only"
JOB_LABEL = "io.github.macos-task-scheduler.user.daily-backup"


class TestLifecycleWorker:
    def test_run_emits_success_outcome_and_restores_busy(
        self, tmp_path: Path
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        world.manage(make_job())
        controller = LifecycleController(world.services)
        listing = world.services.list_agents()[0]
        worker = LifecycleWorker(controller)
        assert (
            controller.request(LifecycleAction.UNINSTALL, listing)
            is RequestVerdict.ACCEPTED
        )
        outcomes: list[LifecycleOutcome] = []
        worker.finished.connect(lambda outcome: outcomes.append(outcome))
        worker.run()
        assert not controller.busy
        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome.action is LifecycleAction.UNINSTALL
        assert outcome.label == JOB_LABEL
        assert outcome.error is None
        assert isinstance(outcome.result, UninstallResult)
        assert world.launch_runner.specs[0].argv[1] == "bootout"

    def test_run_emits_error_outcome_and_restores_busy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        world.manage(make_job())
        controller = LifecycleController(world.services)
        listing = world.services.list_agents()[0]

        def boom(label: str) -> NoReturn:
            raise RuntimeError("boom")

        monkeypatch.setattr(world.services, "enable", boom)
        assert (
            controller.request(LifecycleAction.ENABLE, listing)
            is RequestVerdict.ACCEPTED
        )
        worker = LifecycleWorker(controller)
        outcomes: list[LifecycleOutcome] = []
        worker.finished.connect(lambda outcome: outcomes.append(outcome))
        worker.run()
        assert not controller.busy
        assert len(outcomes) == 1
        assert outcomes[0].action is LifecycleAction.ENABLE
        assert outcomes[0].error == "boom"
        assert outcomes[0].result is None

    def test_run_emits_install_outcome_for_saved_row(
        self, tmp_path: Path
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        world.jobs.import_job(make_job(id=EXTERNAL_ID, label=SAVED_LABEL, name="Saved Job"))
        controller = LifecycleController(world.services)
        listing = world.services.list_agents()[0]
        worker = LifecycleWorker(controller)
        assert (
            controller.request(LifecycleAction.INSTALL, listing)
            is RequestVerdict.ACCEPTED
        )
        outcomes: list[LifecycleOutcome] = []
        worker.finished.connect(lambda outcome: outcomes.append(outcome))
        worker.run()
        assert len(outcomes) == 1
        assert outcomes[0].error is None
        assert isinstance(outcomes[0].result, InstallResult)
        assert (world.la_root / f"{SAVED_LABEL}.plist").is_file()
        assert [spec.argv[1] for spec in world.launch_runner.specs] == ["bootstrap"]
