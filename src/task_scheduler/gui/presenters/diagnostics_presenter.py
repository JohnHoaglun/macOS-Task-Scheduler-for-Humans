"""Presenters that format direct-test results, logs, and environment data.

Every function is pure: it maps service/controller outcomes to display
strings. Environment values are never rendered — only variable names and
difference categories — so secrets in either environment stay hidden.
"""

from __future__ import annotations

from datetime import timedelta

from task_scheduler.application.diagnostic_service import Diagnostic
from task_scheduler.application.log_service import LogStream
from task_scheduler.domain import JobDefinition, PythonCommand
from task_scheduler.gui.controllers.diagnostics_controller import TestOutcome
from task_scheduler.platform.macos import (
    CandidateSource,
    EnvironmentDifference,
    InterpreterCandidate,
    PythonDetectionResult,
)

__all__ = [
    "ENVIRONMENT_DISCLOSURE_TEXT",
    "TEST_LIMITATION_TEXT",
    "format_diagnostics",
    "format_duration",
    "format_environment_difference",
    "format_log_stream",
    "format_python_detection",
    "format_test_summary",
]

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


def format_log_stream(stream: LogStream) -> str:
    """The stream's content or its state: unconfigured, empty, or unavailable."""
    if stream.path is None:
        return "Log path not configured."
    if stream.error is not None:
        return f"Log unavailable: {stream.error}"
    if not stream.content:
        return "(empty)"
    return stream.content


def format_environment_difference(difference: EnvironmentDifference) -> str:
    """Name-only difference report; values are never rendered."""
    return (
        f"GUI process only: {_names(difference.terminal_only)}\n"
        f"Task only: {_names(difference.scheduled_only)}\n"
        f"Different values: {_names(difference.different)}"
    )


def _names(mapping: dict[str, str] | dict[str, tuple[str, str]]) -> str:
    return ", ".join(sorted(mapping)) or "none"


def format_python_detection(
    job: JobDefinition, detection: PythonDetectionResult | None
) -> str:
    """Detected interpreter candidates plus a recommendation line."""
    command = job.command
    if not isinstance(command, PythonCommand):
        return "Python interpreter detection applies to Python commands only."
    if detection is None or not detection.candidates:
        return "No candidate interpreters detected."
    lines = [
        f"{candidate.path} ({candidate.source.value})"
        for candidate in detection.candidates
    ]
    lines.append("")
    project = _project_candidate(detection)
    if project is None:
        lines.append("No project environment detected.")
    elif project.path == command.interpreter:
        lines.append(
            "The configured interpreter matches the detected project interpreter."
        )
    else:
        lines.append(f"Recommended interpreter: {project.path}")
    return "\n".join(lines)


def _project_candidate(
    detection: PythonDetectionResult,
) -> InterpreterCandidate | None:
    """The first venv candidate, if any; the recommendation anchor."""
    return next(
        (
            candidate
            for candidate in detection.candidates
            if candidate.source in (CandidateSource.VENV, CandidateSource.VENV_FALLBACK)
        ),
        None,
    )
