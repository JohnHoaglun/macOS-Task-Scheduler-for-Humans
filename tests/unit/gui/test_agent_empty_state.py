"""Tests for the agent empty-state widget (offscreen Qt)."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton
from pytestqt.qtbot import QtBot

from task_scheduler.gui.widgets.agent_empty_state import AgentEmptyState


def _e(qtbot: QtBot) -> AgentEmptyState:
    w = AgentEmptyState()
    qtbot.addWidget(w)
    w.show()
    return w


class TestCases:
    def test_no_source(self, qtbot: QtBot) -> None:
        w = _e(qtbot)
        w.set_counts(0, 0)
        m, b = w.findChild(QLabel, "empty-message"), w.findChild(QPushButton, "empty-clear-filters")
        assert m.text() == "No tasks found." and b.isHidden() and w.isVisible()

    def test_no_proxy(self, qtbot: QtBot) -> None:
        w = _e(qtbot)
        w.set_counts(5, 0)
        m, b = w.findChild(QLabel, "empty-message"), w.findChild(QPushButton, "empty-clear-filters")
        assert m.text() == "No matching tasks." and b.isVisible() and w.isVisible()

    def test_proxy_rows_hidden(self, qtbot: QtBot) -> None:
        w = _e(qtbot)
        w.set_counts(3, 2)
        assert not w.isVisible()
