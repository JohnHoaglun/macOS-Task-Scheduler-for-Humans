"""Tests for the history table model (offscreen Qt)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from task_scheduler.application.history_models import (
    HistoryEvent,
    HistoryEventKind,
    HistoryOutcome,
)
from task_scheduler.gui.models.history_table_model import COLUMNS, HistoryTableModel


def _event(**overrides) -> HistoryEvent:
    kwargs = {
        "created_at": datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC),
        "job_id": UUID("00000000-0000-4000-8000-000000000001"),
        "label": "com.example.job",
        "kind": HistoryEventKind.DIRECT_TEST,
        "outcome": HistoryOutcome.SUCCESS,
        "exit_code": 0,
        "duration_seconds": 1.250,
        "loaded": None,
        "diagnostic_codes": (),
    }
    kwargs.update(overrides)
    return HistoryEvent(**kwargs)


@pytest.fixture
def model(qtbot: QtBot) -> HistoryTableModel:
    m = HistoryTableModel()
    events = [
        _event(kind=HistoryEventKind.DIRECT_TEST, outcome=HistoryOutcome.SUCCESS, exit_code=0),
        _event(kind=HistoryEventKind.MANUAL_RUN, outcome=HistoryOutcome.FAILURE, exit_code=1),
    ]
    m.set_events(events)
    return m


class TestSetEvents:
    def test_populates_model(self, model: HistoryTableModel):
        assert len(model.events()) == 2
        assert model.rowCount() == 2
        assert model.columnCount() == 4

    def test_empty(self, qtbot: QtBot):
        m = HistoryTableModel()
        m.set_events([])
        assert m.events() == []
        assert m.rowCount() == 0


class TestHeader:
    def test_horizontal_headers(self, model: HistoryTableModel):
        for i, expected in enumerate(COLUMNS):
            assert model.header(i, Qt.Orientation.Horizontal) == expected

    def test_vertical_headers(self, model: HistoryTableModel):
        assert model.header(0, Qt.Orientation.Vertical) == "1"
        assert model.header(1, Qt.Orientation.Vertical) == "2"


class TestData:
    def test_first_row_all_columns(self, model: HistoryTableModel):
        idx0 = model.index(0, 0)
        time_text = model.data(idx0)
        assert "2025-01-15" in time_text
        assert "06:00:00" in time_text
        assert model.data(model.index(0, 1)) == "Direct test"
        assert model.data(model.index(0, 2)) == "Succeeded"
        assert "exit code 0" in model.data(model.index(0, 3))

    def test_second_row(self, model: HistoryTableModel):
        assert model.data(model.index(1, 1)) == "Manual run"
        assert model.data(model.index(1, 2)) == "Failed"
        assert "exit code 1" in model.data(model.index(1, 3))

    def test_non_display_role_returns_none(self, model: HistoryTableModel):
        idx = model.index(0, 0)
        assert model.data(idx, Qt.ItemDataRole.ToolTipRole) is None

    def test_invalid_index_returns_none(self, model: HistoryTableModel):
        from PySide6.QtCore import QModelIndex
        assert model.data(QModelIndex()) is None

    def test_out_of_range_row_returns_none(self, model: HistoryTableModel):
        idx = model.createIndex(999, 0)
        assert idx.isValid()
        assert model.data(idx) is None

    def test_out_of_range_column_returns_none(self, model: HistoryTableModel):
        idx = model.createIndex(0, 7)
        assert idx.isValid()
        assert model.data(idx) is None


class TestReplaceEvents:
    def test_replacing_clears_and_populates(self, qtbot: QtBot):
        m = HistoryTableModel()
        m.set_events([_event(kind=HistoryEventKind.MANUAL_RUN)])
        assert m.rowCount() == 1
        m.set_events([])
        assert m.rowCount() == 0
        m.set_events([_event(kind=HistoryEventKind.STATUS_OBSERVATION)])
        assert m.rowCount() == 1
        assert m.data(m.index(0, 1)) == "Status check"
