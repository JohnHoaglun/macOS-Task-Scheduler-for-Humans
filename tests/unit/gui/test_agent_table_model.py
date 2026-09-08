"""Tests for the agent discovery table model (offscreen Qt)."""

from __future__ import annotations

import shlex
from pathlib import Path
from uuid import UUID

import pytest
from PySide6.QtCore import QModelIndex, Qt
from pytestqt.qtbot import QtBot

from conftest import make_job
from task_scheduler.application.task_command_service import ListingKind, TaskListing
from task_scheduler.domain import PythonCommand, command_argv
from task_scheduler.gui.models.agent_table_model import (
    COLUMNS,
    ROLE_COMMAND,
    ROLE_ENABLED,
    ROLE_INSTALLED,
    ROLE_LOADED,
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


def _saved_agent() -> TaskListing:
    job = make_job(
        id=SAVED_JOB_ID, label="io.github.macos-task-scheduler.user.saved", name="Saved Job"
    )
    return TaskListing(kind=ListingKind.SAVED, path=None, parsed=None, job=job, managed=True)


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


@pytest.fixture
def loaded_managed_model(qtbot: QtBot) -> AgentTableModel:
    job = make_job(enabled=True)
    parsed = _parsed(job=job)
    listing = TaskListing(
        kind=ListingKind.DISCOVERED,
        path=MANAGED_PATH,
        parsed=parsed,
        job=job,
        managed=True,
        loaded=True,
    )
    model = AgentTableModel()
    model.set_agents([listing])
    return model


class TestSetAgents:
    def test_empty(self, agent_model: AgentTableModel) -> None:
        agent_model.set_agents([])
        assert agent_model.agents() == []
        assert agent_model.rowCount() == 0


class TestHeader:
    def test_horizontal_sections(self, agent_model: AgentTableModel) -> None:
        for section, title in enumerate(COLUMNS):
            assert agent_model.header(section, Qt.Orientation.Horizontal) == title

    def test_vertical(self, agent_model: AgentTableModel) -> None:
        assert agent_model.header(0, Qt.Orientation.Vertical) == "1"
        assert agent_model.header(1, Qt.Orientation.Vertical) == "2"


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

    def test_unknown_role_returns_none(self) -> None:
        model = AgentTableModel()
        model.set_agents(_agents())
        assert model.data(model.index(0, 0), Qt.ItemDataRole.ToolTipRole) is None

    @pytest.mark.parametrize(("column", "needle"), ((1, "python"), (2, "Monday")))
    def test_display_role_column(self, agent_model: AgentTableModel, column, needle) -> None:
        data = agent_model.data(agent_model.index(0, column), Qt.ItemDataRole.DisplayRole)
        assert data is not None and needle in data

    def test_listings_none_for_invalid_row(self) -> None:
        model = AgentTableModel()
        model.set_agents(_agents())
        assert model.listing_at(-1) is None
        assert model.listing_at(99) is None

    def test_none_listing_returns_none(self) -> None:
        model = _UnboundedIndexModel()
        model.set_agents(_agents())
        bad_idx = model.index(99, 0)
        assert bad_idx.isValid()
        assert model.data(bad_idx, Qt.ItemDataRole.DisplayRole) is None
        assert model.data(bad_idx, ROLE_STATE) is None
        assert model.data(bad_idx, ROLE_SEARCH_TEXT) is None

    def test_existing_columns_managed(self, agent_model: AgentTableModel) -> None:
        row0 = agent_model.index(0, 0)
        assert agent_model.data(row0, Qt.ItemDataRole.DisplayRole) == "Daily Backup"
        assert agent_model.data(agent_model.index(0, 3), Qt.ItemDataRole.DisplayRole) == "Managed"
        assert "enabled" in (
            agent_model.data(agent_model.index(0, 4), Qt.ItemDataRole.DisplayRole) or ""
        )

    @pytest.mark.parametrize(("row", "state"), ((1, "External"), (2, "Invalid")))
    def test_existing_columns_external_invalid(
        self, agent_model: AgentTableModel, row, state
    ) -> None:
        assert agent_model.data(agent_model.index(row, 3), Qt.ItemDataRole.DisplayRole) == state


class TestRoleData:
    @pytest.mark.parametrize(
        ("row", "role", "expected"),
        [
            (0, ROLE_STATE, "Managed"),
            (1, ROLE_STATE, "External"),
            (2, ROLE_STATE, "Invalid"),
            (0, ROLE_INSTALLED, "installed"),
            (0, ROLE_ENABLED, "enabled"),
            (1, ROLE_ENABLED, "unknown"),
            (0, ROLE_LOADED, "unknown"),
            (0, ROLE_COMMAND, "python"),
            (1, ROLE_COMMAND, "unknown"),
        ],
    )
    def test_agent_rows(
        self, agent_model: AgentTableModel, row: int, role: int, expected: str
    ) -> None:
        assert agent_model.data(agent_model.index(row, 0), role) == expected

    def test_saved_row(self, saved_model: AgentTableModel) -> None:
        assert saved_model.data(saved_model.index(0, 0), ROLE_STATE) == "Managed"
        assert saved_model.data(saved_model.index(0, 0), ROLE_INSTALLED) == "saved"

    def test_loaded_value(self, loaded_managed_model: AgentTableModel) -> None:
        assert loaded_managed_model.data(loaded_managed_model.index(0, 0), ROLE_LOADED) == "loaded"


class TestRoleSearchText:
    def test_contains_name_and_label(self, agent_model: AgentTableModel) -> None:
        text = agent_model.data(agent_model.index(0, 0), ROLE_SEARCH_TEXT)
        assert text is not None
        assert "Daily Backup" in text
        assert "io.github.macos-task-scheduler.user.daily-backup" in text

    def test_contains_quoted_command(self, agent_model: AgentTableModel) -> None:
        text = agent_model.data(agent_model.index(0, 0), ROLE_SEARCH_TEXT)
        assert text is not None
        cmd = command_argv(
            PythonCommand(
                interpreter="/Users/example/project/.venv/bin/python",
                script="/Users/example/project/main.py",
                arguments=["--mode", "daily"],
            )
        )
        expected_token = shlex.quote(cmd[1])
        assert expected_token in text

    def test_saved_no_parsing(self, saved_model: AgentTableModel) -> None:
        text = saved_model.data(saved_model.index(0, 0), ROLE_SEARCH_TEXT)
        assert text is not None
        assert "Saved Job" in text
        assert "io.github.macos-task-scheduler.user.saved" in text

    def test_invalid_no_job(self, agent_model: AgentTableModel) -> None:
        text = agent_model.data(agent_model.index(2, 0), ROLE_SEARCH_TEXT)
        assert text is not None
        assert "unknown" in text

    def test_role_values(self) -> None:
        base = Qt.ItemDataRole.UserRole
        roles = (
            ROLE_STATE,
            ROLE_INSTALLED,
            ROLE_ENABLED,
            ROLE_LOADED,
            ROLE_COMMAND,
            ROLE_SEARCH_TEXT,
        )
        assert roles == tuple(base + i for i in range(6))
