"""Panel rendering execution-history events.

The panel is task-based and outcome-driven: callers feed it controller
outcomes (for a selected managed task). It renders state only — it never
calls services itself; the Refresh button emits a signal the host wires
to the controller.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from task_scheduler.application.history_models import HistoryEvent
from task_scheduler.gui.controllers.history_controller import HistoryOutcome
from task_scheduler.gui.models.history_table_model import HistoryTableModel
from task_scheduler.gui.presenters.history_presenter import (
    HISTORY_DISCLOSURE,
    HISTORY_EMPTY,
)

__all__ = ["HistoryPanel"]


class HistoryPanel(QWidget):
    """Execution-history table with disclosure, state text, and refresh.

    Public surface: :meth:`show_history` and ``refresh_requested`` (the
    signal the host connects to the controller's synchronous query).
    """

    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("history-panel")

        self._disclosure = QLabel(HISTORY_DISCLOSURE, self)
        self._disclosure.setObjectName("history-disclosure")
        self._disclosure.setWordWrap(True)

        self._table_view = QTableView(self)
        self._table_view.setObjectName("history-table")
        self._table_view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self._table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table_view.horizontalHeader().setStretchLastSection(True)
        self._table_view.horizontalHeader().setSortIndicatorShown(False)
        self._table_model = HistoryTableModel(self._table_view)
        self._table_view.setModel(self._table_model)

        self._state_label = QLabel(self)
        self._state_label.setObjectName("history-state-text")
        self._state_label.setWordWrap(True)

        self._refresh_button = QPushButton("Refresh", self)
        self._refresh_button.setObjectName("history-refresh")
        self._refresh_button.clicked.connect(lambda _checked=False: self.refresh_requested.emit())

        layout = QVBoxLayout(self)
        layout.addWidget(self._disclosure)
        layout.addWidget(self._state_label)
        layout.addWidget(self._table_view)
        layout.addWidget(self._refresh_button)

    def show_history(self, outcome: HistoryOutcome) -> None:
        """Render the history outcome in the panel."""
        if outcome.error is not None:
            self._state_label.setText(outcome.error)
            self._table_view.hide()
            return
        if not outcome.events:
            self._state_label.setText(HISTORY_EMPTY)
            self._table_view.hide()
            return
        self._table_model.set_events(list(outcome.events))
        self._state_label.setText("")
        self._table_view.show()

    def events(self) -> list[HistoryEvent]:
        """The events currently in the table model."""
        return self._table_model.events()
