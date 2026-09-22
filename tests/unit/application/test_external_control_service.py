"""Comprehensive tests for the Universal Task Controls service methods (Lane B)."""

from __future__ import annotations

import plistlib
from pathlib import Path
from unittest.mock import patch

import pytest
from tests.conftest import make_job
from tests.fakes import OK_PROCESS, FakeProcessRunner, FakeTaskWorld

from task_scheduler.domain.command import ExecutableCommand
from task_scheduler.platform.macos import ExternalEditField, ParseSupport, PlistCodec, ProcessResult


def _ensure_la_root(world: FakeTaskWorld) -> None:
    world.la_root.mkdir(parents=True, exist_ok=True)


def _write_plist(world: FakeTaskWorld, name: str, data: dict[str, object]) -> Path:
    path = world.la_root / name
    path.write_bytes(plistlib.dumps(data, fmt=plistlib.FMT_XML))
    return path


def _make_raw(replacement: dict[str, object]) -> str:
    """Convert a replacement dict to the str expected by commit_raw_external_edit."""
    return plistlib.dumps(replacement, fmt=plistlib.FMT_XML).decode("utf-8")


class TestOpenExternalEditSession:
    def test_outside_launchagent_root_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        bad = tmp_path / "somewhere" / "bad.plist"
        bad.parent.mkdir()
        bad.write_bytes(plistlib.dumps({"Label": "com.example.bad"}, fmt=plistlib.FMT_XML))
        with pytest.raises(ValueError, match="not a direct child"):
            world.services.open_external_edit_session(bad)

    def test_managed_label_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)
        plist_path = world.la_root / f"{job.label}.plist"
        plist_path.write_bytes(PlistCodec().encode_bytes(job))
        with pytest.raises(ValueError, match="already managed"):
            world.services.open_external_edit_session(plist_path)


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
        plist_path = _write_plist(
            world,
            "com.example.a.plist",
            {
                "Label": "com.example.a",
                "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
                "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
            },
        )
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
        plist_path = _write_plist(
            world,
            "com.example.a.plist",
            {
                "Label": "com.example.a",
                "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
                "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
            },
        )
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        session = world.services.open_external_edit_session(plist_path)
        with pytest.raises(ValueError, match="no changes"):
            world.services.commit_structured_external_edit(session, session.job, frozenset())

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


