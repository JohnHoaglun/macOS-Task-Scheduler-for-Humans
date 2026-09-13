"""Tests for Universal Task Controls platform primitives (v0.0.27).

Covers merge_external_edit, remove_verified, and the new LaunchAgentStore
methods backup_external_from_snapshot, quarantine_external, and
remove_external_verified.
"""

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
from task_scheduler.platform.macos.filesystem import (
    SourceChangedError,
    SourceSnapshot,
)

FIXED_JOB_ID = UUID("12345678-1234-5678-1234-567812345678")


def _make_job(
    label: str = "com.example.test",
    schedule=None,
    enabled: bool = True,
    command=None,
    working_directory=None,
    env: dict[str, str] | None = None,
    stdout_path=None,
    stderr_path=None,
) -> JobDefinition:
    if schedule is None:
        schedule = CalendarSchedule(times=["07:30"], weekdays={Weekday.MONDAY})
    if command is None:
        command = ShellCommand(
            executable=Path("/bin/zsh"),
            arguments=["/tmp/test.sh"],
        )
    return JobDefinition(
        schema_version=2,
        id=FIXED_JOB_ID,
        name=label,
        label=label,
        enabled=enabled,
        command=command,
        schedule=schedule,
        environment=EnvironmentConfig(variables=env or {}),
        working_directory=working_directory,
        logging=LoggingConfig(stdout_path=stdout_path, stderr_path=stderr_path),
    )


class TestMergeExternalEditEachField:
    def test_program_arguments_empty_removes_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from task_scheduler.platform.macos import plist_codec as _pc

        monkeypatch.setattr(_pc, "command_argv", lambda _cmd: [])
        original = {"Label": "x", "ProgramArguments": ["/old"]}
        result = merge_external_edit(
            original, _make_job(), dirty=frozenset({ExternalEditField.PROGRAM_ARGUMENTS})
        )
        assert "ProgramArguments" not in result

    def test_environment_variables_applied(self) -> None:
        original = {"Label": "x", "KeepAlive": True}
        job = _make_job(env={"FOO": "bar"})
        result = merge_external_edit(
            original, job, dirty=frozenset({ExternalEditField.ENVIRONMENT_VARIABLES})
        )
        assert result["EnvironmentVariables"] == {"FOO": "bar"}

    def test_stdout_path_applied(self) -> None:
        original = {"Label": "x", "KeepAlive": True}
        job = _make_job(stdout_path=Path("/tmp/out.log"))
        result = merge_external_edit(
            original, job, dirty=frozenset({ExternalEditField.STDOUT_PATH})
        )
        assert result["StandardOutPath"] == "/tmp/out.log"

    def test_stderr_path_applied(self) -> None:
        original = {"Label": "x", "KeepAlive": True}
        job = _make_job(stderr_path=Path("/tmp/err.log"))
        result = merge_external_edit(
            original, job, dirty=frozenset({ExternalEditField.STDERR_PATH})
        )
        assert result["StandardErrorPath"] == "/tmp/err.log"

    def test_run_at_load_applied(self) -> None:
        original = {"Label": "x", "KeepAlive": True}
        cal = CalendarSchedule(
            times=["09:00"],
            weekdays={Weekday.MONDAY},
            run_at_load=True,
        )
        job = _make_job(schedule=cal)
        result = merge_external_edit(
            original, job, dirty=frozenset({ExternalEditField.RUN_AT_LOAD})
        )
        assert result["RunAtLoad"] is True

    def test_working_directory_applied(self) -> None:
        original = {"Label": "x", "KeepAlive": True}
        job = _make_job(working_directory=Path("/tmp/work"))
        result = merge_external_edit(
            original, job, dirty=frozenset({ExternalEditField.WORKING_DIRECTORY})
        )
        assert result["WorkingDirectory"] == "/tmp/work"

    def test_enabled_inversion(self) -> None:
        original = {"Label": "x"}
        job = _make_job(enabled=False)
        result = merge_external_edit(original, job, dirty=frozenset({ExternalEditField.ENABLED}))
        assert result.get("Disabled") is True

    def test_label_never_touched(self) -> None:
        original = {"Label": "original-label"}
        job = _make_job(label="DIFFERENT_LABEL")
        result = merge_external_edit(original, job, dirty=frozenset({ExternalEditField.ENABLED}))
        assert result["Label"] == "original-label"

    def test_run_at_load_false_removes_key(self) -> None:
        original = {"Label": "x", "RunAtLoad": True}
        cal = CalendarSchedule(
            times=["09:00"],
            weekdays={Weekday.MONDAY},
            run_at_load=False,
        )
        job = _make_job(schedule=cal)
        result = merge_external_edit(
            original, job, dirty=frozenset({ExternalEditField.RUN_AT_LOAD})
        )
        assert "RunAtLoad" not in result

    def test_empty_working_directory_removes_key(self) -> None:
        original = {"Label": "x", "WorkingDirectory": "/old"}
        job = _make_job(working_directory=None)
        result = merge_external_edit(
            original, job, dirty=frozenset({ExternalEditField.WORKING_DIRECTORY})
        )
        assert "WorkingDirectory" not in result

    def test_empty_env_removes_key(self) -> None:
        original = {"Label": "x", "EnvironmentVariables": {"K": "v"}}
        job = _make_job(env={})
        result = merge_external_edit(
            original, job, dirty=frozenset({ExternalEditField.ENVIRONMENT_VARIABLES})
        )
        assert "EnvironmentVariables" not in result

    def test_stdout_path_empty_removes_key(self) -> None:
        original = {"Label": "x", "StandardOutPath": "/old/out.log"}
        job = _make_job(stdout_path=None)
        result = merge_external_edit(
            original, job, dirty=frozenset({ExternalEditField.STDOUT_PATH})
        )
        assert "StandardOutPath" not in result

    def test_stderr_path_empty_removes_key(self) -> None:
        original = {"Label": "x", "StandardErrorPath": "/old/err.log"}
        job = _make_job(stderr_path=None)
        result = merge_external_edit(
            original, job, dirty=frozenset({ExternalEditField.STDERR_PATH})
        )
        assert "StandardErrorPath" not in result


