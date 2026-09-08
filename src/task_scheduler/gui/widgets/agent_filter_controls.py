"""Filter controls for the agent discovery table.

Provides a search box, five category combo-boxes, and a clear-filters
button.  Wires all controls to an :class:`AgentFilterProxyModel` so that
the proxy drives filtering over the underlying agent table model.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from task_scheduler.gui.models.agent_filter_proxy_model import (
    AgentFilterProxyModel,
)

__all__ = ["AgentFilterControls"]

# Ordered filter group labels matching the proxy model options.
_FILTER_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("State", ("Managed", "External", "Invalid")),
    ("Installed", ("installed", "saved")),
    ("Enabled", ("enabled", "disabled", "unknown")),
    ("Loaded", ("loaded", "not loaded", "unknown")),
    ("Command", ("python", "shell", "executable", "unknown")),
)

_ANY = "(any)"

_SETTERS: dict[str, str] = {
    "State": "set_state",
    "Installed": "set_installed",
    "Enabled": "set_enabled",
    "Loaded": "set_loaded",
    "Command": "set_command",
}


class AgentFilterControls(QWidget):
    """Search box + five combo-box filters + clear button."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("agent-filter-controls")

        self._search = QLineEdit(self)
        self._search.setObjectName("agent-search-box")

        self._combos: dict[str, QComboBox] = {}
        for label, options in _FILTER_GROUPS:
            combo = QComboBox(self)
            combo.setObjectName(f"filter-{label.lower()}")
            combo.addItem(_ANY)
            combo.addItems(options)
            combo.currentTextChanged.connect(lambda _t, label=label: self._on_combo_changed(label))
            self._combos[label] = combo

        self._clear_button = QPushButton("Clear filters", self)
        self._clear_button.setObjectName("agent-clear-filters")

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction helpers
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Search:"))
        top_row.addWidget(self._search)
        top_row.addStretch(1)

        filter_row = QHBoxLayout()
        for label, combo in self._combos.items():
            filter_row.addWidget(QLabel(f"{label}:"))
            filter_row.addWidget(combo)
        filter_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addLayout(filter_row)
        layout.addWidget(self._clear_button)

        self._search.textChanged.connect(self._on_search_changed)
        self._clear_button.clicked.connect(self._on_clear_clicked)

    # ------------------------------------------------------------------
    # Proxy wiring
    # ------------------------------------------------------------------

    def attach(self, proxy: AgentFilterProxyModel) -> None:
        """Connect this widget's controls to *proxy* for live filtering."""
        self._proxy = proxy

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_search_changed(self, text: str) -> None:
        if hasattr(self, "_proxy"):
            self._proxy.set_search(text)

    def _on_combo_changed(self, label: str) -> None:
        if hasattr(self, "_proxy"):
            value = self._combos[label].currentText()
            chosen: frozenset[str] = frozenset() if value == _ANY else frozenset({value})
            getattr(self._proxy, _SETTERS[label])(chosen)

    def reset(self) -> None:
        """Clear the search box, all combos, and the proxy filters."""
        if hasattr(self, "_proxy"):
            self._proxy.set_search("")
            self._proxy.clear_filters()
        self._search.clear()
        for combo in self._combos.values():
            combo.setCurrentIndex(0)

    def _on_clear_clicked(self) -> None:
        self.reset()
