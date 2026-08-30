"""Inspector panel that renders the full details of a discovered LaunchAgent."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from task_scheduler.application.task_command_service import (
    DiscoveredInspectReport,
    TaskListing,
)
from task_scheduler.gui.presenters.agent_presenter import (
    classify,
    format_command,
    format_enabled,
    format_environment,
    format_label,
    format_name,
    format_raw_plist,
    format_schedule,
    format_status,
    format_warnings,
    format_working_directory,
)

__all__ = ["AgentInspector"]


class AgentInspector(QWidget):
    """Read-only details panel for the selected discovered agent."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._message = QLabel(self)
        self._message.setWordWrap(True)
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.addWidget(self._build_overview())
        content_layout.addWidget(self._build_command())
        content_layout.addWidget(self._build_schedule())
        content_layout.addWidget(self._build_environment())
        content_layout.addWidget(self._build_warnings())
        content_layout.addWidget(self._build_advanced())
        self._scroll.setWidget(content)
        layout = QVBoxLayout(self)
        layout.addWidget(self._scroll)
        layout.addWidget(self._message)
        self.show_placeholder("Select a task to inspect its details.")

    def _field(self, name: str, wrap: bool = False) -> QLabel:
        """A value QLabel with a stable objectName, optionally word-wrapping."""
        label = QLabel(self)
        label.setObjectName(name)
        if wrap:
            label.setWordWrap(True)
        return label

    def _build_overview(self) -> QGroupBox:
        """The Overview group: identity, classification, and state fields."""
        box = QGroupBox("Overview")
        self._overview = {
            "name": self._field("overview-name"),
            "label": self._field("overview-label"),
            "classification": self._field("overview-classification"),
            "source": self._field("overview-source"),
            "enabled": self._field("overview-enabled"),
            "loaded": self._field("overview-loaded"),
        }
        form = QFormLayout(box)
        form.addRow("Name", self._overview["name"])
        form.addRow("Label", self._overview["label"])
        form.addRow("Classification", self._overview["classification"])
        form.addRow("Source", self._overview["source"])
        form.addRow("Enabled", self._overview["enabled"])
        form.addRow("Loaded", self._overview["loaded"])
        return box

    def _build_command(self) -> QGroupBox:
        """The Command group: executable line and working directory."""
        box = QGroupBox("Command")
        self._command = {
            "command": self._field("command-command", wrap=True),
            "working_directory": self._field("command-working-directory", wrap=True),
        }
        form = QFormLayout(box)
        form.addRow("Command", self._command["command"])
        form.addRow("Working directory", self._command["working_directory"])
        return box

    def _build_schedule(self) -> QGroupBox:
        """The Schedule group: one word-wrapped text line."""
        box = QGroupBox("Schedule")
        self._schedule_text = self._field("schedule-text", wrap=True)
        QVBoxLayout(box).addWidget(self._schedule_text)
        return box

    def _build_environment(self) -> QGroupBox:
        """The Environment group: one word-wrapped text line."""
        box = QGroupBox("Environment")
        self._environment_text = self._field("environment-text", wrap=True)
        QVBoxLayout(box).addWidget(self._environment_text)
        return box

    def _build_warnings(self) -> QGroupBox:
        """The Warnings group: top-aligned word-wrapped text."""
        box = QGroupBox("Warnings")
        self._warnings_text = self._field("warnings-text", wrap=True)
        self._warnings_text.setAlignment(Qt.AlignmentFlag.AlignTop)
        QVBoxLayout(box).addWidget(self._warnings_text)
        return box

    def _build_advanced(self) -> QGroupBox:
        """The Advanced group: a read-only raw plist view."""
        box = QGroupBox("Advanced")
        self._advanced_text = QTextEdit(self)
        self._advanced_text.setObjectName("advanced-text")
        self._advanced_text.setReadOnly(True)
        QVBoxLayout(box).addWidget(self._advanced_text)
        return box

    def show_agent(self, agent: TaskListing, report: DiscoveredInspectReport) -> None:
        """Fill every field for a discovered agent and reveal the form."""
        self._fill(
            agent,
            source=str(agent.path) if agent.path is not None else "(no source)",
            loaded=format_status(report.status),
        )

    def show_saved(self, listing: TaskListing) -> None:
        """Fill every field for a saved (catalog-only) task and reveal the form."""
        self._fill(listing, source="(task catalog — not installed)", loaded="not installed")

    def _fill(self, listing: TaskListing, *, source: str, loaded: str) -> None:
        """Render every section from the presenter output and reveal the form."""
        self._overview["name"].setText(format_name(listing))
        self._overview["label"].setText(format_label(listing))
        self._overview["classification"].setText(classify(listing).value)
        self._overview["source"].setText(source)
        self._overview["enabled"].setText(format_enabled(listing))
        self._overview["loaded"].setText(loaded)
        self._command["command"].setText(format_command(listing))
        self._command["working_directory"].setText(format_working_directory(listing))
        self._schedule_text.setText(format_schedule(listing))
        self._environment_text.setText(format_environment(listing))
        self._warnings_text.setText(format_warnings(listing))
        self._advanced_text.setText(format_raw_plist(listing))
        self._message.hide()
        self._scroll.show()

    def show_placeholder(self, text: str) -> None:
        """Hide the form and show a neutral placeholder message."""
        self._scroll.hide()
        self._message.setText(text)
        self._message.show()

    def show_error(self, text: str) -> None:
        """Hide the form and show an error message."""
        self._scroll.hide()
        self._message.setText(text)
        self._message.show()
