"""Presenters that format direct-test results, logs, and environment data.

Every function is pure: it maps service/controller outcomes to display
strings. Environment values are never rendered — only variable names and
difference categories — so secrets in either environment stay hidden.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

from task_scheduler.application.diagnostic_models import (
    Diagnostic,
    DiagnosticReport,
    DiagnosticSource,
    EvidenceState,
)
from task_scheduler.application.log_service import LogStream
from task_scheduler.application.test_service import DirectTestResult
from task_scheduler.domain import JobDefinition, PythonCommand
from task_scheduler.domain.formatting import format_truncation_marker
from task_scheduler.gui.controllers.diagnostics_controller import TestOutcome
from task_scheduler.platform.macos import (
    DetectionNote,
    DetectorKind,
    EnvironmentDifference,
    InterpreterCandidate,
    PythonDetectionResult,
    project_environment_candidate,
)
from task_scheduler.platform.macos.log_reader import LOG_TAIL_BYTES

__all__ = [
    "ENVIRONMENT_DISCLOSURE_TEXT",
    "SOURCE_TITLES",
    "TEST_LIMITATION_TEXT",
    "format_detection_notes",
    "format_diagnostic_block",
    "format_diagnostics",
    "format_duration",
    "format_environment_difference",
    "format_evidence",
    "format_lifecycle_diagnostics",
    "format_log_diagnostics",
    "format_log_stream",
    "format_python_candidate",
    "format_python_detection",
    "format_report",
    "format_test_summary",
    "direct_test_report_path",
    "interpreter_warning",
    "render_direct_test",
]

SOURCE_TITLES: dict[DiagnosticSource, str] = {
    DiagnosticSource.PREFLIGHT: "Configuration checks",
    DiagnosticSource.DIRECT_TEST: "Direct test",
    DiagnosticSource.PYTHON_ENVIRONMENT: "Python environment",
    DiagnosticSource.LIFECYCLE: "Lifecycle",
    DiagnosticSource.LOGS: "Logs",
    DiagnosticSource.PLIST: "Plist",
}

_EVIDENCE_SUFFIXES: dict[EvidenceState, str] = {
    EvidenceState.CONFIRMED: "(evidence: confirmed)",
    EvidenceState.NOT_PROVABLE: "(evidence: not provable)",
    EvidenceState.UNAVAILABLE: "(evidence: unavailable)",
}

TEST_LIMITATION_TEXT = (
    "Test runs this command directly using its configured executable, "
    "arguments, working directory, and environment. It does not prove "
    "launchd can run it on schedule."
)

ENVIRONMENT_DISCLOSURE_TEXT = (
    "The task's scheduled environment is compared against the GUI process "
    "environment, which can differ from your Terminal environment."
)


def format_test_summary(outcome: TestOutcome) -> str:
    """One summary line: pass/fail state, exit code, and duration.

    A process that never started reports its launch failure instead of an
    exit code; a controller-level failure reports the error reason.
    """
    if outcome.error is not None:
        return f"Test could not run: {outcome.error}"
    assert outcome.result is not None
    process = outcome.result.process
    duration = f" in {format_duration(process.duration)}"
    if process.exit_code is None:
        failure = process.launch_failure
        detail = failure.message if failure is not None else "unknown launch failure"
        return f"Failed to launch{duration}: {detail}"
    state = "Passed" if process.exit_code == 0 else "Failed"
    return f"{state} (exit code {process.exit_code}){duration}"


def _block(text: str) -> list[str]:
    """Render an output stream, marking empty content explicitly."""
    return text.splitlines() if text else ["(empty)"]


def render_direct_test(result: DirectTestResult) -> str:
    """The full direct-test report: exit code (or launch failure), duration,
    stdout, stderr, and diagnostics — the artifact saved to disk and shown in
    the dialog.
    """
    process = result.process
    if process.launch_failure is not None:
        failure = process.launch_failure
        lines: list[str] = [f"launch failed ({failure.kind.value}): {failure.message}"]
    else:
        lines = [f"exit code: {process.exit_code}"]
    lines.append(f"duration: {format_duration(process.duration)}")
    lines.append("stdout:")
    lines.extend(_block(process.stdout))
    lines.append("stderr:")
    lines.extend(_block(process.stderr))
    lines.append("diagnostics:")
    lines.extend(_block(format_diagnostics(result.diagnostics)))
    return "\n".join(lines)


def format_duration(duration: timedelta) -> str:
    """Human-readable duration: seconds under a minute, minutes after."""
    total = duration.total_seconds()
    if total < 60:
        return f"{total:.2f}s"
    minutes = int(total // 60)
    return f"{minutes}m {total - minutes * 60:05.2f}s"


def format_diagnostics(diagnostics: list[Diagnostic]) -> str:
    """One severity/title/description/action block per diagnostic."""
    if not diagnostics:
        return "No diagnostics."
    lines: list[str] = []
    for diagnostic in diagnostics:
        lines.append(f"[{diagnostic.severity.value.upper()}] {diagnostic.title}")
        lines.append(diagnostic.description)
        lines.append(f"Suggested: {diagnostic.suggested_action}")
        lines.append("")
    return "\n".join(lines).rstrip()


def format_evidence(state: EvidenceState) -> str:
    """The parenthesized evidence suffix for a finding's evidence state."""
    return _EVIDENCE_SUFFIXES[state]


