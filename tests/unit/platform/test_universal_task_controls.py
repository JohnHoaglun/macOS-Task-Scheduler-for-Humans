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
    IntervalSchedule,
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


class TestMergeExternalEditEmptyDirty:

    def test_empty_dirty_returns_copy(self) -> None:
        original = {"Label": "x", "KeepAlive": True, "SomeOther": 42}
        job = _make_job()
        result = merge_external_edit(original, job, dirty=frozenset())
        assert result == original
        assert result is not original

    def test_empty_dirty_original_unmutated(self) -> None:
        original = {"Label": "orig-label", "KeepAlive": True}
        job = _make_job(label="DIFFERENT_LABEL", enabled=False)
        result = merge_external_edit(original, job, dirty=frozenset())
        assert result == original
        assert "Label" not in result or result["Label"] == original["Label"]


class TestMergeExternalEditEachField:

    def test_program_arguments_applied(self) -> None:
        original = {"Label": "x", "KeepAlive": True, "CustomKey": "preserved"}
        job = _make_job(
            command=ShellCommand(
                executable=Path("/bin/echo"),
                arguments=["hello"],
            )
        )
        result = merge_external_edit(
            original, job, dirty=frozenset({ExternalEditField.PROGRAM_ARGUMENTS})
        )
        assert result["ProgramArguments"] == ["/bin/echo", "hello"]
        assert "KeepAlive" in result
        assert result["CustomKey"] == "preserved"

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

    def test_schedule_applied_calendar(self) -> None:
        original = {
            "Label": "x",
            "KeepAlive": True,
            "StartInterval": 300,
            "CustomKey": "preserved",
        }
        cal = CalendarSchedule(
            times=["09:00"],
            weekdays={Weekday.MONDAY},
        )
        job = _make_job(schedule=cal)
        result = merge_external_edit(
            original, job, dirty=frozenset({ExternalEditField.SCHEDULE})
        )
        assert "StartCalendarInterval" in result
        assert "StartInterval" not in result
        assert "KeepAlive" in result
        assert result["CustomKey"] == "preserved"

    def test_enabled_inversion(self) -> None:
        original = {"Label": "x"}
        job = _make_job(enabled=False)
        result = merge_external_edit(
            original, job, dirty=frozenset({ExternalEditField.ENABLED})
        )
        assert result.get("Disabled") is True

    def test_enabled_remove_when_true(self) -> None:
        original = {"Label": "x", "Disabled": True}
        job = _make_job(enabled=True)
        result = merge_external_edit(
            original, job, dirty=frozenset({ExternalEditField.ENABLED})
        )
        assert "Disabled" not in result

    def test_schedule_swap_calendar_to_interval(self) -> None:
        original = {
            "Label": "x",
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        }
        job = _make_job(schedule=IntervalSchedule(seconds=300, run_at_load=False))
        result = merge_external_edit(
            original, job, dirty=frozenset({ExternalEditField.SCHEDULE})
        )
        assert "StartInterval" in result
        assert result["StartInterval"] == 300
        assert "StartCalendarInterval" not in result

    def test_schedule_swap_interval_to_calendar(self) -> None:
        original = {
            "Label": "x",
            "StartInterval": 600,
        }
        cal = CalendarSchedule(times=["09:00"], weekdays={Weekday.MONDAY})
        job = _make_job(schedule=cal)
        result = merge_external_edit(
            original, job, dirty=frozenset({ExternalEditField.SCHEDULE})
        )
        assert "StartCalendarInterval" in result
        assert "StartInterval" not in result

    def test_label_never_touched(self) -> None:
        original = {"Label": "original-label"}
        job = _make_job(label="DIFFERENT_LABEL")
        result = merge_external_edit(
            original, job, dirty=frozenset({ExternalEditField.ENABLED})
        )
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

    def test_non_dirty_keys_survive(self) -> None:
        original = {
            "Label": "x",
            "KeepAlive": True,
            "LimitLoadToSessionType": "LoginWindow",
            "CustomKey": "value",
        }
        job = _make_job(enabled=False)
        result = merge_external_edit(
            original, job, dirty=frozenset({ExternalEditField.ENABLED})
        )
        assert result["KeepAlive"] is True
        assert result["LimitLoadToSessionType"] == "LoginWindow"
        assert result["CustomKey"] == "value"
        assert result["Disabled"] is True


class TestRemoveVerifiedLocal:

    def test_success(self, tmp_path: Path) -> None:
        fs = LocalFilesystem()
        f = tmp_path / "test.plist"
        f.write_bytes(b"content")
        snap = fs.read_snapshot(f)
        fs.remove_verified(f, snap)
        assert not f.exists()

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

    def test_identity_drift_raises_source_changed(self, tmp_path: Path) -> None:
        fs = LocalFilesystem()
        f = tmp_path / "test.plist"
        f.write_bytes(b"content")
        snap = fs.read_snapshot(f)
        stale = SourceSnapshot(
            payload=snap.payload,
            sha256=snap.sha256,
            st_dev=999,
            st_ino=999,
            st_size=snap.st_size,
        )
        with pytest.raises(SourceChangedError):
            fs.remove_verified(f, stale)


