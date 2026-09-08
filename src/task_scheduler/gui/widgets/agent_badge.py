"""A label widget that renders a single BadgeDescriptor."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from task_scheduler.gui.presenters.agent_badge_presenter import BadgeDescriptor

__all__ = ["AgentBadge"]


class AgentBadge(QFrame):
    """Renders a single badge descriptor as a labelled label."""

    def __init__(self, parent: QFrame | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("agent-badge")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel(self)
        self._label.setObjectName("agent-badge-label")
        layout.addWidget(self._label)

    def set_descriptor(self, descriptor: BadgeDescriptor) -> None:
        """Configure the badge with the given descriptor values."""
        self._label.setText(descriptor.text)
        self._label.setAccessibleName(descriptor.accessible_name)
        if descriptor.tooltip is not None:
            self.setToolTip(descriptor.tooltip)