class TestRemoveVerifiedLocal:
    def test_absent_raises_source_changed(self, tmp_path: Path) -> None:
        fs = LocalFilesystem()
        f = tmp_path / "gone.plist"
        snap = SourceSnapshot(
            payload=b"x",
            sha256="abc",
            st_dev=1,
            st_ino=2,
            st_size=1,
        )
        with pytest.raises(SourceChangedError):
            fs.remove_verified(f, snap)

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
        store = LaunchAgentStore(tmp_path / "agents")
        outside = tmp_path / "outside.plist"
        outside.write_bytes(b"data")
        snap = SourceSnapshot(payload=b"x", sha256="x", st_dev=1, st_ino=1, st_size=1)
        with pytest.raises(ValueError, match="outside the LaunchAgent root"):
            store.backup_external_from_snapshot(outside, snap)

    def test_exhaustion_raises(self, tmp_path: Path) -> None:
        plist = tmp_path / "agents" / "io.example.job.plist"
        fs = FakeFilesystem(
            files={"io.example.job.plist": b"payload"},
            create_error=FileExistsError("no room"),
        )
        store = LaunchAgentStore(tmp_path / "agents", filesystem=fs)
        snap = SourceSnapshot(payload=b"x", sha256="x", st_dev=1, st_ino=1, st_size=1)
        with pytest.raises(RuntimeError, match="unique backup sibling"):
            store.backup_external_from_snapshot(plist, snap)


class TestQuarantineExternal:
    def test_rejects_outside_root(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        outside = tmp_path / "outside.plist"
        outside.write_bytes(b"data")
        with pytest.raises(ValueError, match="outside the LaunchAgent root"):
            store.quarantine_external(outside)

    def test_exhaustion_raises(self, tmp_path: Path) -> None:
        plist = tmp_path / "agents" / "io.example.job.plist"
        fs = FakeFilesystem(
            files={"io.example.job.plist": b"payload"},
            create_error=FileExistsError("no room"),
        )
        store = LaunchAgentStore(tmp_path / "agents", filesystem=fs)
        with pytest.raises(RuntimeError, match="unique quarantine file"):
            store.quarantine_external(plist)


class TestRemoveExternalVerified:
    def test_rejects_outside_root(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        outside = tmp_path / "outside.plist"
        outside.write_bytes(b"data")
        snap = SourceSnapshot(payload=b"x", sha256="x", st_dev=1, st_ino=1, st_size=1)
        with pytest.raises(ValueError, match="outside the LaunchAgent root"):
            store.remove_external_verified(outside, snap)
