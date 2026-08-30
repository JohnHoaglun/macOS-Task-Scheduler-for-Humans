"""Tests for the Qt-free editor controller."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

import pytest

from task_scheduler.application.job_service import JobNotFoundError, managed_label
from task_scheduler.domain import ExecutableCommand, LoggingConfig, ShellCommand
from task_scheduler.gui.controllers.editor_controller import EditorController
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
        assert d.time == ""
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
        controller.set_time(d, "07:30")
        assert d.time == "07:30"
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
        assert d.time == "07:30"
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
