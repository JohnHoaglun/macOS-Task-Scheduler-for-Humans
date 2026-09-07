"""Direct task testing: run a job's exact command and report the outcome."""

from __future__ import annotations

from pydantic import BaseModel, Field

from task_scheduler.application.diagnostic_models import (
    Diagnostic,
    DiagnosticContext,
    DiagnosticReport,
    DirectTestContext,
    PreflightContext,
    PythonEnvironmentContext,
)
from task_scheduler.application.diagnostic_service import (
    collect_preflight_paths,
    evaluate_diagnostic_report,
    evaluate_diagnostics,
)
from task_scheduler.domain import JobDefinition
from task_scheduler.domain.command import command_argv
from task_scheduler.platform.macos.diagnostic_probes import (
    DiagnosticProbes,
    LocalDiagnosticProbes,
)
from task_scheduler.platform.macos.process_runner import (
    CommandSpec,
    ProcessResult,
    ProcessRunner,
)
from task_scheduler.platform.macos.python_detection import PythonDetectionResult


class DirectTestResult(BaseModel):
    """Transient outcome of a direct test; never persisted into the job."""

    process: ProcessResult
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    report: DiagnosticReport = Field(default_factory=DiagnosticReport)


class DirectTestService:
    """Execute a job's command through an injected runner.

    The process receives exactly the job's configured environment
    variables and working directory. This service never mutates the job,
    never writes log paths, and never calls subprocess directly.
    """

    def __init__(
        self, runner: ProcessRunner, *, probes: DiagnosticProbes | None = None
    ) -> None:
        self._runner = runner
        self._probes = probes or LocalDiagnosticProbes()

    def run(
        self,
        job: JobDefinition,
        *,
        detection: PythonDetectionResult | None = None,
    ) -> DirectTestResult:
        spec = CommandSpec(
            argv=command_argv(job.command),
            environment=dict(job.environment.variables),
            working_directory=job.working_directory,
        )
        process = self._runner.run(spec)
        spec_argv0 = spec.argv[0] if spec.argv else None
        diagnostics = evaluate_diagnostics(
            job,
            process=process,
            spec_argv0=spec_argv0,
            detection=detection,
        )
        paths = collect_preflight_paths(job)
        protected_findings = self._probes.probe_protected_paths(paths)
        architecture_finding = self._probes.probe_executable_architecture(paths[0])
        contexts: list[DiagnosticContext] = [
            PreflightContext(
                job,
                protected_findings=protected_findings,
                architecture_finding=architecture_finding,
            ),
            DirectTestContext(job, process, spec_argv0=spec_argv0),
        ]
        if detection is not None:
            contexts.append(PythonEnvironmentContext(job, detection))
        report = evaluate_diagnostic_report(*contexts)
        return DirectTestResult(process=process, diagnostics=diagnostics, report=report)
