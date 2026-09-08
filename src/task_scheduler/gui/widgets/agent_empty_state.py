"""Empty-state widget shown when the agent table has no visible rows."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

__all__ = ["AgentEmptyState"]


class AgentEmptyState(QWidget):
    """Displays an empty-state message with an optional clear-filters button."""

    cleared = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("agent-empty-state")

        self._message = QLabel(self)
        self._message.setObjectName("empty-message")

        self._clear_button = QPushButton("Clear filters", self)
        self._clear_button.setObjectName("empty-clear-filters")
        self._clear_button.clicked.connect(self.cleared)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._message)
        layout.addWidget(self._clear_button)

    def set_counts(self, source_rows: int, proxy_rows: int) -> None:
        """Update the empty-state visibility based on source and proxy row counts.

        - source_rows == 0: show "No tasks found." and hide the clear button.
        - proxy_rows == 0 (with source_rows > 0): show "No matching tasks." plus
          the clear button.
        - proxy_rows > 0: hide the entire empty-state widget.
        """
        if source_rows == 0:
            self._message.setText("No tasks found.")
            self._clear_button.hide()
            self.show()
        elif proxy_rows == 0:
            self._message.setText("No matching tasks.")
            self._clear_button.show()
            self.show()
        else:
            self.hide()
