"""Tests for the universal external-control worker dispatch."""

from __future__ import annotations

from pathlib import Path

from pytestqt.qtbot import QtBot
from tests.fakes import FakeTaskWorld

from task_scheduler.gui.controllers.external_control_worker import (
    ExternalControlRequest,
    ExternalControlWorker,
)


class TestExternalControlWorker:
    def test_unknown_kind_emits_value_error(self, tmp_path: Path, qtbot: QtBot) -> None:
        world = FakeTaskWorld(tmp_path)
        request = ExternalControlRequest(kind="not-a-kind", path=Path("x.plist"))
        worker = ExternalControlWorker(world.services, request)
        emitted: list[object] = []
        worker.finished.connect(lambda value: emitted.append(value))
        worker.run()
        assert len(emitted) == 1
        assert isinstance(emitted[0], ValueError)
