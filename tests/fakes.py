"""Reusable test fakes for process execution and time."""

from __future__ import annotations

from task_scheduler.platform.macos import CommandSpec, ProcessResult


class FakeClock:
    """Deterministic monotonic clock.

    Each call returns the current time and then advances by ``step``, so a
    two-sample measurement (start/stop) spans exactly one step.
    """

    def __init__(self, start: float = 1000.0, step: float = 0.0) -> None:
        self._now = start
        self._step = step
        self.calls = 0

    def __call__(self) -> float:
        result = self._now
        self.calls += 1
        self._now += self._step
        return result

    def advance(self, seconds: float) -> None:
        self._now += seconds


class FakeProcessRunner:
    """Scripted ProcessRunner: records every spec, returns the scripted result."""

    def __init__(self, result: ProcessResult) -> None:
        self._result = result
        self.specs: list[CommandSpec] = []

    def run(self, spec: CommandSpec) -> ProcessResult:
        self.specs.append(spec)
        return self._result
