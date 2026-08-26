"""Structured, rule-based diagnostics for jobs and direct test results.

Evaluation is pure: it reads the job, an optional process result, an
optional raw command spec, and an optional detection result. No
filesystem writes, no process execution, no environment capture.
"""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from task_scheduler.domain import JobDefinition, PythonCommand
from task_scheduler.platform.macos.process_runner import LaunchFailureKind, ProcessResult
from task_scheduler.platform.macos.python_detection import (
    CandidateSource,
    PythonDetectionResult,
)


class DiagnosticSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Diagnostic(BaseModel):
    """One structured finding, independent of any UI rendering."""

    severity: DiagnosticSeverity
    code: str
    title: str
    description: str
    suggested_action: str


def _command_executable(job: JobDefinition) -> Path:
    if isinstance(job.command, PythonCommand):
        return job.command.interpreter
    return job.command.executable


def _rule_executable_missing(job: JobDefinition | None) -> Diagnostic | None:
    if job is None:
        return None
    executable = _command_executable(job)
    if executable.is_file():
        return None
    return Diagnostic(
        severity=DiagnosticSeverity.ERROR,
        code="executable_missing",
        title="Executable missing",
        description=f"Configured executable {executable} does not exist.",
        suggested_action="Install the executable or correct its path.",
    )


def _rule_script_missing(job: JobDefinition | None) -> Diagnostic | None:
    if job is None or not isinstance(job.command, PythonCommand):
        return None
    if job.command.script.is_file():
        return None
    return Diagnostic(
        severity=DiagnosticSeverity.ERROR,
        code="script_missing",
        title="Script missing",
        description=f"Configured script {job.command.script} does not exist.",
        suggested_action="Create the script or correct its path.",
    )


def _rule_working_directory_missing(job: JobDefinition | None) -> Diagnostic | None:
    if job is None or job.working_directory is None:
        return None
    if job.working_directory.is_dir():
        return None
    return Diagnostic(
        severity=DiagnosticSeverity.ERROR,
        code="working_directory_missing",
        title="Working directory missing",
        description=f"Configured working directory {job.working_directory} does not exist.",
        suggested_action="Create the directory or clear the setting.",
    )


def _rule_permission_denied(
    job: JobDefinition | None, process: ProcessResult | None
) -> Diagnostic | None:
    statically_denied = False
    if job is not None:
        executable = _command_executable(job)
        statically_denied = executable.is_file() and not os.access(executable, os.X_OK)
    runtime_denied = (
        process is not None
        and process.launch_failure is not None
        and process.launch_failure.kind is LaunchFailureKind.PERMISSION_DENIED
    )
    if not (statically_denied or runtime_denied):
        return None
    return Diagnostic(
        severity=DiagnosticSeverity.ERROR,
        code="permission_denied",
        title="Executable lacks execute permission",
        description="The configured executable cannot be executed by the current user.",
        suggested_action="Add execute permission or choose another executable.",
    )


def _rule_relative_executable(argv0: str | None) -> Diagnostic | None:
    if argv0 is None or Path(argv0).is_absolute():
        return None
    return Diagnostic(
        severity=DiagnosticSeverity.WARNING,
        code="relative_executable",
        title="Executable path is relative",
        description=(
            f"Program {argv0!r} depends on PATH resolution, which launchd does not "
            "provide for scheduled jobs."
        ),
        suggested_action="Use the absolute path of the executable.",
    )


def _rule_interpreter_mismatch(
    job: JobDefinition | None, detection: PythonDetectionResult | None
) -> Diagnostic | None:
    if job is None or not isinstance(job.command, PythonCommand) or detection is None:
        return None
    project_candidate = next(
        (
            candidate
            for candidate in detection.candidates
            if candidate.source in (CandidateSource.VENV, CandidateSource.VENV_FALLBACK)
        ),
        None,
    )
    if project_candidate is None or project_candidate.path == job.command.interpreter:
        return None
    return Diagnostic(
        severity=DiagnosticSeverity.WARNING,
        code="interpreter_mismatch",
        title="Interpreter differs from project environment",
        description=(
            f"Job interpreter {job.command.interpreter} differs from detected "
            f"project interpreter {project_candidate.path}."
        ),
        suggested_action=(
            "Select the detected interpreter if the script relies on the "
            "project environment."
        ),
    )


def _rule_module_not_found(process: ProcessResult | None) -> Diagnostic | None:
    if process is None or "ModuleNotFoundError" not in process.stderr:
        return None
    return Diagnostic(
        severity=DiagnosticSeverity.WARNING,
        code="module_not_found",
        title="Module not found in process output",
        description="The process reported ModuleNotFoundError on stderr.",
        suggested_action="Check the interpreter and environment variables.",
    )


def evaluate_diagnostics(
    job: JobDefinition | None = None,
    *,
    process: ProcessResult | None = None,
    spec_argv0: str | None = None,
    detection: PythonDetectionResult | None = None,
) -> list[Diagnostic]:
    """Evaluate all diagnostic rules in a fixed, deterministic order.

    ``spec_argv0`` is the first argv element of a raw command spec, checked
    defensively: valid jobs always carry absolute paths, so this rule only
    fires for lower-level or imported command inputs.
    """
    rules = (
        _rule_executable_missing(job),
        _rule_script_missing(job),
        _rule_working_directory_missing(job),
        _rule_permission_denied(job, process),
        _rule_relative_executable(spec_argv0),
        _rule_interpreter_mismatch(job, detection),
        _rule_module_not_found(process),
    )
    return [diagnostic for diagnostic in rules if diagnostic is not None]
