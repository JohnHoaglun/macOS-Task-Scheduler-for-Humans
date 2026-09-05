"""Tests for the Qt-free editor controller."""

from __future__ import annotations

import sys
from datetime import time as Time
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from task_scheduler.application.job_service import JobNotFoundError, managed_label
from task_scheduler.domain import (
    CalendarSchedule,
    ExecutableCommand,
    IntervalSchedule,
    JobDefinition,
    LoggingConfig,
    ShellCommand,
    Weekday,
)
from task_scheduler.gui.controllers.editor_controller import EditorController, JobDraft
from task_scheduler.platform.macos import CandidateSource
from tests.conftest import make_job
from tests.fakes import FakeTaskWorld


def make_controller(tmp_path: Path) -> tuple[FakeTaskWorld, EditorController]:
    world = FakeTaskWorld(tmp_path)
    return world, EditorController(world.services)


class TestOpenNew:
    def test_open_new_defaults(self, tmp_path: Path) -> None:
        """A new draft carries a generated id and empty values."""
        world, controller = make_controller(tmp_path)
        d = controller.open_new()
        assert isinstance(d.job_id, UUID)
        assert d.name == ""
        assert d.label == ""
        assert d.label_touched is False
        assert d.enabled is True
        assert d.command_kind == "python"
        assert d.interpreter == ""
        assert d.script == ""
        assert d.python_arguments == []
        assert d.shell_executable == ""
        assert d.shell_arguments == []
        assert d.executable_path == ""
        assert d.executable_arguments == []
        assert d.times == [""]
        assert d.weekdays == set()
        assert d.working_directory == ""
        assert d.environment == []
        assert d.stdout_path == ""
        assert d.stderr_path == ""

    def test_open_new_ids_differ(self, tmp_path: Path) -> None:
        """Each new draft gets its own id."""
        world, controller = make_controller(tmp_path)
        first = controller.open_new()
        second = controller.open_new()
        assert first.job_id != second.job_id

    def test_open_new_times_default_is_fresh_per_draft(self, tmp_path: Path) -> None:
        """Each new draft gets its own single empty time, never a shared list."""
        world, controller = make_controller(tmp_path)
        first = controller.open_new()
        second = controller.open_new()
        assert first.times == [""]
        assert second.times == [""]
        assert first.times is not second.times
        first.times.append("07:30")
        assert second.times == [""]


class TestNameAndLabel:
    def test_set_name_derives_label(self, tmp_path: Path) -> None:
        """Setting the name derives a managed label from it."""
        world, controller = make_controller(tmp_path)
        d = controller.open_new()
        controller.set_name(d, "Daily Backup")
        assert d.label == managed_label("Daily Backup", d.job_id)

    def test_touched_label_survives_name_change(self, tmp_path: Path) -> None:
        """A user-touched label is kept when the name changes."""
        world, controller = make_controller(tmp_path)
        d = controller.open_new()
        controller.set_name(d, "A")
        controller.set_label(d, "custom.label-1")
        controller.set_name(d, "B")
        assert d.label == "custom.label-1"
        assert d.label_touched

    def test_blank_name_slug_is_task(self, tmp_path: Path) -> None:
        """A blank name falls back to the task slug."""
        world, controller = make_controller(tmp_path)
        d = controller.open_new()
        controller.set_name(d, "   ")
        assert d.label == f"io.github.macos-task-scheduler.user.task-{d.job_id.hex[:8]}"


class TestScriptWorkingDirectory:
    def test_set_script_fills_empty_working_directory(self, tmp_path: Path) -> None:
        """Setting a script fills an empty working directory from its parent."""
        world, controller = make_controller(tmp_path)
        d = controller.open_new()
        controller.set_script(d, "/Users/x/backup.py")
        assert d.working_directory == "/Users/x"

    def test_set_script_keeps_existing_working_directory(self, tmp_path: Path) -> None:
        """Setting a script never overwrites an existing working directory."""
        world, controller = make_controller(tmp_path)
        d = controller.open_new()
        controller.set_working_directory(d, "/Users/y")
        controller.set_script(d, "/Users/x/backup.py")
        assert d.working_directory == "/Users/y"


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

    def test_kinds_do_not_share_lists(self, tmp_path: Path) -> None:
        """Arguments for one kind never leak into another kind's list."""
        world, controller = make_controller(tmp_path)
        d = controller.open_new()
        controller.add_argument(d, "shell")
        assert d.python_arguments == []
        assert d.executable_arguments == []


