"""Inspector panel that renders the full details of a discovered LaunchAgent."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from task_scheduler.application.diagnostic_models import Diagnostic
from task_scheduler.application.task_command_service import (
    DiscoveredInspectReport,
    TaskListing,
)
from task_scheduler.gui.presenters.agent_presenter import (
    PREVIEW_DISCLOSURE,
    classify,
    enabled_state,
    format_command,
    format_enabled,
    format_environment,
    format_inspection_diagnostics,
    format_label,
    format_lifecycle_state,
    format_name,
    format_raw_plist,
    format_schedule,
    format_status,
    format_upcoming_heading,
    format_upcoming_occurrences_for,
    format_warnings,
    format_working_directory,
)

__all__ = ["AgentInspector"]


class AgentInspector(QWidget):
    """Read-only details panel for the selected discovered agent.

    Every value word-wraps and the scroll area never shows a horizontal
    scrollbar, so long paths/commands are always fully readable at any width.
    The Overview/Command rows use a grid with single-line row labels: the
    label column always fits the widest label and each row's height follows
    the wrapped value's ``heightForWidth``, so nothing is ever clipped.
    """

    def __init__(
        self, parent: QWidget | None = None, *, clock: Callable[[], datetime] | None = None
    ) -> None:
        super().__init__(parent)
        self._clock = clock or datetime.now
        self._message = QLabel(self)
        self._message.setWordWrap(True)
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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

    def _row_label(self, text: str) -> QLabel:
        """A single-line, right-aligned row label that never wraps or clips."""
        label = QLabel(text, self)
        label.setWordWrap(False)
        label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        return label

    def _grid_rows(
        self, box: QGroupBox, rows: tuple[tuple[str, QLabel], ...]
    ) -> None:
        """Lay (label, value) rows out: labels fit their text, values stretch."""
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        for row, (text, value) in enumerate(rows):
            grid.addWidget(self._row_label(text), row, 0)
            grid.addWidget(value, row, 1)

    def _build_overview(self) -> QGroupBox:
        """The Overview group: identity, classification, and state fields."""
        box = QGroupBox("Overview")
        self._overview = {
            "name": self._field("overview-name", wrap=True),
            "label": self._field("overview-label", wrap=True),
            "classification": self._field("overview-classification", wrap=True),
            "source": self._field("overview-source", wrap=True),
            "state": self._field("overview-state", wrap=True),
            "enabled": self._field("overview-enabled", wrap=True),
            "loaded": self._field("overview-loaded", wrap=True),
        }
        self._grid_rows(
            box,
            (
                ("Name", self._overview["name"]),
                ("Label", self._overview["label"]),
                ("Classification", self._overview["classification"]),
                ("Source", self._overview["source"]),
                ("State", self._overview["state"]),
                ("Enabled", self._overview["enabled"]),
                ("Loaded", self._overview["loaded"]),
            ),
        )
        return box

    def _build_command(self) -> QGroupBox:
        """The Command group: executable line and working directory."""
        box = QGroupBox("Command")
        self._command = {
            "command": self._field("command-command", wrap=True),
            "working_directory": self._field("command-working-directory", wrap=True),
        }
        self._grid_rows(
            box,
            (
                ("Command", self._command["command"]),
                ("Working directory", self._command["working_directory"]),
            ),
        )
        return box

    def _build_schedule(self) -> QGroupBox:
        """The Schedule group: the schedule line plus the next-run preview block."""
        box = QGroupBox("Schedule")
        self._schedule_text = self._field("schedule-text", wrap=True)
        self._preview_heading = self._field("schedule-preview-heading", wrap=True)
        self._preview_disclosure = self._field("schedule-preview-disclosure", wrap=True)
        self._preview_occurrences = self._field("schedule-preview-occurrences", wrap=True)
        layout = QVBoxLayout(box)
        layout.addWidget(self._schedule_text)
        layout.addWidget(self._preview_heading)
        layout.addWidget(self._preview_disclosure)
        layout.addWidget(self._preview_occurrences)
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
        self._advanced_text = QPlainTextEdit(self)
        self._advanced_text.setObjectName("advanced-text")
        self._advanced_text.setReadOnly(True)
        QVBoxLayout(box).addWidget(self._advanced_text)
        return box

    def show_agent(
        self,
        agent: TaskListing,
        report: DiscoveredInspectReport,
        *,
        diagnostics: tuple[Diagnostic, ...] = (),
    ) -> None:
        """Fill every field for a discovered agent and reveal the form."""
        enabled = enabled_state(agent)
        loaded = report.status.loaded if report.status is not None else None
        self._fill(
            agent,
            source=str(agent.path) if agent.path is not None else "(no source)",
            loaded=format_status(report.status),
            state=format_lifecycle_state(enabled, loaded),
            diagnostics=diagnostics,
        )

    def show_saved(self, listing: TaskListing) -> None:
        """Fill every field for a saved (catalog-only) task and reveal the form."""
        self._fill(
            listing,
            source="(task catalog — not installed)",
            loaded="not installed",
            state="Saved, not installed",
        )

    def _fill(
        self,
        listing: TaskListing,
        *,
        source: str,
        loaded: str,
        state: str,
        diagnostics: tuple[Diagnostic, ...] = (),
    ) -> None:
        """Render every section from the presenter output and reveal the form."""
        self._overview["name"].setText(format_name(listing))
        self._overview["label"].setText(format_label(listing))
        self._overview["classification"].setText(classify(listing).value)
        self._overview["source"].setText(source)
        self._overview["state"].setText(state)
        self._overview["enabled"].setText(format_enabled(listing))
        self._overview["loaded"].setText(loaded)
        self._command["command"].setText(format_command(listing))
        self._command["working_directory"].setText(format_working_directory(listing))
        self._schedule_text.setText(format_schedule(listing))
        self._preview_heading.setText(format_upcoming_heading(listing))
        self._preview_disclosure.setText(PREVIEW_DISCLOSURE)
        self._preview_occurrences.setText(
            format_upcoming_occurrences_for(listing, now=self._clock())
        )
        self._environment_text.setText(format_environment(listing))
        warnings_text = format_warnings(listing)
        inspection = format_inspection_diagnostics(diagnostics)
        if inspection:
            warnings_text = f"{warnings_text}\n\n{inspection}"
        self._warnings_text.setText(warnings_text)
        self._advanced_text.setPlainText(format_raw_plist(listing))
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
