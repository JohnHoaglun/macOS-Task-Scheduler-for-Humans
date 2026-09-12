"""Comprehensive tests for the Universal Task Controls service methods (Lane B)."""

from __future__ import annotations

import plistlib
from pathlib import Path
from unittest.mock import patch

import pytest
from tests.conftest import make_job
from tests.fakes import OK_PROCESS, FakeProcessRunner, FakeTaskWorld

from task_scheduler.domain import CalendarSchedule, Weekday
from task_scheduler.domain.command import ExecutableCommand
from task_scheduler.platform.macos import (
    ExternalEditField,
    ParseSupport,
    PlistCodec,
    ProcessResult,
)


def _ensure_la_root(world: FakeTaskWorld) -> None:
    world.la_root.mkdir(parents=True, exist_ok=True)


def _write_plist(world: FakeTaskWorld, name: str, data: dict[str, object]) -> Path:
    path = world.la_root / name
    path.write_bytes(plistlib.dumps(data, fmt=plistlib.FMT_XML))
    return path


def _make_raw(replacement: dict[str, object]) -> str:
    """Convert a replacement dict to the str expected by commit_raw_external_edit."""
    return plistlib.dumps(replacement, fmt=plistlib.FMT_XML).decode("utf-8")


# ---------------------------------------------------------------------------
# open_external_edit_session
# ---------------------------------------------------------------------------

