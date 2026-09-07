"""Presenter tests: direct-test summary, logs, environment, and detection text."""

from datetime import timedelta
from pathlib import Path

from task_scheduler.application.diagnostic_models import (
    Diagnostic,
    DiagnosticGroup,
    DiagnosticReport,
    DiagnosticSeverity,
    DiagnosticSource,
    EvidenceState,
)
from task_scheduler.application.log_service import LogStream
from task_scheduler.application.test_service import DirectTestResult
from task_scheduler.domain import ShellCommand
from task_scheduler.gui.controllers.diagnostics_controller import TestOutcome
from task_scheduler.gui.presenters.diagnostics_presenter import (
    ENVIRONMENT_DISCLOSURE_TEXT,
    SOURCE_TITLES,
    TEST_LIMITATION_TEXT,
    format_detection_notes,
    format_diagnostic_block,
    format_diagnostics,
    format_duration,
    format_environment_difference,
    format_evidence,
    format_lifecycle_diagnostics,
    format_log_diagnostics,
    format_log_stream,
    format_python_candidate,
    format_python_detection,
    format_report,
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
    EnvironmentDifference,
    InterpreterCandidate,
    PythonDetectionResult,
)
from tests.conftest import make_job


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
    def test_error_outcome_reports_reason(self) -> None:
        outcome = TestOutcome(label="job", result=None, error="boom")
        assert format_test_summary(outcome) == "Test could not run: boom"

    def test_passing_run_includes_exit_code_and_duration(self) -> None:
        outcome = TestOutcome(label="job", result=_result(), error=None)
        assert (
            format_test_summary(outcome)
            == "Passed (exit code 0) in 0.25s"
        )

    def test_failing_run_reports_nonzero_exit_code(self) -> None:
        outcome = TestOutcome(label="job", result=_result(exit_code=2), error=None)
        assert format_test_summary(outcome) == "Failed (exit code 2) in 0.25s"

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
    def test_sub_minute_uses_seconds(self) -> None:
        assert format_duration(timedelta(milliseconds=1250)) == "1.25s"

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
    def test_unconfigured_path(self) -> None:
        stream = LogStream(name="stdout", path=None)
        assert format_log_stream(stream) == "Log path not configured."

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

    def test_content_passthrough(self) -> None:
        stream = LogStream(name="stdout", path=Path("/logs/stdout.log"), content="hi")
        assert format_log_stream(stream) == "hi"


class TestFormatEnvironmentDifference:
    def test_lists_names_only_in_sorted_order(self) -> None:
        difference = EnvironmentDifference(
            terminal_only={"B_VAR": "1", "A_VAR": "2"},
            scheduled_only={"C_VAR": "3"},
            different={"D_VAR": ("a", "b")},
        )
        text = format_environment_difference(difference)
        assert "GUI process only: A_VAR, B_VAR" in text
        assert "Task only: C_VAR" in text
        assert "Different values: D_VAR" in text
        assert "1" not in text.replace("Different", "")  # values never rendered

    def test_empty_categories_report_none(self) -> None:
        difference = EnvironmentDifference()
        text = format_environment_difference(difference)
        assert "GUI process only: none" in text
        assert "Task only: none" in text
        assert "Different values: none" in text


class TestFormatPythonDetection:
    def test_non_python_jobs_are_out_of_scope(self) -> None:
        job = make_job(command=ShellCommand(executable=Path("/bin/true")))
        assert (
            format_python_detection(job, None)
            == "Python interpreter detection applies to Python commands only."
        )

    def test_no_candidates(self) -> None:
        job = make_job()
        detection = PythonDetectionResult(script=job.command.script, candidates=[])
        assert format_python_detection(job, detection) == (
            "No candidate interpreters detected."
        )

    def test_matching_project_interpreter(self) -> None:
        job = make_job()
        detection = PythonDetectionResult(
            script=job.command.script,
            candidates=[
                InterpreterCandidate(
                    path=job.command.interpreter, source=CandidateSource.VENV
                )
            ],
        )
        text = format_python_detection(job, detection)
        assert str(job.command.interpreter) in text
        assert "(.venv)" in text
        assert (
            "The configured interpreter matches the detected project interpreter."
            in text
        )

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

    def test_no_venv_candidate_reports_missing_project_environment(self) -> None:
        job = make_job()
        detection = PythonDetectionResult(
            script=job.command.script,
            candidates=[
                InterpreterCandidate(
                    path=Path("/usr/bin/python3"), source=CandidateSource.PATH
                )
            ],
        )
        text = format_python_detection(job, detection)
        assert "No project environment detected." in text

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

    def test_notes_appended_after_recommendation(self) -> None:
        job = make_job()
        other = Path("/Users/example/project/.venv-x/bin/python")
        detection = PythonDetectionResult(
            script=job.command.script,
            candidates=[InterpreterCandidate(path=other, source=CandidateSource.VENV)],
            notes=[
                DetectionNote(
                    detector=DetectorKind.POETRY,
                    message="a poetry project was detected, but no usable "
                    ".venv interpreter is available",
                )
            ],
        )
        text = format_python_detection(job, detection)
        assert text.endswith(
            f"Recommended interpreter: {other}\n\n"
            "a poetry project was detected, but no usable "
            ".venv interpreter is available"
        )

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


