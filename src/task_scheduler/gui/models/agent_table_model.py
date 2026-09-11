"""Qt item model backing the agent discovery table."""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
)

from task_scheduler.application.task_command_service import TaskListing
from task_scheduler.domain import command_argv
from task_scheduler.gui.presenters.agent_badge_presenter import dimensions
from task_scheduler.gui.presenters.agent_presenter import (
    classify,
    format_command,
    format_label,
    format_name,
    format_schedule,
    format_state,
)

ROLE_STATE: int = Qt.ItemDataRole.UserRole + 0
ROLE_INSTALLED: int = Qt.ItemDataRole.UserRole + 1
ROLE_ENABLED: int = Qt.ItemDataRole.UserRole + 2
ROLE_LOADED: int = Qt.ItemDataRole.UserRole + 3
ROLE_COMMAND: int = Qt.ItemDataRole.UserRole + 4
ROLE_SEARCH_TEXT: int = Qt.ItemDataRole.UserRole + 5

__all__ = [
    "ROLE_COMMAND",
    "ROLE_ENABLED",
    "ROLE_INSTALLED",
    "ROLE_LOADED",
    "ROLE_SEARCH_TEXT",
    "ROLE_STATE",
    "AgentTableModel",
    "COLUMNS",
]

COLUMNS: tuple[str, ...] = ("Name", "Command", "Schedule", "Classification", "State")

_DEFAULT_INDEX: QModelIndex = QModelIndex()


def _format_search_text(listing: TaskListing) -> str:
    """Produce the haystack string for ROLE_SEARCH_TEXT."""
    parsed = listing.parsed
    if parsed is not None and parsed.job is not None:
        cmd = parsed.job.command
    elif listing.job is not None:
        cmd = listing.job.command
    else:
        cmd = None
    quoted = (
        "unknown"
        if cmd is None
        else " ".join(shlex.quote(arg) for arg in command_argv(cmd))
    )
    return f"{format_name(listing)} {format_label(listing)} {quoted}"


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

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole.value,
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(COLUMNS):
                return COLUMNS[section]
            return None
        return super().headerData(section, orientation, role)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if not index.isValid():
            return None
        listing = self.listing_at(index.row())
        if listing is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(listing, index.column())
        dims = dimensions(listing)
        if role == ROLE_STATE:
            return dims.state
        if role == ROLE_INSTALLED:
            return dims.installed
        if role == ROLE_ENABLED:
            return dims.enabled
        if role == ROLE_LOADED:
            return dims.loaded
        if role == ROLE_COMMAND:
            return dims.command
        if role == ROLE_SEARCH_TEXT:
            return _format_search_text(listing)
        return None

    def _display(self, listing: TaskListing, column: int) -> object:
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


