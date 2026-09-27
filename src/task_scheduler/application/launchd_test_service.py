"""LaunchD task testing (Mode B): kick a saved job and verify the real run.

Where the direct test (Mode A) runs a job's command in a child process, the
LaunchD test asks launchd itself to run an already-installed job via
``kickstart -k`` and then confirms the run actually happened by watching the
wrapper's canonical run log for a fresh STOP record. A test passes only when a
new run is observed *and* it exited 0.

The kickstart (backend) and the observation (run-log watcher) are injected, and
a clock/sleeper are passed through so the wait is unit-testable. Nothing here
is persisted into the job.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from task_scheduler.platform.macos import LaunchAgentBackend, LaunchctlResult
from task_scheduler.platform.macos.run_log_watcher import RunLogWatcher, RunObservation

__all__ = ["DEFAULT_LAUNCHD_TEST_TIMEOUT", "LaunchdTestResult", "LaunchdTestService"]

DEFAULT_LAUNCHD_TEST_TIMEOUT = 180.0


@dataclass(frozen=True, slots=True)
class LaunchdTestResult:
    """Outcome of a LaunchD (Mode B) test of a saved job."""

    label: str
    kickstart: LaunchctlResult
    observed: bool
    timed_out: bool
    run: RunObservation | None
    passed: bool
    reason: str


class LaunchdTestService:
    """Kick a managed job through launchd and verify the run via its log."""

    def __init__(
        self,
        backend: LaunchAgentBackend,
        watcher: RunLogWatcher,
        *,
        poll_interval: float = 0.25,
    ) -> None:
        self._backend = backend
        self._watcher = watcher
        self._poll_interval = poll_interval

    def run(
        self,
        label: str,
        *,
        timeout: float = DEFAULT_LAUNCHD_TEST_TIMEOUT,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> LaunchdTestResult:
        """Kick *label* via launchd and wait for its run to complete in the log."""
        baseline = self._watcher.known_run_ids(label)
        kickstart = self._backend.trigger(label)
        if kickstart.process.exit_code != 0 or kickstart.process.launch_failure is not None:
            return LaunchdTestResult(
                label=label,
                kickstart=kickstart,
                observed=False,
                timed_out=False,
                run=None,
                passed=False,
                reason=f"kickstart rejected (launchctl exit {kickstart.process.exit_code})",
            )
        observed = self._watcher.wait_for_new_stop(
            label,
            baseline,
            timeout=timeout,
            poll_interval=self._poll_interval,
            now=now,
            sleep=sleep,
        )
        if observed is None:
            return LaunchdTestResult(
                label=label,
                kickstart=kickstart,
                observed=False,
                timed_out=True,
                run=None,
                passed=False,
                reason=f"no run observed within {timeout:g}s",
            )
        passed = observed.exit_code == 0
        detail = (
            f"run exited {observed.exit_code} in {observed.duration_seconds:.1f}s "
            f"({observed.status})"
        )
        return LaunchdTestResult(
            label=label,
            kickstart=kickstart,
            observed=True,
            timed_out=False,
            run=observed,
            passed=passed,
            reason=detail if passed else f"run failed: {detail}",
        )
