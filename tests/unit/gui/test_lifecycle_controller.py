"""Tests for the lifecycle controller (pure Python, no Qt)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from tests.fakes import FakeTaskWorld

from conftest import make_job
from task_scheduler.application.task_command_service import (
    InstallResult,
    TaskListing,
    UninstallResult,
)
from task_scheduler.gui.controllers.lifecycle_controller import (
    LifecycleAction,
    LifecycleController,
    RequestVerdict,
)
from task_scheduler.platform.macos import LaunchctlResult

EXTERNAL_ID = UUID("87654321-4321-4321-4321-432143214321")
SAVED_LABEL = "com.example.saved-only"
JOB_LABEL = "io.github.macos-task-scheduler.user.daily-backup"
INSTALLED_ACTIONS = frozenset(
    {
        LifecycleAction.REINSTALL,
        LifecycleAction.UNINSTALL,
        LifecycleAction.ENABLE,
        LifecycleAction.DISABLE,
        LifecycleAction.RUN_NOW,
    }
)

def _saved_world(tmp_path: Path) -> tuple[FakeTaskWorld, TaskListing]:
    world = FakeTaskWorld(tmp_path)
    world.jobs.import_job(make_job(id=EXTERNAL_ID, label=SAVED_LABEL, name="Saved Job"))
    return world, world.services.list_agents()[0]

def _managed_world(tmp_path: Path) -> tuple[FakeTaskWorld, TaskListing]:
    world = FakeTaskWorld(tmp_path)
    world.manage(make_job())
    return world, world.services.list_agents()[0]

def _external_world(tmp_path: Path) -> tuple[FakeTaskWorld, TaskListing]:
    world = FakeTaskWorld(tmp_path)
    world.store.write(
        make_job(id=EXTERNAL_ID, label="com.example.external", name="External Job")
    )
    return world, world.services.list_agents()[0]

class TestRequest:

    def test_refuses_second_request_while_busy(self, tmp_path: Path) -> None:
        world, listing = _managed_world(tmp_path)
        controller = LifecycleController(world.services)
        assert (
            controller.request(LifecycleAction.UNINSTALL, listing)
            is RequestVerdict.ACCEPTED
        )
        assert controller.request(LifecycleAction.ENABLE, listing) is RequestVerdict.BUSY

    def test_refuses_unmanaged_target(self, tmp_path: Path) -> None:
        world, listing = _external_world(tmp_path)
        controller = LifecycleController(world.services)
        assert (
            controller.request(LifecycleAction.UNINSTALL, listing)
            is RequestVerdict.NOT_MANAGED
        )
        assert not controller.busy

class TestExecute:
    def test_install_deploys_and_bootstraps(self, tmp_path: Path) -> None:
        world, listing = _saved_world(tmp_path)
        controller = LifecycleController(world.services)
        controller.request(LifecycleAction.INSTALL, listing)
        outcome = controller.execute()
        assert outcome.error is None
        assert isinstance(outcome.result, InstallResult)
        assert outcome.result.process.exit_code == 0
        assert outcome.result.plist_path == world.la_root / f"{SAVED_LABEL}.plist"
        assert (world.la_root / f"{SAVED_LABEL}.plist").is_file()
        assert [spec.argv[1] for spec in world.launch_runner.specs] == ["bootstrap"]

    def test_uninstall_removes_plist_and_catalog_record(self, tmp_path: Path) -> None:
        world, listing = _managed_world(tmp_path)
        controller = LifecycleController(world.services)
        controller.request(LifecycleAction.UNINSTALL, listing)
        outcome = controller.execute()
        assert isinstance(outcome.result, UninstallResult)
        assert outcome.result.catalog_removed is True
        assert not (world.la_root / f"{JOB_LABEL}.plist").exists()
        assert world.services.list_agents() == []

    @pytest.mark.parametrize(
        "action",
        [LifecycleAction.ENABLE, LifecycleAction.DISABLE, LifecycleAction.RUN_NOW],
    )
    def test_launchctl_actions_return_launchctl_result(
        self, tmp_path: Path, action: LifecycleAction
    ) -> None:
        world, listing = _managed_world(tmp_path)
        controller = LifecycleController(world.services)
        assert controller.request(action, listing) is RequestVerdict.ACCEPTED
        outcome = controller.execute()
        assert outcome.error is None
        assert isinstance(outcome.result, LaunchctlResult)
        assert outcome.result.process.exit_code == 0

    def test_reinstall_after_catalog_removal_reports_error(self, tmp_path: Path) -> None:
        world, listing = _managed_world(tmp_path)
        assert listing.job is not None
        controller = LifecycleController(world.services)
        controller.request(LifecycleAction.REINSTALL, listing)
        world.jobs.remove(listing.job.id)
        outcome = controller.execute()
        assert outcome.result is None
        assert "no managed job" in (outcome.error or "")
