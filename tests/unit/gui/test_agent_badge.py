"""Tests for the agent badge widget (offscreen Qt)."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from task_scheduler.gui.presenters.agent_badge_presenter import BadgeDescriptor
from task_scheduler.gui.widgets.agent_badge import AgentBadge


def _b(qtbot: QtBot) -> AgentBadge:
    w = AgentBadge()
    qtbot.addWidget(w)
    w.show()
    return w


class TestObjectNames:
    def test_all_names(self, qtbot: QtBot) -> None:
        w = _b(qtbot)
        assert w.objectName() == "agent-badge"
        assert w.findChild(QLabel, "agent-badge-label") is not None


class TestSetDescriptor:
    def test_all_fields(self, qtbot: QtBot) -> None:
        w = _b(qtbot)
        w.set_descriptor(BadgeDescriptor(text="Managed", accessible_name="S: M", tooltip="tip"))
        label = w.findChild(QLabel, "agent-badge-label")
        assert label.text() == "Managed"
        assert label.accessibleName() == "S: M"
        assert w.toolTip() == "tip"

    def test_no_tooltip(self, qtbot: QtBot) -> None:
        w = _b(qtbot)
        w.set_descriptor(BadgeDescriptor(text="X", accessible_name="X"))
        assert w.toolTip() == ""