class TestFormatPythonCandidate:
    def test_core_only_keeps_plain_form(self) -> None:
        candidate = InterpreterCandidate(
            path=Path("/proj/.venv/bin/python"), source=CandidateSource.VENV
        )
        assert format_python_candidate(candidate) == "/proj/.venv/bin/python (.venv)"

    def test_single_ecosystem_detector_appended(self) -> None:
        candidate = InterpreterCandidate(
            path=Path("/proj/.venv/bin/python"),
            source=CandidateSource.VENV,
            detectors=(DetectorKind.UV,),
        )
        assert format_python_candidate(candidate) == "/proj/.venv/bin/python (.venv; uv)"

    def test_multiple_ecosystem_detectors_comma_joined(self) -> None:
        candidate = InterpreterCandidate(
            path=Path("/proj/.venv/bin/python"),
            source=CandidateSource.VENV,
            detectors=(DetectorKind.CORE, DetectorKind.UV, DetectorKind.POETRY),
        )
        assert (
            format_python_candidate(candidate)
            == "/proj/.venv/bin/python (.venv; uv, poetry)"
        )


class TestFormatDetectionNotes:
    def test_empty_notes_yield_empty_string(self) -> None:
        assert format_detection_notes([]) == ""

    def test_messages_joined_on_newlines(self) -> None:
        notes = [
            DetectionNote(detector=DetectorKind.UV, message="first note"),
            DetectionNote(detector=DetectorKind.POETRY, message="second note"),
        ]
        assert format_detection_notes(notes) == "first note\nsecond note"


def _finding(
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR,
    code: str = "some_code",
    title: str = "Something broke",
    description: str = "It did not work.",
    suggested_action: str = "Fix it.",
    evidence_state: EvidenceState | None = None,
) -> Diagnostic:
    return Diagnostic(
        severity=severity,
        code=code,
        title=title,
        description=description,
        suggested_action=suggested_action,
        evidence_state=evidence_state,
    )


class TestSourceTitles:
    def test_all_sources_have_human_titles(self) -> None:
        assert SOURCE_TITLES == {
            DiagnosticSource.PREFLIGHT: "Configuration checks",
            DiagnosticSource.DIRECT_TEST: "Direct test",
            DiagnosticSource.PYTHON_ENVIRONMENT: "Python environment",
            DiagnosticSource.LIFECYCLE: "Lifecycle",
            DiagnosticSource.LOGS: "Logs",
            DiagnosticSource.PLIST: "Plist",
        }


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


class TestFormatDiagnosticBlock:
    def test_without_evidence_state(self) -> None:
        assert (
            format_diagnostic_block(_finding())
            == "[ERROR] Something broke\nIt did not work.\nSuggested: Fix it."
        )

    def test_with_evidence_state(self) -> None:
        assert (
            format_diagnostic_block(
                _finding(evidence_state=EvidenceState.CONFIRMED)
            )
            == "[ERROR] Something broke (evidence: confirmed)\n"
            "It did not work.\nSuggested: Fix it."
        )


class TestFormatReport:
    def test_empty_report_reports_no_diagnostics(self) -> None:
        assert format_report(DiagnosticReport()) == "No diagnostics."

    def test_report_with_empty_group_reports_no_diagnostics(self) -> None:
        report = DiagnosticReport(
            groups=(DiagnosticGroup(source=DiagnosticSource.LOGS, diagnostics=()),)
        )
        assert format_report(report) == "No diagnostics."

    def test_single_group_section(self) -> None:
        report = DiagnosticReport(
            groups=(
                DiagnosticGroup(
                    source=DiagnosticSource.DIRECT_TEST, diagnostics=(_finding(),)
                ),
            )
        )
        assert (
            format_report(report)
            == "== Direct test ==\n[ERROR] Something broke\n"
            "It did not work.\nSuggested: Fix it."
        )

    def test_multiple_groups_joined_with_blank_line(self) -> None:
        report = DiagnosticReport(
            groups=(
                DiagnosticGroup(
                    source=DiagnosticSource.PREFLIGHT,
                    diagnostics=(_finding(title="First"),),
                ),
                DiagnosticGroup(
                    source=DiagnosticSource.LOGS,
                    diagnostics=(_finding(title="Second"),),
                ),
            )
        )
        assert (
            format_report(report)
            == "== Configuration checks ==\n[ERROR] First\n"
            "It did not work.\nSuggested: Fix it.\n\n"
            "== Logs ==\n[ERROR] Second\nIt did not work.\nSuggested: Fix it."
        )


class TestFormatLogAndLifecycleDiagnostics:
    def test_empty_log_diagnostics_yield_empty_string(self) -> None:
        assert format_log_diagnostics(()) == ""

    def test_log_diagnostics_render_logs_section(self) -> None:
        assert (
            format_log_diagnostics((_finding(code="log_path_unreadable"),))
            == "== Logs ==\n[ERROR] Something broke\n"
            "It did not work.\nSuggested: Fix it."
        )

    def test_empty_lifecycle_diagnostics_yield_empty_string(self) -> None:
        assert format_lifecycle_diagnostics(()) == ""

    def test_lifecycle_diagnostics_render_lifecycle_section(self) -> None:
        assert (
            format_lifecycle_diagnostics((_finding(code="bootstrap_failure"),))
            == "== Lifecycle ==\n[ERROR] Something broke\n"
            "It did not work.\nSuggested: Fix it."
        )


class TestConstants:
    def test_limitation_text_mentions_direct_run_and_launchd(self) -> None:
        assert "directly" in TEST_LIMITATION_TEXT
        assert "launchd" in TEST_LIMITATION_TEXT

    def test_environment_disclosure_mentions_gui_process(self) -> None:
        assert "GUI process" in ENVIRONMENT_DISCLOSURE_TEXT
