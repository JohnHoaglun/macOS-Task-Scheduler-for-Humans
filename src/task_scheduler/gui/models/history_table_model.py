"""Qt item model backing the execution-history table."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
)

from task_scheduler.application.history_models import HistoryEvent
from task_scheduler.gui.presenters.history_presenter import (
    format_event_details,
    format_event_kind,
    format_event_outcome,
    format_event_time,
)

__all__ = ["HistoryTableModel", "COLUMNS"]

COLUMNS: tuple[str, ...] = ("Time", "Type", "Result", "Details")

_DEFAULT_INDEX: QModelIndex = QModelIndex()


class HistoryTableModel(QAbstractTableModel):
    """Read-only history rows: one event per row, newest first."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._events: list[HistoryEvent] = []

    def set_events(self, events: list[HistoryEvent]) -> None:
        """Replace the event list and emit a model reset."""
        self.beginResetModel()
        self._events = list(events)
        self.endResetModel()

    def events(self) -> list[HistoryEvent]:
        return self._events

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _DEFAULT_INDEX) -> int:
        return len(self._events)

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
        if index.row() < 0 or index.row() >= len(self._events):
            return None
        event = self._events[index.row()]
        column = index.column()
        if column == 0:
            return format_event_time(event)
        if column == 1:
            return format_event_kind(event.kind)
        if column == 2:
            return format_event_outcome(event.outcome)
        if column == 3:
            return format_event_details(event)
        return None
