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
from task_scheduler.application.run_wrapper_deploy import ensure_run_wrapper
from task_scheduler.application.test_service import DirectTestService
from task_scheduler.platform.macos import (
    LaunchAgentBackend,
    LaunchAgentStore,
    LocalFinderRevealer,
    PlistCodec,
    SubprocessRunner,
)
from task_scheduler.storage import (
    ExecutionHistoryRepository,
    JsonJobRepository,
    default_history_path,
)

__all__ = ["build_services", "gui_environment"]


def build_services() -> TaskCommandService:
    """Construct the production application services (the only real wiring).

    The run wrapper is deployed to its stable local path first: every
    managed plist the codec emits runs the job command through it, giving
    every launchd run a guaranteed local start/stop record and letting the
    user's configured log paths live on network volumes.
    """
    store = LaunchAgentStore()
    try:
        wrapper_path = ensure_run_wrapper()
    except OSError:
        wrapper_path = None
    return TaskCommandService(
        repository=JsonJobRepository(),
        jobs=JobService(),
        store=store,
        backend=LaunchAgentBackend(store, SubprocessRunner()),
        codec=PlistCodec(wrapper_path=wrapper_path),
        test=DirectTestService(SubprocessRunner()),
        logs=LogService(),
        history=ExecutionHistoryRepository(default_history_path()),
        finder=LocalFinderRevealer(SubprocessRunner()),
    )


def gui_environment() -> dict[str, str]:
    """A copy of the GUI process environment, for presentation-safe comparison.

    The GUI itself never reads ``os.environ``; the composition layer takes
    the snapshot and hands it to the diagnostics controller.
    """
    return dict(os.environ)
