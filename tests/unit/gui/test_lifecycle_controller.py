"""Tests for the lifecycle controller (pure Python, no Qt)."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn
from uuid import UUID

import pytest

from conftest import make_job
from task_scheduler.application.task_command_service import (
    InstallResult,
    ListingKind,
    TaskListing,
    UninstallResult,
)
from task_scheduler.gui.controllers.lifecycle_controller import (
    LifecycleAction,
    LifecycleController,
    RequestVerdict,
)
from task_scheduler.platform.macos import LaunchctlResult
from tests.fakes import FakeTaskWorld

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


class TestEnabledActions:
    def test_saved_row_offers_install_only(self, tmp_path: Path) -> None:
        world, listing = _saved_world(tmp_path)
        assert listing.kind is ListingKind.SAVED
        controller = LifecycleController(world.services)
        assert controller.enabled_actions(listing) == frozenset({LifecycleAction.INSTALL})

    def test_installed_managed_row_offers_the_other_five(self, tmp_path: Path) -> None:
        world, listing = _managed_world(tmp_path)
        assert listing.kind is ListingKind.DISCOVERED
        controller = LifecycleController(world.services)
        assert controller.enabled_actions(listing) == INSTALLED_ACTIONS

    def test_external_row_offers_nothing(self, tmp_path: Path) -> None:
        world, listing = _external_world(tmp_path)
        assert listing.managed is False
        controller = LifecycleController(world.services)
        assert controller.enabled_actions(listing) == frozenset()

    def test_none_selection_offers_nothing(self, tmp_path: Path) -> None:
        world, _ = _managed_world(tmp_path)
        controller = LifecycleController(world.services)
        assert controller.enabled_actions(None) == frozenset()

    def test_managed_flag_without_job_offers_nothing(self, tmp_path: Path) -> None:
        world, _ = _managed_world(tmp_path)
        controller = LifecycleController(world.services)
        listing = TaskListing(
            kind=ListingKind.DISCOVERED, path=None, parsed=None, job=None, managed=True
        )
        assert controller.enabled_actions(listing) == frozenset()


class TestRequest:
    def test_accepts_install_for_saved_row(self, tmp_path: Path) -> None:
        world, listing = _saved_world(tmp_path)
        controller = LifecycleController(world.services)
        assert controller.request(LifecycleAction.INSTALL, listing) is RequestVerdict.ACCEPTED
        assert controller.busy

    def test_accepts_uninstall_for_installed_row(self, tmp_path: Path) -> None:
        world, listing = _managed_world(tmp_path)
        controller = LifecycleController(world.services)
        assert (
            controller.request(LifecycleAction.UNINSTALL, listing)
            is RequestVerdict.ACCEPTED
        )

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

    def test_refuses_none_selection(self, tmp_path: Path) -> None:
        world, _ = _managed_world(tmp_path)
        controller = LifecycleController(world.services)
        assert controller.request(LifecycleAction.INSTALL, None) is RequestVerdict.NOT_MANAGED

    def test_refuses_action_not_allowed_for_row(self, tmp_path: Path) -> None:
        world, saved = _saved_world(tmp_path)
        controller = LifecycleController(world.services)
        assert (
            controller.request(LifecycleAction.UNINSTALL, saved)
            is RequestVerdict.NOT_ALLOWED
        )
        managed = make_job()
        world.manage(managed)
        installed = [listing for listing in world.services.list_agents()
                     if listing.kind is ListingKind.DISCOVERED][0]
        assert controller.request(LifecycleAction.INSTALL, installed) is RequestVerdict.NOT_ALLOWED


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

    def test_reinstall_runs_bootout_then_bootstrap(self, tmp_path: Path) -> None:
        world, listing = _managed_world(tmp_path)
        controller = LifecycleController(world.services)
        controller.request(LifecycleAction.REINSTALL, listing)
        outcome = controller.execute()
        assert outcome.error is None
        assert isinstance(outcome.result, InstallResult)
        assert [phase.name for phase in outcome.result.phases] == ["bootout", "bootstrap"]
        assert outcome.result.completed_phases == ("bootout", "bootstrap")
        assert outcome.result.retained_artifacts == ()

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

    def test_unexpected_error_becomes_error_outcome(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world, listing = _managed_world(tmp_path)

        def boom(label: str) -> NoReturn:
            raise RuntimeError("boom")

        monkeypatch.setattr(world.services, "enable", boom)
        controller = LifecycleController(world.services)
        controller.request(LifecycleAction.ENABLE, listing)
        outcome = controller.execute()
        assert outcome.error == "boom"
        assert outcome.result is None
        controller.finish()
        assert not controller.busy
