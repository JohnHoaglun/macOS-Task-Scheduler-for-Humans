"""Finder reveal adapter (Increment 22, spec §63).

Reveals an existing file in Finder via the absolute ``/usr/bin/open -R``
command. Every invocation goes through the injected :class:`ProcessRunner`;
no other layer reveals paths directly. GUI-only capability — there is no CLI
surface for it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from task_scheduler.platform.macos.process_runner import CommandSpec, ProcessRunner

__all__ = [
    "FINDER_OPEN_PATH",
    "FinderRevealer",
    "LocalFinderRevealer",
]

FINDER_OPEN_PATH = "/usr/bin/open"


class FinderRevealer(Protocol):
    """Port for revealing a path in Finder."""

    def reveal(self, path: Path) -> str | None:
        """Reveal *path*; return ``None`` on success or a failure message."""


class LocalFinderRevealer:
    """Reveal a path in Finder via ``/usr/bin/open -R`` (empty environment)."""

    def __init__(self, runner: ProcessRunner) -> None:
        self._runner = runner

    def reveal(self, path: Path) -> str | None:
        spec = CommandSpec(argv=[FINDER_OPEN_PATH, "-R", str(path)])
        result = self._runner.run(spec)
        if result.launch_failure is not None:
            return f"could not launch Finder reveal: {result.launch_failure.message}"
        if result.exit_code != 0:
            detail = result.stderr.strip()
            if detail:
                return f"Finder reveal failed (exit {result.exit_code}): {detail}"
            return f"Finder reveal failed (exit {result.exit_code})"
        return None
