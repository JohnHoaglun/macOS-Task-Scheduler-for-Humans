"""Tests for the agent filter controls widget (offscreen Qt)."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QLineEdit, QPushButton
from pytestqt.qtbot import QtBot

from task_scheduler.gui.widgets.agent_filter_controls import AgentFilterControls


def _c(qtbot: QtBot) -> AgentFilterControls:
    w = AgentFilterControls()
    qtbot.addWidget(w)
    w.show()
    return w


class TestAll:
    def test_all(self, qtbot: QtBot) -> None:
        w = _c(qtbot)
        assert w.objectName() == "agent-filter-controls"
        assert w.findChild(QLineEdit, "agent-search-box") is not None
        assert w.findChild(QPushButton, "agent-clear-filters") is not None
        assert w.findChild(QComboBox, "filter-state") is not None
        assert w.findChild(QComboBox, "filter-installed") is not None
        assert w.findChild(QComboBox, "filter-enabled") is not None
        assert w.findChild(QComboBox, "filter-loaded") is not None
        assert w.findChild(QComboBox, "filter-command") is not None
        p = _Fake()
        w.attach(p)
        assert w._proxy is p
        w._on_search_changed("foo")
        assert p.set_search_calls == ["foo"]
        w._clear_button.click()
        assert w._search.text() == "" and p.clear_filters_calls == [True]
        w._on_filter_changed("x")


class _Fake:
    """Minimal mock for AgentFilterProxyModel."""

    def __init__(self) -> None:
        self.set_search_calls: list[str] = []
        self.clear_filters_calls: list[bool] = []

    def set_search(self, t: str) -> None:
        self.set_search_calls.append(t)

    def set_state(self, v: frozenset[str]) -> None:
        pass

    def set_installed(self, v: frozenset[str]) -> None:
        pass

    def set_enabled(self, v: frozenset[str]) -> None:
        pass

    def set_loaded(self, v: frozenset[str]) -> None:
        pass

    def set_command(self, v: frozenset[str]) -> None:
        pass

    def clear_filters(self) -> None:
        self.clear_filters_calls.append(True)

    def invalidateFilter(self) -> None:
        pass
