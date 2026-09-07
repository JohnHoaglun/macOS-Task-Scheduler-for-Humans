"""Tests for the Qt-free editor controller."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.conftest import make_job
from tests.fakes import FakeTaskWorld

from task_scheduler.domain import (
    ExecutableCommand,
    IntervalSchedule,
    JobDefinition,
    ShellCommand,
)
from task_scheduler.gui.controllers.editor_controller import EditorController, JobDraft


def make_controller(tmp_path: Path) -> tuple[FakeTaskWorld, EditorController]:
    world = FakeTaskWorld(tmp_path)
    return world, EditorController(world.services)

class TestArguments:
    def test_arguments_per_kind(self, tmp_path: Path) -> None:
        """Each kind appends to its own argument list."""
        world, controller = make_controller(tmp_path)
        for kind, attr in [
            ("python", "python_arguments"),
            ("shell", "shell_arguments"),
            ("executable", "executable_arguments"),
        ]:
            d = controller.open_new()
            controller.add_argument(d, kind)
            controller.add_argument(d, kind)
            controller.add_argument(d, kind)
            assert getattr(d, attr) == ["", "", ""]
            assert controller.arguments_for(d, kind) is getattr(d, attr)

    def test_set_and_remove_argument(self, tmp_path: Path) -> None:
        """Arguments can be set in place and removed by index."""
        world, controller = make_controller(tmp_path)
        d = controller.open_new()
        controller.add_argument(d, "python")
        controller.add_argument(d, "python")
        controller.set_argument(d, "python", 0, "--flag")
        controller.add_argument(d, "python")
        controller.set_argument(d, "python", 2, "x")
        controller.remove_argument(d, "python", 0)
        assert d.python_arguments == ["", "x"]

class TestOtherMutators:

    def test_environment_rows(self, tmp_path: Path) -> None:
        """Environment rows are appended, edited in place, and removable."""
        world, controller = make_controller(tmp_path)
        d = controller.open_new()
        controller.add_environment_row(d)
        assert d.environment == [("", "")]
        controller.add_environment_row(d)
        controller.set_environment_key(d, 0, "PATH")
        controller.set_environment_key(d, 1, "HOME")
        controller.set_environment_value(d, 1, "/opt/bin")
        controller.remove_environment_row(d, 0)
        assert d.environment == [("HOME", "/opt/bin")]

class TestOpenExisting:

    def test_shell_job(self, tmp_path: Path) -> None:
        """A persisted shell job populates only the shell fields."""
        world, controller = make_controller(tmp_path)
        job = make_job(command=ShellCommand(executable="/bin/zsh", arguments=["-c", "echo hi"]))
        d = controller.open_existing(job)
        assert d.command_kind == "shell"
        assert d.shell_executable == "/bin/zsh"
        assert d.shell_arguments == ["-c", "echo hi"]
        assert d.interpreter == ""
        assert d.script == ""
        assert d.executable_path == ""

    def test_executable_job(self, tmp_path: Path) -> None:
        """A persisted executable job populates only the executable fields."""
        world, controller = make_controller(tmp_path)
        job = make_job(
            command=ExecutableCommand(executable="/usr/local/bin/backup", arguments=["--all"])
        )
        d = controller.open_existing(job)
        assert d.command_kind == "executable"
        assert d.executable_path == "/usr/local/bin/backup"
        assert d.executable_arguments == ["--all"]
        assert d.shell_executable == ""
        assert d.shell_arguments == []

    @pytest.mark.parametrize(
        ("seconds", "value", "unit"),
        [
            (61, "61", "seconds"),
            (90, "90", "seconds"),
            (3600, "1", "hours"),
            (93600, "26", "hours"),
            (172800, "2", "days"),
        ],
    )
    def test_interval_load_normalization(
        self, tmp_path: Path, seconds: int, value: str, unit: str
    ) -> None:
        """Persisted seconds load as the largest unit that divides them exactly."""
        world, controller = make_controller(tmp_path)
        job = make_job(schedule=IntervalSchedule(seconds=seconds))
        d = controller.open_existing(job)
        assert d.schedule_kind == "interval"
        assert d.interval_value == value
        assert d.interval_unit == unit

    def test_interval_job_preserves_run_at_load(self, tmp_path: Path) -> None:
        """An interval job with login behavior opens with run_at_load set."""
        world, controller = make_controller(tmp_path)
        job = make_job(schedule=IntervalSchedule(seconds=1800, run_at_load=True))
        d = controller.open_existing(job)
        assert d.run_at_load is True

def valid_draft(controller: EditorController, tmp_path: Path) -> JobDraft:
    draft = controller.open_new()
    controller.set_name(draft, "Editor Job")
    controller.set_interpreter(draft, "/usr/bin/python3")
    controller.set_script(draft, str(tmp_path / "job.py"))
    controller.set_times(draft, ["07:30"])
    controller.set_weekdays(draft, {"monday"})
    return draft

class TestValidate:

    def test_missing_interpreter(self, tmp_path: Path) -> None:
        """A blank interpreter fails with an interpreter field error."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_interpreter(d, "")
        o = controller.validate(d)
        assert o.fields == {"interpreter": "an interpreter is required"}

    def test_relative_interpreter(self, tmp_path: Path) -> None:
        """A relative interpreter path fails validation."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_interpreter(d, "python3")
        o = controller.validate(d)
        assert o.fields == {"interpreter": "the interpreter path must be absolute"}

    def test_missing_script(self, tmp_path: Path) -> None:
        """A blank script fails with a script field error."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_script(d, "")
        o = controller.validate(d)
        assert o.fields == {"script": "a script is required"}

    def test_relative_script(self, tmp_path: Path) -> None:
        """A relative script path fails validation."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_script(d, "job.py")
        o = controller.validate(d)
        assert o.fields == {"script": "the script path must be absolute"}

    def test_shell_kind_missing_executable(self, tmp_path: Path) -> None:
        """A shell draft without an executable fails validation."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_command_kind(d, "shell")
        o = controller.validate(d)
        assert o.fields == {"shell_executable": "a shell executable is required"}

    def test_executable_kind_missing_executable(self, tmp_path: Path) -> None:
        """An executable draft without a path fails validation."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_command_kind(d, "executable")
        o = controller.validate(d)
        assert o.fields == {"executable": "an executable is required"}

    def test_no_times(self, tmp_path: Path) -> None:
        """A draft with no times fails with a times field error."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_times(d, [])
        o = controller.validate(d)
        assert o.fields == {"times": "at least one time is required"}

    def test_bad_time_value(self, tmp_path: Path) -> None:
        """An invalid time value surfaces the exact domain message on the times field."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_times(d, ["99:99"])
        o = controller.validate(d)
        assert o.fields == {"times": "schedule time out of range (00:00-23:59), got '99:99'"}

    def test_no_weekdays(self, tmp_path: Path) -> None:
        """A draft with no weekdays fails validation."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_weekdays(d, set())
        o = controller.validate(d)
        assert o.fields == {"weekdays": "at least one weekday is required"}

    def test_relative_stdout(self, tmp_path: Path) -> None:
        """A relative stdout path fails validation."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_stdout_path(d, "rel/out.log")
        o = controller.validate(d)
        assert "stdout_path" in o.fields and o.fields["stdout_path"]

    def test_invalid_weekday_value(self, tmp_path: Path) -> None:
        """An unknown weekday value fails as a whole-job error."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        d.weekdays = {"notaday"}
        o = controller.validate(d)
        assert list(o.fields) == ["job"] and "notaday" in o.fields["job"]

