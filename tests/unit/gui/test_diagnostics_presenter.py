"""Presenter tests: direct-test summary, logs, environment, and detection text."""

from datetime import timedelta
from pathlib import Path

from tests.conftest import make_job

from task_scheduler.application.diagnostic_models import (
    Diagnostic,
    DiagnosticSeverity,
    EvidenceState,
)
from task_scheduler.application.log_service import LogStream
from task_scheduler.application.test_service import DirectTestResult
from task_scheduler.gui.controllers.diagnostics_controller import TestOutcome
from task_scheduler.gui.presenters.diagnostics_presenter import (
    format_diagnostics,
    format_duration,
    format_evidence,
    format_log_stream,
    format_python_detection,
    format_test_summary,
)
from task_scheduler.platform.macos.process_runner import (
    LaunchFailureKind,
    ProcessLaunchFailure,
    ProcessResult,
)
from task_scheduler.platform.macos.python_detection import (
    CandidateSource,
    DetectionNote,
    DetectorKind,
    InterpreterCandidate,
    PythonDetectionResult,
)


def _result(
    *,
    exit_code: int | None = 0,
    stdout: str = "out",
    stderr: str = "err",
    duration: timedelta = timedelta(milliseconds=250),
    launch_failure: ProcessLaunchFailure | None = None,
    diagnostics: list[Diagnostic] | None = None,
) -> DirectTestResult:
    process = ProcessResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration=duration,
        launch_failure=launch_failure,
    )
    return DirectTestResult(process=process, diagnostics=diagnostics or [])

class TestFormatTestSummary:

    def test_launch_failure_reports_message_instead_of_exit_code(self) -> None:
        failure = ProcessLaunchFailure(
            kind=LaunchFailureKind.NOT_FOUND,
            message="executable not found: /missing/python",
        )
        outcome = TestOutcome(
            label="job",
            result=_result(exit_code=None, launch_failure=failure),
            error=None,
        )
        assert (
            format_test_summary(outcome)
            == "Failed to launch in 0.25s: executable not found: /missing/python"
        )

class TestFormatDuration:

    def test_minute_and_up_uses_minutes_and_seconds(self) -> None:
        assert format_duration(timedelta(seconds=125)) == "2m 05.00s"

class TestFormatDiagnostics:
    def test_empty_reports_no_diagnostics(self) -> None:
        assert format_diagnostics([]) == "No diagnostics."

    def test_one_per_finding_with_severity_and_suggestion(self) -> None:
        diagnostics = [
            Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="env_differs",
                title="Environment differs",
                description="Values changed.",
                suggested_action="Review the variables.",
            )
        ]
        text = format_diagnostics(diagnostics)
        assert "[WARNING] Environment differs" in text
        assert "Values changed." in text
        assert "Suggested: Review the variables." in text

class TestFormatLogStream:

    def test_read_error(self) -> None:
        stream = LogStream(
            name="stdout",
            path=Path("/logs/stdout.log"),
            error="log file not found: /logs/stdout.log",
        )
        assert format_log_stream(stream) == (
            "Log unavailable: log file not found: /logs/stdout.log"
        )

    def test_empty_content(self) -> None:
        stream = LogStream(name="stdout", path=Path("/logs/stdout.log"), content="")
        assert format_log_stream(stream) == "(empty)"

class TestFormatPythonDetection:

    def test_mismatching_project_interpreter_recommends(self) -> None:
        job = make_job()
        other = Path("/Users/example/project/.venv-x/bin/python")
        detection = PythonDetectionResult(
            script=job.command.script,
            candidates=[
                InterpreterCandidate(path=other, source=CandidateSource.VENV),
                InterpreterCandidate(
                    path=Path("/usr/bin/python3"), source=CandidateSource.PATH
                ),
            ],
        )
        text = format_python_detection(job, detection)
        assert f"Recommended interpreter: {other}" in text
        assert str(job.command.interpreter) not in text

    def test_ecosystem_provenance_is_rendered(self) -> None:
        job = make_job()
        other = Path("/Users/example/project/.venv/bin/python")
        detection = PythonDetectionResult(
            script=job.command.script,
            candidates=[
                InterpreterCandidate(
                    path=other,
                    source=CandidateSource.VENV,
                    detectors=(DetectorKind.CORE, DetectorKind.UV),
                )
            ],
        )
        text = format_python_detection(job, detection)
        assert f"{other} (.venv; uv)" in text

    def test_notes_without_candidates(self) -> None:
        job = make_job()
        detection = PythonDetectionResult(
            script=job.command.script,
            candidates=[],
            notes=[
                DetectionNote(
                    detector=DetectorKind.UV,
                    message="a uv project was detected, but no usable "
                    ".venv interpreter is available",
                )
            ],
        )
        assert format_python_detection(job, detection) == (
            "No candidate interpreters detected.\n\n"
            "a uv project was detected, but no usable .venv interpreter is available"
        )

class TestFormatEvidence:
    def test_each_state_has_its_suffix(self) -> None:
        assert format_evidence(EvidenceState.CONFIRMED) == "(evidence: confirmed)"
        assert (
            format_evidence(EvidenceState.NOT_PROVABLE)
            == "(evidence: not provable)"
        )
        assert (
            format_evidence(EvidenceState.UNAVAILABLE) == "(evidence: unavailable)"
        )

