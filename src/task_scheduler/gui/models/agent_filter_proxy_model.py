"""QSortFilterProxyModel that filters agents by badge dimensions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QModelIndex, QObject, QPersistentModelIndex, QSortFilterProxyModel

from task_scheduler.gui.models.agent_table_model import (
    ROLE_COMMAND,
    ROLE_ENABLED,
    ROLE_INSTALLED,
    ROLE_LOADED,
    ROLE_SEARCH_TEXT,
    ROLE_STATE,
    AgentTableModel,
)

if TYPE_CHECKING:
    from task_scheduler.application.task_command_service import TaskListing

__all__ = ["AgentFilterProxyModel", "accepts_row"]


class AgentFilterProxyModel(QSortFilterProxyModel):
    """Filters an AgentTableModel by state, installed, enabled, loaded, and command."""

    STATE_OPTIONS: frozenset[str] = frozenset({"Managed", "External", "Invalid"})
    INSTALLED_OPTIONS: frozenset[str] = frozenset({"installed", "saved"})
    ENABLED_OPTIONS: frozenset[str] = frozenset({"enabled", "disabled", "unknown"})
    LOADED_OPTIONS: frozenset[str] = frozenset({"loaded", "not loaded", "unknown"})
    COMMAND_OPTIONS: frozenset[str] = frozenset({"python", "shell", "executable", "unknown"})

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._search: str = ""
        self._state: frozenset[str] = frozenset()
        self._installed: frozenset[str] = frozenset()
        self._enabled: frozenset[str] = frozenset()
        self._loaded: frozenset[str] = frozenset()
        self._command: frozenset[str] = frozenset()

    def set_state(self, values: frozenset[str]) -> None:
        self._state = values
        self.invalidateFilter()

    def set_installed(self, values: frozenset[str]) -> None:
        self._installed = values
        self.invalidateFilter()

    def set_enabled(self, values: frozenset[str]) -> None:
        self._enabled = values
        self.invalidateFilter()

    def set_loaded(self, values: frozenset[str]) -> None:
        self._loaded = values
        self.invalidateFilter()

    def set_command(self, values: frozenset[str]) -> None:
        self._command = values
        self.invalidateFilter()

    def set_search(self, text: str) -> None:
        self._search = text
        self.invalidateFilter()

    def clear_filters(self) -> None:
        self._search = ""
        self._state = frozenset()
        self._installed = frozenset()
        self._enabled = frozenset()
        self._loaded = frozenset()
        self._command = frozenset()
        self.invalidateFilter()

    def listing_at(self, row: int) -> TaskListing | None:
        """The listing for proxy row *row*, mapped through the source model."""
        source = self.sourceModel()
        assert isinstance(source, AgentTableModel)
        return source.listing_at(self.mapToSource(self.index(row, 0)).row())

    def filterAcceptsRow(
        self,
        source_row: int,
        source_parent: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        model = self.sourceModel()
        if model is None:
            return False
        idx = model.index(source_row, 0, source_parent)
        haystack = model.index(source_row, 0).data(ROLE_SEARCH_TEXT) or ""
        state_val = model.data(idx, ROLE_STATE) or ""
        installed_val = model.data(idx, ROLE_INSTALLED) or ""
        enabled_val = model.data(idx, ROLE_ENABLED) or ""
        loaded_val = model.data(idx, ROLE_LOADED) or ""
        command_val = model.data(idx, ROLE_COMMAND) or ""
        return accepts_row(
            dims=AgentFilterProxyModel._make_dims(
                state_val, installed_val, enabled_val, loaded_val, command_val
            ),
            haystack=haystack,
            search=self._search,
            state=self._state,
            installed=self._installed,
            enabled=self._enabled,
            loaded=self._loaded,
            command=self._command,
        )

    @staticmethod
    def _make_dims(state: str, installed: str, enabled: str, loaded: str, command: str) -> object:
        from task_scheduler.gui.presenters.agent_badge_presenter import AgentDimensions

        return AgentDimensions(
            state=state,
            installed=installed,
            enabled=enabled,
            loaded=loaded,
            command=command,
        )


def accepts_row(
    dims: object,
    haystack: str,
    search: str,
    state: frozenset[str],
    installed: frozenset[str],
    enabled: frozenset[str],
    loaded: frozenset[str],
    command: frozenset[str],
) -> bool:
    """Pure predicate that checks one row against all filter constraints."""
    return (
        ((not search) or search.lower() in haystack.lower())
        and ((not state) or getattr(dims, "state", "") in state)
        and ((not installed) or getattr(dims, "installed", "") in installed)
        and ((not enabled) or getattr(dims, "enabled", "") in enabled)
        and ((not loaded) or getattr(dims, "loaded", "") in loaded)
        and ((not command) or getattr(dims, "command", "") in command)
    )
