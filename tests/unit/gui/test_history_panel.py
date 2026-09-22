"""Tests for the history panel widget (offscreen Qt)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from PySide6.QtWidgets import QToolButton, QWidget
from pytestqt.qtbot import QtBot

from task_scheduler.application.history_models import (
    HistoryEvent,
    HistoryEventKind,
)
from task_scheduler.application.history_models import (
    HistoryOutcome as HistoryOutcomeEnum,
)
from task_scheduler.gui.controllers.history_controller import (
    HistoryOutcome,
)
from task_scheduler.gui.widgets.history_panel import HistoryPanel


def _event(**overrides) -> HistoryEvent:
    kwargs = {
        "created_at": datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC),
        "job_id": UUID("00000000-0000-4000-8000-000000000001"),
        "label": "com.example.job",
        "kind": HistoryEventKind.DIRECT_TEST,
        "outcome": HistoryOutcomeEnum.SUCCESS,
        "exit_code": 0,
        "duration_seconds": 1.250,
        "loaded": None,
        "diagnostic_codes": (),
    }
    kwargs.update(overrides)
    return HistoryEvent(**kwargs)


class TestShowHistoryEvents:
    def test_panel_events_accessor(self, qtbot: QtBot):
        panel = HistoryPanel()
        qtbot.addWidget(panel)
        assert panel.events() == []
        events = [_event()]
        panel.show_history(HistoryOutcome(label="test", events=tuple(events)))
        assert panel.events() == events


class TestCollapsedByDefault:
    def test_show_history_never_expands(self, qtbot: QtBot) -> None:
        """Rendering events on selection keeps the panel collapsed."""
        panel = HistoryPanel()
        qtbot.addWidget(panel)
        panel.show_history(HistoryOutcome(label="test", events=(_event(),)))
        toggle = panel.findChild(QToolButton, "history-toggle")
        content = panel.findChild(QWidget, "history-content")
        assert toggle is not None and not toggle.isChecked()
        assert content is not None and content.isHidden()
