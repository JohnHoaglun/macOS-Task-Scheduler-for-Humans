"""Main window presenting the discovered-agent browser with an inspector."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QItemSelection, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QMainWindow,
    QSplitter,
    QTreeView,
    QWidget,
)

from task_scheduler.application.job_service import JobNotFoundError
from task_scheduler.gui.controllers.discovery_controller import DiscoveryController
from task_scheduler.gui.controllers.editor_controller import EditorController
from task_scheduler.gui.models.agent_table_model import AgentTableModel
from task_scheduler.gui.widgets.agent_inspector import AgentInspector
from task_scheduler.gui.widgets.job_editor import JobEditor

__all__ = ["MainWindow"]


class MainWindow(QMainWindow):
    """Main window: a discovered-agent table on the left, an inspector on the right."""

    def __init__(
        self,
        controller: DiscoveryController,
        editor: EditorController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._editor_controller = editor
        self._editor = JobEditor(editor)
        self._model = AgentTableModel()
        self.table = QTreeView()
        self.table.setModel(self._model)
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.header().setStretchLastSection(True)
        self.inspector = AgentInspector()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(self.inspector)
        splitter.setSizes([600, 400])
        self.setCentralWidget(splitter)
        self.refresh_action = QAction("Refresh", self)
        self.refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)
        self.refresh_action.triggered.connect(self.refresh)
        self.new_task_action = QAction("New Task...", self)
        self.new_task_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_task_action.triggered.connect(self.new_task)
        self.edit_task_action = QAction("Edit Managed Task...", self)
        self.edit_task_action.triggered.connect(self.edit_managed_task)
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self.new_task_action)
        file_menu.addAction(self.edit_task_action)
        file_menu.addAction(self.refresh_action)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.refresh()

    def refresh(self) -> None:
        """Reload the agent listings, preserving the selected agent when possible."""
        outcome = self._controller.refresh()
        if outcome.error is not None:
            self._model.set_agents([])
            self.inspector.show_error(outcome.error)
            self.statusBar().showMessage(outcome.error)
            return
        if not outcome.agents:
            self._model.set_agents([])
            self.inspector.show_placeholder("No tasks found.")
            self.statusBar().clearMessage()
            return
        previous = self._selected_path()
        self._model.set_agents(outcome.agents)
        row = self._row_for_path(previous)
        self.table.setCurrentIndex(self.table.model().index(row, 0))
        self.statusBar().clearMessage()

    def new_task(self) -> None:
        """Open the editor for a new managed task and refresh on save."""
        self._editor.open_new()
        self._editor.exec()
        if self._editor.saved_path is not None:
            self.refresh()

    def edit_managed_task(self) -> None:
        """Open the editor for the selected managed task and refresh on save."""
        row = self.table.currentIndex().row()
        listing = self._model.listing_at(row) if row >= 0 else None
        if listing is None or not listing.managed:
            self.statusBar().showMessage("Select a managed task to edit it.")
            return
        job = listing.parsed.job
        if job is None:
            self.statusBar().showMessage("This task cannot be parsed for editing.")
            return
        try:
            resolved = self._editor_controller.resolve(job.label)
        except JobNotFoundError:
            self.statusBar().showMessage("This task is not in the task catalog.")
            return
        self._editor.open_existing(resolved)
        self._editor.exec()
        if self._editor.saved_path is not None:
            self.refresh()

    def _selected_path(self) -> Path | None:
        """Path of the currently selected agent, or None when nothing is selected."""
        row = self.table.currentIndex().row()
        listing = self._model.listing_at(row) if row >= 0 else None
        return listing.path if listing is not None else None

    def _row_for_path(self, path: Path | None) -> int:
        """First row holding the given path, else row 0."""
        if path is None:
            return 0
        for row in range(self._model.rowCount()):
            listing = self._model.listing_at(row)
            if listing is not None and listing.path == path:
                return row
        return 0

    def _on_selection_changed(self, selected: QItemSelection, _deselected: QItemSelection) -> None:
        """Inspect the selected agent, or show a placeholder when the selection is empty."""
        rows = sorted({index.row() for index in selected.indexes()})
        if not rows:
            self.inspector.show_placeholder("Select a task to inspect its details.")
            return
        listing = self._model.listing_at(rows[0])
        if listing is None:
            return
        result = self._controller.inspect(listing)
        if result.error is not None:
            self.inspector.show_error(result.error)
            return
        assert result.report is not None
        self.inspector.show_agent(listing, result.report)
