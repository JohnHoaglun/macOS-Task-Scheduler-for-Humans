"""Tests for the command models and discriminated union."""

import pytest
from pydantic import TypeAdapter, ValidationError

from task_scheduler.domain import (
    Command,
    PythonCommand,
    ShellCommand,
)

COMMAND_ADAPTER = TypeAdapter(Command)

INTERPRETER = "/Users/example/project/.venv/bin/python"
SCRIPT = "/Users/example/project/main.py"
SHELL = "/bin/zsh"
TOOL = "/opt/homebrew/bin/some-tool"

@pytest.mark.parametrize("field", ["interpreter", "script"])
def test_python_command_rejects_relative_path(field: str) -> None:
    kwargs = {"interpreter": "relative/python", "script": "relative/script.py"}
    kwargs[field] = f"also/{field}/relative"
    with pytest.raises(ValidationError):
        PythonCommand(**kwargs)  # type: ignore[arg-type]

def test_shell_command_rejects_relative_executable() -> None:
    with pytest.raises(ValidationError):
        ShellCommand(executable="bin/zsh")

