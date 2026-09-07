"""Tests for the discovery controller (pure Python, no Qt)."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn
from uuid import UUID

from tests.fakes import FakeTaskWorld

from conftest import make_job
from task_scheduler.application.task_command_service import (
    ListingKind,
)
from task_scheduler.gui.controllers.discovery_controller import DiscoveryController

EXTERNAL_ID = UUID("87654321-4321-4321-4321-432143214321")

class _BoomServices:
    def list_agents(self) -> NoReturn:
        raise RuntimeError("boom")

class _OutsideRootServices:
    def inspect_discovered(self, path: Path) -> NoReturn:
        raise ValueError("outside root")

class TestInspect:

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
        assert outcome.diagnostics == ()
