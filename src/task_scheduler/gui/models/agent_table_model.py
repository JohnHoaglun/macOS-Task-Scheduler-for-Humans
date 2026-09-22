"""Qt item model backing the agent discovery table."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
)

from task_scheduler.application.task_command_service import TaskListing
from task_scheduler.domain.formatting import format_command_argv
from task_scheduler.gui.presenters.agent_badge_presenter import AgentDimensions, dimensions
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
    quoted = "unknown" if cmd is None else format_command_argv(cmd)
    return f"{format_name(listing)} {format_label(listing)} {quoted}"


@dataclass(frozen=True)
class _RowView:
    """Per-row precomputed display data: dimensions and search haystack.

    Built once per row inside ``set_agents`` so ``data()`` is O(1) and
    ``dimensions()`` / argv quoting run exactly once per row per reset.
    """

    listing: TaskListing
    dims: AgentDimensions
    search_text: str


class AgentTableModel(QAbstractTableModel):
    """Read-only task rows: discovered LaunchAgents and saved catalog jobs."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._agents: list[TaskListing] = []
        self._row_views: list[_RowView] = []

    def set_agents(self, agents: Sequence[TaskListing]) -> None:
        self.beginResetModel()
        self._agents = list(agents)
        self._row_views = [
            _RowView(
                listing=agent, dims=dimensions(agent), search_text=_format_search_text(agent)
            )
            for agent in self._agents
        ]
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
        row = index.row()
        if row >= len(self._row_views):
            return None
        view = self._row_views[row]
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(view.listing, index.column())
        if role == ROLE_STATE:
            return view.dims.state
        if role == ROLE_INSTALLED:
            return view.dims.installed
        if role == ROLE_ENABLED:
            return view.dims.enabled
        if role == ROLE_LOADED:
            return view.dims.loaded
        if role == ROLE_COMMAND:
            return view.dims.command
        if role == ROLE_SEARCH_TEXT:
            return view.search_text
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
