"""Focused coverage for the raw plist inspector widget."""

from PySide6.QtWidgets import QPlainTextEdit
from pytestqt.qtbot import QtBot

from task_scheduler.gui.widgets.agent_inspector import AgentInspector


def test_advanced_text_is_read_only_plain_text(qtbot: QtBot) -> None:
    inspector = AgentInspector()
    qtbot.addWidget(inspector)
    advanced = inspector.findChild(QPlainTextEdit, "advanced-text")
    assert advanced is not None
    assert advanced.isReadOnly()
