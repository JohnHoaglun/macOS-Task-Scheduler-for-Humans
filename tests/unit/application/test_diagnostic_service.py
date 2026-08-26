"""Tests for the diagnostic rules: positive and negative coverage per rule."""

from __future__ import annotations

from pathlib import Path

from conftest import make_job
from task_scheduler.application.diagnostic_service import evaluate_diagnostics
from task_scheduler.domain import JobDefinition, PythonCommand
from task_scheduler.platform.macos import (
    CandidateSource,
    InterpreterCandidate,
    LaunchFailureKind,
    ProcessLaunchFailure,
    ProcessResult,
    PythonDetectionResult,
)


def _healthy_job(tmp_path: Path) -> tuple[JobDefinition, Path, Path]:
    interpreter = tmp_path / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    interpreter.chmod(0o755)
    script = tmp_path / "report.py"
    script.touch()
    job = make_job(
        command=PythonCommand(interpreter=interpreter, script=script),
        working_directory=tmp_path,
    )
    return job, interpreter, script


def _codes(result: list[object]) -> list[str]:
    return [diagnostic.code for diagnostic in result]


def _process(stderr: str = "") -> ProcessResult:
    return ProcessResult(exit_code=0, stderr=stderr)


class TestRuleCoverage:
    def test_no_inputs_no_diagnostics(self) -> None:
        assert evaluate_diagnostics() == []

    def test_executable_missing_positive(self, tmp_path: Path) -> None:
        job, _, _ = _healthy_job(tmp_path)
        missing = tmp_path / "missing.py"
        job = job.model_copy(
            update={"command": job.command.model_copy(update={"interpreter": missing})}
        )
        assert "executable_missing" in _codes(evaluate_diagnostics(job))

    def test_executable_missing_negative(self, tmp_path: Path) -> None:
        job, _, _ = _healthy_job(tmp_path)
        assert "executable_missing" not in _codes(evaluate_diagnostics(job))

    def test_script_missing_positive(self, tmp_path: Path) -> None:
        job, interpreter, _ = _healthy_job(tmp_path)
        job = job.model_copy(
            update={"command": job.command.model_copy(update={"script": tmp_path / "gone.py"})}
        )
        assert "script_missing" in _codes(evaluate_diagnostics(job))

    def test_script_missing_negative(self, tmp_path: Path) -> None:
        job, interpreter, _ = _healthy_job(tmp_path)
        assert "script_missing" not in _codes(evaluate_diagnostics(job))

    def test_working_directory_missing_positive(self, tmp_path: Path) -> None:
        job, _, _ = _healthy_job(tmp_path)
        job = job.model_copy(update={"working_directory": tmp_path / "nowhere"})
        assert "working_directory_missing" in _codes(evaluate_diagnostics(job))

    def test_working_directory_missing_negative(self, tmp_path: Path) -> None:
        job, _, _ = _healthy_job(tmp_path)
        assert "working_directory_missing" not in _codes(evaluate_diagnostics(job))

    def test_permission_denied_static_positive(self, tmp_path: Path) -> None:
        job, interpreter, _ = _healthy_job(tmp_path)
        interpreter.chmod(0o644)
        assert "permission_denied" in _codes(evaluate_diagnostics(job))

    def test_permission_denied_static_negative(self, tmp_path: Path) -> None:
        job, _, _ = _healthy_job(tmp_path)
        assert "permission_denied" not in _codes(evaluate_diagnostics(job))

    def test_permission_denied_runtime(self, tmp_path: Path) -> None:
        job, _, _ = _healthy_job(tmp_path)
        process = ProcessResult(
            exit_code=None,
            launch_failure=ProcessLaunchFailure(
                kind=LaunchFailureKind.PERMISSION_DENIED, message="denied"
            ),
        )
        assert "permission_denied" in _codes(evaluate_diagnostics(job, process=process))

    def test_relative_executable_positive(self) -> None:
        assert "relative_executable" in _codes(
            evaluate_diagnostics(spec_argv0="relative-tool")
        )

    def test_relative_executable_negative(self) -> None:
        assert "relative_executable" not in _codes(
            evaluate_diagnostics(spec_argv0="/usr/bin/tool")
        )

    def test_interpreter_mismatch_positive(self, tmp_path: Path) -> None:
        job, interpreter, script = _healthy_job(tmp_path)
        detection = PythonDetectionResult(
            script=script,
            candidates=[
                InterpreterCandidate(
                    path=tmp_path / "other" / "python", source=CandidateSource.VENV
                )
            ],
        )
        assert "interpreter_mismatch" in _codes(
            evaluate_diagnostics(job, detection=detection)
        )

    def test_interpreter_mismatch_negative(self, tmp_path: Path) -> None:
        job, interpreter, script = _healthy_job(tmp_path)
        detection = PythonDetectionResult(
            script=script,
            candidates=[InterpreterCandidate(path=interpreter, source=CandidateSource.VENV)],
        )
        assert "interpreter_mismatch" not in _codes(
            evaluate_diagnostics(job, detection=detection)
        )

    def test_module_not_found_positive(self) -> None:
        process = _process(stderr="Traceback: ModuleNotFoundError: No module named 'requests'")
        assert "module_not_found" in _codes(evaluate_diagnostics(process=process))

    def test_module_not_found_negative(self) -> None:
        assert "module_not_found" not in _codes(evaluate_diagnostics(process=_process()))


class TestRuleOrder:
    def test_rules_emit_in_documented_order(self, tmp_path: Path) -> None:
        interpreter = tmp_path / "missing.py"
        job = make_job(
            command=PythonCommand(interpreter=interpreter, script=interpreter),
            working_directory=tmp_path / "nowhere",
        )
        process = ProcessResult(
            exit_code=None,
            launch_failure=ProcessLaunchFailure(
                kind=LaunchFailureKind.PERMISSION_DENIED, message="denied"
            ),
            stderr="ModuleNotFoundError: boom",
        )
        codes = _codes(
            evaluate_diagnostics(job, process=process, spec_argv0="relative-tool")
        )
        assert codes == [
            "executable_missing",
            "script_missing",
            "working_directory_missing",
            "permission_denied",
            "relative_executable",
            "module_not_found",
        ]