class TestCommitRawExternalEdit:
    def test_non_dict_plist_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(
            world,
            "com.example.a.plist",
            {
                "Label": "com.example.a",
                "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
                "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
            },
        )
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        session = world.services.open_external_edit_session(plist_path)
        with pytest.raises(ValueError, match="not a valid plist"):
            world.services.commit_raw_external_edit(session, "[1, 2, 3]")

    def test_no_label_in_replacement_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(
            world,
            "com.example.a.plist",
            {
                "Label": "com.example.a",
                "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
                "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
            },
        )
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        session = world.services.open_external_edit_session(plist_path)
        no_label: dict[str, object] = {"ProgramArguments": ["/bin/echo"]}
        with pytest.raises(ValueError, match="valid launchd label"):
            world.services.commit_raw_external_edit(session, _make_raw(no_label))

    def test_label_mismatch_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(
            world,
            "com.example.a.plist",
            {
                "Label": "com.example.a",
                "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
                "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
            },
        )
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
        original = plistlib.dumps(
            {
                "Label": "com.example.a",
                "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
                "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
            },
            fmt=plistlib.FMT_XML,
        )
        plist_path = world.la_root / "com.example.a.plist"
        plist_path.write_bytes(original)
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        session = world.services.open_external_edit_session(plist_path)
        with pytest.raises(ValueError, match="no changes"):
            world.services.commit_raw_external_edit(session, original.decode("utf-8"))

    def test_drift_detection_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(
            world,
            "com.example.a.plist",
            {
                "Label": "com.example.a",
                "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
                "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
            },
        )
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        session = world.services.open_external_edit_session(plist_path)
        plist_path.write_bytes(
            plistlib.dumps(
                {
                    "Label": "com.example.a",
                    "ProgramArguments": ["/bin/echo"],
                },
                fmt=plistlib.FMT_XML,
            )
        )
        replacement: dict[str, object] = {
            "Label": "com.example.a",
            "ProgramArguments": ["/bin/date"],
        }
        with pytest.raises(ValueError, match="changed outside"):
            world.services.commit_raw_external_edit(session, _make_raw(replacement))

    def test_unloaded_raw_edit_no_launchctl(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(
            world,
            "com.example.a.plist",
            {
                "Label": "com.example.a",
                "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
                "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
            },
        )
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


class TestDisableExternal:
    def test_outside_root_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        bad = tmp_path / "outside" / "com.example.plist"
        bad.parent.mkdir()
        bad.write_bytes(
            plistlib.dumps(
                {"Label": "com.example", "ProgramArguments": ["/bin/echo"]},
                fmt=plistlib.FMT_XML,
            )
        )
        with pytest.raises(ValueError, match="outside"):
            world.services.disable_external(bad)

    def test_marks_plist_disabled_when_loaded(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        original = {"Label": "com.example.d1", "ProgramArguments": ["/bin/true"]}
        plist_path = _write_plist(world, "com.example.d1.plist", original)
        world.backend._runner = FakeProcessRunner(results=[OK_PROCESS, OK_PROCESS, OK_PROCESS])
        result = world.services.disable_external(plist_path)
        assert result.replaced is True
        assert result.reloaded is False
        assert result.completed_phases == ("disable", "bootout")
        assert len(result.retained_artifacts) == 1
        expected = plistlib.dumps({**original, "Disabled": True}, fmt=plistlib.FMT_XML)
        assert plist_path.read_bytes() == expected
        assert len(list(world.la_root.glob("*.backup.*"))) == 1

    def test_unloaded_skips_bootout(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        original = {"Label": "com.example.d2", "ProgramArguments": ["/bin/true"]}
        plist_path = _write_plist(world, "com.example.d2.plist", original)
        world.backend._runner = FakeProcessRunner(results=[ProcessResult(exit_code=1), OK_PROCESS])
        result = world.services.disable_external(plist_path)
        assert "disable" in result.completed_phases
        assert "bootout" not in result.completed_phases
        assert result.replaced is True
        expected = plistlib.dumps({**original, "Disabled": True}, fmt=plistlib.FMT_XML)
        assert plist_path.read_bytes() == expected


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
        bad.write_bytes(
            plistlib.dumps(
                {"Label": "com.example", "ProgramArguments": ["/bin/echo"]},
                fmt=plistlib.FMT_XML,
            )
        )
        with pytest.raises(ValueError, match="outside"):
            world.services.enable_external(bad)

    def test_clears_disabled_and_bootstraps_when_unloaded(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        original = {"Label": "com.example.e1", "ProgramArguments": ["/bin/true"], "Disabled": True}
        plist_path = _write_plist(world, "com.example.e1.plist", original)
        world.backend._runner = FakeProcessRunner(
            results=[ProcessResult(exit_code=1), OK_PROCESS, OK_PROCESS]
        )
        result = world.services.enable_external(plist_path)
        assert result.replaced is True
        assert result.reloaded is True
        assert result.completed_phases == ("enable", "bootstrap")
        assert len(result.retained_artifacts) == 1
        expected = plistlib.dumps(
            {key: value for key, value in original.items() if key != "Disabled"},
            fmt=plistlib.FMT_XML,
        )
        assert plist_path.read_bytes() == expected
        assert len(list(world.la_root.glob("*.backup.*"))) == 1

    def test_loaded_skips_bootstrap(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        original = {"Label": "com.example.e2", "ProgramArguments": ["/bin/true"], "Disabled": True}
        plist_path = _write_plist(world, "com.example.e2.plist", original)
        world.backend._runner = FakeProcessRunner(results=[OK_PROCESS, OK_PROCESS])
        result = world.services.enable_external(plist_path)
        assert "enable" in result.completed_phases
        assert "bootstrap" not in result.completed_phases
        assert result.reloaded is False
        expected = plistlib.dumps(
            {key: value for key, value in original.items() if key != "Disabled"},
            fmt=plistlib.FMT_XML,
        )
        assert plist_path.read_bytes() == expected


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
        bad.write_bytes(
            plistlib.dumps(
                {"Label": "com.example", "ProgramArguments": ["/bin/echo"]},
                fmt=plistlib.FMT_XML,
            )
        )
        with pytest.raises(ValueError, match="outside"):
            world.services.run_now_external(bad)

    def test_not_loaded_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(
            world,
            "com.example.a.plist",
            {
                "Label": "com.example.a",
                "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
                "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
            },
        )
        world.backend._runner = FakeProcessRunner(
            result=ProcessResult(exit_code=1, stderr="not loaded")
        )
        with pytest.raises(ValueError, match="not loaded in launchd"):
            world.services.run_now_external(plist_path)


class TestRemoveExternal:
    def test_outside_root_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        bad = tmp_path / "outside" / "com.example.plist"
        bad.parent.mkdir()
        bad.write_bytes(
            plistlib.dumps(
                {"Label": "com.example", "ProgramArguments": ["/bin/echo"]},
                fmt=plistlib.FMT_XML,
            )
        )
        with pytest.raises(ValueError, match="outside"):
            world.services.remove_external(bad)

    def test_drift_detection_before_remove_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        _ensure_la_root(world)
        plist_path = _write_plist(
            world,
            "com.example.a.plist",
            {
                "Label": "com.example.a",
                "ProgramArguments": ["/usr/bin/python3", "/Users/test/script.py"],
                "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
            },
        )
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout="true"))
        first_snapshot = world.store.read_external(plist_path)
        plist_path.write_bytes(
            plistlib.dumps(
                {
                    "Label": "com.example.a",
                    "ProgramArguments": ["/bin/echo"],
                },
                fmt=plistlib.FMT_XML,
            )
        )
        drifted_snapshot = world.store.read_external(plist_path)
        with (
            patch.object(
                world.store, "read_external", side_effect=[first_snapshot, drifted_snapshot]
            ),
            pytest.raises(ValueError, match="review it and remove again"),
        ):
            world.services.remove_external(plist_path)
        assert plist_path.exists()
        assert len(list(world.la_root.glob("*.backup.*"))) == 1

    def test_failed_bootout_preserves_source_and_returns_not_removed(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(
            tmp_path,
            launches=[OK_PROCESS, ProcessResult(exit_code=1, stderr="bootout failed")],
        )
        _ensure_la_root(world)
        plist_path = _write_plist(
            world,
            "com.example.rmf.plist",
            {"Label": "com.example.rmf", "ProgramArguments": ["/bin/true"]},
        )
        result = world.services.remove_external(plist_path)
        assert result.removed is False
        assert result.completed_phases == ()
        assert result.process is not None and result.process.exit_code == 1
        assert plist_path.exists()
        assert len(list(world.la_root.glob("*.backup.*"))) == 1


def _boom_status(label: str) -> None:
    raise ValueError("status unavailable")


def _labeled_plist(world: FakeTaskWorld, label: str) -> Path:
    _ensure_la_root(world)
    return _write_plist(
        world, f"{label}.plist", {"Label": label, "ProgramArguments": ["/bin/true"]}
    )


class TestStatusValueErrorBranches:
    def test_open_session_status_error_yields_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        plist_path = _labeled_plist(world, "com.example.se")
        monkeypatch.setattr(world.backend, "status", _boom_status)
        session = world.services.open_external_edit_session(plist_path)
        assert session.loaded is None

    def test_disable_status_error_skips_bootout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        plist_path = _labeled_plist(world, "com.example.de")
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        monkeypatch.setattr(world.backend, "status", _boom_status)
        result = world.services.disable_external(plist_path)
        assert "disable" in result.completed_phases
        assert "bootout" not in result.completed_phases

    def test_enable_status_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        world = FakeTaskWorld(tmp_path)
        plist_path = _labeled_plist(world, "com.example.en")
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        monkeypatch.setattr(world.backend, "status", _boom_status)
        result = world.services.enable_external(plist_path)
        assert "enable" in result.completed_phases

    def test_run_now_status_error_raises_unknown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        plist_path = _labeled_plist(world, "com.example.rn")
        monkeypatch.setattr(world.backend, "status", _boom_status)
        with pytest.raises(ValueError, match="unknown"):
            world.services.run_now_external(plist_path)

    def test_remove_status_error_skips_bootout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        plist_path = _labeled_plist(world, "com.example.rm")
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        monkeypatch.setattr(world.backend, "status", _boom_status)
        result = world.services.remove_external(plist_path)
        assert result.removed is True
        assert "bootout" not in result.completed_phases


class TestEdgeValidations:
    def test_commit_structured_original_none_raises(self, tmp_path: Path) -> None:
        from task_scheduler.application import ExternalEditSession

        world = FakeTaskWorld(tmp_path)
        job = make_job(label="com.example.orig")
        session = ExternalEditSession(
            source_path=world.la_root / "com.example.orig.plist",
            sha256="abc",
            identity=(1, 2),
            nonce="n",
            label="com.example.orig",
            loaded=False,
            original=None,
            status=ParseSupport.SUPPORTED,
            job=job,
        )
        with pytest.raises(ValueError, match="no changes"):
            world.services.commit_structured_external_edit(
                session, job, frozenset({ExternalEditField.SCHEDULE})
            )

    def test_commit_raw_non_dict_raises(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        plist_path = _labeled_plist(world, "com.example.raw")
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        session = world.services.open_external_edit_session(plist_path)
        replacement = plistlib.dumps([1, 2, 3], fmt=plistlib.FMT_XML).decode("utf-8")
        with pytest.raises(ValueError, match="not a valid plist"):
            world.services.commit_raw_external_edit(session, replacement)

    def test_commit_raw_loaded_bootout_fail_retains_staged(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        plist_path = _labeled_plist(world, "com.example.rf")
        world.backend._runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
        session = world.services.open_external_edit_session(plist_path)
        assert session.loaded is True
        world.backend._runner = FakeProcessRunner(
            results=[ProcessResult(exit_code=1, stderr="bootout fail")]
        )
        replacement = _make_raw(
            {"Label": "com.example.rf", "ProgramArguments": ["/bin/true", "extra"]}
        )
        result = world.services.commit_raw_external_edit(session, replacement)
        assert result.process.exit_code != 0
        assert result.replaced is False
        assert result.phases[0].name == "bootout"
        assert result.retained_artifacts
