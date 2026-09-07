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
    InspectionContext,
    LifecycleContext,
)
from task_scheduler.application.diagnostic_service import (
    evaluate_diagnostic_report,
    evaluate_diagnostics,
)
from task_scheduler.domain import JobDefinition, PythonCommand
from task_scheduler.platform.macos import (
    LaunchFailureKind,
    ProcessLaunchFailure,
    ProcessResult,
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

    def test_permission_denied_static_positive(self, tmp_path: Path) -> None:
        job, interpreter, _ = _healthy_job(tmp_path)
        interpreter.chmod(0o644)
        assert "permission_denied" in _codes(evaluate_diagnostics(job))

    def test_relative_executable_negative(self) -> None:
        assert "relative_executable" not in _codes(
            evaluate_diagnostics(spec_argv0="/usr/bin/tool")
        )

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
        report = evaluate_diagnostic_report(
            LifecycleContext(job.label, "reinstall", result)
        )
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
        self, raw: dict[str, object], title: str
    ) -> None:
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

