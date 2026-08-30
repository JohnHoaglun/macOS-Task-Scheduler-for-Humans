"""Tests for the agent discovery table model (offscreen Qt)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from PySide6.QtCore import QModelIndex, Qt
from pytestqt.qtbot import QtBot

from conftest import make_job
from task_scheduler.application.task_command_service import ListingKind, TaskListing
from task_scheduler.gui.models.agent_table_model import COLUMNS, AgentTableModel
from task_scheduler.gui.presenters.agent_presenter import (
    classify,
    format_command,
    format_name,
    format_schedule,
    format_state,
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
                unsupported_keys=["KeepAlive"],
                warnings=["no calendar schedule found"],
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


def _saved_agent() -> TaskListing:
    job = make_job(
        id=SAVED_JOB_ID, label="io.github.macos-task-scheduler.user.saved", name="Saved Job"
    )
    return TaskListing(
        kind=ListingKind.SAVED, path=None, parsed=None, job=job, managed=True
    )


def _expected_row(listing: TaskListing) -> list[str]:
    return [
        format_name(listing),
        format_command(listing),
        format_schedule(listing),
        classify(listing).value,
        format_state(listing),
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


@pytest.fixture
def saved_model(qtbot: QtBot) -> AgentTableModel:
    model = AgentTableModel()
    model.set_agents([_saved_agent()])
    return model


class TestSetAgents:
    def test_populates_model(self, agent_model: AgentTableModel) -> None:
        agents = _agents()
        agent_model.set_agents(agents)
        assert agent_model.agents() == agents
        assert agent_model.rowCount() == 3
        assert agent_model.columnCount() == 5

    def test_empty(self, agent_model: AgentTableModel) -> None:
        agent_model.set_agents([])
        assert agent_model.agents() == []
        assert agent_model.rowCount() == 0


class TestListingAt:
    def test_in_range(self, agent_model: AgentTableModel) -> None:
        agents = _agents()
        assert agent_model.listing_at(0) == agents[0]
        assert agent_model.listing_at(2) == agents[2]

    def test_out_of_range(self, agent_model: AgentTableModel) -> None:
        assert agent_model.listing_at(3) is None
        assert agent_model.listing_at(-1) is None


class TestHeader:
    def test_horizontal_sections(self, agent_model: AgentTableModel) -> None:
        for section, title in enumerate(COLUMNS):
            assert agent_model.header(section, Qt.Orientation.Horizontal) == title

    def test_vertical(self, agent_model: AgentTableModel) -> None:
        assert agent_model.header(0, Qt.Orientation.Vertical) == "1"
        assert agent_model.header(1, Qt.Orientation.Vertical) == "2"


class TestData:
    def test_every_cell_matches_presenter(self, agent_model: AgentTableModel) -> None:
        agents = _agents()
        for row, listing in enumerate(agents):
            for column, expected in enumerate(_expected_row(listing)):
                assert agent_model.data(agent_model.index(row, column)) == expected

    def test_first_row_literal_values(self, agent_model: AgentTableModel) -> None:
        assert agent_model.data(agent_model.index(0, 0)) == "Daily Backup"
        assert agent_model.data(agent_model.index(0, 1)) == (
            "/Users/example/project/.venv/bin/python /Users/example/project/main.py --mode daily"
        )
        assert agent_model.data(agent_model.index(0, 2)) == "at 07:30:00 on Monday"
        assert agent_model.data(agent_model.index(0, 3)) == "Managed"
        assert agent_model.data(agent_model.index(0, 4)) == "supported"

    def test_non_display_role_returns_none(self, agent_model: AgentTableModel) -> None:
        index = agent_model.index(0, 0)
        assert agent_model.data(index, Qt.ItemDataRole.ToolTipRole) is None

    def test_invalid_index_returns_none(self, agent_model: AgentTableModel) -> None:
        assert agent_model.data(QModelIndex()) is None

    def test_valid_index_out_of_range_row_returns_none(self) -> None:
        model = _UnboundedIndexModel()
        model.set_agents(_agents())
        index = model.index(999, 0)
        assert index.isValid()
        assert model.data(index) is None

    def test_valid_index_out_of_range_column_returns_none(self) -> None:
        model = _UnboundedIndexModel()
        model.set_agents(_agents())
        index = model.index(0, 7)
        assert index.isValid()
        assert model.data(index) is None


class TestSavedRow:
    def test_saved_row_renders_saved_state(self, saved_model: AgentTableModel) -> None:
        assert saved_model.data(saved_model.index(0, 0)) == "Saved Job"
        assert saved_model.data(saved_model.index(0, 1)) == (
            "/Users/example/project/.venv/bin/python /Users/example/project/main.py "
            "--mode daily"
        )
        assert saved_model.data(saved_model.index(0, 2)) == "at 07:30:00 on Monday"
        assert saved_model.data(saved_model.index(0, 3)) == "Managed"
        assert saved_model.data(saved_model.index(0, 4)) == "saved, not installed"
        listing = saved_model.listing_at(0)
        assert listing is not None
        assert listing.kind is ListingKind.SAVED
        assert listing.path is None


class TestOrder:
    def test_discovery_order_preserved(self, agent_model: AgentTableModel) -> None:
        ordered = list(reversed(_agents()))
        agent_model.set_agents(ordered)
        assert agent_model.listing_at(0) == ordered[0]
        assert agent_model.data(agent_model.index(0, 0)) == "com.example.invalid"
