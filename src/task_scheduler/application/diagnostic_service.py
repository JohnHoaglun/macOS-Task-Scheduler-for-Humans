"""Structured, rule-based diagnostics for jobs and direct test results.

Evaluation is pure: it reads the job, an optional process result, an
optional raw command spec, and an optional detection result. No
filesystem writes, no process execution, no environment capture. The
report models and contexts live in ``diagnostic_models``.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from task_scheduler.application.diagnostic_models import (
    Diagnostic,
    DiagnosticContext,
    DiagnosticGroup,
    DiagnosticReport,
    DiagnosticSeverity,
    DiagnosticSource,
    DirectTestContext,
    EvidenceState,
    InspectionContext,
    LifecycleContext,
    LogContext,
    PreflightContext,
    PythonEnvironmentContext,
)
from task_scheduler.application.log_service import JobLogs
from task_scheduler.domain import JobDefinition, PythonCommand
from task_scheduler.platform.macos.diagnostic_probes import (
    ArchitectureFinding,
    ProtectedPathFinding,
)
from task_scheduler.platform.macos.launch_agent_store import validate_label
from task_scheduler.platform.macos.plist_models import ParsedLaunchAgent, ParseSupport
from task_scheduler.platform.macos.process_runner import LaunchFailureKind, ProcessResult
from task_scheduler.platform.macos.python_detection import (
    PythonDetectionResult,
    project_environment_candidate,
)

_CPU_LABELS: dict[int, str] = {
    0x0100000C: "arm64",
    0x07000003: "x86_64",
    7: "x86",
}

_MODULE_FAILURE_PATTERNS: tuple[str, ...] = (
    "ModuleNotFoundError",
    "ImportError",
    "No module named",
    "cannot import name",
)


def _first_of[T: DiagnosticContext](
    contexts: Sequence[DiagnosticContext], context_type: type[T]
) -> T | None:
    for context in contexts:
        if isinstance(context, context_type):
            return context
    return None


def _command_executable(job: JobDefinition) -> Path:
    if isinstance(job.command, PythonCommand):
        return job.command.interpreter
    return job.command.executable


def collect_preflight_paths(job: JobDefinition) -> tuple[Path, ...]:
    """Return the deduplicated probe paths for *job*, executable first."""
    paths: list[Path] = []
    seen: set[str] = set()
    for path in (
        _command_executable(job),
        job.command.script if isinstance(job.command, PythonCommand) else None,
        job.working_directory,
        job.logging.stdout_path,
        job.logging.stderr_path,
    ):
        if path is None or str(path) in seen:
            continue
        seen.add(str(path))
        paths.append(path)
    return tuple(paths)


def _cpu_label(cputype: int) -> str:
    return _CPU_LABELS.get(cputype, f"0x{cputype:08X}")


def _permission_denied_diagnostic() -> Diagnostic:
    return Diagnostic(
        severity=DiagnosticSeverity.ERROR,
        code="permission_denied",
        title="Executable lacks execute permission",
        description="The configured executable cannot be executed by the current user.",
        suggested_action="Add execute permission or choose another executable.",
    )


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


def _rule_permission_denied_static(job: JobDefinition | None) -> Diagnostic | None:
    if job is None:
        return None
    executable = _command_executable(job)
    if not (executable.is_file() and not os.access(executable, os.X_OK)):
        return None
    return _permission_denied_diagnostic()


def _rule_permission_denied_runtime(process: ProcessResult | None) -> Diagnostic | None:
    if process is None:
        return None
    if (
        process.launch_failure is not None
        and process.launch_failure.kind is LaunchFailureKind.PERMISSION_DENIED
    ):
        return _permission_denied_diagnostic()
    return None


def _rule_executable_not_found_runtime(
    job: JobDefinition | None, process: ProcessResult | None
) -> Diagnostic | None:
    if job is None or process is None:
        return None
    if process.launch_failure is None:
        return None
    if process.launch_failure.kind is not LaunchFailureKind.NOT_FOUND:
        return None
    executable = _command_executable(job)
    if not executable.is_file():
        return None
    return Diagnostic(
        severity=DiagnosticSeverity.ERROR,
        code="executable_not_found_runtime",
        title="Executable exists but launch failed",
        description=(
            f"Executable {executable} exists on disk but the direct launch "
            "failed with a not-found error (possible architecture mismatch, "
            "missing shebang, or unsatisfied dependencies)."
        ),
        suggested_action="Verify the executable can run on this machine.",
        evidence_state=EvidenceState.CONFIRMED,
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
    project_candidate = project_environment_candidate(detection)
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
    if process is None:
        return None
    if not any(pattern in process.stderr for pattern in _MODULE_FAILURE_PATTERNS):
        return None
    return Diagnostic(
        severity=DiagnosticSeverity.WARNING,
        code="module_not_found",
        title="Python import failure in process output",
        description="The process reported a Python import failure on stderr.",
        suggested_action="Check the interpreter and environment variables.",
    )


def _rule_protected_path(
    findings: tuple[ProtectedPathFinding, ...],
) -> tuple[Diagnostic, ...]:
    return tuple(
        Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="protected_path",
            title="Path is in a macOS-protected location",
            description=(
                f"Path {finding.path} falls under {finding.root}. macOS may restrict "
                "this location for launchd-run jobs and this app cannot confirm the "
                "access decision."
            ),
            suggested_action=(
                "Move the job to a non-restricted location, or grant Full Disk "
                "Access if it must stay here."
            ),
            evidence_state=EvidenceState.NOT_PROVABLE,
        )
        for finding in findings
    )


def _rule_architecture_mismatch(
    finding: ArchitectureFinding | None,
) -> Diagnostic | None:
    if finding is None:
        return None
    declared_labels = ", ".join(_cpu_label(c) for c in finding.declared)
    return Diagnostic(
        severity=DiagnosticSeverity.WARNING,
        code="architecture_mismatch",
        title="Executable architecture may not match host",
        description=(
            f"The executable {finding.path} declares cputype(s) {declared_labels} "
            f"but the host is {_cpu_label(finding.host)}. launchd may not start it "
            "without translation, and this app cannot confirm Rosetta behavior."
        ),
        suggested_action="Provide an executable built for the host architecture.",
        evidence_state=EvidenceState.CONFIRMED,
    )


def _rule_log_path_unreadable(logs: JobLogs) -> tuple[Diagnostic, ...]:
    return tuple(
        Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="log_path_unreadable",
            title="Log path is unreadable",
            description=(
                f"Could not read the {stream.name} log at {stream.path}: "
                f"{stream.error}."
            ),
            suggested_action="Check that the log path exists and is readable.",
        )
        for stream in (logs.stdout, logs.stderr)
        if stream.error is not None
    )


def _rule_bootstrap_failure(label: str, action: str, result: object) -> Diagnostic | None:
    phases = getattr(result, "phases", None)
    if phases is None:
        return None
    for phase in phases:
        if phase.name != "bootstrap":
            continue
        if phase.process.exit_code != 0:
            return Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                code="bootstrap_failure",
                title="launchctl bootstrap failed",
                description=(
                    f"launchctl bootstrap of {label} during {action} exited with "
                    f"code {phase.process.exit_code}."
                ),
                suggested_action=(
                    "Check the installed plist and verify the executable can run "
                    "on this machine."
                ),
            )
    return None


def _rule_malformed_plist(path: Path, parsed: ParsedLaunchAgent) -> Diagnostic | None:
    if parsed.status is not ParseSupport.INVALID:
        return None
    details = f" Parser warnings: {'; '.join(parsed.warnings)}." if parsed.warnings else ""
    return Diagnostic(
        severity=DiagnosticSeverity.ERROR,
        code="malformed_plist",
        title="Plist could not be parsed",
        description=f"The plist at {path} could not be parsed as a LaunchAgent.{details}",
        suggested_action="Fix the plist syntax or recreate the agent.",
    )


def _rule_invalid_plist_label(path: Path, parsed: ParsedLaunchAgent) -> Diagnostic | None:
    if not parsed.raw:
        return None
    label = parsed.raw.get("Label")
    if not isinstance(label, str) or not label:
        return Diagnostic(
            severity=DiagnosticSeverity.ERROR,
            code="invalid_plist_label",
            title="Plist label missing or empty",
            description=f"The plist at {path} has no usable Label value: {label!r}.",
            suggested_action="Add a valid Label key to the plist.",
        )
    try:
        validate_label(label)
    except ValueError:
        return Diagnostic(
            severity=DiagnosticSeverity.ERROR,
            code="invalid_plist_label",
            title="Plist label invalid",
            description=(
                f"The Label value {label!r} in the plist at {path} would be "
                "rejected by launchd."
            ),
            suggested_action="Correct the Label key to a valid identifier.",
        )
    return None


def _evaluate_preflight(
    context: PreflightContext, spec_argv0: str | None
) -> tuple[Diagnostic, ...]:
    candidates = (
        _rule_executable_missing(context.job),
        _rule_script_missing(context.job),
        _rule_working_directory_missing(context.job),
        _rule_permission_denied_static(context.job),
        _rule_relative_executable(spec_argv0),
    )
    diagnostics: list[Diagnostic] = [d for d in candidates if d is not None]
    diagnostics.extend(_rule_protected_path(context.protected_findings))
    architecture = _rule_architecture_mismatch(context.architecture_finding)
    if architecture is not None:
        diagnostics.append(architecture)
    return tuple(diagnostics)


def _evaluate_direct_test(context: DirectTestContext) -> tuple[Diagnostic, ...]:
    static = _rule_permission_denied_static(context.job)
    runtime = _rule_permission_denied_runtime(context.process)
    candidates = (
        None if static is not None else runtime,
        _rule_executable_not_found_runtime(context.job, context.process),
        _rule_module_not_found(context.process),
    )
    return tuple(d for d in candidates if d is not None)


def _evaluate_python_env(context: PythonEnvironmentContext) -> tuple[Diagnostic, ...]:
    diagnostic = _rule_interpreter_mismatch(context.job, context.detection)
    return () if diagnostic is None else (diagnostic,)


def _evaluate_lifecycle(context: LifecycleContext) -> tuple[Diagnostic, ...]:
    diagnostic = _rule_bootstrap_failure(context.label, context.action, context.result)
    return () if diagnostic is None else (diagnostic,)


def _evaluate_logs(context: LogContext) -> tuple[Diagnostic, ...]:
    return _rule_log_path_unreadable(context.logs)


def _evaluate_plist(context: InspectionContext) -> tuple[Diagnostic, ...]:
    candidates = (
        _rule_malformed_plist(context.path, context.parsed),
        _rule_invalid_plist_label(context.path, context.parsed),
    )
    return tuple(d for d in candidates if d is not None)


def evaluate_diagnostics(
    job: JobDefinition | None = None,
    *,
    process: ProcessResult | None = None,
    spec_argv0: str | None = None,
    detection: PythonDetectionResult | None = None,
) -> list[Diagnostic]:
    """Evaluate all diagnostic rules in a fixed, deterministic order.

    ``spec_argv0`` is the first argv element of a raw command spec; valid
    jobs carry absolute paths, so ``relative_executable`` only fires for
    imported command inputs. ``permission_denied`` fires once for a static
    or runtime failure; ``executable_not_found_runtime`` follows on a
    not-found launch failure when the executable exists on disk.
    """
    permission = _rule_permission_denied_static(job) or _rule_permission_denied_runtime(
        process
    )
    rules = (
        _rule_executable_missing(job),
        _rule_script_missing(job),
        _rule_working_directory_missing(job),
        permission,
        _rule_executable_not_found_runtime(job, process),
        _rule_relative_executable(spec_argv0),
        _rule_interpreter_mismatch(job, detection),
        _rule_module_not_found(process),
    )
    return [diagnostic for diagnostic in rules if diagnostic is not None]


def _add_group(
    groups: list[DiagnosticGroup], source: DiagnosticSource, diagnostics: tuple[Diagnostic, ...]
) -> None:
    if diagnostics:
        groups.append(DiagnosticGroup(source, diagnostics))


def evaluate_diagnostic_report(
    *contexts: DiagnosticContext,
) -> DiagnosticReport:
    """Evaluate structured diagnostics from typed contexts.

    Contexts may arrive in any order; groups are emitted in the pinned
    order (preflight, direct test, lifecycle, logs, python environment,
    plist) and empty groups are omitted.
    """
    direct_test = _first_of(contexts, DirectTestContext)
    spec_argv0 = direct_test.spec_argv0 if direct_test is not None else None
    groups: list[DiagnosticGroup] = []

    preflight = _first_of(contexts, PreflightContext)
    if preflight is not None:
        _add_group(groups, DiagnosticSource.PREFLIGHT, _evaluate_preflight(preflight, spec_argv0))

    if direct_test is not None:
        _add_group(groups, DiagnosticSource.DIRECT_TEST, _evaluate_direct_test(direct_test))

    lifecycle = _first_of(contexts, LifecycleContext)
    if lifecycle is not None:
        _add_group(groups, DiagnosticSource.LIFECYCLE, _evaluate_lifecycle(lifecycle))

    logs = _first_of(contexts, LogContext)
    if logs is not None:
        _add_group(groups, DiagnosticSource.LOGS, _evaluate_logs(logs))

    python_env = _first_of(contexts, PythonEnvironmentContext)
    if python_env is not None:
        _add_group(
            groups, DiagnosticSource.PYTHON_ENVIRONMENT, _evaluate_python_env(python_env)
        )

    inspection = _first_of(contexts, InspectionContext)
    if inspection is not None:
        _add_group(groups, DiagnosticSource.PLIST, _evaluate_plist(inspection))

    return DiagnosticReport(tuple(groups))