class TestRemoveVerifiedFake:

    def test_success(self) -> None:
        fs = FakeFilesystem(files={"test.plist": b"content"})
        path = Path("/root/test.plist")
        snap = fs.read_snapshot(path)
        fs.remove_verified(path, snap)
        assert "test.plist" not in fs._files
        assert fs.removed == ["test.plist"]

    def test_absent_raises_file_not_found(self) -> None:
        fs = FakeFilesystem()
        path = Path("/root/missing.plist")
        snap = SourceSnapshot(
            payload=b"x",
            sha256="x",
            st_dev=1,
            st_ino=2,
            st_size=1,
        )
        with pytest.raises(FileNotFoundError):
            fs.remove_verified(path, snap)

    def test_sha_drift_raises_source_changed(self) -> None:
        fs = FakeFilesystem(files={"test.plist": b"content"})
        path = Path("/root/test.plist")
        snap = fs.read_snapshot(path)
        fs._files["test.plist"] = b"mutated"
        with pytest.raises(SourceChangedError):
            fs.remove_verified(path, snap)

    def test_identity_drift_raises_source_changed(self) -> None:
        fs = FakeFilesystem(files={"test.plist": b"content"})
        path = Path("/root/test.plist")
        snap = fs.read_snapshot(path)
        fs._name_to_identity["test.plist"] = (999, 999)
        with pytest.raises(SourceChangedError):
            fs.remove_verified(path, snap)


class TestBackupExternalFromSnapshot:

    def test_writes_snapshot_payload(self, tmp_path: Path) -> None:
        plist = tmp_path / "agents" / "io.example.job.plist"
        plist.parent.mkdir(parents=True)
        plist.write_bytes(b"original-file-content")
        store = LaunchAgentStore(tmp_path / "agents")
        stale_snap = SourceSnapshot(
            payload=b"snapshot-payload-not-file",
            sha256="fake-sha",
            st_dev=1,
            st_ino=1,
            st_size=21,
        )
        backup = store.backup_external_from_snapshot(plist, stale_snap)
        assert backup.name == "io.example.job.plist.backup.1"
        assert backup.read_bytes() == b"snapshot-payload-not-file"

    def test_uniqueness_on_collision(self, tmp_path: Path) -> None:
        plist = tmp_path / "agents" / "io.example.job.plist"
        plist.parent.mkdir(parents=True)
        plist.write_bytes(b"data")
        fs = FakeFilesystem(
            files={
                "io.example.job.plist.backup.1": b"old-backup",
            },
        )
        store = LaunchAgentStore(tmp_path / "agents", filesystem=fs)
        snap = SourceSnapshot(
            payload=b"new-payload",
            sha256="fake",
            st_dev=1,
            st_ino=1,
            st_size=11,
        )
        backup = store.backup_external_from_snapshot(plist, snap)
        assert backup.name == "io.example.job.plist.backup.2"

    def test_rejects_outside_root(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        outside = tmp_path / "outside.plist"
        outside.write_bytes(b"data")
        snap = SourceSnapshot(payload=b"x", sha256="x", st_dev=1, st_ino=1, st_size=1)
        with pytest.raises(ValueError, match="outside the LaunchAgent root"):
            store.backup_external_from_snapshot(outside, snap)


class TestQuarantineExternal:

    def test_moves_file_to_quarantine(self, tmp_path: Path) -> None:
        plist = tmp_path / "agents" / "io.example.job.plist"
        plist.parent.mkdir(parents=True)
        plist.write_bytes(b"quarantine-me")
        store = LaunchAgentStore(tmp_path / "agents")
        dest = store.quarantine_external(plist)
        assert dest.parent.name == ".task-scheduler-disabled"
        assert dest.name == "io.example.job-1.plist"
        assert dest.read_bytes() == b"quarantine-me"
        assert not plist.exists()

    def test_uniqueness_on_collision(self, tmp_path: Path) -> None:
        plist = tmp_path / "agents" / "io.example.job.plist"
        plist.parent.mkdir(parents=True)
        plist.write_bytes(b"quarantine")
        quarantine_dir = tmp_path / "agents" / ".task-scheduler-disabled"
        quarantine_dir.mkdir()
        (quarantine_dir / "io.example.job-1.plist").write_bytes(b"old")
        store = LaunchAgentStore(tmp_path / "agents")
        dest = store.quarantine_external(plist)
        assert dest.name == "io.example.job-2.plist"
        assert dest.read_bytes() == b"quarantine"
        assert not plist.exists()

    def test_rejects_outside_root(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        outside = tmp_path / "outside.plist"
        outside.write_bytes(b"data")
        with pytest.raises(ValueError, match="outside the LaunchAgent root"):
            store.quarantine_external(outside)


class TestRemoveExternalVerified:

    def test_removes_on_match(self, tmp_path: Path) -> None:
        plist = tmp_path / "agents" / "io.example.job.plist"
        plist.parent.mkdir(parents=True)
        plist.write_bytes(b"remove-me")
        store = LaunchAgentStore(tmp_path / "agents")
        snap = store.read_external(plist)
        store.remove_external_verified(plist, snap)
        assert not plist.exists()

    def test_raises_on_drift(self, tmp_path: Path) -> None:
        plist = tmp_path / "agents" / "io.example.job.plist"
        plist.parent.mkdir(parents=True)
        plist.write_bytes(b"original")
        store = LaunchAgentStore(tmp_path / "agents")
        snap = store.read_external(plist)
        plist.write_bytes(b"drifted")
        with pytest.raises(SourceChangedError):
            store.remove_external_verified(plist, snap)

    def test_rejects_outside_root(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        outside = tmp_path / "outside.plist"
        outside.write_bytes(b"data")
        snap = SourceSnapshot(payload=b"x", sha256="x", st_dev=1, st_ino=1, st_size=1)
        with pytest.raises(ValueError, match="outside the LaunchAgent root"):
            store.remove_external_verified(outside, snap)
