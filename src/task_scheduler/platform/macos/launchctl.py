"""launchctl adapter: user-domain LaunchAgent lifecycle (Increment 7).

Implements ``install``, ``uninstall``, ``status``, ``enable``, ``disable``,
and ``trigger`` (spec lines 1833–1852). Every command goes through the
injected :class:`ProcessRunner`; every plist path is derived from the
:class:`LaunchAgentStore`. User ``gui/<uid>`` domain only — never
``/Library``, never system domains, never LaunchDaemons.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

from task_scheduler.domain import JobDefinition
from task_scheduler.platform.macos.launch_agent_store import (
    LaunchAgentStore,
    validate_label,
)
from task_scheduler.platform.macos.process_runner import (
    CommandSpec,
    ProcessResult,
    ProcessRunner,
)

__all__ = [
    "LAUNCHCTL_PATH",
    "LaunchAgentBackend",
    "LaunchAgentStatus",
    "LaunchctlAction",
    "LaunchctlResult",
]

LAUNCHCTL_PATH = "/bin/launchctl"


class LaunchctlAction(StrEnum):
    """The six lifecycle operations this adapter performs."""

    INSTALL = "install"
    UNINSTALL = "uninstall"
    STATUS = "status"
    ENABLE = "enable"
    DISABLE = "disable"
    TRIGGER = "trigger"


@dataclass(frozen=True, slots=True)
class LaunchctlResult:
    """Outcome of a lifecycle operation, preserving the exact process result."""

    action: LaunchctlAction
    process: ProcessResult


@dataclass(frozen=True, slots=True)
class LaunchAgentStatus:
    """Whether a label is loaded in launchd, with the raw process result.

    ``loaded`` is ``None`` (unknown) when the ``print`` process never
    launched; a launch failure is never reported as unloaded.
    """

    loaded: bool | None
    process: ProcessResult


class LaunchAgentBackend:
    """User LaunchAgent lifecycle: storage plus launchctl coordination.

    ``install(job)`` writes the managed plist and then bootstraps it; on a
    failed bootstrap the plist is retained for diagnosis. ``uninstall(label)``
    boots the service out first and removes the plist only when the bootout
    completed successfully. No operation mutates ``JobDefinition.enabled``.
    """

    def __init__(
        self,
        store: LaunchAgentStore,
        runner: ProcessRunner,
        *,
        uid: int | None = None,
    ) -> None:
        self._store = store
        self._runner = runner
        self._uid = uid if uid is not None else os.getuid()

    @property
    def domain(self) -> str:
        """The launchd domain string for this backend (``gui/<uid>``)."""
        return f"gui/{self._uid}"

    def install(self, job: JobDefinition) -> LaunchctlResult:
        """Write the job's plist (create-only) and bootstrap it into launchd."""
        self._store.write(job)
        return self.bootstrap(job.label)

    def uninstall(self, label: str) -> LaunchctlResult:
        """Boot the label out, then remove its plist only on success.

        A failed bootout retains the plist so the caller can diagnose or
        retry; the returned result is always the bootout's.
        """
        booted_out = self.bootout(label)
        if booted_out.process.exit_code == 0:
            self._store.remove(label)
        return booted_out

    def bootout(self, label: str) -> LaunchctlResult:
        """Boot the label out of launchd (``bootout``); no plist is touched."""
        validate_label(label)
        return self._run(LaunchctlAction.UNINSTALL, "bootout", self._target(label))

    def bootstrap(self, label: str) -> LaunchctlResult:
        """Bootstrap the label's deployed plist into launchd (``bootstrap``)."""
        validate_label(label)
        return self._run(
            LaunchctlAction.INSTALL,
            "bootstrap",
            self.domain,
            str(self._store.destination_for(label)),
        )

    def status(self, label: str) -> LaunchAgentStatus:
        """Report whether the label is loaded (``print`` exit 0)."""
        validate_label(label)
        result = self._run(LaunchctlAction.STATUS, "print", self._target(label))
        exit_code = result.process.exit_code
        if exit_code is None:
            loaded: bool | None = None
        else:
            loaded = exit_code == 0
        return LaunchAgentStatus(loaded=loaded, process=result.process)

    def enable(self, label: str) -> LaunchctlResult:
        """Re-enable a previously disabled service (``enable``)."""
        validate_label(label)
        return self._run(LaunchctlAction.ENABLE, "enable", self._target(label))

    def disable(self, label: str) -> LaunchctlResult:
        """Disable a service (``disable``); it stays loaded until uninstalled."""
        validate_label(label)
        return self._run(LaunchctlAction.DISABLE, "disable", self._target(label))

    def trigger(self, label: str) -> LaunchctlResult:
        """Ask launchd to run the job now (``kickstart -k``)."""
        validate_label(label)
        return self._run(LaunchctlAction.TRIGGER, "kickstart", "-k", self._target(label))

    def _target(self, label: str) -> str:
        return f"{self.domain}/{label}"

    def _run(self, action: LaunchctlAction, *arguments: str) -> LaunchctlResult:
        # Absolute launchctl path + empty environment on purpose: the child
        # inherits nothing (exact launchd-style semantics), and /bin/launchctl
        # needs no PATH of its own.
        spec = CommandSpec(argv=[LAUNCHCTL_PATH, *arguments])
        return LaunchctlResult(action=action, process=self._runner.run(spec))
