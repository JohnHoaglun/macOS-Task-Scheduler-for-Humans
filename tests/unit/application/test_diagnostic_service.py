"""Tests for the diagnostic rule engine and structured report builder: positive/negative coverage
per rule, the pinned emission order, and grouped report semantics (any-order input, pinned group
order, empty-group omission, and runtime-permission suppression)."""

from __future__ import annotations

from pathlib import Path

import pytest

import task_scheduler.application.diagnostic_service as diagnostic_service
from conftest import make_job
from task_scheduler.application import InstallPhase, InstallResult
from task_scheduler.application.diagnostic_models import (
    EvidenceState,
    InspectionContext,
    LifecycleContext,
    LogContext,
)
from task_scheduler.application.diagnostic_service import (
    evaluate_diagnostic_report,
    evaluate_diagnostics,
)
from task_scheduler.application.log_service import JobLogs, LogStream
from task_scheduler.domain import JobDefinition, PythonCommand
from task_scheduler.platform.macos import LaunchFailureKind, ProcessLaunchFailure, ProcessResult
from task_scheduler.platform.macos.diagnostic_probes import InterpreterForwardingFinding
from task_scheduler.platform.macos.plist_models import ParsedLaunchAgent, ParseSupport


def _tcc_stderr(path: str) -> str:
    return f"PermissionError: [Errno 1] Operation not permitted: '{path}'"

REAL_PYTHON = "/Applications/Xcode.app/Contents/Developer/usr/bin/python3"

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

def _launch_failure(kind: LaunchFailureKind, message: str = "boom") -> ProcessResult:
    return ProcessResult(
        exit_code=None, launch_failure=ProcessLaunchFailure(kind=kind, message=message)
    )

class TestRuleCoverage:
    def test_permission_denied_static_positive(self, tmp_path: Path) -> None:
        job, interpreter, _ = _healthy_job(tmp_path)
        interpreter.chmod(0o644)
        assert "permission_denied" in _codes(evaluate_diagnostics(job))

    def test_relative_executable_negative(self) -> None:
        assert "relative_executable" not in _codes(evaluate_diagnostics(spec_argv0="/usr/bin/tool"))

class TestLifecycleRules:
    def test_other_phases_ignored(self) -> None:
        job = make_job()
        process = ProcessResult(exit_code=1, stderr="boom")
        result = InstallResult(
            job=job,
            plist_path=Path("/tmp/a.plist"),
            process=process,
            phases=(InstallPhase("bootout", process),),
            completed_phases=(),
            retained_artifacts=(),
        )
        report = evaluate_diagnostic_report(LifecycleContext(job.label, "reinstall", result))
        assert report.groups == ()

class TestPlistRules:
    @pytest.mark.parametrize(
        ("raw", "title"),
        [
            ({"ProgramArguments": ["/bin/true"]}, "Plist label missing or empty"),
            ({"Label": ""}, "Plist label missing or empty"),
            ({"Label": 42}, "Plist label missing or empty"),
            ({"Label": "../escape"}, "Plist label invalid"),
        ],
    )
    def test_invalid_label_fires_for_decoded_plists(
        self, raw: dict[str, object], title: str) -> None:
        parsed = ParsedLaunchAgent(status=ParseSupport.INVALID, raw=raw, warnings=["bad"])
        report = evaluate_diagnostic_report(InspectionContext(Path("/tmp/a.plist"), parsed))
        (label,) = [d for d in report.all if d.code == "invalid_plist_label"]
        assert label.title == title

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
        codes = _codes(evaluate_diagnostics(job, process=process, spec_argv0="relative-tool"))
        assert codes == [
            "executable_missing",
            "script_missing",
            "working_directory_missing",
            "permission_denied",
            "relative_executable",
            "module_not_found",
        ]

    def test_runtime_not_found_rule_follows_permission(self, tmp_path: Path) -> None:
        job, _, _ = _healthy_job(tmp_path)
        process = _launch_failure(LaunchFailureKind.NOT_FOUND, "gone")
        codes = _codes(evaluate_diagnostics(job, process=process, spec_argv0="relative-tool"))
        assert codes == ["executable_not_found_runtime", "relative_executable"]

class TestTccDeniedRule:
    def _job(self, tmp_path: Path) -> JobDefinition:
        return make_job(
            command=PythonCommand(
                interpreter="/usr/bin/python3", script=tmp_path / "report.py"
            )
        )

    @pytest.fixture
    def shim(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            diagnostic_service,
            "probe_interpreter_forwarding",
            lambda _interpreter: InterpreterForwardingFinding(
                shim=Path("/usr/bin/python3"), real=Path(REAL_PYTHON)
            ),
        )

    def test_shim_action_names_real_binary(self, tmp_path: Path, shim: None) -> None:
        protected = Path.home() / "Documents" / "vault" / "Dev" / "logs"
        process = ProcessResult(exit_code=1, stderr=_tcc_stderr(str(protected)))
        result = evaluate_diagnostics(self._job(tmp_path), process=process)
        (diagnostic,) = [d for d in result if d.code == "tcc_denied"]
        assert str(protected) in diagnostic.description
        assert REAL_PYTHON in diagnostic.suggested_action
        assert diagnostic.evidence_state is EvidenceState.CONFIRMED

    def test_non_shim_action_names_interpreter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(diagnostic_service, "probe_interpreter_forwarding", lambda _i: None)
        process = ProcessResult(
            exit_code=1, stderr=_tcc_stderr(str(Path.home() / "Documents" / "x"))
        )
        result = evaluate_diagnostics(self._job(tmp_path), process=process)
        (diagnostic,) = [d for d in result if d.code == "tcc_denied"]
        assert "/usr/bin/python3" in diagnostic.suggested_action
        assert "system shim" not in diagnostic.suggested_action

    def test_fires_from_persisted_logs(self, tmp_path: Path, shim: None) -> None:
        path = str(Path.home() / "Documents" / "logs")
        stderr = LogStream(name="stderr", path=tmp_path / "e.log", content=_tcc_stderr(path))
        logs = JobLogs(stdout=LogStream(name="stdout", path=None), stderr=stderr)
        report = evaluate_diagnostic_report(LogContext(self._job(tmp_path), logs))
        assert "tcc_denied" in [d.code for d in report.all]

    @pytest.mark.parametrize(
        "stderr",
        [_tcc_stderr("/tmp/somewhere/logs"), "ModuleNotFoundError: No module named 'foo'"],
    )
    def test_negative_cases(self, tmp_path: Path, stderr: str) -> None:
        process = ProcessResult(exit_code=1, stderr=stderr)
        assert "tcc_denied" not in _codes(
            evaluate_diagnostics(self._job(tmp_path), process=process)
        )
