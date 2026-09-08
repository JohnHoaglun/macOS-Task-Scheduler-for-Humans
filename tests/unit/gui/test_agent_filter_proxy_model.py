"""Tests for AgentFilterProxyModel and the pure accepts_row predicate."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QModelIndex, Qt
from pytestqt.qtbot import QtBot

from conftest import make_job
from task_scheduler.application.task_command_service import ListingKind, TaskListing
from task_scheduler.gui.models.agent_filter_proxy_model import (
    AgentFilterProxyModel,
    accepts_row,
)
from task_scheduler.gui.models.agent_table_model import (
    ROLE_COMMAND,
    ROLE_ENABLED,
    ROLE_INSTALLED,
    ROLE_LOADED,
    ROLE_SEARCH_TEXT,
    ROLE_STATE,
    AgentTableModel,
)
from task_scheduler.gui.presenters.agent_badge_presenter import AgentDimensions
from task_scheduler.platform.macos import ParsedLaunchAgent, ParseSupport

TEST_PATH = Path("/Users/example/Library/LaunchAgents/com.example.plist")
_EMPTY = frozenset()


def _dims(**over: str) -> AgentDimensions:
    base = {
        "state": "Managed",
        "installed": "installed",
        "enabled": "enabled",
        "loaded": "loaded",
        "command": "python",
    }
    base.update(over)
    return AgentDimensions(**base)


def _row(
    haystack: str = "haystack",
    search: str = "",
    dims: AgentDimensions | None = None,
    state: frozenset[str] = _EMPTY,
    installed: frozenset[str] = _EMPTY,
    enabled: frozenset[str] = _EMPTY,
    loaded: frozenset[str] = _EMPTY,
    command: frozenset[str] = _EMPTY,
) -> bool:
    return accepts_row(
        dims or _dims(), haystack, search, state, installed, enabled, loaded, command
    )


def _parsed(**overrides: object) -> ParsedLaunchAgent:
    kwargs: dict[str, object] = {"status": ParseSupport.SUPPORTED}
    kwargs.update(overrides)
    return ParsedLaunchAgent(**kwargs)  # type: ignore[arg-type]


def _managed_listing(enabled: bool = True, loaded: bool | None = None) -> TaskListing:
    job = make_job(enabled=enabled)
    return TaskListing(
        kind=ListingKind.DISCOVERED,
        path=TEST_PATH,
        parsed=_parsed(job=job),
        job=job,
        managed=True,
        loaded=loaded,
    )


def _external_listing(enabled: bool = True, loaded: bool | None = None) -> TaskListing:
    job = make_job(enabled=enabled)
    return TaskListing(
        kind=ListingKind.DISCOVERED,
        path=TEST_PATH,
        parsed=_parsed(job=job),
        job=job,
        managed=False,
        loaded=loaded,
    )


def _invalid_listing() -> TaskListing:
    return TaskListing(
        kind=ListingKind.DISCOVERED,
        path=TEST_PATH,
        parsed=_parsed(status=ParseSupport.INVALID, raw={"Label": "com.example.invalid"}),
        job=None,
        managed=False,
    )


def _saved_listing() -> TaskListing:
    job = make_job(label="io.github.macos-task-scheduler.user.saved", name="Saved Job")
    return TaskListing(
        kind=ListingKind.SAVED, path=None, parsed=None, job=job, managed=True, loaded=None
    )


def _no_job_discovered() -> TaskListing:
    return TaskListing(
        kind=ListingKind.DISCOVERED,
        path=TEST_PATH,
        parsed=_parsed(
            status=ParseSupport.PARTIALLY_SUPPORTED,
            raw={"ProgramArguments": ["/bin/zsh", "-c", "echo hi"]},
        ),
        job=None,
        managed=False,
    )


def _agents() -> list[TaskListing]:
    return [
        _managed_listing(enabled=True, loaded=True),
        _managed_listing(enabled=False, loaded=False),
        _external_listing(enabled=True, loaded=None),
        _invalid_listing(),
        _saved_listing(),
        _no_job_discovered(),
    ]


class TestAcceptsRow:
    def test_no_constraints_passes(self) -> None:
        assert _row()

    def test_search_case_insensitive(self) -> None:
        assert _row(haystack="Daily Backup python script", search="daily")
        assert _row(haystack="Daily Backup python script", search="BACKUP")
        assert not _row(haystack="Daily Backup python script", search="nope")

    @pytest.mark.parametrize(
        ("attr", "value", "match", "no_match"),
        [
            ("state", "Managed", frozenset({"Managed"}), frozenset({"Invalid"})),
            ("installed", "saved", frozenset({"saved"}), frozenset({"installed"})),
            ("enabled", "disabled", frozenset({"disabled"}), frozenset({"enabled"})),
            ("loaded", "not loaded", frozenset({"not loaded"}), frozenset({"loaded"})),
            ("command", "shell", frozenset({"shell"}), frozenset({"python"})),
        ],
    )
    def test_group_match_and_mismatch(self, attr, value, match, no_match) -> None:
        assert _row(dims=_dims(**{attr: value}), **{attr: match})
        assert not _row(dims=_dims(**{attr: value}), **{attr: no_match})

    def test_or_within_group(self) -> None:
        assert _row(dims=_dims(state="External"), state=frozenset({"Managed", "External"}))
        assert not _row(dims=_dims(state="External"), state=frozenset({"Invalid"}))

    def test_and_across_groups(self) -> None:
        assert _row(
            dims=_dims(installed="saved"),
            state=frozenset({"Managed"}),
            installed=frozenset({"saved"}),
        )
        assert not _row(
            dims=_dims(installed="installed"),
            state=frozenset({"Managed"}),
            installed=frozenset({"saved"}),
        )


class TestFilterProxyIntegration:
    def _proxy(self, qtbot: QtBot, agents: list[TaskListing]) -> AgentFilterProxyModel:
        model = AgentTableModel()
        model.set_agents(agents)
        proxy = AgentFilterProxyModel()
        proxy.setSourceModel(model)
        return proxy

    def test_default_show_all_rows(self, qtbot: QtBot) -> None:
        assert self._proxy(qtbot, _agents()).rowCount() == 6

    @pytest.mark.parametrize(
        ("setter", "values", "expected"),
        [
            ("set_state", frozenset({"Managed"}), 3),
            ("set_state", frozenset({"Invalid"}), 1),
            ("set_installed", frozenset({"saved"}), 1),
            ("set_enabled", frozenset({"disabled"}), 1),
            ("set_loaded", frozenset({"unknown"}), 4),
            ("set_command", frozenset({"python"}), 4),
            ("set_command", frozenset({"unknown"}), 2),
        ],
    )
    def test_dimension_filters(self, qtbot: QtBot, setter, values, expected) -> None:
        proxy = self._proxy(qtbot, _agents())
        getattr(proxy, setter)(values)
        assert proxy.rowCount() == expected

    def test_or_in_one_group(self, qtbot: QtBot) -> None:
        proxy = self._proxy(qtbot, _agents())
        proxy.set_loaded(frozenset({"loaded", "not loaded"}))
        assert proxy.rowCount() == 2

    def test_and_across_groups(self, qtbot: QtBot) -> None:
        proxy = self._proxy(qtbot, _agents())
        proxy.set_state(frozenset({"Managed"}))
        proxy.set_loaded(frozenset({"loaded"}))
        assert proxy.rowCount() == 1

    def test_set_search(self, qtbot: QtBot) -> None:
        proxy = self._proxy(qtbot, _agents())
        proxy.set_search("external")
        assert proxy.rowCount() == 0
        proxy.set_search("daily-backup")
        assert proxy.rowCount() == 3
        proxy.set_search("saved job")
        assert proxy.rowCount() == 1

    def test_clear_filters(self, qtbot: QtBot) -> None:
        proxy = self._proxy(qtbot, _agents())
        proxy.set_state(frozenset({"Managed"}))
        assert proxy.rowCount() == 3
        proxy.clear_filters()
        assert proxy.rowCount() == 6

    def test_no_source_model_returns_false(self) -> None:
        assert not AgentFilterProxyModel().filterAcceptsRow(0, QModelIndex())

    def test_role_values_on_proxy(self, qtbot: QtBot) -> None:
        model = AgentTableModel()
        model.set_agents(_agents())
        proxy = AgentFilterProxyModel()
        proxy.setSourceModel(model)
        idx = proxy.mapFromSource(model.index(0, 0))
        for role, expected in (
            (ROLE_STATE, "Managed"),
            (ROLE_INSTALLED, "installed"),
            (ROLE_ENABLED, "enabled"),
            (ROLE_LOADED, "loaded"),
            (ROLE_COMMAND, "python"),
        ):
            assert proxy.data(idx, role) == expected
        assert "Daily Backup" in (proxy.data(idx, ROLE_SEARCH_TEXT) or "")
        assert "Daily Backup" in (proxy.data(idx, Qt.ItemDataRole.DisplayRole) or "")
