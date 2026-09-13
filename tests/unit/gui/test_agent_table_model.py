"""Tests for the agent discovery table model (offscreen Qt)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from PySide6.QtCore import QModelIndex, Qt
from pytestqt.qtbot import QtBot

from conftest import make_job
from task_scheduler.application.task_command_service import ListingKind, TaskListing
from task_scheduler.gui.models.agent_table_model import (
    ROLE_SEARCH_TEXT,
    ROLE_STATE,
    AgentTableModel,
)
from task_scheduler.platform.macos import ParsedLaunchAgent, ParseSupport

MANAGED_PATH = Path("/Users/example/Library/LaunchAgents/com.example.backup.plist")
EXTERNAL_PATH = Path("/Users/example/Library/LaunchAgents/com.example.external.plist")
INVALID_PATH = Path("/Users/example/Library/LaunchAgents/com.example.invalid.plist")
SAVED_JOB_ID = UUID("44444444-4444-4444-8444-444444444444")


def _parsed(**overrides: object) -> ParsedLaunchAgent:
    kwargs: dict[str, object] = {"status": ParseSupport.SUPPORTED}
    kwargs.update(overrides)
    return ParsedLaunchAgent(**kwargs)  # type: ignore[arg-type]


def _agents() -> list[TaskListing]:
    return [
        TaskListing(
            kind=ListingKind.DISCOVERED,
            path=MANAGED_PATH,
            parsed=_parsed(job=make_job()),
            job=make_job(),
            managed=True,
        ),
        TaskListing(
            kind=ListingKind.DISCOVERED,
            path=EXTERNAL_PATH,
            parsed=_parsed(
                status=ParseSupport.PARTIALLY_SUPPORTED,
                raw={"ProgramArguments": ["/bin/zsh", "/Users/example/scripts/x.sh"]},
            ),
            job=None,
            managed=False,
        ),
        TaskListing(
            kind=ListingKind.DISCOVERED,
            path=INVALID_PATH,
            parsed=_parsed(status=ParseSupport.INVALID, raw={"Label": "com.example.invalid"}),
            job=None,
            managed=False,
        ),
    ]


_DEFAULT_INDEX: QModelIndex = QModelIndex()


class _UnboundedIndexModel(AgentTableModel):
    """Model that issues valid indices for rows/columns beyond its bounds."""

    def index(
        self,
        row: int,
        column: int,
        parent: QModelIndex = _DEFAULT_INDEX,
    ) -> QModelIndex:
        return self.createIndex(row, column)


@pytest.fixture
def agent_model(qtbot: QtBot) -> AgentTableModel:
    model = AgentTableModel()
    model.set_agents(_agents())
    return model


class TestSetAgents:
    def test_empty(self, agent_model: AgentTableModel) -> None:
        agent_model.set_agents([])
        assert agent_model.agents() == []
        assert agent_model.rowCount() == 0


class TestHeader:
    def test_horizontal_out_of_range(self, agent_model: AgentTableModel) -> None:
        assert agent_model.headerData(5, Qt.Orientation.Horizontal) is None


class TestData:
    def test_valid_index_out_of_range_column_returns_none(self) -> None:
        model = _UnboundedIndexModel()
        model.set_agents(_agents())
        index = model.index(0, 7)
        assert index.isValid()
        assert model.data(index) is None

    def test_invalid_index_returns_none(self) -> None:
        model = AgentTableModel()
        model.set_agents(_agents())
        bad_index = QModelIndex()
        assert model.data(bad_index, Qt.ItemDataRole.DisplayRole) is None
        assert model.data(bad_index, ROLE_STATE) is None

    def test_none_listing_returns_none(self) -> None:
        model = _UnboundedIndexModel()
        model.set_agents(_agents())
        bad_idx = model.index(99, 0)
        assert bad_idx.isValid()
        assert model.data(bad_idx, Qt.ItemDataRole.DisplayRole) is None
        assert model.data(bad_idx, ROLE_STATE) is None
        assert model.data(bad_idx, ROLE_SEARCH_TEXT) is None
