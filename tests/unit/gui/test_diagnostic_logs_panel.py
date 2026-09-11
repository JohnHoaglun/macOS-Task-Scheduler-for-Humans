"""Widget tests for the diagnostics/logs panel rendering."""

from datetime import timedelta
from pathlib import Path

from PySide6.QtWidgets import QToolButton, QWidget
from tests.conftest import make_job

from task_scheduler.application.diagnostic_models import (
    Diagnostic,
    DiagnosticGroup,
    DiagnosticReport,
    DiagnosticSeverity,
    DiagnosticSource,
)
from task_scheduler.application.log_service import JobLogs, LogStream
from task_scheduler.application.test_service import DirectTestResult
from task_scheduler.domain import JobDefinition, ShellCommand
from task_scheduler.gui.controllers.diagnostics_controller import (
    EnvironmentOutcome,
    LogsOutcome,
    TestOutcome,
)
from task_scheduler.gui.widgets.diagnostic_logs_panel import DiagnosticLogsPanel
from task_scheduler.platform.macos.process_runner import ProcessResult
from task_scheduler.platform.macos.python_detection import (
    PythonDetectionResult,
)


def _outcome(
    job: JobDefinition,
    *,
    exit_code: int = 0,
    stdout: str = "direct out",
    stderr: str = "direct err",
    detection: PythonDetectionResult | None = None,
    diagnostics: list[Diagnostic] | None = None,
) -> TestOutcome:
    process = ProcessResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration=timedelta(milliseconds=50),
    )
    report = DiagnosticReport(
        groups=(
            DiagnosticGroup(
                source=DiagnosticSource.DIRECT_TEST,
                diagnostics=tuple(diagnostics or ()),
            ),
        )
    )
    return TestOutcome(
        label=job.label,
        result=DirectTestResult(process=process, report=report),
        error=None,
        detection=detection,
    )

class TestShowTestOutcome:

    def test_error_outcome_updates_summary_only(self, qtbot) -> None:
        panel = DiagnosticLogsPanel()
        qtbot.addWidget(panel)
        job = make_job(command=ShellCommand(executable=Path("/bin/true")))
        panel.show_test_outcome(job, _outcome(job))
        panel.show_test_outcome(
            job, TestOutcome(label=job.label, result=None, error="boom")
        )
        assert (
            panel.findChild(object, "diagnostics-summary").text()
            == "Test could not run: boom"
        )
        # Direct output from the earlier render is untouched.
        assert (
            panel.findChild(object, "diagnostics-direct-stdout").toPlainText()
            == "direct out"
        )


class TestCollapsibleSections:
    def test_sections_start_collapsed_toggle_and_stay_collapsed(self, qtbot) -> None:
        panel = DiagnosticLogsPanel()
        qtbot.addWidget(panel)
        names = ("diagnostics-section", "diagnostics-persisted", "diagnostics-python")
        for name in names:
            content = panel.findChild(QWidget, f"{name}-content")
            toggle = panel.findChild(QToolButton, f"{name}-toggle")
            assert content is not None and toggle is not None and content.isHidden()
            toggle.click()
            assert not content.isHidden()
            toggle.click()
            assert content.isHidden()
        job = make_job()
        panel.show_test_outcome(job, _outcome(job))
        panel.show_logs_outcome(LogsOutcome(label=job.label, logs=None, error="missing"))
        assert all(panel.findChild(QWidget, f"{name}-content").isHidden() for name in names)


class TestShowLogsOutcome:

    def test_read_error_reports_unavailable(self, qtbot) -> None:
        panel = DiagnosticLogsPanel()
        qtbot.addWidget(panel)
        panel.show_logs_outcome(
            LogsOutcome(label="job", logs=None, error="catalog failed")
        )
        assert (
            panel.findChild(object, "diagnostics-persisted-stdout").toPlainText()
            == "Logs unavailable: catalog failed"
        )

class TestShowEnvironmentOutcome:

    def test_error_reports_unavailable(self, qtbot) -> None:
        panel = DiagnosticLogsPanel()
        qtbot.addWidget(panel)
        panel.show_environment_outcome(
            EnvironmentOutcome(label="job", difference=None, error="nope")
        )
        assert (
            panel.findChild(object, "diagnostics-environment-text").text()
            == "Comparison unavailable: nope"
        )

class TestDiagnosticsPane:

    def test_logs_outcome_appends_logs_group(self, qtbot) -> None:
        panel = DiagnosticLogsPanel()
        qtbot.addWidget(panel)
        job = make_job()
        panel.show_test_outcome(job, _outcome(job))
        logs = JobLogs(
            stdout=LogStream(
                name="stdout", path=Path("/logs/out.log"), content="persisted"
            ),
            stderr=LogStream(name="stderr", path=None),
        )
        outcome = LogsOutcome(
            label="job",
            logs=logs,
            error=None,
            diagnostics=(
                Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    code="log_path_unreadable",
                    title="Unreadable stdout log",
                    description="The stdout log file could not be read.",
                    suggested_action="Check the configured path.",
                ),
            ),
        )
        panel.show_logs_outcome(outcome)
        assert (
            panel.findChild(object, "diagnostics-diagnostics").toPlainText()
            == "No diagnostics.\n== Logs ==\n[ERROR] Unreadable stdout log\n"
            "The stdout log file could not be read.\n"
            "Suggested: Check the configured path."
        )
