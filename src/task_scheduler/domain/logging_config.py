"""Log output configuration for scheduled jobs."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, field_validator


class LoggingConfig(BaseModel):
    """Optional stdout/stderr capture paths.

    Paths are not created and no directories are managed here.
    """

    stdout_path: Path | None = None
    stderr_path: Path | None = None

    @field_validator("stdout_path", "stderr_path")
    @classmethod
    def _require_absolute_paths(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError(f"path must be absolute, got {value!r}")
        return value
