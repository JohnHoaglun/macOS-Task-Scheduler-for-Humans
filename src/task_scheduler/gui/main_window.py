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

from task_scheduler.gui.controllers.discovery_controller import DiscoveryController
from task_scheduler.gui.models.agent_table_model import AgentTableModel
from task_scheduler.gui.widgets.agent_inspector import AgentInspector

__all__ = ["MainWindow"]


class MainWindow(QMainWindow):
    """Main window: a discovered-agent table on the left, an inspector on the right."""

    def __init__(self, controller: DiscoveryController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
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
        self.menuBar().addMenu("File").addAction(self.refresh_action)
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
