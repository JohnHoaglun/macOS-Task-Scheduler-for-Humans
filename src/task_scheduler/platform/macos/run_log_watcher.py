"""Run-log observation: parse the wrapper's START/STOP records and await a new run.

The launchd run wrapper (``run_wrapper``) appends a ``START`` line and a
matching ``STOP`` line to a job's canonical run log for every run, each stamped
with a unique ``run`` id. This module turns that append-only log into an
observable signal: handed the run ids already present, it polls until a
``STOP`` line carrying a *new* id appears (the run a fresh ``kickstart``
started) and reports that run's exit code, duration, and status.

Pure file/regex work — no launchctl, no subprocess. A clock and a sleeper are
injected so the wait is unit-testable without real delays.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from task_scheduler.platform.macos.run_wrapper import (
    default_job_logs_root,
    run_log_path,
)

__all__ = ["RunLogWatcher", "RunObservation"]

# A STOP record: "=== STOP  <ts> run=<id> exit=<n> duration=<x>s status=<s> ==="
_STOP_RE = re.compile(
    r"^===\s+STOP\s+(?P<ts>\S+)\s+run=(?P<run_id>\S+)\s+"
    r"exit=(?P<exit>-?\d+)\s+duration=(?P<duration>\d+(?:\.\d+)?)s\s+"
    r"status=(?P<status>\S+)\s+==="
)
# Any START/STOP record, to harvest its run id: "=== <KIND> <ts> run=<id> ..."
_RUN_ID_RE = re.compile(r"^===\s+(?:START|STOP)\s+\S+\s+run=(?P<run_id>\S+)")


@dataclass(frozen=True, slots=True)
class RunObservation:
    """One completed run parsed from a STOP record in the canonical run log."""

    run_id: str
    exit_code: int
    duration_seconds: float
    status: str
    stopped_at: str


class RunLogWatcher:
    """Watch a job's canonical run log for the completion of a new run.

    ``known_run_ids`` harvests the ids already recorded so a caller can take a
    baseline before kicking a job; ``wait_for_new_stop`` then polls until a STOP
    record with an id outside that baseline appears, or the timeout elapses.
    """

    def __init__(self, *, job_logs_root: Path | None = None) -> None:
        self._root = job_logs_root if job_logs_root is not None else default_job_logs_root()

    def run_log_path(self, label: str) -> Path:
        """The canonical run record for *label* (``jobs/<label>/run.log``)."""
        return run_log_path(label, self._root)

    def known_run_ids(self, label: str) -> frozenset[str]:
        """Every run id already present in the run log; empty when absent."""
        ids: set[str] = set()
        for line in self._read_lines(self.run_log_path(label)):
            match = _RUN_ID_RE.match(line)
            if match is not None:
                ids.add(match.group("run_id"))
        return frozenset(ids)

    def wait_for_new_stop(
        self,
        label: str,
        known: frozenset[str],
        *,
        timeout: float,
        poll_interval: float,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> RunObservation | None:
        """Poll until a STOP record with a *new* run id appears, else ``None``.

        *now*/*sleep* are injectable so tests drive the deadline without
        blocking. Returns as soon as the new run's STOP line is observed.
        """
        deadline = now() + timeout
        path = self.run_log_path(label)
        while True:
            observed = self._find_new_stop(path, known)
            if observed is not None:
                return observed
            remaining = deadline - now()
            if remaining <= 0:
                return None
            sleep(min(poll_interval, remaining))

    def _find_new_stop(self, path: Path, known: frozenset[str]) -> RunObservation | None:
        for line in self._read_lines(path):
            match = _STOP_RE.match(line)
            if match is None:
                continue
            run_id = match.group("run_id")
            if run_id in known:
                continue
            return RunObservation(
                run_id=run_id,
                exit_code=int(match.group("exit")),
                duration_seconds=float(match.group("duration")),
                status=match.group("status"),
                stopped_at=match.group("ts"),
            )
        return None

    @staticmethod
    def _read_lines(path: Path) -> list[str]:
        try:
            return path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
