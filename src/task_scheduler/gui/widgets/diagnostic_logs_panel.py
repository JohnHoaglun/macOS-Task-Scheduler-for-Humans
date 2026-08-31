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
    format_diagnostics,
    format_environment_difference,
    format_log_stream,
    format_python_detection,
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
        self._summary = QLabel(self)
        self._summary.setObjectName("diagnostics-summary")
        self._summary.setWordWrap(True)
        self._summary.setText("Run Test to check this task directly.")

        self._limitation = QLabel(TEST_LIMITATION_TEXT, self)
        self._limitation.setObjectName("diagnostics-limitation")
        self._limitation.setWordWrap(True)

        self._diagnostics_text = QPlainTextEdit(self)
        self._diagnostics_text.setObjectName("diagnostics-diagnostics")
        self._diagnostics_text.setReadOnly(True)

        self._tabs = QTabWidget(self)
        self._tabs.setObjectName("diagnostics-tabs")
        self._direct_stdout = self._add_tab(
            "Direct stdout", "diagnostics-direct-stdout"
        )
        self._direct_stderr = self._add_tab(
            "Direct stderr", "diagnostics-direct-stderr"
        )
        self._persisted_stdout = self._add_tab(
            "Persisted stdout", "diagnostics-persisted-stdout"
        )
        self._persisted_stderr = self._add_tab(
            "Persisted stderr", "diagnostics-persisted-stderr"
        )

        refresh_row = QHBoxLayout()
        refresh_row.addWidget(QLabel("Persisted logs", self))
        refresh_row.addStretch(1)
        self.refresh_button = QPushButton("Refresh", self)
        self.refresh_button.setObjectName("diagnostics-log-refresh")
        refresh_row.addWidget(self.refresh_button)

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

        self._python_text = QLabel(self)
        self._python_text.setObjectName("diagnostics-python-text")
        self._python_text.setWordWrap(True)
        python_layout = QVBoxLayout()
        python_layout.addWidget(self._python_text)
        self._python_box = QGroupBox("Python interpreter", self)
        self._python_box.setObjectName("diagnostics-python")
        self._python_box.setLayout(python_layout)

        layout = QVBoxLayout(self)
        layout.addWidget(self._summary)
        layout.addWidget(self._limitation)
        layout.addWidget(self._diagnostics_text)
        layout.addWidget(self._tabs)
        layout.addLayout(refresh_row)
        layout.addWidget(self._environment_box)
        layout.addWidget(self._python_box)

    def _add_tab(self, title: str, object_name: str) -> QPlainTextEdit:
        """Create a read-only tab page and return it."""
        edit = QPlainTextEdit(self)
        edit.setObjectName(object_name)
        edit.setReadOnly(True)
        self._tabs.addTab(edit, title)
        return edit

    def show_test_outcome(self, job: JobDefinition, outcome: TestOutcome) -> None:
        """Render the summary, diagnostics, direct-output tabs, and detection."""
        self._summary.setText(format_test_summary(outcome))
        if outcome.result is not None:
            self._diagnostics_text.setPlainText(
                format_diagnostics(outcome.result.diagnostics)
            )
            self._direct_stdout.setPlainText(outcome.result.process.stdout)
            self._direct_stderr.setPlainText(outcome.result.process.stderr)
        self._python_text.setText(format_python_detection(job, outcome.detection))

    def show_logs_outcome(self, outcome: LogsOutcome) -> None:
        """Render the persisted stdout/stderr tabs from a synchronous read."""
        if outcome.logs is None:
            message = f"Logs unavailable: {outcome.error}"
            self._persisted_stdout.setPlainText(message)
            self._persisted_stderr.setPlainText(message)
            return
        self._persisted_stdout.setPlainText(format_log_stream(outcome.logs.stdout))
        self._persisted_stderr.setPlainText(format_log_stream(outcome.logs.stderr))

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