class TestOtherMutators:
    def test_scalar_mutators(self, tmp_path: Path) -> None:
        """Scalar setters write directly onto the draft."""
        world, controller = make_controller(tmp_path)
        d = controller.open_new()
        controller.set_times(d, ["07:30"])
        assert d.times == ["07:30"]
        controller.set_weekdays(d, {"monday", "friday"})
        assert d.weekdays == {"monday", "friday"}
        controller.set_working_directory(d, "/tmp/x")
        assert d.working_directory == "/tmp/x"
        controller.set_stdout_path(d, "/tmp/o.log")
        assert d.stdout_path == "/tmp/o.log"
        controller.set_stderr_path(d, "/tmp/e.log")
        assert d.stderr_path == "/tmp/e.log"
        controller.set_interpreter(d, "/usr/bin/python3")
        assert d.interpreter == "/usr/bin/python3"
        controller.set_shell_executable(d, "/bin/zsh")
        assert d.shell_executable == "/bin/zsh"
        controller.set_executable_path(d, "/usr/bin/ls")
        assert d.executable_path == "/usr/bin/ls"
        controller.set_command_kind(d, "shell")
        assert d.command_kind == "shell"

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
    def test_round_trip_python_job(self, tmp_path: Path) -> None:
        """A persisted Python job round-trips into a fully populated draft."""
        world, controller = make_controller(tmp_path)
        job = make_job()
        d = controller.open_existing(job)
        assert d.job_id == job.id
        assert d.name == job.name
        assert d.label == job.label
        assert d.label_touched is True
        assert d.enabled is True
        assert d.command_kind == "python"
        assert d.interpreter == "/Users/example/project/.venv/bin/python"
        assert d.script == "/Users/example/project/main.py"
        assert d.python_arguments == ["--mode", "daily"]
        assert d.times == ["07:30"]
        assert d.weekdays == {"monday"}
        assert d.working_directory == ""
        assert d.environment == []
        assert d.stdout_path == ""
        assert d.stderr_path == ""

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

    def test_populated_paths(self, tmp_path: Path) -> None:
        """Persisted working directory and log paths land on the draft."""
        world, controller = make_controller(tmp_path)
        job = make_job(
            working_directory="/Users/me/scripts",
            logging=LoggingConfig(
                stdout_path=Path("/tmp/out.log"), stderr_path=Path("/tmp/err.log")
            ),
        )
        d = controller.open_existing(job)
        assert d.working_directory == "/Users/me/scripts"
        assert d.stdout_path == "/tmp/out.log"
        assert d.stderr_path == "/tmp/err.log"

    def test_disabled_job(self, tmp_path: Path) -> None:
        """A disabled job opens as a disabled draft."""
        world, controller = make_controller(tmp_path)
        job = make_job(enabled=False)
        d = controller.open_existing(job)
        assert d.enabled is False

    def test_multi_time_job_opens_in_canonical_order(self, tmp_path: Path) -> None:
        """A persisted multi-time job opens with every time in canonical HH:MM order."""
        world, controller = make_controller(tmp_path)
        job = make_job(
            schedule=CalendarSchedule(
                times=[Time(17, 30), Time(7, 30)], weekdays={Weekday.MONDAY, Weekday.FRIDAY}
            )
        )
        d = controller.open_existing(job)
        assert d.times == ["07:30", "17:30"]
        assert d.weekdays == {"monday", "friday"}

    def test_interval_job_opens_empty(self, tmp_path: Path) -> None:
        """An interval job opens with a single empty time and no weekdays."""
        world, controller = make_controller(tmp_path)
        job = make_job(schedule=IntervalSchedule(seconds=900))
        d = controller.open_existing(job)
        assert d.times == [""]
        assert d.weekdays == set()


class TestDelegation:
    def test_detect_python_returns_current_interpreter(self, tmp_path: Path) -> None:
        """detect_python delegates to the service and lists the current interpreter."""
        world, controller = make_controller(tmp_path)
        script = tmp_path / "run.py"
        script.write_text("print(1)\n")
        result = controller.detect_python(script)
        assert result.script == script
        current = [c for c in result.candidates if c.source is CandidateSource.CURRENT]
        assert current and current[0].path == Path(sys.executable)

    def test_resolve_returns_managed_job(self, tmp_path: Path) -> None:
        """resolve returns the saved managed job for its label."""
        world, controller = make_controller(tmp_path)
        job = make_job()
        world.services.save_managed_job(job)
        assert controller.resolve(job.label).id == job.id

    def test_resolve_unknown_raises(self, tmp_path: Path) -> None:
        """resolve raises JobNotFoundError for an unknown label."""
        world, controller = make_controller(tmp_path)
        with pytest.raises(JobNotFoundError):
            controller.resolve("io.github.macos-task-scheduler.user.nope")