class TestIntervalSchedule:
    def interval_draft(
        self, controller: EditorController, tmp_path: Path, value: str, unit: str
    ) -> JobDraft:
        draft = controller.open_new()
        controller.set_name(draft, "Interval Job")
        controller.set_interpreter(draft, "/usr/bin/python3")
        controller.set_script(draft, str(tmp_path / "job.py"))
        controller.set_schedule_kind(draft, "interval")
        controller.set_interval(draft, value, unit)
        return draft

    def test_interval_sub_minimum_uses_domain_message(self, tmp_path: Path) -> None:
        """A converted total below 60 seconds fails with the domain message on interval."""
        world, controller = make_controller(tmp_path)
        o = controller.validate(self.interval_draft(controller, tmp_path, "30", "seconds"))
        assert o.ok is False
        assert o.fields == {"interval": "interval must be at least 60 seconds"}

    @pytest.mark.parametrize("value", ["", "  ", "1.5", "abc"])
    def test_interval_non_whole_number(self, tmp_path: Path, value: str) -> None:
        """A blank or non-integer duration fails with a whole-number message on interval."""
        world, controller = make_controller(tmp_path)
        o = controller.validate(self.interval_draft(controller, tmp_path, value, "minutes"))
        assert o.ok is False
        assert o.fields == {"interval": "enter a whole number of seconds, minutes, hours, or days"}

    @pytest.mark.parametrize("value", ["0", "-5"])
    def test_interval_non_positive(self, tmp_path: Path, value: str) -> None:
        """A zero or negative duration fails with a positive-number message on interval."""
        world, controller = make_controller(tmp_path)
        o = controller.validate(self.interval_draft(controller, tmp_path, value, "minutes"))
        assert o.ok is False
        assert o.fields == {
            "interval": "enter a positive whole number of seconds, minutes, hours, or days"
        }

    def test_interval_bad_unit(self, tmp_path: Path) -> None:
        """An unknown unit fails with a unit message on interval."""
        world, controller = make_controller(tmp_path)
        draft = self.interval_draft(controller, tmp_path, "5", "fortnights")
        o = controller.validate(draft)
        assert o.ok is False
        assert o.fields == {
            "interval": "the interval unit must be one of seconds, minutes, hours, or days"
        }

