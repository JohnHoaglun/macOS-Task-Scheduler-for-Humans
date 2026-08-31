"""Tests for the GUI entry point (offscreen Qt)."""

from __future__ import annotations

import runpy
import tomllib
from pathlib import Path
from typing import NoReturn

import pytest
from PySide6 import QtWidgets
from pytestqt.qtbot import QtBot

import task_scheduler.bootstrap as bootstrap
from task_scheduler.application.task_command_service import TaskListing
from task_scheduler.gui import app as app_module
from task_scheduler.gui import main_window
from task_scheduler.gui.app import create_main_window
from task_scheduler.gui.main_window import MainWindow


class _EmptyServices:
    """Duck-typed TaskCommandService: empty discovery, inspect never used."""

    def list_agents(self) -> list[TaskListing]:
        return []

    def inspect_discovered(self, path: Path) -> NoReturn:
        raise NotImplementedError


class _FakeApp:
    """Stands in for QApplication: records the exec call, returns code 42."""

    def __init__(self, argv: list[str]) -> None:
        self.argv = argv
        self.exec_called = False

    def exec(self) -> int:
        self.exec_called = True
        return 42


def test_create_main_window_returns_main_window(qtbot: QtBot) -> None:
    win = create_main_window(_EmptyServices())
    qtbot.addWidget(win)
    assert isinstance(win, MainWindow)


def test_main_returns_event_loop_exit_code(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _EmptyServices()
    monkeypatch.setattr(app_module, "QApplication", _FakeApp)
    monkeypatch.setattr(app_module, "build_services", lambda: stub)
    assert app_module.main() == 42


class _FakeWindow:
    """Stands in for MainWindow: records show, creates no C++ widget."""

    def __init__(self, *controllers: object) -> None:
        self.shown = False

    def show(self) -> None:
        self.shown = True


def test_main_module_launcher_exits_with_return_code(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``__main__`` launcher exits with the event-loop exit code.

    ``QApplication.instance()`` must keep working: pytest-qt processes events
    after every test and resolves the class through the module attribute.
    """
    real_qapplication = QtWidgets.QApplication

    class _FakeAppWithInstance(_FakeApp):
        @classmethod
        def instance(cls) -> object:
            return real_qapplication.instance()

    stub = _EmptyServices()
    monkeypatch.setattr(QtWidgets, "QApplication", _FakeAppWithInstance)
    monkeypatch.setattr(bootstrap, "build_services", lambda: stub)
    monkeypatch.setattr(bootstrap, "gui_environment", lambda: {})
    monkeypatch.setattr(main_window, "MainWindow", _FakeWindow)
    app_file = Path(__file__).resolve().parents[3] / "src" / "task_scheduler" / "gui" / "app.py"
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path(str(app_file), run_name="__main__")
    assert excinfo.value.code == 42


def test_scripts_entry_points() -> None:
    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    with pyproject.open("rb") as handle:
        data = tomllib.load(handle)
    assert data["project"]["scripts"]["mactask-gui"] == "task_scheduler.gui.app:main"