def valid_draft(controller: EditorController, tmp_path: Path) -> JobDraft:
    draft = controller.open_new()
    controller.set_name(draft, "Editor Job")
    controller.set_interpreter(draft, "/usr/bin/python3")
    controller.set_script(draft, str(tmp_path / "job.py"))
    controller.set_times(draft, ["07:30"])
    controller.set_weekdays(draft, {"monday"})
    return draft


class TestValidate:
    def test_valid_draft(self, tmp_path: Path) -> None:
        """A fully populated draft validates cleanly."""
        world, controller = make_controller(tmp_path)
        o = controller.validate(valid_draft(controller, tmp_path))
        assert o.ok is True
        assert o.message == "Valid"
        assert o.fields == {}

    def test_missing_name(self, tmp_path: Path) -> None:
        """A draft without a name fails with a name field error."""
        world, controller = make_controller(tmp_path)
        d = controller.open_new()
        controller.set_interpreter(d, "/usr/bin/python3")
        controller.set_script(d, "/tmp/job.py")
        controller.set_times(d, ["07:30"])
        controller.set_weekdays(d, {"monday"})
        o = controller.validate(d)
        assert o.ok is False
        assert o.message == "Fix the highlighted fields."
        assert o.fields == {"name": "a job name is required"}

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

    def test_bad_time(self, tmp_path: Path) -> None:
        """An out-of-range time fails with the domain message on the times field."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_times(d, ["25:00"])
        o = controller.validate(d)
        assert o.fields == {"times": "schedule time out of range (00:00-23:59), got '25:00'"}

    def test_single_time_compat(self, tmp_path: Path) -> None:
        """A one-time draft builds a schedule with exactly one time."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        job = controller.build_job(d)
        assert isinstance(job.schedule, CalendarSchedule)
        assert job.schedule.times == [Time(7, 30)]

    def test_multi_time_unsorted_input_is_sorted(self, tmp_path: Path) -> None:
        """Times entered out of order come back sorted in the built job."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_times(d, ["17:30", "07:30"])
        job = controller.build_job(d)
        assert isinstance(job.schedule, CalendarSchedule)
        assert job.schedule.times == [Time(7, 30), Time(17, 30)]

    def test_duplicate_times_collapse(self, tmp_path: Path) -> None:
        """Duplicate times collapse to a single entry in the built job."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_times(d, ["07:30", "07:30"])
        job = controller.build_job(d)
        assert isinstance(job.schedule, CalendarSchedule)
        assert job.schedule.times == [Time(7, 30)]

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

    def test_whitespace_time_passed_verbatim(self, tmp_path: Path) -> None:
        """A padded time is stored verbatim and delegated to the domain untouched."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_times(d, [" 07:30 "])
        assert d.times == [" 07:30 "]
        o = controller.validate(d)
        assert o.ok is True
        job = controller.build_job(d)
        assert isinstance(job.schedule, CalendarSchedule)
        assert job.schedule.times == [Time(7, 30)]

    def test_no_weekdays(self, tmp_path: Path) -> None:
        """A draft with no weekdays fails validation."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_weekdays(d, set())
        o = controller.validate(d)
        assert o.fields == {"weekdays": "at least one weekday is required"}

    def test_relative_working_directory(self, tmp_path: Path) -> None:
        """A relative working directory fails validation."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_working_directory(d, "relative/dir")
        o = controller.validate(d)
        assert "working_directory" in o.fields and o.fields["working_directory"]

    def test_relative_stdout(self, tmp_path: Path) -> None:
        """A relative stdout path fails validation."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_stdout_path(d, "rel/out.log")
        o = controller.validate(d)
        assert "stdout_path" in o.fields and o.fields["stdout_path"]

    def test_invalid_label(self, tmp_path: Path) -> None:
        """A label with whitespace fails validation."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_label(d, "bad label")
        o = controller.validate(d)
        assert "label" in o.fields and o.fields["label"]

    def test_name_too_long(self, tmp_path: Path) -> None:
        """A name over the length limit fails validation."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.set_name(d, "x" * 150)
        o = controller.validate(d)
        assert "name" in o.fields and o.fields["name"]

    def test_invalid_weekday_value(self, tmp_path: Path) -> None:
        """An unknown weekday value fails as a whole-job error."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        d.weekdays = {"notaday"}
        o = controller.validate(d)
        assert list(o.fields) == ["job"] and "notaday" in o.fields["job"]


class TestPreview:
    def test_preview_ok(self, tmp_path: Path) -> None:
        """A valid draft renders a launchd plist containing its label."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        o = controller.preview(d)
        assert o.ok is True
        assert "<?xml" in o.xml
        assert d.label in o.xml

    def test_preview_invalid(self, tmp_path: Path) -> None:
        """An invalid draft produces no preview and a name field error."""
        world, controller = make_controller(tmp_path)
        d = controller.open_new()
        o = controller.preview(d)
        assert o.ok is False
        assert o.xml == ""
        assert o.fields == {"name": "a job name is required"}


