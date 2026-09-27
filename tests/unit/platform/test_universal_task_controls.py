"""Tests for Universal Task Controls platform primitives (v0.0.27)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from tests.fakes import FakeFilesystem

from task_scheduler.domain import (
    CalendarSchedule,
    JobDefinition,
    LoggingConfig,
    ShellCommand,
    Weekday,
)
from task_scheduler.domain.environment import EnvironmentConfig
from task_scheduler.platform.macos import (
    ExternalEditField,
    LaunchAgentStore,
    LocalFilesystem,
    merge_external_edit,
)
from task_scheduler.platform.macos.filesystem import SourceChangedError, SourceSnapshot

FIXED_JOB_ID = UUID("12345678-1234-5678-1234-567812345678")

def _make_job(
    label: str = "com.example.test",
    schedule=None,
    enabled: bool = True,
    working_directory=None,
    env: dict[str, str] | None = None,
    stdout_path=None,
    stderr_path=None,
) -> JobDefinition:
    if schedule is None:
        schedule = CalendarSchedule(times=["07:30"], weekdays={Weekday.MONDAY})
    return JobDefinition(
        schema_version=2,
        id=FIXED_JOB_ID,
        name=label,
        label=label,
        enabled=enabled,
        command=ShellCommand(executable=Path("/bin/zsh"), arguments=["/tmp/test.sh"]),
        schedule=schedule,
        environment=EnvironmentConfig(variables=env or {}),
        working_directory=working_directory,
        logging=LoggingConfig(stdout_path=stdout_path, stderr_path=stderr_path),
    )

def _SNAP() -> SourceSnapshot:
    return SourceSnapshot(payload=b"x", sha256="x", st_dev=1, st_ino=1, st_size=1)

class TestMergeExternalEditEachField:
    def test_env_applied(self) -> None:
        merged = merge_external_edit(
            {"Label": "x"}, _make_job(env={"FOO": "bar"}),
            dirty=frozenset({ExternalEditField.ENVIRONMENT_VARIABLES}),
        )
        assert merged["EnvironmentVariables"] == {"FOO": "bar"}

    def test_stdout_path_applied(self) -> None:
        merged = merge_external_edit(
            {"Label": "x"}, _make_job(stdout_path=Path("/tmp/out.log")),
            dirty=frozenset({ExternalEditField.STDOUT_PATH}),
        )
        assert merged["StandardOutPath"] == "/tmp/out.log"

    def test_stderr_path_applied(self) -> None:
        merged = merge_external_edit(
            {"Label": "x"}, _make_job(stderr_path=Path("/tmp/err.log")),
            dirty=frozenset({ExternalEditField.STDERR_PATH}),
        )
        assert merged["StandardErrorPath"] == "/tmp/err.log"

    def test_working_directory_applied(self) -> None:
        merged = merge_external_edit(
            {"Label": "x"}, _make_job(working_directory=Path("/tmp/work")),
            dirty=frozenset({ExternalEditField.WORKING_DIRECTORY}),
        )
        assert merged["WorkingDirectory"] == "/tmp/work"

    def test_run_at_load_applied(self) -> None:
        cal = CalendarSchedule(times=["09:00"], weekdays={Weekday.MONDAY}, run_at_load=True)
        merged = merge_external_edit(
            {"Label": "x"}, _make_job(schedule=cal),
            dirty=frozenset({ExternalEditField.RUN_AT_LOAD}),
        )
        assert merged["RunAtLoad"] is True

    def test_enabled_inversion(self) -> None:
        merged = merge_external_edit(
            {"Label": "x"}, _make_job(enabled=False),
            dirty=frozenset({ExternalEditField.ENABLED}),
        )
        assert merged.get("Disabled") is True

    def test_label_never_touched(self) -> None:
        merged = merge_external_edit(
            {"Label": "original-label"}, _make_job(label="DIFFERENT_LABEL"),
            dirty=frozenset({ExternalEditField.ENABLED}),
        )
        assert merged["Label"] == "original-label"

    def test_program_arguments_empty_removes_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from task_scheduler.platform.macos import plist_codec as _pc

        monkeypatch.setattr(_pc, "command_argv", lambda _cmd: [])
        merged = merge_external_edit(
            {"Label": "x", "ProgramArguments": ["/old"]}, _make_job(),
            dirty=frozenset({ExternalEditField.PROGRAM_ARGUMENTS}),
        )
        assert "ProgramArguments" not in merged

    @pytest.mark.parametrize(
        ("field", "key", "old"),
        [
            (ExternalEditField.RUN_AT_LOAD, "RunAtLoad", True),
            (ExternalEditField.WORKING_DIRECTORY, "WorkingDirectory", "/old"),
            (ExternalEditField.ENVIRONMENT_VARIABLES, "EnvironmentVariables", {"K": "v"}),
            (ExternalEditField.STDOUT_PATH, "StandardOutPath", "/old/out.log"),
            (ExternalEditField.STDERR_PATH, "StandardErrorPath", "/old/err.log"),
        ],
    )
    def test_empty_field_removes_key(self, field: ExternalEditField, key: str, old: object) -> None:
        merged = merge_external_edit(
            {"Label": "x", key: old}, _make_job(), dirty=frozenset({field})
        )
        assert key not in merged

class TestRemoveVerifiedLocal:
    def test_absent_raises_source_changed(self, tmp_path: Path) -> None:
        with pytest.raises(SourceChangedError):
            LocalFilesystem().remove_verified(tmp_path / "gone.plist", _SNAP())

    def test_sha_drift_raises_source_changed(self, tmp_path: Path) -> None:
        fs = LocalFilesystem()
        f = tmp_path / "test.plist"
        f.write_bytes(b"original")
        snap = fs.read_snapshot(f)
        f.write_bytes(b"mutated")
        with pytest.raises(SourceChangedError):
            fs.remove_verified(f, snap)

class TestBackupExternalFromSnapshot:
    def test_rejects_outside_root(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside.plist"
        outside.write_bytes(b"data")
        with pytest.raises(ValueError, match="outside the LaunchAgent root"):
            LaunchAgentStore(tmp_path / "agents").backup_external_from_snapshot(outside, _SNAP())

    def test_exhaustion_raises(self, tmp_path: Path) -> None:
        fs = FakeFilesystem(
            files={"io.example.job.plist": b"payload"}, create_error=FileExistsError()
        )
        with pytest.raises(RuntimeError, match="unique backup sibling"):
            LaunchAgentStore(tmp_path / "agents", filesystem=fs).backup_external_from_snapshot(
                tmp_path / "agents" / "io.example.job.plist", _SNAP()
            )

class TestQuarantineExternal:
    def test_rejects_outside_root(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside.plist"
        outside.write_bytes(b"data")
        with pytest.raises(ValueError, match="outside the LaunchAgent root"):
            LaunchAgentStore(tmp_path / "agents").quarantine_external(outside, _SNAP())

    def test_exhaustion_raises(self, tmp_path: Path) -> None:
        plist = tmp_path / "agents" / "io.example.job.plist"
        fs = FakeFilesystem(
            files={"io.example.job.plist": b"payload"}, create_error=FileExistsError()
        )
        store = LaunchAgentStore(tmp_path / "agents", filesystem=fs)
        with pytest.raises(RuntimeError, match="unique quarantine file"):
            store.quarantine_external(plist, store.read_external(plist))

    def test_source_drift_fails_cleanly(self, tmp_path: Path) -> None:
        plist = tmp_path / "agents" / "io.example.job.plist"
        fs = FakeFilesystem(files={"io.example.job.plist": b"observed"})
        store = LaunchAgentStore(tmp_path / "agents", filesystem=fs)
        snap = store.read_external(plist)
        fs._files["io.example.job.plist"] = b"mutated"  # concurrent writer drift
        with pytest.raises(SourceChangedError):
            store.quarantine_external(plist, snap)
        # Source left intact and no orphan quarantine artifact.
        assert fs.read_plist_bytes(plist) == b"mutated"
        quarantined = tmp_path / "agents" / ".task-scheduler-disabled" / "io.example.job-1.plist"
        with pytest.raises(FileNotFoundError):
            fs.read_plist_bytes(quarantined)

class TestRemoveExternalVerified:
    def test_rejects_outside_root(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside.plist"
        outside.write_bytes(b"data")
        with pytest.raises(ValueError, match="outside the LaunchAgent root"):
            LaunchAgentStore(tmp_path / "agents").remove_external_verified(outside, _SNAP())
