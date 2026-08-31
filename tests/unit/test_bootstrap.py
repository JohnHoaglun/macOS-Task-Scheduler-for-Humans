"""Tests for the shared production composition root (task_scheduler.bootstrap)."""

import os

import pytest

import task_scheduler.bootstrap as bootstrap
from task_scheduler.application import TaskCommandService
from task_scheduler.bootstrap import build_services, gui_environment
from task_scheduler.cli import app as cli_app


def test_cli_reuses_bootstrap_build_services() -> None:
    assert cli_app.build_services is bootstrap.build_services


def test_build_services_returns_task_command_service() -> None:
    assert isinstance(build_services(), TaskCommandService)


def test_gui_environment_snapshots_a_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MACTASK_GUI_PROBE", "visible")
    snapshot = gui_environment()
    assert snapshot["MACTASK_GUI_PROBE"] == "visible"
    snapshot["MACTASK_GUI_PROBE"] = "mutated"
    assert os.environ["MACTASK_GUI_PROBE"] == "visible"
