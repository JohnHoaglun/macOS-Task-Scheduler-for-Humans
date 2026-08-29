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

from task_scheduler.application.task_command_service import AgentListing
from task_scheduler.gui.presenters.agent_presenter import (
    classify,
    format_command,
    format_name,
    format_parsed_support,
    format_schedule,
)

__all__ = ["AgentTableModel", "COLUMNS"]

COLUMNS: tuple[str, ...] = ("Name", "Command", "Schedule", "Classification", "Support")

_DEFAULT_INDEX: QModelIndex = QModelIndex()


class AgentTableModel(QAbstractTableModel):
    """Read-only rows for discovered LaunchAgents, kept in discovery order."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._agents: list[AgentListing] = []

    def set_agents(self, agents: Sequence[AgentListing]) -> None:
        self.beginResetModel()
        self._agents = list(agents)
        self.endResetModel()

    def agents(self) -> list[AgentListing]:
        return self._agents

    def listing_at(self, row: int) -> AgentListing | None:
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
        parsed = listing.parsed
        column = index.column()
        if column == 0:
            return format_name(listing)
        if column == 1:
            return format_command(parsed)
        if column == 2:
            return format_schedule(parsed)
        if column == 3:
            return classify(parsed, listing.managed).value
        if column == 4:
            return format_parsed_support(parsed)
        return None
