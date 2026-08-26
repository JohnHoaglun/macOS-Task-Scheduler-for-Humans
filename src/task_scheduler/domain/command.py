"""Command domain models: python, shell, and executable."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator


class PythonCommand(BaseModel):
    """Run a Python script with an explicit interpreter."""

    type: Literal["python"] = "python"
    interpreter: Path
    script: Path
    arguments: list[str] = Field(default_factory=list)

    @field_validator("interpreter", "script")
    @classmethod
    def _require_absolute_paths(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError(f"path must be absolute, got {value!r}")
        return value


class ShellCommand(BaseModel):
    """Run a shell executable (for example a script via /bin/zsh)."""

    type: Literal["shell"] = "shell"
    executable: Path
    arguments: list[str] = Field(default_factory=list)

    @field_validator("executable")
    @classmethod
    def _require_absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError(f"path must be absolute, got {value!r}")
        return value


class ExecutableCommand(BaseModel):
    """Run an arbitrary executable with arguments."""

    type: Literal["executable"] = "executable"
    executable: Path
    arguments: list[str] = Field(default_factory=list)

    @field_validator("executable")
    @classmethod
    def _require_absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError(f"path must be absolute, got {value!r}")
        return value


Command = Annotated[
    PythonCommand | ShellCommand | ExecutableCommand,
    Field(discriminator="type"),
]


def command_argv(command: Command) -> list[str]:
    """Flatten *command* into the argv launchd (and direct tests) execute.

    The single source of truth for argv construction, shared by the plist
    codec and the direct-test service so the two can never diverge.
    """
    if isinstance(command, PythonCommand):
        return [str(command.interpreter), str(command.script), *command.arguments]
    if isinstance(command, ShellCommand):
        return [str(command.executable), *command.arguments]
    return [str(command.executable), *command.arguments]
