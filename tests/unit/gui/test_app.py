"""Tests for the GUI entry point (offscreen Qt)."""

from __future__ import annotations

import runpy
import threading
from pathlib import Path
from typing import NoReturn

import pytest
from PySide6 import QtCore, QtWidgets
from pytestqt.qtbot import QtBot

import task_scheduler.bootstrap as bootstrap
from task_scheduler.application import app_logging as app_logging_mod
from task_scheduler.application.task_command_service import TaskListing
from task_scheduler.gui import app as gui_app
from task_scheduler.gui import main_window
from task_scheduler.gui import qt_message_logging as qt_msg_mod
from task_scheduler.gui.app import create_main_window, startup_window_size
from task_scheduler.gui.main_window import MainWindow


class _EmptyServices:
    """Duck-typed TaskCommandService: empty discovery, inspect never used."""

    def list_agents(self) -> list[TaskListing]:
        return []

    def inspect_discovered(self, path: Path) -> NoReturn:
        raise NotImplementedError


class _FakeApp(QtCore.QObject):
    """Stands in for QApplication: records the exec call, returns code 42."""

    def __init__(self, argv: list[str]) -> None:
        super().__init__()
        self.argv = argv
        self.exec_called = False

    def exec(self) -> int:
        self.exec_called = True
        return 42

    def primaryScreen(self) -> None:
        return None


def test_create_main_window_returns_main_window(qtbot: QtBot) -> None:
    win = create_main_window(_EmptyServices())
    qtbot.addWidget(win)
    assert isinstance(win, MainWindow)


class _FakeStatus:
    """Stands in for QStatusBar: records persistent messages."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, message: str) -> None:
        self.messages.append(message)


class _FakeWindow:
    """Stands in for MainWindow: records show, creates no C++ widget."""

    def __init__(self, *controllers: object, **options: object) -> None:
        self.shown = False
        self.status = _FakeStatus()

    def show(self) -> None:
        self.shown = True

    def resize(self, _size: object) -> None:
        pass

    def statusBar(self) -> _FakeStatus:
        return self.status


def test_startup_window_size_is_bounded_to_usable_display() -> None:
    assert startup_window_size(QtCore.QSize(1600, 1000)) == QtCore.QSize(1280, 900)
    assert startup_window_size(QtCore.QSize(1100, 800)) == QtCore.QSize(1100, 800)


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
    # Keep the entry point's logging/crash wiring out of the test's real env.
    monkeypatch.setattr(app_logging_mod, "configure_logging", lambda log_path=None: Path("app.log"))
    monkeypatch.setattr(app_logging_mod, "install_crash_hooks", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_logging_mod, "logging_degraded_reason", lambda: None)
    monkeypatch.setattr(qt_msg_mod, "install_qt_message_handler", lambda: None)
    app_file = Path(__file__).resolve().parents[3] / "src" / "task_scheduler" / "gui" / "app.py"
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path(str(app_file), run_name="__main__")
    assert excinfo.value.code == 42


class _FakeMessageBox:
    """Records QMessageBox.critical/warning calls instead of showing modal dialogs."""

    def __init__(self) -> None:
        self.critical_calls: list[tuple[object, str, str]] = []
        self.warning_calls: list[tuple[object, str, str]] = []

    def critical(self, parent: object, title: str, text: str) -> int:
        self.critical_calls.append((parent, title, text))
        return 0

    def warning(self, parent: object, title: str, text: str) -> int:
        self.warning_calls.append((parent, title, text))
        return 0


def test_show_crash_dialog_displays_log_path(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeMessageBox()
    monkeypatch.setattr(gui_app, "QMessageBox", fake)
    gui_app._show_crash_dialog(Path("/tmp/app.log"))
    assert len(fake.critical_calls) == 1
    parent, title, text = fake.critical_calls[0]
    assert parent is None  # top-level dialog (QApplication is not a QWidget parent)
    assert title == "Unexpected error"
    assert "/tmp/app.log" in text


class _AppWithQuit(QtCore.QObject):
    def __init__(self) -> None:
        super().__init__()
        self.quit_called = False

    def quit(self) -> None:
        self.quit_called = True


def test_crash_callback_shows_dialog_and_quits(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeMessageBox()
    monkeypatch.setattr(gui_app, "QMessageBox", fake)
    app = _AppWithQuit()
    gui_app._make_crash_callback(app, Path("/tmp/app.log"))()
    assert len(fake.critical_calls) == 1
    assert app.quit_called


def test_crash_callback_without_app_shows_dialog_only(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeMessageBox()
    monkeypatch.setattr(gui_app, "QMessageBox", fake)
    gui_app._make_crash_callback(None, Path("/tmp/app.log"))()
    assert len(fake.critical_calls) == 1


def test_main_degraded_logging_shows_warning_and_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    box = _FakeMessageBox()
    window = _FakeWindow()
    monkeypatch.setattr(gui_app, "QApplication", _FakeApp)
    monkeypatch.setattr(gui_app, "install_qt_message_handler", lambda: None)
    monkeypatch.setattr(gui_app, "configure_logging", lambda: Path("app.log"))
    monkeypatch.setattr(gui_app, "logging_degraded_reason", lambda: "log-write-failed")
    monkeypatch.setattr(gui_app, "install_crash_hooks", lambda on_crash=None, log_path=None: None)
    monkeypatch.setattr(gui_app, "create_main_window", lambda _services: window)
    monkeypatch.setattr(gui_app, "QMessageBox", box)
    assert gui_app.main() == 42
    assert box.warning_calls == [(None, "Logging degraded", gui_app._degraded_logging_notice())]
    assert window.status.messages == [gui_app._degraded_logging_notice()]
    assert window.shown


def test_crash_dialog_and_callback_are_degraded_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeMessageBox()
    monkeypatch.setattr(gui_app, "QMessageBox", fake)
    gui_app._show_crash_dialog(Path("/tmp/app.log"), degraded=True)
    gui_app._make_crash_callback(None, Path("/tmp/app.log"), "log-write-failed")()
    assert len(fake.critical_calls) == 2
    for _parent, _title, text in fake.critical_calls:
        assert "/tmp/app.log" not in text
        assert "may not have been saved" in text


def test_crash_from_worker_thread_marshals_dialog_to_gui_thread(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[tuple[Path, bool, QtCore.QThread]] = []

    def _record(log_path: Path, degraded: bool) -> None:
        shown.append((log_path, degraded, QtCore.QThread.currentThread()))

    class _SpyApp(QtCore.QObject):
        def __init__(self) -> None:
            super().__init__()
            self.quit_requested = False

        def quit(self) -> None:
            self.quit_requested = True

    monkeypatch.setattr(gui_app, "_show_crash_dialog", _record)
    app = _SpyApp()
    callback = gui_app._make_crash_callback(app, Path("/tmp/app.log"))
    worker = threading.Thread(target=callback)
    worker.start()
    worker.join()
    qtbot.waitUntil(lambda: len(shown) == 1)
    log_path, degraded, gui_thread = shown[0]
    assert (log_path, degraded) == (Path("/tmp/app.log"), False)
    assert gui_thread is QtCore.QCoreApplication.instance().thread()
    assert app.quit_requested
