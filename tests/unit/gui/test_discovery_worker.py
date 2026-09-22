"""Tests for the discovery refresh worker."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import NoReturn, cast

import pytest
from pytestqt.qtbot import QtBot
from tests.fakes import FakeTaskWorld

from conftest import make_job
from task_scheduler.gui.controllers.discovery_controller import (
    DiscoveryController,
    RefreshOutcome,
)
from task_scheduler.gui.controllers.discovery_worker import (
    DISCOVERY_FAILED_MESSAGE,
    DiscoveryWorker,
)


class _RaisingController:
    """Duck-typed DiscoveryController: refresh always raises."""

    def refresh(self) -> NoReturn:
        raise RuntimeError("boom")


def _run(worker: DiscoveryWorker) -> RefreshOutcome:
    emitted: list[object] = []
    worker.finished.connect(lambda value: emitted.append(value))
    worker.run()
    assert len(emitted) == 1
    return cast(RefreshOutcome, emitted[0])


class TestDiscoveryWorker:
    def test_success_emits_controller_outcome(
        self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        world.manage(make_job())
        outcome = _run(DiscoveryWorker(DiscoveryController(world.services)))
        assert outcome.error is None
        assert outcome.diagnostics == ()
        assert [listing.job.label for listing in outcome.agents] == [
            make_job().label
        ]

    def test_unexpected_failure_emits_typed_outcome(
        self, qtbot: QtBot, caplog: pytest.LogCaptureFixture) -> None:
        worker = DiscoveryWorker(
            cast(DiscoveryController, _RaisingController())
        )
        with caplog.at_level(
            logging.ERROR, logger="task_scheduler.gui.controllers.discovery_worker"
        ):
            outcome = _run(worker)
        assert outcome.agents is None
        assert outcome.error == DISCOVERY_FAILED_MESSAGE
        assert sum(1 for record in caplog.records if record.levelno == logging.ERROR) == 1
