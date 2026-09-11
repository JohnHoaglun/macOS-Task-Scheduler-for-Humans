"""Panel rendering direct-test results, diagnostics, and persisted logs.

The panel is job-based and outcome-driven: callers feed it controller
outcomes (for a selected managed task or a validated draft). It renders
state only — it never calls services itself; the Refresh button emits a
signal the host wires to the controller.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from task_scheduler.domain import JobDefinition
from task_scheduler.gui.controllers.diagnostics_controller import (
    EnvironmentOutcome,
    LogsOutcome,
    TestOutcome,
)
from task_scheduler.gui.presenters.diagnostics_presenter import (
    ENVIRONMENT_DISCLOSURE_TEXT,
    TEST_LIMITATION_TEXT,
    format_environment_difference,
    format_log_diagnostics,
    format_log_stream,
    format_python_detection,
    format_report,
    format_test_summary,
)

__all__ = ["DiagnosticLogsPanel"]


class DiagnosticLogsPanel(QWidget):
    """Direct-test summary, diagnostics, log tabs, and environment groups.

    Public surface: :meth:`show_test_outcome`, :meth:`show_logs_outcome`,
    :meth:`show_environment_outcome`, and ``refresh_button`` (the host
    connects its ``clicked`` signal to the controller's synchronous read).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        diagnostics_content = QWidget(self)
        self._summary = QLabel(diagnostics_content)
        self._summary.setObjectName("diagnostics-summary")
        self._summary.setWordWrap(True)
        self._summary.setText("Run Test to check this task directly.")

        self._limitation = QLabel(TEST_LIMITATION_TEXT, diagnostics_content)
        self._limitation.setObjectName("diagnostics-limitation")
        self._limitation.setWordWrap(True)

        self._diagnostics_text = QPlainTextEdit(diagnostics_content)
        self._diagnostics_text.setObjectName("diagnostics-diagnostics")
        self._diagnostics_text.setReadOnly(True)
        self._diagnostics_text.setPlainText("No diagnostics.")

        self._tabs = QTabWidget(diagnostics_content)
        self._tabs.setObjectName("diagnostics-tabs")
        self._direct_stdout = self._add_tab(
            "Direct stdout", "diagnostics-direct-stdout"
        )
        self._direct_stderr = self._add_tab(
            "Direct stderr", "diagnostics-direct-stderr"
        )

        diagnostics_layout = QVBoxLayout(diagnostics_content)
        diagnostics_layout.addWidget(self._summary)
        diagnostics_layout.addWidget(self._limitation)
        diagnostics_layout.addWidget(self._diagnostics_text)
        diagnostics_layout.addWidget(self._tabs)

        persisted_content = QWidget(self)
        self._persisted_tabs = QTabWidget(persisted_content)
        self._persisted_tabs.setObjectName("diagnostics-persisted-tabs")
        self._persisted_stdout = self._add_tab(
            "Persisted stdout", "diagnostics-persisted-stdout", self._persisted_tabs
        )
        self._persisted_stderr = self._add_tab(
            "Persisted stderr", "diagnostics-persisted-stderr", self._persisted_tabs
        )

        refresh_row = QHBoxLayout()
        refresh_row.addWidget(QLabel("Persisted logs", persisted_content))
        refresh_row.addStretch(1)
        self.refresh_button = QPushButton("Refresh", persisted_content)
        self.refresh_button.setObjectName("diagnostics-log-refresh")
        refresh_row.addWidget(self.refresh_button)

        persisted_layout = QVBoxLayout(persisted_content)
        persisted_layout.addWidget(self._persisted_tabs)
        persisted_layout.addLayout(refresh_row)

        self._environment_disclosure = QLabel(ENVIRONMENT_DISCLOSURE_TEXT, self)
        self._environment_disclosure.setObjectName(
            "diagnostics-environment-disclosure"
        )
        self._environment_disclosure.setWordWrap(True)
        self._environment_text = QLabel(self)
        self._environment_text.setObjectName("diagnostics-environment-text")
        self._environment_text.setWordWrap(True)
        environment_layout = QVBoxLayout()
        environment_layout.addWidget(self._environment_disclosure)
        environment_layout.addWidget(self._environment_text)
        self._environment_box = QGroupBox("Environment", self)
        self._environment_box.setObjectName("diagnostics-environment")
        self._environment_box.setLayout(environment_layout)

        python_content = QWidget(self)
        self._python_text = QLabel(python_content)
        self._python_text.setObjectName("diagnostics-python-text")
        self._python_text.setWordWrap(True)
        python_layout = QVBoxLayout()
        python_layout.addWidget(self._python_text)
        python_content.setLayout(python_layout)

        layout = QVBoxLayout(self)
        layout.addWidget(
            self._collapsible_section("Diagnostics", "diagnostics-section", diagnostics_content)
        )
        layout.addWidget(
            self._collapsible_section("Persisted logs", "diagnostics-persisted", persisted_content)
        )
        layout.addWidget(self._environment_box)
        layout.addWidget(
            self._collapsible_section("Python interpreter", "diagnostics-python", python_content)
        )

    def _collapsible_section(
        self, title: str, object_name: str, content: QWidget
    ) -> QWidget:
        """Create a collapsed disclosure header and its hidden content."""
        section = QWidget(self)
        section.setObjectName(object_name)
        toggle = QToolButton(section)
        toggle.setObjectName(f"{object_name}-toggle")
        toggle.setText(title)
        toggle.setCheckable(True)
        content.setObjectName(f"{object_name}-content")
        content.hide()
        toggle.toggled.connect(content.setVisible)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(toggle)
        layout.addWidget(content)
        return section

    def _add_tab(
        self, title: str, object_name: str, tabs: QTabWidget | None = None
    ) -> QPlainTextEdit:
        """Create a read-only tab page and return it."""
        parent = tabs or self._tabs
        edit = QPlainTextEdit(parent)
        edit.setObjectName(object_name)
        edit.setReadOnly(True)
        parent.addTab(edit, title)
        return edit

    def show_notice(self, text: str) -> None:
        """Replace the summary line with a caller-supplied notice."""
        self._summary.setText(text)

    def show_test_outcome(self, job: JobDefinition, outcome: TestOutcome) -> None:
        """Render the summary, diagnostics, direct-output tabs, and detection."""
        self._summary.setText(format_test_summary(outcome))
        if outcome.result is not None:
            self._diagnostics_text.setPlainText(format_report(outcome.result.report))
            self._direct_stdout.setPlainText(outcome.result.process.stdout)
            self._direct_stderr.setPlainText(outcome.result.process.stderr)
        else:
            self._diagnostics_text.setPlainText("No diagnostics.")
        self._python_text.setText(format_python_detection(job, outcome.detection))

    def show_logs_outcome(self, outcome: LogsOutcome) -> None:
        """Render the persisted stdout/stderr tabs from a synchronous read."""
        if outcome.logs is None:
            message = f"Logs unavailable: {outcome.error}"
            self._persisted_stdout.setPlainText(message)
            self._persisted_stderr.setPlainText(message)
            self._diagnostics_text.setPlainText("No diagnostics.")
            return
        self._persisted_stdout.setPlainText(format_log_stream(outcome.logs.stdout))
        self._persisted_stderr.setPlainText(format_log_stream(outcome.logs.stderr))
        if outcome.diagnostics:
            self._diagnostics_text.appendPlainText(
                format_log_diagnostics(outcome.diagnostics)
            )

    def show_environment_outcome(self, outcome: EnvironmentOutcome) -> None:
        """Render the environment comparison (names only, never values)."""
        if outcome.difference is None:
            self._environment_text.setText(
                f"Comparison unavailable: {outcome.error}"
            )
            return
        self._environment_text.setText(
            format_environment_difference(outcome.difference)
        )
