"""Tests for the GUI entry point (offscreen Qt)."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import NoReturn

import pytest
from pytestqt.qtbot import QtBot

from task_scheduler.application.task_command_service import AgentListing
from task_scheduler.gui import app as app_module
from task_scheduler.gui.app import create_main_window
from task_scheduler.gui.main_window import MainWindow


class _EmptyServices:
    """Duck-typed TaskCommandService: empty discovery, inspect never used."""

    def list_agents(self) -> list[AgentListing]:
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


def test_main_exits_with_app_return_code(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _EmptyServices()
    monkeypatch.setattr(app_module, "QApplication", _FakeApp)
    monkeypatch.setattr(app_module, "build_services", lambda: stub)
    with pytest.raises(SystemExit) as excinfo:
        app_module.main()
    assert excinfo.value.code == 42


def test_scripts_entry_points() -> None:
    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    with pyproject.open("rb") as handle:
        data = tomllib.load(handle)
    assert data["project"]["scripts"]["mactask-gui"] == "task_scheduler.gui.app:main"
