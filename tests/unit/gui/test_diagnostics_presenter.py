"""Presenter tests: summary, duration, evidence, log stream, and detection text."""

from datetime import timedelta
from pathlib import Path

from tests.conftest import make_job

from task_scheduler.application.diagnostic_models import EvidenceState
from task_scheduler.application.log_service import LogStream
from task_scheduler.application.test_service import DirectTestResult
from task_scheduler.gui.controllers.diagnostics_controller import TestOutcome
from task_scheduler.gui.presenters.diagnostics_presenter import (
    format_duration,
    format_evidence,
    format_log_stream,
    format_python_detection,
    format_test_summary,
    render_direct_test,
)
from task_scheduler.platform.macos.log_reader import LOG_TAIL_BYTES
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
    duration: timedelta = timedelta(milliseconds=250),
    launch_failure: ProcessLaunchFailure | None = None,
) -> DirectTestResult:
    process = ProcessResult(
        exit_code=exit_code, stdout="out", stderr="err",
        duration=duration, launch_failure=launch_failure,
    )
    return DirectTestResult(process=process, diagnostics=[])

class TestFormatTestSummary:
    def test_launch_failure_reports_message_instead_of_exit_code(self) -> None:
        failure = ProcessLaunchFailure(
            kind=LaunchFailureKind.NOT_FOUND, message="executable not found: /missing/python")
        outcome = TestOutcome(
            label="job", result=_result(exit_code=None, launch_failure=failure), error=None)
        assert format_test_summary(outcome) == (
            "Failed to launch in 0.25s: executable not found: /missing/python")

class TestFormatDuration:
    def test_minute_and_up_uses_minutes_and_seconds(self) -> None:
        assert format_duration(timedelta(seconds=125)) == "2m 05.00s"

class TestFormatEvidence:
    def test_each_state_has_its_suffix(self) -> None:
        assert format_evidence(EvidenceState.CONFIRMED) == "(evidence: confirmed)"
        assert format_evidence(EvidenceState.NOT_PROVABLE) == "(evidence: not provable)"
        assert format_evidence(EvidenceState.UNAVAILABLE) == "(evidence: unavailable)"

class TestFormatLogStream:
    def test_read_error(self) -> None:
        stream = LogStream(
            name="stdout", path=Path("/logs/stdout.log"),
            error="log file not found: /logs/stdout.log")
        assert format_log_stream(stream) == "Log unavailable: log file not found: /logs/stdout.log"

    def test_truncated_content_is_prefixed_with_marker(self) -> None:
        stream = LogStream(
            name="stdout", path=Path("/logs/stdout.log"), content="line",
            truncated=True, total_bytes=LOG_TAIL_BYTES * 3)
        assert format_log_stream(stream) == (
            f"(truncated: showing the last 256 KiB of {LOG_TAIL_BYTES * 3} bytes)\nline"
        )

class TestFormatPythonDetection:
    def test_mismatching_project_interpreter_recommends(self) -> None:
        job = make_job()
        other = Path("/Users/example/project/.venv-x/bin/python")
        detection = PythonDetectionResult(
            script=job.command.script, candidates=[
                InterpreterCandidate(path=other, source=CandidateSource.VENV),
                InterpreterCandidate(path=Path("/usr/bin/python3"), source=CandidateSource.PATH),
            ])
        text = format_python_detection(job, detection)
        assert f"Recommended interpreter: {other}" in text
        assert str(job.command.interpreter) not in text

    def test_ecosystem_provenance_is_rendered(self) -> None:
        job = make_job()
        other = Path("/Users/example/project/.venv/bin/python")
        detection = PythonDetectionResult(
            script=job.command.script, candidates=[InterpreterCandidate(
                path=other, source=CandidateSource.VENV,
                detectors=(DetectorKind.CORE, DetectorKind.UV),
            )])
        text = format_python_detection(job, detection)
        assert f"{other} (.venv; uv)" in text

    def test_notes_without_candidates(self) -> None:
        job = make_job()
        detection = PythonDetectionResult(
            script=job.command.script, candidates=[], notes=[DetectionNote(
                detector=DetectorKind.UV, message="a uv project was detected, "
                "but no usable .venv interpreter is available",
            )])
        assert format_python_detection(job, detection) == (
            "No candidate interpreters detected.\n\n"
            "a uv project was detected, but no usable .venv interpreter is available"
        )

class TestRenderDirectTest:
    def test_launch_failure_replaces_exit_code(self) -> None:
        failure = ProcessLaunchFailure(
            kind=LaunchFailureKind.NOT_FOUND, message="executable not found: /missing/python"
        )
        text = render_direct_test(_result(exit_code=None, launch_failure=failure))
        assert "launch failed" in text and "executable not found: /missing/python" in text
        assert "exit code:" not in text