class TestSave:

    def test_save_conflict(self, tmp_path: Path) -> None:
        """Saving under an existing job's label conflicts without overwriting."""
        world, controller = make_controller(tmp_path)
        job = make_job()
        world.services.save_managed_job(job)
        seeded = world.catalog_root / f"{job.id}.json"
        before = seeded.read_bytes()
        d = valid_draft(controller, tmp_path)
        controller.set_name(d, "Other")
        controller.set_label(d, job.label)
        o = controller.save(d)
        assert o.ok is False
        assert o.path is None
        assert o.label == ""
        assert "label" in o.fields
        assert job.label in o.message
        assert seeded.read_bytes() == before

    def test_save_oserror(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A disk failure during save surfaces as a whole-job error."""
        world, controller = make_controller(tmp_path)

        def _boom(job: JobDefinition) -> Path:
            """Simulate a disk failure during persistence."""
            raise OSError("disk full")

        monkeypatch.setattr(world.services, "save_managed_job", _boom)
        d = valid_draft(controller, tmp_path)
        o = controller.save(d)
        assert o.ok is False
        assert o.message == "disk full"
        assert o.fields == {"job": "disk full"}
        assert o.path is None

    def test_save_shell_kind(self, tmp_path: Path) -> None:
        """A populated shell draft saves and persists a shell command job."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_command_kind(d, "shell")
        controller.set_shell_executable(d, "/bin/zsh")
        o = controller.save(d)
        assert o.ok is True
        assert o.path is not None
        assert o.path.is_file()
        saved = world.services.resolve_managed_job(d.label)
        assert isinstance(saved.command, ShellCommand)

    def test_save_relative_shell_executable(self, tmp_path: Path) -> None:
        """A relative shell executable fails with a shell_executable error."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_command_kind(d, "shell")
        controller.set_shell_executable(d, "zsh")
        o = controller.save(d)
        assert o.ok is False
        assert o.fields == {"shell_executable": "the shell executable path must be absolute"}

    def test_save_executable_kind(self, tmp_path: Path) -> None:
        """A populated executable draft saves and persists an executable job."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_command_kind(d, "executable")
        controller.set_executable_path(d, "/usr/local/bin/backup")
        o = controller.save(d)
        assert o.ok is True
        assert o.path is not None
        assert o.path.is_file()
        saved = world.services.resolve_managed_job(d.label)
        assert isinstance(saved.command, ExecutableCommand)

    def test_save_relative_executable(self, tmp_path: Path) -> None:
        """A relative executable path fails with an executable error."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_command_kind(d, "executable")
        controller.set_executable_path(d, "backup")
        o = controller.save(d)
        assert o.ok is False
        assert o.fields == {"executable": "the executable path must be absolute"}

    def test_save_blank_environment_key(self, tmp_path: Path) -> None:
        """A blank environment key fails with an environment error."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.add_environment_row(d)
        o = controller.save(d)
        assert o.ok is False
        assert o.fields == {"environment": "environment variable names must not be empty"}

    def test_save_duplicate_environment_key(self, tmp_path: Path) -> None:
        """A duplicated environment key fails with an environment error."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.add_environment_row(d)
        controller.add_environment_row(d)
        controller.set_environment_key(d, 0, "PATH")
        controller.set_environment_key(d, 1, "PATH")
        o = controller.save(d)
        assert o.ok is False
        assert o.fields == {"environment": "duplicate environment variable: PATH"}

class TestFieldErrors:

    def test_command_type_loc(self, tmp_path: Path) -> None:
        """An unknown command type maps to the script fallback key."""
        world, controller = make_controller(tmp_path)
        data = make_job().model_dump()
        data["command"]["type"] = "bogus"
        with pytest.raises(ValidationError) as excinfo:
            JobDefinition.model_validate(data)
        result = controller._field_errors(excinfo.value)
        assert list(result) == ["script"]

    def test_command_executable_loc(self, tmp_path: Path) -> None:
        """A relative executable maps to the executable key in the command branch."""
        world, controller = make_controller(tmp_path)
        data = make_job(
            command=ExecutableCommand(executable="/usr/local/bin/backup", arguments=["--all"])
        ).model_dump()
        data["command"]["executable"] = "relative/bin"
        with pytest.raises(ValidationError) as excinfo:
            JobDefinition.model_validate(data)
        result = controller._field_errors(excinfo.value)
        assert list(result) == ["executable"]
        assert result["executable"]

    def test_schedule_time_loc(self, tmp_path: Path) -> None:
        """A malformed schedule time maps to the times key."""
        world, controller = make_controller(tmp_path)
        data = make_job().model_dump()
        data["schedule"]["times"] = ["garbage"]
        with pytest.raises(ValidationError) as excinfo:
            JobDefinition.model_validate(data)
        result = controller._field_errors(excinfo.value)
        assert list(result) == ["times"]

    def test_schedule_weekdays_loc(self, tmp_path: Path) -> None:
        """Empty schedule weekdays map to the weekdays key."""
        world, controller = make_controller(tmp_path)
        data = make_job().model_dump()
        data["schedule"]["weekdays"] = []
        with pytest.raises(ValidationError) as excinfo:
            JobDefinition.model_validate(data)
        result = controller._field_errors(excinfo.value)
        assert list(result) == ["weekdays"]

    def test_schedule_seconds_loc(self, tmp_path: Path) -> None:
        """A sub-minimum interval seconds loc maps to the interval key."""
        world, controller = make_controller(tmp_path)
        data = make_job().model_dump()
        data["schedule"] = {"kind": "interval", "seconds": 30}
        with pytest.raises(ValidationError) as excinfo:
            JobDefinition.model_validate(data)
        result = controller._field_errors(excinfo.value)
        assert list(result) == ["interval"]

    def test_logging_nested_loc(self, tmp_path: Path) -> None:
        """A nested logging path error maps through the logging branch."""
        world, controller = make_controller(tmp_path)
        data = make_job().model_dump()
        data["logging"]["stdout_path"] = "relative/out.log"
        with pytest.raises(ValidationError) as excinfo:
            JobDefinition.model_validate(data)
        result = controller._field_errors(excinfo.value)
        assert list(result) == ["stdout_path"]

class TestBulkMutators:

    def test_set_arguments_shell_and_executable(self, tmp_path: Path) -> None:
        """set_arguments targets the right per-kind list."""
        world, controller = make_controller(tmp_path)
        d = controller.open_new()
        controller.set_arguments(d, "shell", ["-c", "true"])
        assert d.shell_arguments == ["-c", "true"]
        assert d.python_arguments == []
        controller.set_arguments(d, "executable", ["--verbose"])
        assert d.executable_arguments == ["--verbose"]
        assert d.shell_arguments == ["-c", "true"]
