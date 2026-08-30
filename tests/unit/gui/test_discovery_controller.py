"""Tests for the discovery controller (pure Python, no Qt)."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn
from uuid import UUID

from conftest import make_job
from task_scheduler.application.task_command_service import ListingKind
from task_scheduler.gui.controllers.discovery_controller import DiscoveryController
from tests.fakes import FakeTaskWorld

EXTERNAL_ID = UUID("87654321-4321-4321-4321-432143214321")


class _BoomServices:
    def list_agents(self) -> NoReturn:
        raise RuntimeError("boom")


class _OutsideRootServices:
    def inspect_discovered(self, path: Path) -> NoReturn:
        raise ValueError("outside root")


class TestRefresh:
    def test_lists_managed_and_external_agents(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        managed = make_job()
        world.manage(managed)
        external = make_job(
            id=EXTERNAL_ID, label="com.example.external", name="External Job"
        )
        world.store.write(external)
        controller = DiscoveryController(world.services)
        outcome = controller.refresh()
        assert outcome.error is None
        assert outcome.agents is not None
        discovered = [agent for agent in outcome.agents if agent.path is not None]
        by_name = {agent.path.name: agent for agent in discovered}
        assert len(discovered) == 2
        assert by_name[f"{managed.label}.plist"].managed is True
        assert by_name[f"{external.label}.plist"].managed is False

    def test_saved_only_jobs_follow_discovered_rows(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        managed = make_job()
        world.manage(managed)
        saved = make_job(
            id=EXTERNAL_ID, label="com.example.saved-only", name="Saved Job"
        )
        world.jobs.import_job(saved)
        controller = DiscoveryController(world.services)
        outcome = controller.refresh()
        assert outcome.error is None
        assert outcome.agents is not None
        assert [agent.kind for agent in outcome.agents] == [
            ListingKind.DISCOVERED,
            ListingKind.SAVED,
        ]
        saved_row = outcome.agents[-1]
        assert saved_row.path is None
        assert saved_row.parsed is None
        assert saved_row.job is not None
        assert saved_row.job.label == "com.example.saved-only"
        assert saved_row.managed is True

    def test_reports_service_failure(self) -> None:
        controller = DiscoveryController(_BoomServices())
        outcome = controller.refresh()
        assert outcome.agents is None
        assert outcome.error == "boom"


class TestInspect:
    def test_managed_listing_reports_managed(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)
        controller = DiscoveryController(world.services)
        listing = next(
            agent for agent in world.services.list_agents() if agent.managed
        )
        outcome = controller.inspect(listing)
        assert outcome.error is None
        assert outcome.report is not None
        assert outcome.report.path == listing.path
        assert outcome.report.managed is True

    def test_reports_boundary_error(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        world.manage(make_job())
        listing = next(
            agent for agent in world.services.list_agents() if agent.managed
        )
        controller = DiscoveryController(_OutsideRootServices())
        outcome = controller.inspect(listing)
        assert outcome.report is None
        assert outcome.error == "outside root"

    def test_inspect_saved_listing_is_a_noop(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        saved = make_job(id=EXTERNAL_ID, label="com.example.saved-only", name="Saved Job")
        world.jobs.import_job(saved)
        controller = DiscoveryController(world.services)
        listing = next(
            agent for agent in world.services.list_agents() if agent.kind is ListingKind.SAVED
        )
        outcome = controller.inspect(listing)
        assert outcome.report is None
        assert outcome.error is None
