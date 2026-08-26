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
