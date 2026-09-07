"""Tests for the history panel widget (offscreen Qt)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

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
from task_scheduler.gui.presenters.history_presenter import (
    HISTORY_DISCLOSURE,
    HISTORY_EMPTY,
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


class TestPanelConstruction:
    def test_has_disclosure(self, qtbot: QtBot):
        panel = HistoryPanel()
        qtbot.addWidget(panel)
        assert panel.findChild(object, "history-disclosure").text() == HISTORY_DISCLOSURE

    def test_has_table_view(self, qtbot: QtBot):
        panel = HistoryPanel()
        qtbot.addWidget(panel)
        tv = panel.findChild(object, "history-table")
        assert tv is not None

    def test_has_state_label(self, qtbot: QtBot):
        panel = HistoryPanel()
        qtbot.addWidget(panel)
        sl = panel.findChild(object, "history-state-text")
        assert sl is not None

    def test_has_refresh_button(self, qtbot: QtBot):
        panel = HistoryPanel()
        qtbot.addWidget(panel)
        btn = panel.findChild(object, "history-refresh")
        assert btn is not None
        assert btn.text() == "Refresh"

    def test_refresh_button_emits_signal(self, qtbot: QtBot):
        panel = HistoryPanel()
        qtbot.addWidget(panel)
        clicks: list[bool] = []
        panel.refresh_requested.connect(lambda: clicks.append(True))
        panel._refresh_button.click()
        assert len(clicks) == 1

    def test_object_name(self, qtbot: QtBot):
        panel = HistoryPanel()
        qtbot.addWidget(panel)
        assert panel.objectName() == "history-panel"


class TestShowHistoryError:
    def test_error_shows_error_text(self, qtbot: QtBot):
        panel = HistoryPanel()
        qtbot.addWidget(panel)
        outcome = HistoryOutcome(label="test", events=(), error="boom")
        panel.show_history(outcome)
        assert panel.findChild(object, "history-state-text").text() == "boom"

    def test_error_hides_table(self, qtbot: QtBot):
        panel = HistoryPanel()
        qtbot.addWidget(panel)
        outcome = HistoryOutcome(label="test", events=(), error="boom")
        panel.show_history(outcome)
        assert not panel.findChild(object, "history-table").isVisible()

    def test_disclosure_present(self, qtbot: QtBot):
        panel = HistoryPanel()
        qtbot.addWidget(panel)
        panel.show_history(HistoryOutcome(label="test", events=(), error="boom"))
        assert panel.findChild(object, "history-disclosure") is not None


class TestShowHistoryEmpty:
    def test_empty_shows_empty_message(self, qtbot: QtBot):
        panel = HistoryPanel()
        qtbot.addWidget(panel)
        panel.show_history(HistoryOutcome(label="test", events=()))
        assert panel.findChild(object, "history-state-text").text() == HISTORY_EMPTY

    def test_empty_hides_table(self, qtbot: QtBot):
        panel = HistoryPanel()
        qtbot.addWidget(panel)
        panel.show_history(HistoryOutcome(label="test", events=()))
        assert not panel.findChild(object, "history-table").isVisible()


class TestShowHistoryEvents:
    def test_events_populates_table(self, qtbot: QtBot):
        panel = HistoryPanel()
        qtbot.addWidget(panel)
        events = [
            _event(kind=HistoryEventKind.DIRECT_TEST),
            _event(kind=HistoryEventKind.MANUAL_RUN),
        ]
        panel.show_history(HistoryOutcome(label="test", events=tuple(events)))
        table_model = panel._table_view.model()
        assert table_model.rowCount() == 2
        assert panel.findChild(object, "history-table") is not None

    def test_events_clears_state_text(self, qtbot: QtBot):
        panel = HistoryPanel()
        qtbot.addWidget(panel)
        events = [_event()]
        panel.show_history(HistoryOutcome(label="test", events=tuple(events)))
        assert panel.findChild(object, "history-state-text").text() == ""

    def test_events_preserves_order_newest_first(self, qtbot: QtBot):
        panel = HistoryPanel()
        qtbot.addWidget(panel)
        e1 = _event(created_at=datetime(2025, 1, 16, 0, 0, 0, tzinfo=UTC))
        e0 = _event(created_at=datetime(2025, 1, 15, 0, 0, 0, tzinfo=UTC))
        panel.show_history(HistoryOutcome(label="test", events=(e1, e0)))
        table_model = panel._table_view.model()
        # First row should be the newer event (e1)
        assert table_model.rowCount() == 2
        first_event = table_model.events()[0]
        assert first_event.created_at == e1.created_at

    def test_panel_events_accessor(self, qtbot: QtBot):
        panel = HistoryPanel()
        qtbot.addWidget(panel)
        assert panel.events() == []
        events = [_event()]
        panel.show_history(HistoryOutcome(label="test", events=tuple(events)))
        assert panel.events() == events
