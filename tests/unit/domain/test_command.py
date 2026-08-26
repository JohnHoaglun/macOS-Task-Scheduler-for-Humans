"""Tests for the command models and discriminated union."""

import pytest
from pydantic import TypeAdapter, ValidationError

from task_scheduler.domain import (
    Command,
    ExecutableCommand,
    PythonCommand,
    ShellCommand,
)

COMMAND_ADAPTER = TypeAdapter(Command)

INTERPRETER = "/Users/example/project/.venv/bin/python"
SCRIPT = "/Users/example/project/main.py"
SHELL = "/bin/zsh"
TOOL = "/opt/homebrew/bin/some-tool"


def test_python_command_valid() -> None:
    cmd = PythonCommand(interpreter=INTERPRETER, script=SCRIPT, arguments=["--mode", "daily"])
    assert cmd.interpreter.as_posix() == INTERPRETER
    assert cmd.script.as_posix() == SCRIPT
    assert cmd.arguments == ["--mode", "daily"]


def test_python_command_arguments_default_empty() -> None:
    cmd = PythonCommand(interpreter=INTERPRETER, script=SCRIPT)
    assert cmd.arguments == []


@pytest.mark.parametrize("field", ["interpreter", "script"])
def test_python_command_rejects_relative_path(field: str) -> None:
    kwargs = {"interpreter": "relative/python", "script": "relative/script.py"}
    kwargs[field] = f"also/{field}/relative"
    with pytest.raises(ValidationError):
        PythonCommand(**kwargs)  # type: ignore[arg-type]


def test_shell_command_valid() -> None:
    cmd = ShellCommand(executable=SHELL, arguments=["/Users/example/scripts/backup.sh"])
    assert cmd.executable.as_posix() == SHELL
    assert cmd.arguments == ["/Users/example/scripts/backup.sh"]


def test_shell_command_rejects_relative_executable() -> None:
    with pytest.raises(ValidationError):
        ShellCommand(executable="bin/zsh")


def test_executable_command_valid() -> None:
    cmd = ExecutableCommand(executable=TOOL, arguments=["--sync"])
    assert cmd.executable.as_posix() == TOOL
    assert cmd.arguments == ["--sync"]


def test_executable_command_rejects_relative_executable() -> None:
    with pytest.raises(ValidationError):
        ExecutableCommand(executable="some-tool")


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {
                "type": "python",
                "interpreter": INTERPRETER,
                "script": SCRIPT,
                "arguments": [],
            },
            PythonCommand,
        ),
        ({"type": "shell", "executable": SHELL, "arguments": []}, ShellCommand),
        ({"type": "executable", "executable": TOOL, "arguments": []}, ExecutableCommand),
    ],
)
def test_union_discriminates_command_types(payload: dict[str, object], expected: type) -> None:
    assert isinstance(COMMAND_ADAPTER.validate_python(payload), expected)


def test_union_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        COMMAND_ADAPTER.validate_python({"type": "cron", "executable": TOOL})