class TestOpenExternalEditSession:

    def test_outside_launchagent_root_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        bad = tmp_path / "somewhere" / "bad.plist"
        bad.parent.mkdir()
        bad.write_bytes(plistlib.dumps({"Label": "com.example.bad"}, fmt=plistlib.FMT_XML))
        with pytest.raises(ValueError, match="not a direct child"):
            world.services.open_external_edit_session(bad)

    def test_unparsable_plist_returns_invalid_session(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(
            world, "com.example.bad.plist", {"ProgramArguments": ["/bin/echo"]}
        )
        plist_path.write_bytes(b"not a plist")
        session = world.services.open_external_edit_session(plist_path)
        assert session.source_path == plist_path
        assert session.label is None
        assert session.job is None
        assert session.status is ParseSupport.INVALID

    def test_labelless_plist_returns_session_without_label(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(
            world, "com.example.nolabel.plist", {"ProgramArguments": ["/bin/echo"]}
        )
        session = world.services.open_external_edit_session(plist_path)
        assert session.label is None
        assert session.loaded is None
        assert session.status is ParseSupport.INVALID

    def test_managed_label_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)
        plist_path = world.la_root / f"{job.label}.plist"
        plist_path.write_bytes(PlistCodec().encode_bytes(job))
        with pytest.raises(ValueError, match="already managed"):
            world.services.open_external_edit_session(plist_path)

    def test_loaded_status_when_label_exists(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.loaded.plist", {
            "Label": "com.example.loaded",
            "ProgramArguments": ["/bin/true"],
        })
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout="true"))
        session = world.services.open_external_edit_session(plist_path)
        assert session.loaded is True

    def test_loaded_false_when_status_fail(self, tmp_path: Path) -> None:
        """exit_code=1 -> loaded=False (not None)."""
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.fail.plist", {
            "Label": "com.example.fail",
            "ProgramArguments": ["/bin/true"],
        })
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=1, stderr="fail"))
        session = world.services.open_external_edit_session(plist_path)
        assert session.loaded is False

    def test_unrepresentable_plist_provides_raw_but_no_job(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.weird.plist", {
            "Label": "com.example.weird",
            "ProgramArguments": [1, 2, 3],
        })
        session = world.services.open_external_edit_session(plist_path)
        assert session.job is None
        assert session.original is not None

    def test_representable_plist_provides_job(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        job = make_job()
        plist_path = _write_plist(world, f"{job.label}.plist", PlistCodec().encode_dict(job))
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        session = world.services.open_external_edit_session(plist_path)
        assert session.job is not None
        assert session.job.label == job.label
        assert session.edit_mode() == "structured"


# ---------------------------------------------------------------------------
# commit_structured_external_edit
# ---------------------------------------------------------------------------

class TestCommitStructuredExternalEdit:

    def test_no_job_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(
            world, "com.example.bad.plist", {"ProgramArguments": ["/bin/echo"]}
        )
        session = world.services.open_external_edit_session(plist_path)
        modified = session.job.model_copy() if session.job else make_job()
        with pytest.raises(ValueError, match="no representable job"):
            world.services.commit_structured_external_edit(
                session, modified, frozenset({ExternalEditField.SCHEDULE})
            )

    def test_label_mismatch_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.a.plist", {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        })
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        session = world.services.open_external_edit_session(plist_path)
        altered_job = session.job.model_copy(update={"label": "com.example.other"})
        with pytest.raises(ValueError, match="label cannot change"):
            world.services.commit_structured_external_edit(
                session, altered_job, frozenset({ExternalEditField.SCHEDULE})
            )

    def test_no_dirty_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.a.plist", {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        })
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        session = world.services.open_external_edit_session(plist_path)
        with pytest.raises(ValueError, match="no changes"):
            world.services.commit_structured_external_edit(
                session, session.job, frozenset()
            )

    def test_drift_detection_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.a.plist", {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        })
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        session = world.services.open_external_edit_session(plist_path)
        plist_path.write_bytes(plistlib.dumps({
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/other.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        }, fmt=plistlib.FMT_XML))
        modified = session.job.model_copy(
            update={"command": ExecutableCommand(executable="/bin/date", arguments=[])}
        )
        with pytest.raises(ValueError, match="changed outside"):
            world.services.commit_structured_external_edit(
                session, modified, frozenset({ExternalEditField.PROGRAM_ARGUMENTS})
            )

    def test_no_changes_after_merge_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        job = make_job()
        plist_path = _write_plist(world, "com.example.a.plist", PlistCodec().encode_dict(job))
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        session = world.services.open_external_edit_session(plist_path)
        with pytest.raises(ValueError, match="no changes"):
            world.services.commit_structured_external_edit(
                session, session.job, frozenset({ExternalEditField.PROGRAM_ARGUMENTS})
            )

    def test_unloaded_edit_no_launchctl(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        job = make_job()
        plist_path = _write_plist(world, "com.example.a.plist", PlistCodec().encode_dict(job))
        world.backend._runner = FakeProcessRunner(
            result=ProcessResult(exit_code=1, stderr="not loaded")
        )
        session = world.services.open_external_edit_session(plist_path)
        assert session.loaded is False
        modified = session.job.model_copy(
            update={"command": ExecutableCommand(executable="/bin/date", arguments=[])}
        )
        result = world.services.commit_structured_external_edit(
            session, modified, frozenset({ExternalEditField.PROGRAM_ARGUMENTS})
        )
        assert result.phases == ()
        assert result.completed_phases == ()
        assert result.replaced is True
        assert result.reloaded is False
        assert len(result.retained_artifacts) == 1
        assert ".backup." in result.retained_artifacts[0].name

    def test_loaded_edit_bootout_then_bootstrap(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        job = make_job()
        plist_path = _write_plist(world, "com.example.a.plist", PlistCodec().encode_dict(job))
        world.backend._runner = FakeProcessRunner(results=[OK_PROCESS, OK_PROCESS])
        session = world.services.open_external_edit_session(plist_path)
        assert session.loaded is True
        modified = session.job.model_copy(
            update={"command": ExecutableCommand(executable="/bin/date", arguments=[])}
        )
        result = world.services.commit_structured_external_edit(
            session, modified, frozenset({ExternalEditField.PROGRAM_ARGUMENTS})
        )
        assert result.completed_phases == ("bootout", "bootstrap")
        assert result.reloaded is True
        assert result.replaced is True

    def test_bootout_failure_retains_staged(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(
            tmp_path,
            launches=[OK_PROCESS, ProcessResult(exit_code=1, stderr="bootout failed")],
        )
        _ensure_la_root(world)
        job = make_job()
        plist_path = _write_plist(world, "com.example.a.plist", PlistCodec().encode_dict(job))
        session = world.services.open_external_edit_session(plist_path)
        modified = session.job.model_copy(
            update={"command": ExecutableCommand(executable="/bin/date", arguments=[])}
        )
        result = world.services.commit_structured_external_edit(
            session, modified, frozenset({ExternalEditField.PROGRAM_ARGUMENTS})
        )
        assert result.completed_phases == ()
        assert result.replaced is False
        assert result.reloaded is False
        assert len(result.retained_artifacts) == 1

    def test_bootstrap_failure_retains_backup(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(
            tmp_path,
            launches=[
                OK_PROCESS,
                OK_PROCESS,
                ProcessResult(exit_code=1, stderr="bootstrap failed"),
            ],
        )
        _ensure_la_root(world)
        job = make_job()
        plist_path = _write_plist(world, "com.example.a.plist", PlistCodec().encode_dict(job))
        session = world.services.open_external_edit_session(plist_path)
        modified = session.job.model_copy(
            update={"command": ExecutableCommand(executable="/bin/date", arguments=[])}
        )
        result = world.services.commit_structured_external_edit(
            session, modified, frozenset({ExternalEditField.PROGRAM_ARGUMENTS})
        )
        assert result.completed_phases == ("bootout",)
        assert result.reloaded is False
        assert result.replaced is True
        assert len(result.retained_artifacts) == 1

    def test_structured_edit_preserves_unchanged_keys(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        raw_plist: dict[str, object] = {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py", "--old-flag"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
            "MyCustomKey": "custom-value",
        }
        plist_path = _write_plist(world, "com.example.a.plist", raw_plist)
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        session = world.services.open_external_edit_session(plist_path)
        assert session.job is not None
        job = session.job
        new_job = job.model_copy(
            update={"schedule": CalendarSchedule(times=["12:00"], weekdays={Weekday.MONDAY})}
        )
        result = world.services.commit_structured_external_edit(
            session, new_job, frozenset({ExternalEditField.SCHEDULE})
        )
        assert result.replaced is True
        loaded = plistlib.loads(result.retained_artifacts[0].read_bytes())
        assert loaded["MyCustomKey"] == "custom-value"


# ---------------------------------------------------------------------------
# commit_raw_external_edit
# ---------------------------------------------------------------------------

class TestCommitRawExternalEdit:

    def test_invalid_plist_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.a.plist", {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        })
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        session = world.services.open_external_edit_session(plist_path)
        with pytest.raises(ValueError, match="not a valid plist"):
            world.services.commit_raw_external_edit(session, "not valid")

    def test_non_dict_plist_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.a.plist", {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        })
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        session = world.services.open_external_edit_session(plist_path)
        with pytest.raises(ValueError, match="not a valid plist"):
            world.services.commit_raw_external_edit(session, "[1, 2, 3]")

    def test_no_label_in_replacement_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.a.plist", {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        })
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        session = world.services.open_external_edit_session(plist_path)
        no_label: dict[str, object] = {"ProgramArguments": ["/bin/echo"]}
        with pytest.raises(ValueError, match="valid launchd label"):
            world.services.commit_raw_external_edit(session, _make_raw(no_label))

    def test_label_mismatch_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.a.plist", {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        })
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        session = world.services.open_external_edit_session(plist_path)
        replacement: dict[str, object] = {
            "Label": "com.example.b",
            "ProgramArguments": ["/bin/echo"],
        }
        with pytest.raises(ValueError, match="label cannot change"):
            world.services.commit_raw_external_edit(session, _make_raw(replacement))

    def test_no_changes_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        original = plistlib.dumps({
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        }, fmt=plistlib.FMT_XML)
        plist_path = world.la_root / "com.example.a.plist"
        plist_path.write_bytes(original)
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        session = world.services.open_external_edit_session(plist_path)
        with pytest.raises(ValueError, match="no changes"):
            world.services.commit_raw_external_edit(session, original.decode("utf-8"))

    def test_drift_detection_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.a.plist", {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        })
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        session = world.services.open_external_edit_session(plist_path)
        plist_path.write_bytes(plistlib.dumps({
            "Label": "com.example.a",
            "ProgramArguments": ["/bin/echo"],
        }, fmt=plistlib.FMT_XML))
        replacement: dict[str, object] = {
            "Label": "com.example.a",
            "ProgramArguments": ["/bin/date"],
        }
        with pytest.raises(ValueError, match="changed outside"):
            world.services.commit_raw_external_edit(session, _make_raw(replacement))

    def test_unloaded_raw_edit_no_launchctl(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.a.plist", {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        })
        world.backend._runner = FakeProcessRunner(
            result=ProcessResult(exit_code=1, stderr="not loaded")
        )
        session = world.services.open_external_edit_session(plist_path)
        replacement: dict[str, object] = {
            "Label": "com.example.a",
            "ProgramArguments": ["/bin/date"],
        }
        result = world.services.commit_raw_external_edit(session, _make_raw(replacement))
        assert result.phases == ()
        assert result.replaced is True
        assert result.reloaded is False

    def test_loaded_raw_edit_bootout_then_bootstrap(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.a.plist", {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        })
        world.backend._runner = FakeProcessRunner(results=[OK_PROCESS, OK_PROCESS])
        session = world.services.open_external_edit_session(plist_path)
        replacement: dict[str, object] = {
            "Label": "com.example.a",
            "ProgramArguments": ["/bin/date"],
        }
        result = world.services.commit_raw_external_edit(session, _make_raw(replacement))
        assert result.completed_phases == ("bootout", "bootstrap")
        assert result.reloaded is True


# ---------------------------------------------------------------------------
# disable_external / enable_external / run_now_external
# ---------------------------------------------------------------------------

class TestDisableExternal:

    def test_no_label_quarantines(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "no-label.plist", {"ProgramArguments": ["/bin/echo"]})
        result = world.services.disable_external(plist_path)
        assert result.quarantined_path is not None
        assert result.quarantined_path.exists()
        assert result.phases == ()
        assert result.completed_phases == ()
        assert result.process is None

    def test_loaded_job_disables_and_bootouts(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.a.plist", {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        })
        world.backend._runner = FakeProcessRunner(results=[OK_PROCESS, OK_PROCESS])
        result = world.services.disable_external(plist_path)
        assert "disable" in result.completed_phases
        assert "bootout" in result.completed_phases
        assert result.process is not None

    def test_disabled_job_only_disables(self, tmp_path: Path) -> None:
        """When loaded=False (status exit_code=1), only 'disable' runs; no bootout."""
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.a.plist", {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        })
        world.backend._runner = FakeProcessRunner(
            results=[ProcessResult(exit_code=1, stderr="not loaded"), OK_PROCESS]
        )
        result = world.services.disable_external(plist_path)
        assert result.completed_phases == ("disable",)
        assert "bootout" not in result.completed_phases

    def test_outside_root_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        bad = tmp_path / "outside" / "com.example.plist"
        bad.parent.mkdir()
        bad.write_bytes(plistlib.dumps(
            {"Label": "com.example", "ProgramArguments": ["/bin/echo"]},
            fmt=plistlib.FMT_XML,
        ))
        with pytest.raises(ValueError, match="outside"):
            world.services.disable_external(bad)


class TestEnableExternal:

    def test_no_label_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "no-label.plist", {"ProgramArguments": ["/bin/echo"]})
        with pytest.raises(ValueError, match="no usable launchd label"):
            world.services.enable_external(plist_path)

    def test_outside_root_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        bad = tmp_path / "outside" / "com.example.plist"
        bad.parent.mkdir()
        bad.write_bytes(plistlib.dumps(
            {"Label": "com.example", "ProgramArguments": ["/bin/echo"]},
            fmt=plistlib.FMT_XML,
        ))
        with pytest.raises(ValueError, match="outside"):
            world.services.enable_external(bad)

    def test_not_loaded_triggers_bootstrap(self, tmp_path: Path) -> None:
        """loaded=False triggers bootstrap."""
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.a.plist", {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        })
        world.backend._runner = FakeProcessRunner(
            results=[ProcessResult(exit_code=1, stderr="not loaded"), OK_PROCESS, OK_PROCESS]
        )
        result = world.services.enable_external(plist_path)
        assert result.completed_phases == ("enable", "bootstrap")
        assert result.reloaded is True

    def test_already_loaded_only_enables(self, tmp_path: Path) -> None:
        """loaded=True skips bootstrap."""
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.a.plist", {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        })
        world.backend._runner = FakeProcessRunner(results=[OK_PROCESS, OK_PROCESS])
        result = world.services.enable_external(plist_path)
        assert result.completed_phases == ("enable",)
        assert "bootstrap" not in result.completed_phases
        assert result.reloaded is False


class TestRunNowExternal:

    def test_no_label_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "no-label.plist", {"ProgramArguments": ["/bin/echo"]})
        with pytest.raises(ValueError, match="no usable launchd label"):
            world.services.run_now_external(plist_path)

    def test_outside_root_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        bad = tmp_path / "outside" / "com.example.plist"
        bad.parent.mkdir()
        bad.write_bytes(plistlib.dumps(
            {"Label": "com.example", "ProgramArguments": ["/bin/echo"]},
            fmt=plistlib.FMT_XML,
        ))
        with pytest.raises(ValueError, match="outside"):
            world.services.run_now_external(bad)

    def test_unknown_status_raises(self, tmp_path: Path) -> None:
        """exit_code=None -> loaded=None -> raises 'status is unknown'."""
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.a.plist", {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        })
        world.backend._runner = FakeProcessRunner(
            result=ProcessResult(exit_code=None, stderr="unknown")
        )
        with pytest.raises(ValueError, match="status is unknown"):
            world.services.run_now_external(plist_path)

    def test_not_loaded_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.a.plist", {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        })
        world.backend._runner = FakeProcessRunner(
            result=ProcessResult(exit_code=1, stderr="not loaded")
        )
        with pytest.raises(ValueError, match="not loaded in launchd"):
            world.services.run_now_external(plist_path)

    def test_loaded_triggers(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.a.plist", {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        })
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout="true"))
        result = world.services.run_now_external(plist_path)
        assert result.completed_phases == ("run",)
        assert result.process.exit_code == 0


# ---------------------------------------------------------------------------
# remove_external / remove_saved_job
# ---------------------------------------------------------------------------

class TestRemoveExternal:

    def test_outside_root_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        bad = tmp_path / "outside" / "com.example.plist"
        bad.parent.mkdir()
        bad.write_bytes(plistlib.dumps(
            {"Label": "com.example", "ProgramArguments": ["/bin/echo"]},
            fmt=plistlib.FMT_XML,
        ))
        with pytest.raises(ValueError, match="outside"):
            world.services.remove_external(bad)

    def test_no_label_no_bootout(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "no-label.plist", {"ProgramArguments": ["/bin/echo"]})
        result = world.services.remove_external(plist_path)
        assert result.phases == ()
        assert result.completed_phases == ()
        assert result.removed is True
        assert len(result.retained_artifacts) == 1
        assert not plist_path.exists()

    def test_label_without_bootout(self, tmp_path: Path) -> None:
        """loaded=False -> no bootout phase."""
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.a.plist", {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        })
        world.backend._runner = FakeProcessRunner(
            result=ProcessResult(exit_code=1, stderr="not loaded")
        )
        result = world.services.remove_external(plist_path)
        assert result.phases == ()
        assert result.completed_phases == ()
        assert result.removed is True
        assert len(result.retained_artifacts) == 1
        assert not plist_path.exists()

    def test_label_with_bootout(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.a.plist", {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        })
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout="true"))
        result = world.services.remove_external(plist_path)
        assert "bootout" in result.completed_phases
        assert result.removed is True

    def test_drift_detection_before_remove_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(world, "com.example.a.plist", {
            "Label": "com.example.a",
            "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
        })
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout="true"))
        first_snapshot = world.store.read_external(plist_path)
        plist_path.write_bytes(plistlib.dumps({
            "Label": "com.example.a",
            "ProgramArguments": ["/bin/echo"],
        }, fmt=plistlib.FMT_XML))
        drifted_snapshot = world.store.read_external(plist_path)
        with patch.object(
            world.store, "read_external", side_effect=[first_snapshot, drifted_snapshot]
        ), pytest.raises(ValueError, match="review it and remove again"):
            world.services.remove_external(plist_path)
        assert plist_path.exists()
        assert len(list(world.la_root.glob("*.backup.*"))) == 1


class TestRemoveSavedJob:

    def test_removes_from_catalog(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)
        assert world.jobs.find(job.label) is not None
        deleted_path = world.services.remove_saved_job(job.label)
        assert not deleted_path.exists()

    def test_unknown_label_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        from task_scheduler.application.job_service import JobNotFoundError
        with pytest.raises(JobNotFoundError):
            world.services.remove_saved_job("com.example.nonexistent")
