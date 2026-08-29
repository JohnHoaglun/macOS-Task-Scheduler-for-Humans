"""Tests for the shared production composition root (task_scheduler.bootstrap)."""

import task_scheduler.bootstrap as bootstrap
from task_scheduler.application import TaskCommandService
from task_scheduler.bootstrap import build_services
from task_scheduler.cli import app as cli_app


def test_cli_reuses_bootstrap_build_services() -> None:
    assert cli_app.build_services is bootstrap.build_services


def test_build_services_returns_task_command_service() -> None:
    assert isinstance(build_services(), TaskCommandService)
