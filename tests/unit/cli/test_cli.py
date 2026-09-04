"""Unit tests for the mactask CLI (Increment 8).

Drives the real Typer app built over a fully faked TaskCommandService:
no test touches the real home directory or invokes the real launchctl.
"""

from __future__ import annotations

import plistlib
import sys
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from typer.testing import CliRunner

from task_scheduler.cli import app as cli_app
from task_scheduler.cli.app import main
from task_scheduler.domain import (
    EnvironmentConfig,
    ExecutableCommand,
    LoggingConfig,
)
from task_scheduler.platform.macos import ProcessLaunchFailure, ProcessResult
from tests.conftest import make_job
from tests.fakes import FakeTaskWorld

RUNNER = CliRunner()
OTHER_ID = UUID("87654321-4321-4321-4321-432143214321")


def invoke(world: FakeTaskWorld, *args: str) -> object:
    return RUNNER.invoke(cli_app.create_app(world.services), list(args))


def job_file(tmp_path: Path, job) -> Path:
    path = tmp_path / "job.json"
    path.write_text(job.model_dump_json(exclude_none=True), encoding="utf-8")
    return path


def test_help_lists_all_twelve_commands(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    result = invoke(world, "--help")
    assert result.exit_code == 0
    for command in (
        "list", "inspect", "validate", "generate", "install", "uninstall",
        "enable", "disable", "status", "run", "test", "logs",
    ):
        assert command in result.stdout


def test_list_empty(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    result = invoke(world, "list")
    assert result.exit_code == 0
    assert "No LaunchAgents found." in result.stdout


def test_list_managed_external_and_invalid(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    managed = make_job()
    world.manage(managed)
    external = make_job(label="com.example.external", id=OTHER_ID)
    world.store.write(external)
    (world.la_root / "com.example.broken.plist").write_bytes(b"garbage")
    partial = plistlib.dumps(
        {"Label": "com.example.partial", "ProgramArguments": ["/bin/echo", "hi"]}
    )
    (world.la_root / "com.example.partial.plist").write_bytes(partial)
    result = invoke(world, "list")
    assert result.exit_code == 0
    plist_path = world.la_root / f"{managed.label}.plist"
    assert f"{managed.label} [supported] (managed) {plist_path}" in result.stdout
    assert f"{external.label} [supported] (external)" in result.stdout
    assert "com.example.partial [partially_supported] (external)" in result.stdout
    assert "com.example.broken.plist [invalid] (external)" in result.stdout


def test_list_shows_saved_catalog_only_jobs(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.jobs.import_job(job)
    result = invoke(world, "list")
    assert result.exit_code == 0
    assert (
        f"{job.label} [saved] (managed) (task catalog — not installed)"
        in result.stdout
    )


def test_inspect_managed_job(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    job = make_job(
        working_directory=Path("/tmp"),
        environment=EnvironmentConfig(variables={"FOO": "bar"}),
        logging=LoggingConfig(
            stdout_path=Path("/tmp/out.log"), stderr_path=Path("/tmp/err.log")
        ),
    )
    world.manage(job)
    result = invoke(world, "inspect", job.label)
    assert result.exit_code == 0
    assert f"label: {job.label}" in result.stdout
    assert "working directory: /tmp" in result.stdout
    assert "env FOO=bar" in result.stdout
    assert "stdout log: /tmp/out.log" in result.stdout
    assert "stderr log: /tmp/err.log" in result.stdout
    assert "plist:" in result.stdout
    assert "launchd: loaded in launchd" in result.stdout


def test_inspect_shows_unsupported_keys_and_warnings(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.jobs.import_job(job)
    world.la_root.mkdir()
    payload = plistlib.dumps(
        {
            "Label": job.label,
            "ProgramArguments": ["/bin/echo", "hello"],
            "KeepAlive": True,
        }
    )
    (world.la_root / f"{job.label}.plist").write_bytes(payload)
    result = invoke(world, "inspect", job.label)
    assert result.exit_code == 0
    assert "plist:" in result.stdout
    assert "unsupported key: KeepAlive" in result.stdout
    assert "warning: no schedule found" in result.stdout


def test_inspect_unknown_label_exits_usage(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    result = invoke(world, "inspect", "missing.label")
    assert result.exit_code == 2
    assert "no managed job with label" in result.stderr


def test_validate_ok(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    result = invoke(world, "validate", str(job_file(tmp_path, job)))
    assert result.exit_code == 0
    assert f"OK: {job.label}" in result.stdout
    assert f"label: {job.label}" in result.stdout


def test_validate_invalid_json_exits_usage(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    result = invoke(world, "validate", str(bad))
    assert result.exit_code == 2
    assert "invalid job definition:" in result.stderr


def test_validate_missing_file_exits_usage(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    result = invoke(world, "validate", str(tmp_path / "nope.json"))
    assert result.exit_code == 2
    assert "does not exist" in result.stderr


def test_validate_non_utf8_file_exits_usage(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    bad = tmp_path / "binary.json"
    bad.write_bytes(b"\xff\xfe\x00binary")
    result = invoke(world, "validate", str(bad))
    assert result.exit_code == 2
    assert "invalid job definition:" in result.stderr


def test_generate_prints_xml_without_side_effects(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    result = invoke(world, "generate", str(job_file(tmp_path, job)))
    assert result.exit_code == 0
    assert result.stdout.startswith("<?xml")
    assert result.stdout.rstrip("\n").endswith("</plist>")
    assert f"<string>{job.label}</string>" in result.stdout
    assert not world.la_root.exists()
    assert result.stderr == ""


def test_generate_invalid_json_exits_usage(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    result = invoke(world, "generate", str(bad))
    assert result.exit_code == 2
    assert "invalid job definition:" in result.stderr


def test_install_success(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    result = invoke(world, "install", str(job_file(tmp_path, job)))
    assert result.exit_code == 0
    assert f"installed {job.label} -> {world.la_root / f'{job.label}.plist'}" in result.stdout
    assert (world.catalog_root / f"{job.id}.json").is_file()
    assert (world.la_root / f"{job.label}.plist").is_file()


def test_install_already_saved_job_deploys(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.jobs.import_job(job)
    result = invoke(world, "install", str(job_file(tmp_path, job)))
    assert result.exit_code == 0
    assert (world.la_root / f"{job.label}.plist").is_file()
    assert world.jobs.find(job.label) is not None


def test_install_existing_plist_exits_usage(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.store.write(job)
    result = invoke(world, "install", str(job_file(tmp_path, job)))
    assert result.exit_code == 2
    assert "install refused" in result.stderr


def test_install_invalid_json_exits_usage(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    result = invoke(world, "install", str(bad))
    assert result.exit_code == 2
    assert "invalid job definition:" in result.stderr


def test_install_failed_bootstrap_exits_failure(tmp_path: Path) -> None:
    world = FakeTaskWorld(
        tmp_path, launch=ProcessResult(exit_code=1, stderr="bootstrap failed")
    )
    job = make_job()
    result = invoke(world, "install", str(job_file(tmp_path, job)))
    assert result.exit_code == 1
    assert "install failed for" in result.stderr
    assert "bootstrap failed" in result.stderr


def test_uninstall_success(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.manage(job)
    result = invoke(world, "uninstall", job.label)
    assert result.exit_code == 0
    assert f"uninstalled {job.label} and catalog record" in result.stdout


def test_uninstall_failure_exits_failure(tmp_path: Path) -> None:
    world = FakeTaskWorld(
        tmp_path, launch=ProcessResult(exit_code=1, stderr="bootout failed")
    )
    job = make_job()
    world.manage(job)
    result = invoke(world, "uninstall", job.label)
    assert result.exit_code == 1
    assert "uninstall failed for" in result.stderr
    assert "bootout failed" in result.stderr


def test_uninstall_invalid_label_exits_usage(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    result = invoke(world, "uninstall", "../escape")
    assert result.exit_code == 2
    assert "Label must not be" in result.stderr


def test_enable_success(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    world.manage(make_job(label="com.example.job"))
    result = invoke(world, "enable", "com.example.job")
    assert result.exit_code == 0
    assert "enabled com.example.job" in result.stdout


def test_lifecycle_external_labels_exit_usage(tmp_path: Path) -> None:
    """Every lifecycle command rejects a non-managed label with no backend call."""
    world = FakeTaskWorld(tmp_path)
    external = make_job(label="com.example.external", id=OTHER_ID)
    world.store.write(external)
    for command in ("uninstall", "enable", "disable", "status", "run"):
        result = invoke(world, command, external.label)
        assert result.exit_code == 2
        assert "no managed job with label" in result.stderr
    assert world.launch_runner.specs == []


def test_enable_invalid_label_exits_usage(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    result = invoke(world, "enable", "../escape")
    assert result.exit_code == 2
    assert "Label must not be" in result.stderr


def test_enable_failure_exits_failure(tmp_path: Path) -> None:
    world = FakeTaskWorld(
        tmp_path, launch=ProcessResult(exit_code=1, stderr="enable failed")
    )
    world.manage(make_job(label="com.example.job"))
    result = invoke(world, "enable", "com.example.job")
    assert result.exit_code == 1
    assert "enable failed for com.example.job: exit code 1" in result.stderr


def test_disable_success(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    world.manage(make_job(label="com.example.job"))
    result = invoke(world, "disable", "com.example.job")
    assert result.exit_code == 0
    assert "disabled com.example.job" in result.stdout


def test_disable_invalid_label_exits_usage(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    result = invoke(world, "disable", "../escape")
    assert result.exit_code == 2
    assert "Label must not be" in result.stderr


def test_disable_failure_exits_failure(tmp_path: Path) -> None:
    world = FakeTaskWorld(
        tmp_path, launch=ProcessResult(exit_code=1, stderr="deny")
    )
    world.manage(make_job(label="com.example.job"))
    result = invoke(world, "disable", "com.example.job")
    assert result.exit_code == 1
    assert "disable failed for com.example.job: exit code 1" in result.stderr
    assert "deny" in result.stderr


def test_status_loaded(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    world.manage(make_job(label="com.example.job"))
    result = invoke(world, "status", "com.example.job")
    assert result.exit_code == 0
    assert "com.example.job: loaded in launchd" in result.stdout


def test_status_unloaded_still_exits_success(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path, launch=ProcessResult(exit_code=7))
    world.manage(make_job(label="com.example.job"))
    result = invoke(world, "status", "com.example.job")
    assert result.exit_code == 0
    assert "not loaded in launchd" in result.stdout


def test_status_launch_failure_exits_failure(tmp_path: Path) -> None:
    world = FakeTaskWorld(
        tmp_path,
        launch=ProcessResult(
            exit_code=None,
            stderr="print failed",
            launch_failure=ProcessLaunchFailure(kind="not_found", message="gone"),
        ),
    )
    world.manage(make_job(label="com.example.job"))
    result = invoke(world, "status", "com.example.job")
    assert result.exit_code == 1
    assert "status unknown for com.example.job" in result.stderr
    assert "print failed" in result.stderr


def test_status_invalid_label_exits_usage(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    result = invoke(world, "status", "../escape")
    assert result.exit_code == 2
    assert "Label must not be" in result.stderr


def test_run_success(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    world.manage(make_job(label="com.example.job"))
    result = invoke(world, "run", "com.example.job")
    assert result.exit_code == 0
    assert "requested run of com.example.job" in result.stdout


def test_run_invalid_label_exits_usage(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    result = invoke(world, "run", "../escape")
    assert result.exit_code == 2
    assert "Label must not be" in result.stderr


def test_run_failure_exits_failure(tmp_path: Path) -> None:
    world = FakeTaskWorld(
        tmp_path, launch=ProcessResult(exit_code=1, stderr="kickstart failed")
    )
    world.manage(make_job(label="com.example.job"))
    result = invoke(world, "run", "com.example.job")
    assert result.exit_code == 1
    assert "run failed for com.example.job: exit code 1" in result.stderr
    assert "kickstart failed" in result.stderr


def test_test_reports_process_output_and_diagnostics(tmp_path: Path) -> None:
    world = FakeTaskWorld(
        tmp_path,
        test=ProcessResult(
            exit_code=0, stdout="hello", stderr="warn",
            duration=timedelta(milliseconds=120),
        ),
    )
    job = make_job()
    world.jobs.import_job(job)
    result = invoke(world, "test", job.label)
    assert result.exit_code == 0
    assert "exit code: 0" in result.stdout
    assert "hello" in result.stdout
    assert "warn" in result.stdout
    assert "diagnostics:" in result.stdout
    assert "[error] executable_missing" in result.stdout


def test_test_failure_exits_failure(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path, test=ProcessResult(exit_code=2))
    job = make_job()
    world.jobs.import_job(job)
    result = invoke(world, "test", job.label)
    assert result.exit_code == 1
    assert "exit code: 2" in result.stdout


def test_test_launch_failure_reports_kind(tmp_path: Path) -> None:
    world = FakeTaskWorld(
        tmp_path,
        test=ProcessResult(
            exit_code=None,
            launch_failure=ProcessLaunchFailure(kind="not_found", message="no such file"),
        ),
    )
    job = make_job()
    world.jobs.import_job(job)
    result = invoke(world, "test", job.label)
    assert result.exit_code == 1
    assert "launch failed (not_found): no such file" in result.stdout


def test_test_no_diagnostics_when_executable_exists(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path, test=ProcessResult(exit_code=0))
    job = make_job(
        command=ExecutableCommand(executable=Path("/bin/echo"), arguments=["hi"])
    )
    world.jobs.import_job(job)
    result = invoke(world, "test", job.label)
    assert result.exit_code == 0
    assert "exit code: 0" in result.stdout
    assert "diagnostics:\nnone" in result.stdout


def test_test_unknown_label_exits_usage(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    result = invoke(world, "test", "missing.label")
    assert result.exit_code == 2
    assert "no managed job with label" in result.stderr


def test_logs_reads_configured_streams(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    out = tmp_path / "out.log"
    err = tmp_path / "err.log"
    out.write_text("out line\n")
    err.write_text("err line\n")
    job = make_job(logging=LoggingConfig(stdout_path=out, stderr_path=err))
    world.jobs.import_job(job)
    result = invoke(world, "logs", job.label)
    assert result.exit_code == 0
    assert "=== stdout ===" in result.stdout
    assert "out line" in result.stdout
    assert "=== stderr ===" in result.stdout
    assert "err line" in result.stdout


def test_logs_missing_file_exits_usage(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    job = make_job(
        logging=LoggingConfig(stdout_path=tmp_path / "missing.log", stderr_path=None)
    )
    world.jobs.import_job(job)
    result = invoke(world, "logs", job.label)
    assert result.exit_code == 2
    assert "log file not found" in result.stdout


def test_logs_empty_files_show_empty_marker(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    out = tmp_path / "out.log"
    err = tmp_path / "err.log"
    out.write_text("")
    err.write_text("")
    job = make_job(logging=LoggingConfig(stdout_path=out, stderr_path=err))
    world.jobs.import_job(job)
    result = invoke(world, "logs", job.label)
    assert result.exit_code == 0
    assert result.stdout.count("(empty)") == 2


def test_logs_unconfigured_exits_usage(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.jobs.import_job(job)
    result = invoke(world, "logs", job.label)
    assert result.exit_code == 2
    assert "not configured" in result.stdout


def test_logs_unknown_label_exits_usage(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    result = invoke(world, "logs", "missing.label")
    assert result.exit_code == 2
    assert "no managed job with label" in result.stderr


def test_main_entrypoint_shows_help(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["mactask"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
