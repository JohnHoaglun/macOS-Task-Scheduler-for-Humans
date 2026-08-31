"""Production composition root shared by the CLI and GUI entry points.

This is the only place that constructs the real platform adapters (store,
backend, subprocess runner, catalog repository, codec). Both the CLI and the
GUI build their single :class:`TaskCommandService` through
:func:`build_services` rather than wiring adapters themselves.
"""

from __future__ import annotations

import os

from task_scheduler.application import TaskCommandService
from task_scheduler.application.job_service import JobService
from task_scheduler.application.log_service import LogService
from task_scheduler.application.test_service import DirectTestService
from task_scheduler.platform.macos import (
    LaunchAgentBackend,
    LaunchAgentStore,
    PlistCodec,
    SubprocessRunner,
)
from task_scheduler.storage import JsonJobRepository

__all__ = ["build_services", "gui_environment"]


def build_services() -> TaskCommandService:
    """Construct the production application services (the only real wiring)."""
    store = LaunchAgentStore()
    return TaskCommandService(
        repository=JsonJobRepository(),
        jobs=JobService(),
        store=store,
        backend=LaunchAgentBackend(store, SubprocessRunner()),
        codec=PlistCodec(),
        test=DirectTestService(SubprocessRunner()),
        logs=LogService(),
    )


def gui_environment() -> dict[str, str]:
    """A copy of the GUI process environment, for presentation-safe comparison.

    The GUI itself never reads ``os.environ``; the composition layer takes
    the snapshot and hands it to the diagnostics controller.
    """
    return dict(os.environ)
