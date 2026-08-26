"""Direct task testing: run a job's exact command and report the outcome."""

from __future__ import annotations

from pydantic import BaseModel, Field

from task_scheduler.application.diagnostic_service import (
    Diagnostic,
    evaluate_diagnostics,
)
from task_scheduler.domain import JobDefinition
from task_scheduler.domain.command import command_argv
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


class DirectTestService:
    """Execute a job's command through an injected runner.

    The process receives exactly the job's configured environment
    variables and working directory. This service never mutates the job,
    never writes log paths, and never calls subprocess directly.
    """

    def __init__(self, runner: ProcessRunner) -> None:
        self._runner = runner

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
        diagnostics = evaluate_diagnostics(
            job,
            process=process,
            spec_argv0=spec.argv[0] if spec.argv else None,
            detection=detection,
        )
        return DirectTestResult(process=process, diagnostics=diagnostics)
