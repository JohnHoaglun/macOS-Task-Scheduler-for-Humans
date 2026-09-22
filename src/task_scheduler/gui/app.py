"""GUI entry point: production composition root plus main window launcher."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from task_scheduler.application.app_logging import (
    configure_logging,
    install_crash_hooks,
    logging_degraded_reason,
)
from task_scheduler.application.task_command_service import TaskCommandService
from task_scheduler.bootstrap import build_services, gui_environment
from task_scheduler.gui.controllers.diagnostics_controller import DiagnosticsController
from task_scheduler.gui.controllers.discovery_controller import DiscoveryController
from task_scheduler.gui.controllers.editor_controller import EditorController
from task_scheduler.gui.controllers.history_controller import HistoryController
from task_scheduler.gui.controllers.import_controller import ImportController
from task_scheduler.gui.controllers.json_transfer_controller import JsonTransferController
from task_scheduler.gui.controllers.lifecycle_controller import LifecycleController
from task_scheduler.gui.main_window import MainWindow
from task_scheduler.gui.qt_message_logging import install_qt_message_handler

__all__ = ["create_main_window", "main"]

MAIN_WINDOW_STARTUP_SIZE = QSize(1280, 900)


def startup_window_size(available_size: QSize | None) -> QSize:
    """Return the preferred startup size bounded to usable display space."""
    if available_size is None:
        return MAIN_WINDOW_STARTUP_SIZE
    return MAIN_WINDOW_STARTUP_SIZE.boundedTo(available_size)


def _degraded_logging_notice() -> str:
    """Return user-facing wording for degraded logging without revealing paths or details."""
    return "Application logging is degraded. Some details may not be saved."


def _show_degraded_logging_warning() -> None:
    """Show a one-time modal warning that logging is degraded."""
    QMessageBox.warning(None, "Logging degraded", _degraded_logging_notice())


def _show_crash_dialog(log_path: Path, degraded: bool = False) -> None:
    """Show a modal, top-level crash dialog with degraded-safe wording."""
    if degraded:
        text = "An unexpected error occurred. Details may not have been saved."
    else:
        text = f"An unexpected error occurred. Details were written to:\n{log_path}"
    QMessageBox.critical(None, "Unexpected error", text)


class _CrashDialogPoster(QObject):
    """Shows the crash dialog on the GUI thread no matter where the crash happened."""

    _request = Signal(Path, bool)

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._request.connect(self._show)

    def request(self, log_path: Path, degraded: bool) -> None:
        self._request.emit(log_path, degraded)

    def _show(self, log_path: Path, degraded: bool) -> None:
        _show_crash_dialog(log_path, degraded)


def _make_crash_callback(
    app: QApplication | None,
    log_path: Path,
    degraded_reason: str | None = None,
) -> Callable[[], None]:
    """A crash callback that shows the dialog and then quits the application."""
    degraded = degraded_reason is not None
    if app is not None:
        poster = _CrashDialogPoster(app)

        def _callback_with_app() -> None:
            poster.request(log_path, degraded)
            app.quit()

        return _callback_with_app

    def _callback() -> None:
        _show_crash_dialog(log_path, degraded)

    return _callback


def create_main_window(services: TaskCommandService) -> MainWindow:
    """Create the main window wired to the given application services."""
    return MainWindow(
        DiscoveryController(services),
        EditorController(services),
        LifecycleController(services),
        DiagnosticsController(services, gui_environment()),
        HistoryController(services),
        ImportController(services),
        services=services,
        json_transfer=JsonTransferController(services),
    )


def main() -> int:
    """Configure logging and crash capture, build services, show the window, return on close."""
    log_path = configure_logging()
    app = QApplication(sys.argv)
    install_qt_message_handler()
    degraded_reason = logging_degraded_reason()
    install_crash_hooks(
        on_crash=_make_crash_callback(app, log_path, degraded_reason), log_path=log_path
    )
    window = create_main_window(build_services())
    if degraded_reason is not None:
        _show_degraded_logging_warning()
        window.statusBar().showMessage(_degraded_logging_notice())
    screen = app.primaryScreen()
    available_size = screen.availableGeometry().size() if screen is not None else None
    window.resize(startup_window_size(available_size))
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