class TestSave:
    def test_save_persists(self, tmp_path: Path) -> None:
        """A valid draft persists to the catalog and resolves by label."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        o = controller.save(d)
        assert o.ok is True
        assert o.label == d.label
        assert o.path is not None
        assert o.path == world.catalog_root / f"{d.job_id}.json"
        assert o.path.is_file()
        assert world.services.resolve_managed_job(d.label).id == d.job_id

    def test_save_rejects_invalid_draft(self, tmp_path: Path) -> None:
        """An empty draft fails with a name error before any catalog write."""
        world, controller = make_controller(tmp_path)
        d = controller.open_new()
        o = controller.save(d)
        assert o.ok is False
        assert o.fields == {"name": "a job name is required"}
        assert o.path is None
        assert o.label == ""

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

    def test_save_environment_rows(self, tmp_path: Path) -> None:
        """Environment rows persist onto the saved job definition."""
        world, controller = make_controller(tmp_path)
        d = valid_draft(controller, tmp_path)
        controller.add_environment_row(d)
        controller.set_environment_key(d, 0, "PATH")
        controller.set_environment_value(d, 0, "/usr/bin")
        o = controller.save(d)
        assert o.ok is True
        saved = world.services.resolve_managed_job(d.label)
        assert saved.environment.variables == {"PATH": "/usr/bin"}

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
    def test_command_interpreter_loc(self, tmp_path: Path) -> None:
        """A relative interpreter maps through the command branch to script."""
        world, controller = make_controller(tmp_path)
        data = make_job().model_dump()
        data["command"]["interpreter"] = "relative/path"
        with pytest.raises(ValidationError) as excinfo:
            JobDefinition.model_validate(data)
        result = controller._field_errors(excinfo.value)
        assert list(result) == ["script"]
        assert result["script"]

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

    def test_logging_nested_loc(self, tmp_path: Path) -> None:
        """A nested logging path error maps through the logging branch."""
        world, controller = make_controller(tmp_path)
        data = make_job().model_dump()
        data["logging"]["stdout_path"] = "relative/out.log"
        with pytest.raises(ValidationError) as excinfo:
            JobDefinition.model_validate(data)
        result = controller._field_errors(excinfo.value)
        assert list(result) == ["stdout_path"]

    def test_unmapped_loc_falls_back(self, tmp_path: Path) -> None:
        """An unmapped error location falls back to the job key."""
        world, controller = make_controller(tmp_path)
        data = make_job().model_dump()
        data["id"] = "not-a-uuid"
        with pytest.raises(ValidationError) as excinfo:
            JobDefinition.model_validate(data)
        result = controller._field_errors(excinfo.value)
        assert list(result) == ["job"]


class TestBulkMutators:
    def test_set_arguments_python(self, tmp_path: Path) -> None:
        """set_arguments replaces the python argument list."""
        world, controller = make_controller(tmp_path)
        d = controller.open_new()
        controller.set_arguments(d, "python", ["--mode", "full"])
        assert d.python_arguments == ["--mode", "full"]

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

    def test_set_arguments_does_not_alias_input(self, tmp_path: Path) -> None:
        """The draft stores a copy, not the caller's list."""
        world, controller = make_controller(tmp_path)
        d = controller.open_new()
        values = ["a"]
        controller.set_arguments(d, "python", values)
        values.append("mutated")
        assert d.python_arguments == ["a"]

    def test_set_environment_replaces(self, tmp_path: Path) -> None:
        """set_environment replaces all environment rows."""
        world, controller = make_controller(tmp_path)
        d = controller.open_new()
        controller.set_environment(d, [("HOME", "/tmp"), ("PATH", "/usr/bin")])
        assert d.environment == [("HOME", "/tmp"), ("PATH", "/usr/bin")]

    def test_set_environment_empty_clears(self, tmp_path: Path) -> None:
        """An empty row list clears the environment."""
        world, controller = make_controller(tmp_path)
        d = controller.open_new()
        controller.set_environment(d, [("A", "1")])
        controller.set_environment(d, [])
        assert d.environment == []
