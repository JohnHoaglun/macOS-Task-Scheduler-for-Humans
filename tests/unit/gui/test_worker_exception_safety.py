"""Tests for worker-thread exception safety (finished signal always emitted)."""

from __future__ import annotations

from typing import cast

from pytestqt.qtbot import QtBot

from task_scheduler.gui.controllers.diagnostics_controller import DiagnosticsController
from task_scheduler.gui.controllers.diagnostics_worker import DiagnosticsWorker
from task_scheduler.gui.controllers.lifecycle_controller import LifecycleController
from task_scheduler.gui.controllers.lifecycle_worker import LifecycleWorker


class TestLifecycleWorkerExceptionSafety:
    def test_emits_finished_when_execute_raises(self, qtbot: QtBot) -> None:
        controller = _raise_on_execute()
        worker = LifecycleWorker(cast(LifecycleController, controller))
        emitted: list[object] = []
        worker.finished.connect(lambda value: emitted.append(value))
        worker.run()
        assert len(emitted) == 1
        assert emitted[0] is None
        assert not controller.busy

    def test_emits_finished_when_execute_succeeds(self, qtbot: QtBot) -> None:
        controller = _return_outcome("ok")
        worker = LifecycleWorker(cast(LifecycleController, controller))
        emitted: list[object] = []
        worker.finished.connect(lambda value: emitted.append(value))
        worker.run()
        assert len(emitted) == 1
        assert emitted[0] == "ok"
        assert not controller.busy


class TestDiagnosticsWorkerExceptionSafety:
    def test_emits_finished_when_execute_raises(self, qtbot: QtBot) -> None:
        controller = _raise_on_execute()
        worker = DiagnosticsWorker(cast(DiagnosticsController, controller))
        emitted: list[object] = []
        worker.finished.connect(lambda value: emitted.append(value))
        worker.run()
        assert len(emitted) == 1
        assert emitted[0] is None
        assert not controller.busy

    def test_emits_finished_when_execute_succeeds(self, qtbot: QtBot) -> None:
        controller = _return_outcome("ok")
        worker = DiagnosticsWorker(cast(DiagnosticsController, controller))
        emitted: list[object] = []
        worker.finished.connect(lambda value: emitted.append(value))
        worker.run()
        assert len(emitted) == 1
        assert emitted[0] == "ok"
        assert not controller.busy


class _FakeController:
    def __init__(self, execute_result: object | None, execute_exc: Exception | None) -> None:
        self._execute_result = execute_result
        self._execute_exc = execute_exc
        self.busy = True

    def execute(self) -> object:
        if self._execute_exc is not None:
            raise self._execute_exc
        return self._execute_result

    def finish(self) -> None:
        self.busy = False


def _raise_on_execute() -> _FakeController:
    return _FakeController(None, RuntimeError("boom"))


def _return_outcome(value: object) -> _FakeController:
    return _FakeController(value, None)
