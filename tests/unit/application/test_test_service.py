"""Tests for DirectTestService (fake runner only; no real processes)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from conftest import make_job
from fakes import FakeDiagnosticProbes, FakeProcessRunner
from task_scheduler.application import DirectTestService
from task_scheduler.application.diagnostic_models import DiagnosticSource
from task_scheduler.domain import (
    EnvironmentConfig,
    ExecutableCommand,
    JobDefinition,
    PythonCommand,
    ShellCommand,
)
from task_scheduler.platform.macos import (
    CandidateSource,
    InterpreterCandidate,
    ProcessResult,
    PythonDetectionResult,
)
from task_scheduler.platform.macos.diagnostic_probes import (
    ArchitectureFinding,
    ProtectedPathFinding,
)
from task_scheduler.platform.macos.process_runner import (
    LaunchFailureKind,
    ProcessLaunchFailure,
)

HEALTHY = ProcessResult(exit_code=0, stdout="ok", stderr="", duration=timedelta(seconds=1))


def _make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    path.chmod(0o755)
    return path


def _python_job(
    tmp_path: Path, arguments: list[str] | None = None
) -> tuple[JobDefinition, Path, Path]:
    venv_python = _make_executable(tmp_path / ".venv" / "bin" / "python")
    script = _make_executable(tmp_path / "report.py")
    job = make_job(
        command=PythonCommand(
            interpreter=venv_python, script=script, arguments=arguments or []
        ),
        environment=EnvironmentConfig(variables={"FOO": "bar"}),
        working_directory=tmp_path,
    )
    return job, venv_python, script


class TestCommandTranslation:
    def test_python_argv(self, tmp_path: Path) -> None:
        runner = FakeProcessRunner(HEALTHY)
        job, venv_python, script = _python_job(tmp_path)
        DirectTestService(runner).run(job)
        assert runner.specs[0].argv == [str(venv_python), str(script)]

    def test_python_argv_with_arguments(self, tmp_path: Path) -> None:
        runner = FakeProcessRunner(HEALTHY)
        job, venv_python, script = _python_job(tmp_path, arguments=["--mode", "daily"])
        DirectTestService(runner).run(job)
        assert runner.specs[0].argv == [str(venv_python), str(script), "--mode", "daily"]

    def test_shell_argv(self, tmp_path: Path) -> None:
        shell_script = _make_executable(tmp_path / "run.sh")
        job = make_job(command=ShellCommand(executable=shell_script, arguments=["a", "b"]))
        runner = FakeProcessRunner(HEALTHY)
        DirectTestService(runner).run(job)
        assert runner.specs[0].argv == [str(shell_script), "a", "b"]

    def test_executable_argv(self, tmp_path: Path) -> None:
        tool = _make_executable(tmp_path / "tool")
        job = make_job(command=ExecutableCommand(executable=tool, arguments=["--sync"]))
        runner = FakeProcessRunner(HEALTHY)
        DirectTestService(runner).run(job)
        assert runner.specs[0].argv == [str(tool), "--sync"]


class TestForwarding:
    def test_exact_environment_and_cwd(self, tmp_path: Path) -> None:
        runner = FakeProcessRunner(HEALTHY)
        job, _, _ = _python_job(tmp_path)
        DirectTestService(runner).run(job)
        spec = runner.specs[0]
        assert spec.environment == {"FOO": "bar"}
        assert spec.working_directory == tmp_path

    def test_no_working_directory(self, tmp_path: Path) -> None:
        runner = FakeProcessRunner(HEALTHY)
        job, _, _ = _python_job(tmp_path)
        job = job.model_copy(update={"working_directory": None})
        DirectTestService(runner).run(job)
        assert runner.specs[0].working_directory is None

    def test_result_propagated(self, tmp_path: Path) -> None:
        failing = ProcessResult(
            exit_code=3, stdout="out", stderr="err", duration=timedelta(seconds=2)
        )
        runner = FakeProcessRunner(failing)
        job, _, _ = _python_job(tmp_path)
        result = DirectTestService(runner).run(job)
        assert result.process.exit_code == 3
        assert result.process.stdout == "out"
        assert result.process.stderr == "err"
        assert result.process.duration == timedelta(seconds=2)

    def test_job_not_mutated(self, tmp_path: Path) -> None:
        runner = FakeProcessRunner(HEALTHY)
        job, _, _ = _python_job(tmp_path)
        before = job.model_dump(mode="json")
        DirectTestService(runner).run(job)
        assert job.model_dump(mode="json") == before

    def test_healthy_job_has_no_diagnostics(self, tmp_path: Path) -> None:
        runner = FakeProcessRunner(HEALTHY)
        job, _, _ = _python_job(tmp_path)
        result = DirectTestService(runner).run(job)
        assert result.diagnostics == []


class TestDetectionInput:
    def test_interpreter_mismatch_reported(self, tmp_path: Path) -> None:
        runner = FakeProcessRunner(HEALTHY)
        job, venv_python, script = _python_job(tmp_path)
        other = _make_executable(tmp_path / "elsewhere" / "python")
        detection = PythonDetectionResult(
            script=script,
            candidates=[InterpreterCandidate(path=other, source=CandidateSource.VENV)],
        )
        result = DirectTestService(runner).run(job, detection=detection)
        assert [d.code for d in result.diagnostics] == ["interpreter_mismatch"]
        assert venv_python != other

    def test_matching_interpreter_has_no_mismatch(self, tmp_path: Path) -> None:
        runner = FakeProcessRunner(HEALTHY)
        job, venv_python, script = _python_job(tmp_path)
        detection = PythonDetectionResult(
            script=script,
            candidates=[InterpreterCandidate(path=venv_python, source=CandidateSource.VENV)],
        )
        result = DirectTestService(runner).run(job, detection=detection)
        assert result.diagnostics == []


class TestReport:
    def test_healthy_job_report_is_empty(self, tmp_path: Path) -> None:
        runner = FakeProcessRunner(HEALTHY)
        job, _, _ = _python_job(tmp_path)
        result = DirectTestService(runner).run(job)
        assert result.report.groups == ()
        assert result.report.all == ()

    def test_report_preflight_group_from_injected_probes(self, tmp_path: Path) -> None:
        probes = FakeDiagnosticProbes(
            protected_findings=(
                ProtectedPathFinding(
                    path=Path("/Users/t/Desktop/a.py"),
                    root=Path("/Users/t/Desktop"),
                ),
            ),
            architecture_finding=ArchitectureFinding(
                path=Path("/bin/true"), declared=(0x07000003,), host=0x0100000C
            ),
        )
        runner = FakeProcessRunner(HEALTHY)
        job, venv_python, script = _python_job(tmp_path)
        result = DirectTestService(runner, probes=probes).run(job)
        assert [group.source for group in result.report.groups] == [
            DiagnosticSource.PREFLIGHT
        ]
        assert [d.code for d in result.report.all] == [
            "protected_path",
            "architecture_mismatch",
        ]
        assert probes.protected_calls == [((venv_python, script, tmp_path), {"home": None})]
        assert probes.architecture_calls == [(venv_python, {"machine": None})]

    def test_report_direct_test_group_on_runtime_permission(self, tmp_path: Path) -> None:
        failure = ProcessResult(
            exit_code=None,
            launch_failure=ProcessLaunchFailure(
                kind=LaunchFailureKind.PERMISSION_DENIED, message="denied"
            ),
        )
        runner = FakeProcessRunner(failure)
        job, _, _ = _python_job(tmp_path)
        result = DirectTestService(runner).run(job)
        assert [group.source for group in result.report.groups] == [
            DiagnosticSource.DIRECT_TEST
        ]
        assert [d.code for d in result.report.all] == ["permission_denied"]

    def test_report_python_environment_group(self, tmp_path: Path) -> None:
        runner = FakeProcessRunner(HEALTHY)
        job, venv_python, script = _python_job(tmp_path)
        other = _make_executable(tmp_path / "elsewhere" / "python")
        detection = PythonDetectionResult(
            script=script,
            candidates=[InterpreterCandidate(path=other, source=CandidateSource.VENV)],
        )
        result = DirectTestService(runner).run(job, detection=detection)
        assert [group.source for group in result.report.groups] == [
            DiagnosticSource.PYTHON_ENVIRONMENT
        ]
        assert [d.code for d in result.report.all] == ["interpreter_mismatch"]

    def test_report_all_flattens_groups_in_order(self, tmp_path: Path) -> None:
        probes = FakeDiagnosticProbes(
            protected_findings=(
                ProtectedPathFinding(path=Path("/p"), root=Path("/r")),
            ),
            architecture_finding=ArchitectureFinding(
                path=Path("/bin/true"), declared=(0x07000003,), host=0x0100000C
            ),
        )
        not_found = ProcessResult(
            exit_code=None,
            launch_failure=ProcessLaunchFailure(
                kind=LaunchFailureKind.NOT_FOUND, message="gone"
            ),
        )
        runner = FakeProcessRunner(not_found)
        job, venv_python, script = _python_job(tmp_path)
        other = _make_executable(tmp_path / "elsewhere" / "python")
        detection = PythonDetectionResult(
            script=script,
            candidates=[InterpreterCandidate(path=other, source=CandidateSource.VENV)],
        )
        result = DirectTestService(runner, probes=probes).run(job, detection=detection)
        assert [d.code for d in result.report.all] == [
            "protected_path",
            "architecture_mismatch",
            "executable_not_found_runtime",
            "interpreter_mismatch",
        ]
        assert [d.code for d in result.diagnostics] == [
            "executable_not_found_runtime",
            "interpreter_mismatch",
        ]
