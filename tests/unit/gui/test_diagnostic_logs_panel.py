"""Widget tests for the diagnostics/logs panel rendering."""

from datetime import timedelta
from pathlib import Path

from PySide6.QtWidgets import QPlainTextEdit

from task_scheduler.application.diagnostic_service import (
    Diagnostic,
    DiagnosticSeverity,
)
from task_scheduler.application.log_service import JobLogs, LogStream
from task_scheduler.application.test_service import DirectTestResult
from task_scheduler.domain import JobDefinition, ShellCommand
from task_scheduler.gui.controllers.diagnostics_controller import (
    EnvironmentOutcome,
    LogsOutcome,
    TestOutcome,
)
from task_scheduler.gui.presenters.diagnostics_presenter import (
    ENVIRONMENT_DISCLOSURE_TEXT,
    TEST_LIMITATION_TEXT,
)
from task_scheduler.gui.widgets.diagnostic_logs_panel import DiagnosticLogsPanel
from task_scheduler.platform.macos.process_runner import ProcessResult
from task_scheduler.platform.macos.python_detection import (
    CandidateSource,
    EnvironmentDifference,
    InterpreterCandidate,
    PythonDetectionResult,
)
from tests.conftest import make_job


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
    return TestOutcome(
        label=job.label,
        result=DirectTestResult(
            process=process, diagnostics=diagnostics or []
        ),
        error=None,
        detection=detection,
    )


class TestPanelConstruction:
    def test_initial_state(self, qtbot) -> None:
        panel = DiagnosticLogsPanel()
        qtbot.addWidget(panel)
        assert (
            panel.findChild(object, "diagnostics-summary").text()
            == "Run Test to check this task directly."
        )
        assert (
            panel.findChild(object, "diagnostics-limitation").text()
            == TEST_LIMITATION_TEXT
        )
        assert panel.refresh_button.objectName() == "diagnostics-log-refresh"
        assert (
            panel.findChild(object, "diagnostics-environment-disclosure").text()
            == ENVIRONMENT_DISCLOSURE_TEXT
        )

    def test_tabs_are_read_only(self, qtbot) -> None:
        panel = DiagnosticLogsPanel()
        qtbot.addWidget(panel)
        tabs = panel.findChild(object, "diagnostics-tabs")
        for index in range(tabs.count()):
            page = tabs.widget(index)
            assert isinstance(page, QPlainTextEdit)
            assert page.isReadOnly()

    def test_refresh_button_emits_clicked(self, qtbot) -> None:
        panel = DiagnosticLogsPanel()
        qtbot.addWidget(panel)
        clicks: list[bool] = []
        panel.refresh_button.clicked.connect(lambda checked: clicks.append(checked))
        panel.refresh_button.click()
        assert len(clicks) == 1


class TestShowTestOutcome:
    def test_renders_summary_diagnostics_and_direct_output(
        self, qtbot
    ) -> None:
        panel = DiagnosticLogsPanel()
        qtbot.addWidget(panel)
        job = make_job(
            command=ShellCommand(executable=Path("/bin/true"))
        )
        outcome = _outcome(
            job,
            diagnostics=[
                Diagnostic(
                    severity=DiagnosticSeverity.INFO,
                    code="ok",
                    title="Looks fine",
                    description="No issues.",
                    suggested_action="None.",
                )
            ],
        )
        panel.show_test_outcome(job, outcome)
        assert (
            panel.findChild(object, "diagnostics-summary").text()
            == "Passed (exit code 0) in 0.05s"
        )
        assert (
            panel.findChild(object, "diagnostics-direct-stdout").toPlainText()
            == "direct out"
        )
        assert (
            panel.findChild(object, "diagnostics-direct-stderr").toPlainText()
            == "direct err"
        )
        assert "[INFO] Looks fine" in panel.findChild(
            object, "diagnostics-diagnostics"
        ).toPlainText()

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

    def test_python_detection_renders_recommendation(self, qtbot) -> None:
        panel = DiagnosticLogsPanel()
        qtbot.addWidget(panel)
        job = make_job()
        other = Path("/Users/example/project/.venv/bin/python3.13")
        outcome = _outcome(
            job,
            detection=PythonDetectionResult(
                script=job.command.script,
                candidates=[InterpreterCandidate(path=other, source=CandidateSource.VENV)],
            ),
        )
        panel.show_test_outcome(job, outcome)
        assert f"Recommended interpreter: {other}" in panel.findChild(
            object, "diagnostics-python-text"
        ).text()


class TestShowLogsOutcome:
    def test_renders_persisted_tabs(self, qtbot) -> None:
        panel = DiagnosticLogsPanel()
        qtbot.addWidget(panel)
        logs = JobLogs(
            stdout=LogStream(
                name="stdout", path=Path("/logs/out.log"), content="persisted"
            ),
            stderr=LogStream(
                name="stderr",
                path=Path("/logs/err.log"),
                error="log file not found: /logs/err.log",
            ),
        )
        panel.show_logs_outcome(LogsOutcome(label="job", logs=logs, error=None))
        assert (
            panel.findChild(object, "diagnostics-persisted-stdout").toPlainText()
            == "persisted"
        )
        assert (
            panel.findChild(object, "diagnostics-persisted-stderr").toPlainText()
            == "Log unavailable: log file not found: /logs/err.log"
        )

    def test_unconfigured_stream_reports_state(self, qtbot) -> None:
        panel = DiagnosticLogsPanel()
        qtbot.addWidget(panel)
        logs = JobLogs(
            stdout=LogStream(name="stdout", path=None),
            stderr=LogStream(name="stderr", path=None),
        )
        panel.show_logs_outcome(LogsOutcome(label="job", logs=logs, error=None))
        assert (
            panel.findChild(object, "diagnostics-persisted-stdout").toPlainText()
            == "Log path not configured."
        )

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
    def test_renders_difference(self, qtbot) -> None:
        panel = DiagnosticLogsPanel()
        qtbot.addWidget(panel)
        difference = EnvironmentDifference(
            terminal_only={"B_VAR": "1"},
            scheduled_only={"C_VAR": "2"},
            different={"D_VAR": ("a", "b")},
        )
        panel.show_environment_outcome(
            EnvironmentOutcome(label="job", difference=difference, error=None)
        )
        text = panel.findChild(object, "diagnostics-environment-text").text()
        assert "A_VAR" not in text
        assert "B_VAR" in text and "C_VAR" in text and "D_VAR" in text
        assert "1" not in text

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
