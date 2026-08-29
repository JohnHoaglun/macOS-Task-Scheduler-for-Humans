"""Discovery controller bridging the agent-discovery UI to TaskCommandService."""

from __future__ import annotations

from dataclasses import dataclass

from task_scheduler.application.task_command_service import (
    AgentListing,
    DiscoveredInspectReport,
    TaskCommandService,
)

__all__ = ["DiscoveryController", "InspectOutcome", "RefreshOutcome"]


@dataclass(frozen=True, slots=True)
class RefreshOutcome:
    """Result of a discovery refresh: the listings, or an error message."""

    agents: list[AgentListing] | None
    error: str | None


@dataclass(frozen=True, slots=True)
class InspectOutcome:
    """Result of a discovered-agent inspect: the report, or an error message."""

    report: DiscoveredInspectReport | None
    error: str | None


class DiscoveryController:
    """Bridges the discovery view to TaskCommandService without Qt imports."""

    def __init__(self, services: TaskCommandService) -> None:
        self._services = services

    def refresh(self) -> RefreshOutcome:
        """List discovered agents, converting any failure into an error string."""
        try:
            agents = self._services.list_agents()
        except Exception as exc:
            return RefreshOutcome(agents=None, error=str(exc))
        return RefreshOutcome(agents=agents, error=None)

    def inspect(self, agent: AgentListing) -> InspectOutcome:
        """Inspect one discovered plist, converting boundary errors to text."""
        try:
            report = self._services.inspect_discovered(agent.path)
        except (ValueError, OSError) as exc:
            return InspectOutcome(report=None, error=str(exc))
        return InspectOutcome(report=report, error=None)
