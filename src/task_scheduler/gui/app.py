"""GUI entry point: production composition root plus main window launcher."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from task_scheduler.application.task_command_service import TaskCommandService
from task_scheduler.bootstrap import build_services, gui_environment
from task_scheduler.gui.controllers.diagnostics_controller import DiagnosticsController
from task_scheduler.gui.controllers.discovery_controller import DiscoveryController
from task_scheduler.gui.controllers.editor_controller import EditorController
from task_scheduler.gui.controllers.lifecycle_controller import LifecycleController
from task_scheduler.gui.main_window import MainWindow

__all__ = ["create_main_window", "main"]


def create_main_window(services: TaskCommandService) -> MainWindow:
    """Create the main window wired to the given application services."""
    return MainWindow(
        DiscoveryController(services),
        EditorController(services),
        LifecycleController(services),
        DiagnosticsController(services, gui_environment()),
    )


def main() -> int:
    """Build the production services, show the main window, and return on close."""
    app = QApplication(sys.argv)
    window = create_main_window(build_services())
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
