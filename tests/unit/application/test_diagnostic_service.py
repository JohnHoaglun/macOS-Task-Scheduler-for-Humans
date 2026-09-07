"""Tests for the diagnostic rule engine and the structured report builder.

Per-rule positive/negative coverage, the pinned emission order, and the
grouped report semantics (any-order input, pinned group order, empty-group
omission, runtime-permission suppression).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_job
from task_scheduler.application import InstallPhase, InstallResult
from task_scheduler.application.diagnostic_models import (
    Diagnostic,
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
from task_scheduler.application.diagnostic_service import (
    evaluate_diagnostic_report,
    evaluate_diagnostics,
)
from task_scheduler.application.log_service import JobLogs, LogStream
from task_scheduler.domain import JobDefinition, PythonCommand
from task_scheduler.platform.macos import (
    CandidateSource,
    DetectorKind,
    InterpreterCandidate,
    LaunchFailureKind,
    ProcessLaunchFailure,
    ProcessResult,
    PythonDetectionResult,
)
from task_scheduler.platform.macos.diagnostic_probes import (
    ArchitectureFinding,
    ProtectedPathFinding,
)
from task_scheduler.platform.macos.plist_models import ParsedLaunchAgent, ParseSupport


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


def _launch_failure(kind: LaunchFailureKind, message: str = "boom") -> ProcessResult:
    return ProcessResult(
        exit_code=None, launch_failure=ProcessLaunchFailure(kind=kind, message=message)
    )


def _install_result(job: JobDefinition, exit_code: int) -> InstallResult:
    process = ProcessResult(exit_code=exit_code, stderr="denied")
    return InstallResult(
        job=job,
        plist_path=Path("/tmp/a.plist"),
        process=process,
        phases=(InstallPhase("bootstrap", process),),
        completed_phases=("bootstrap",) if exit_code == 0 else (),
        retained_artifacts=(),
    )


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
        process = _launch_failure(LaunchFailureKind.PERMISSION_DENIED, "denied")
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

    def test_interpreter_mismatch_with_ecosystem_provenance(self, tmp_path: Path) -> None:
        job, interpreter, script = _healthy_job(tmp_path)
        detection = PythonDetectionResult(
            script=script,
            candidates=[
                InterpreterCandidate(
                    path=tmp_path / "other" / ".venv" / "bin" / "python",
                    source=CandidateSource.VENV,
                    detectors=(DetectorKind.CORE, DetectorKind.UV),
                )
            ],
        )
        assert "interpreter_mismatch" in _codes(
            evaluate_diagnostics(job, detection=detection)
        )

    def test_module_not_found_positive(self) -> None:
        process = _process(stderr="Traceback: ModuleNotFoundError: No module named 'requests'")
        assert "module_not_found" in _codes(evaluate_diagnostics(process=process))

    def test_module_not_found_negative(self) -> None:
        assert "module_not_found" not in _codes(evaluate_diagnostics(process=_process()))


class TestExecutableNotFoundRuntime:
    def test_fires_when_executable_exists(self, tmp_path: Path) -> None:
        job, _, _ = _healthy_job(tmp_path)
        codes = _codes(
            evaluate_diagnostics(job, process=_launch_failure(LaunchFailureKind.NOT_FOUND))
        )
        assert "executable_not_found_runtime" in codes

    def test_silent_when_executable_missing(self, tmp_path: Path) -> None:
        job, _, _ = _healthy_job(tmp_path)
        job = job.model_copy(
            update={"command": job.command.model_copy(update={"interpreter": tmp_path / "gone"})}
        )
        codes = _codes(
            evaluate_diagnostics(job, process=_launch_failure(LaunchFailureKind.NOT_FOUND))
        )
        assert "executable_missing" in codes
        assert "executable_not_found_runtime" not in codes

    def test_silent_without_launch_failure(self, tmp_path: Path) -> None:
        job, _, _ = _healthy_job(tmp_path)
        codes = _codes(evaluate_diagnostics(job, process=ProcessResult(exit_code=1)))
        assert "executable_not_found_runtime" not in codes

    def test_silent_for_other_failure_kinds(self, tmp_path: Path) -> None:
        job, _, _ = _healthy_job(tmp_path)
        codes = _codes(
            evaluate_diagnostics(job, process=_launch_failure(LaunchFailureKind.PERMISSION_DENIED))
        )
        assert "permission_denied" in codes
        assert "executable_not_found_runtime" not in codes


class TestPreflightProbeRules:
    def test_protected_path_finding(self, tmp_path: Path) -> None:
        job, _, script = _healthy_job(tmp_path)
        finding = ProtectedPathFinding(path=script, root=tmp_path)
        report = evaluate_diagnostic_report(
            PreflightContext(job, protected_findings=(finding,))
        )
        (diagnostic,) = report.all
        assert diagnostic.code == "protected_path"
        assert diagnostic.severity is DiagnosticSeverity.WARNING
        assert diagnostic.evidence_state is EvidenceState.NOT_PROVABLE
        assert str(finding.path) in diagnostic.description
        assert str(finding.root) in diagnostic.description

    def test_protected_path_silent_without_findings(self, tmp_path: Path) -> None:
        job, _, _ = _healthy_job(tmp_path)
        assert evaluate_diagnostic_report(PreflightContext(job)).groups == ()

    def test_architecture_mismatch_finding(self, tmp_path: Path) -> None:
        job, interpreter, _ = _healthy_job(tmp_path)
        finding = ArchitectureFinding(
            path=interpreter, declared=(0x07000003,), host=0x0100000C
        )
        report = evaluate_diagnostic_report(
            PreflightContext(job, architecture_finding=finding)
        )
        (diagnostic,) = report.all
        assert diagnostic.code == "architecture_mismatch"
        assert diagnostic.evidence_state is EvidenceState.CONFIRMED
        assert "x86_64" in diagnostic.description
        assert "arm64" in diagnostic.description

    def test_architecture_mismatch_silent_without_finding(self, tmp_path: Path) -> None:
        job, _, _ = _healthy_job(tmp_path)
        assert evaluate_diagnostic_report(PreflightContext(job)).groups == ()


class TestLogRules:
    def test_unreadable_streams_reported_stdout_first(self) -> None:
        logs = JobLogs(
            stdout=LogStream(name="stdout", path=Path("/tmp/out.log"), error="No such file"),
            stderr=LogStream(name="stderr", path=Path("/tmp/err.log"), error="Permission denied"),
        )
        report = evaluate_diagnostic_report(LogContext(make_job(), logs))
        diagnostics = report.all
        assert [d.code for d in diagnostics] == ["log_path_unreadable", "log_path_unreadable"]
        assert "stdout" in diagnostics[0].description
        assert "stderr" in diagnostics[1].description
        assert "No such file" in diagnostics[0].description

    def test_only_failed_stream_reported(self) -> None:
        logs = JobLogs(
            stdout=LogStream(name="stdout", path=Path("/tmp/out.log"), content="ok"),
            stderr=LogStream(name="stderr", path=None, error="gone"),
        )
        report = evaluate_diagnostic_report(LogContext(make_job(), logs))
        assert [d.code for d in report.all] == ["log_path_unreadable"]

    def test_clean_logs_silent(self) -> None:
        logs = JobLogs(
            stdout=LogStream(name="stdout", path=None),
            stderr=LogStream(name="stderr", path=None),
        )
        assert evaluate_diagnostic_report(LogContext(make_job(), logs)).groups == ()


class TestLifecycleRules:
    def test_failed_bootstrap_reports(self) -> None:
        report = evaluate_diagnostic_report(
            LifecycleContext("com.example.job", "install", _install_result(make_job(), 1))
        )
        (diagnostic,) = report.all
        assert diagnostic.code == "bootstrap_failure"
        assert diagnostic.severity is DiagnosticSeverity.ERROR
        assert "com.example.job" in diagnostic.description

    def test_successful_bootstrap_silent(self) -> None:
        report = evaluate_diagnostic_report(
            LifecycleContext("com.example.job", "install", _install_result(make_job(), 0))
        )
        assert report.groups == ()

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
        report = evaluate_diagnostic_report(
            LifecycleContext(job.label, "reinstall", result)
        )
        assert report.groups == ()


class TestPlistRules:
    def test_malformed_plist_with_warnings(self) -> None:
        parsed = ParsedLaunchAgent(status=ParseSupport.INVALID, warnings=["plist:1: parse error"])
        report = evaluate_diagnostic_report(InspectionContext(Path("/tmp/a.plist"), parsed))
        (diagnostic,) = report.all
        assert diagnostic.code == "malformed_plist"
        assert "parse error" in diagnostic.description

    def test_undecodable_plist_reports_malformed_only(self) -> None:
        # Empty raw means the plist itself failed to decode: the label rule
        # stays silent and malformed_plist alone covers the failure.
        parsed = ParsedLaunchAgent(status=ParseSupport.INVALID, raw={})
        report = evaluate_diagnostic_report(InspectionContext(Path("/tmp/a.plist"), parsed))
        assert [d.code for d in report.all] == ["malformed_plist"]

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
        self, raw: dict[str, object], title: str
    ) -> None:
        parsed = ParsedLaunchAgent(status=ParseSupport.INVALID, raw=raw, warnings=["bad"])
        report = evaluate_diagnostic_report(InspectionContext(Path("/tmp/a.plist"), parsed))
        (label,) = [d for d in report.all if d.code == "invalid_plist_label"]
        assert label.title == title

    def test_invalid_label_fires_regardless_of_support_status(self) -> None:
        parsed = ParsedLaunchAgent(
            status=ParseSupport.PARTIALLY_SUPPORTED,
            raw={"Label": "../escape", "KeepAlive": True},
            unsupported_keys=["KeepAlive"],
        )
        report = evaluate_diagnostic_report(InspectionContext(Path("/tmp/a.plist"), parsed))
        assert [d.code for d in report.all] == ["invalid_plist_label"]

    def test_valid_label_silent(self) -> None:
        parsed = ParsedLaunchAgent(
            status=ParseSupport.SUPPORTED, raw={"Label": "com.example.ok"}
        )
        assert (
            evaluate_diagnostic_report(
                InspectionContext(Path("/tmp/a.plist"), parsed)
            ).groups
            == ()
        )


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

    def test_runtime_not_found_rule_follows_permission(self, tmp_path: Path) -> None:
        job, _, _ = _healthy_job(tmp_path)
        process = _launch_failure(LaunchFailureKind.NOT_FOUND, "gone")
        codes = _codes(
            evaluate_diagnostics(job, process=process, spec_argv0="relative-tool")
        )
        assert codes == ["executable_not_found_runtime", "relative_executable"]


class TestReport:
    def test_no_contexts_empty_report(self) -> None:
        report = evaluate_diagnostic_report()
        assert report.groups == ()
        assert report.all == ()

    def test_report_empty_when_everything_healthy(self, tmp_path: Path) -> None:
        job, _, _ = _healthy_job(tmp_path)
        report = evaluate_diagnostic_report(
            PreflightContext(job), DirectTestContext(job, ProcessResult(exit_code=0))
        )
        assert report.groups == ()

    def test_spec_argv0_attributed_to_preflight_group(self, tmp_path: Path) -> None:
        job, _, _ = _healthy_job(tmp_path)
        report = evaluate_diagnostic_report(
            PreflightContext(job),
            DirectTestContext(job, ProcessResult(exit_code=0), spec_argv0="relative-tool"),
        )
        assert [group.source for group in report.groups] == [DiagnosticSource.PREFLIGHT]
        assert [d.code for d in report.all] == ["relative_executable"]

    def test_groups_emitted_in_pinned_order_regardless_of_input_order(
        self, tmp_path: Path
    ) -> None:
        job, interpreter, script = _healthy_job(tmp_path)
        detection = PythonDetectionResult(
            script=script,
            candidates=[
                InterpreterCandidate(
                    path=tmp_path / "other" / "python", source=CandidateSource.VENV
                )
            ],
        )
        logs = JobLogs(
            stdout=LogStream(name="stdout", path=Path("/tmp/out.log"), error="gone"),
            stderr=LogStream(name="stderr", path=None),
        )
        contexts = [
            InspectionContext(
                Path("/tmp/a.plist"),
                ParsedLaunchAgent(
                    status=ParseSupport.INVALID, raw={"Label": "../escape"}
                ),
            ),
            LogContext(job, logs),
            PreflightContext(
                job,
                protected_findings=(ProtectedPathFinding(path=script, root=tmp_path),),
                architecture_finding=ArchitectureFinding(
                    path=interpreter, declared=(0x07000003,), host=0x0100000C
                ),
            ),
            PythonEnvironmentContext(job, detection),
            LifecycleContext(job.label, "install", _install_result(job, 1)),
            DirectTestContext(job, ProcessResult(exit_code=1, stderr="ModuleNotFoundError: x")),
        ]
        report = evaluate_diagnostic_report(*contexts)
        assert [group.source for group in report.groups] == [
            DiagnosticSource.PREFLIGHT,
            DiagnosticSource.DIRECT_TEST,
            DiagnosticSource.LIFECYCLE,
            DiagnosticSource.LOGS,
            DiagnosticSource.PYTHON_ENVIRONMENT,
            DiagnosticSource.PLIST,
        ]
        assert [d.code for d in report.all] == [
            "protected_path",
            "architecture_mismatch",
            "module_not_found",
            "bootstrap_failure",
            "log_path_unreadable",
            "interpreter_mismatch",
            "malformed_plist",
            "invalid_plist_label",
        ]

    def test_runtime_permission_suppressed_when_static_fires(self, tmp_path: Path) -> None:
        job, interpreter, _ = _healthy_job(tmp_path)
        interpreter.chmod(0o644)
        process = _launch_failure(LaunchFailureKind.PERMISSION_DENIED, "denied")
        report = evaluate_diagnostic_report(
            PreflightContext(job), DirectTestContext(job, process)
        )
        assert [group.source for group in report.groups] == [DiagnosticSource.PREFLIGHT]
        assert [d.code for d in report.all] == ["permission_denied"]


class TestModels:
    def test_report_flattens_groups_in_order(self) -> None:
        first = Diagnostic(
            severity=DiagnosticSeverity.ERROR,
            code="a",
            title="A",
            description="A description",
            suggested_action="Do A",
        )
        second = Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="b",
            title="B",
            description="B description",
            suggested_action="Do B",
        )
        report = DiagnosticReport(
            groups=(
                DiagnosticGroup(source=DiagnosticSource.PREFLIGHT, diagnostics=(first,)),
                DiagnosticGroup(source=DiagnosticSource.LOGS, diagnostics=(second,)),
            )
        )
        assert report.all == (first, second)

    def test_diagnostic_evidence_state_defaults_to_none(self) -> None:
        diagnostic = Diagnostic(
            severity=DiagnosticSeverity.INFO,
            code="x",
            title="X",
            description="X description",
            suggested_action="Do X",
        )
        assert diagnostic.evidence_state is None