def format_diagnostic_block(diagnostic: Diagnostic) -> str:
    """One block: severity/title (+ evidence suffix), description, action."""
    state = diagnostic.evidence_state
    suffix = f" {format_evidence(state)}" if state is not None else ""
    lines = [
        f"[{diagnostic.severity.value.upper()}] {diagnostic.title}{suffix}",
        diagnostic.description,
        f"Suggested: {diagnostic.suggested_action}",
    ]
    return "\n".join(lines)


def format_report(report: DiagnosticReport) -> str:
    """Grouped report text: ``== <title> ==`` headings, one block per finding.

    Returns "No diagnostics." when the report carries no findings at all.
    """
    if not report.all:
        return "No diagnostics."
    sections: list[str] = []
    for group in report.groups:
        blocks = "\n\n".join(
            format_diagnostic_block(diagnostic) for diagnostic in group.diagnostics
        )
        sections.append(f"== {SOURCE_TITLES[group.source]} ==\n{blocks}")
    return "\n\n".join(sections)


def _format_single_group(source: DiagnosticSource, diagnostics: tuple[Diagnostic, ...]) -> str:
    """One ``== <title> ==`` section; empty string when there are no findings."""
    if not diagnostics:
        return ""
    blocks = "\n\n".join(format_diagnostic_block(diagnostic) for diagnostic in diagnostics)
    return f"== {SOURCE_TITLES[source]} ==\n{blocks}"


def format_log_diagnostics(diagnostics: tuple[Diagnostic, ...]) -> str:
    """The Logs group rendered as a single section; "" when empty."""
    return _format_single_group(DiagnosticSource.LOGS, diagnostics)


def format_lifecycle_diagnostics(diagnostics: tuple[Diagnostic, ...]) -> str:
    """The Lifecycle group rendered as a single section; "" when empty."""
    return _format_single_group(DiagnosticSource.LIFECYCLE, diagnostics)


def format_log_stream(stream: LogStream) -> str:
    """The stream's content or its state: unconfigured, empty, or unavailable.

    A stream read past the 256 KiB cap is prefixed with the shared
    truncation marker.
    """
    if stream.path is None:
        return "Log path not configured."
    if stream.error is not None:
        return f"Log unavailable: {stream.error}"
    text = stream.content if stream.content else "(empty)"
    if stream.truncated and stream.total_bytes is not None:
        return format_truncation_marker(stream.total_bytes, LOG_TAIL_BYTES) + "\n" + text
    return text


def format_environment_difference(difference: EnvironmentDifference) -> str:
    """Name-only difference report; values are never rendered."""
    return (
        f"GUI process only: {_names(difference.terminal_only)}\n"
        f"Task only: {_names(difference.scheduled_only)}\n"
        f"Different values: {_names(difference.different)}"
    )


def _names(mapping: dict[str, str] | dict[str, tuple[str, str]]) -> str:
    return ", ".join(sorted(mapping)) or "none"


def format_python_candidate(candidate: InterpreterCandidate) -> str:
    """One candidate line: ``path (source)`` plus ecosystem detectors.

    A candidate found by an ecosystem detector appends those detectors
    after a semicolon (``path (source; uv, poetry)``); core-only
    candidates keep the plain ``path (source)`` form.
    """
    ecosystems = [kind.value for kind in candidate.detectors if kind is not DetectorKind.CORE]
    if not ecosystems:
        return f"{candidate.path} ({candidate.source.value})"
    return f"{candidate.path} ({candidate.source.value}; {', '.join(ecosystems)})"


def format_detection_notes(notes: Sequence[DetectionNote]) -> str:
    """The note messages joined on newlines; empty when there are none."""
    return "\n".join(note.message for note in notes)


def format_python_detection(job: JobDefinition, detection: PythonDetectionResult | None) -> str:
    """Detected interpreter candidates, a recommendation line, and notes."""
    command = job.command
    if not isinstance(command, PythonCommand):
        return "Python interpreter detection applies to Python commands only."
    if detection is None:
        return "No candidate interpreters detected."
    if not detection.candidates:
        lines = ["No candidate interpreters detected."]
    else:
        lines = [format_python_candidate(candidate) for candidate in detection.candidates]
        lines.append("")
        project = project_environment_candidate(detection)
        if project is None:
            lines.append("No project environment detected.")
        elif project.path == command.interpreter:
            lines.append("The configured interpreter matches the detected project interpreter.")
        else:
            lines.append(f"Recommended interpreter: {project.path}")
    notes = format_detection_notes(detection.notes)
    if notes:
        lines.append("")
        lines.append(notes)
    return "\n".join(lines)


def interpreter_warning(interpreter_text: str, app_interpreter: Path) -> str | None:
    """Warn when the chosen interpreter lives in the app's own venv.

    The GUI runs from its own virtualenv, which has the app's dependencies but
    not the user's project's. Picking that interpreter (same ``bin`` directory
    as the app's Python) usually means a missing-package failure. Blank or any
    other interpreter yields ``None``.
    """
    text = interpreter_text.strip()
    if not text:
        return None
    if Path(text).parent == app_interpreter.parent:
        return (
            "This is the Python this app runs under; it may lack your script's "
            "dependencies. Pick your project's interpreter instead."
        )
    return None


def direct_test_report_path(job: JobDefinition) -> Path | None:
    """Where a direct-test report is saved: beside the job's configured logs.

    Uses the parent of the job's stdout (else stderr) log path — the log
    directory the user chose in the editor. ``None`` when the job has no
    configured log directory, so nothing is written by default.
    """
    base = job.logging.stdout_path or job.logging.stderr_path
    if base is None:
        return None
    name = job.name.strip() or "task"
    return base.parent / f"{name}.direct-test.log"
