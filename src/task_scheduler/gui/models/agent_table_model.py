"""Qt item model backing the agent discovery table."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
)

from task_scheduler.application.task_command_service import TaskListing
from task_scheduler.gui.presenters.agent_presenter import (
    classify,
    format_command,
    format_name,
    format_schedule,
    format_state,
)

__all__ = ["AgentTableModel", "COLUMNS"]

COLUMNS: tuple[str, ...] = ("Name", "Command", "Schedule", "Classification", "State")

_DEFAULT_INDEX: QModelIndex = QModelIndex()


class AgentTableModel(QAbstractTableModel):
    """Read-only task rows: discovered LaunchAgents and saved catalog jobs."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._agents: list[TaskListing] = []

    def set_agents(self, agents: Sequence[TaskListing]) -> None:
        self.beginResetModel()
        self._agents = list(agents)
        self.endResetModel()

    def agents(self) -> list[TaskListing]:
        return self._agents

    def listing_at(self, row: int) -> TaskListing | None:
        if row < 0 or row >= len(self._agents):
            return None
        return self._agents[row]

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _DEFAULT_INDEX) -> int:
        return len(self._agents)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = _DEFAULT_INDEX) -> int:
        return len(COLUMNS)

    def header(self, section: int, orientation: Qt.Orientation) -> object:
        if orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        return str(section + 1)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        listing = self.listing_at(index.row())
        if listing is None:
            return None
        column = index.column()
        if column == 0:
            return format_name(listing)
        if column == 1:
            return format_command(listing)
        if column == 2:
            return format_schedule(listing)
        if column == 3:
            return classify(listing).value
        if column == 4:
            return format_state(listing)
        return None
