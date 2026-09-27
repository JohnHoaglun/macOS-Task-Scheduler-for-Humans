"""Tests for run-log observation (RunLogWatcher) used by the LaunchD test."""

from __future__ import annotations

from pathlib import Path

from task_scheduler.platform.macos.run_log_watcher import RunLogWatcher


def _stop_line(
    run_id: str, exit_code: int = 0, duration: float = 1.0, status: str = "exited"
) -> str:
    return (
        f"=== STOP  2026-01-01T00:00:00+00:00 run={run_id} exit={exit_code} "
        f"duration={duration:.1f}s status={status} ===\n"
    )

def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)

def _watcher(tmp_path: Path) -> RunLogWatcher:
    return RunLogWatcher(job_logs_root=tmp_path / "run-logs")

class TestRunLogWatcher:
    def test_known_run_ids_missing_file_is_empty(self, tmp_path: Path) -> None:
        watcher = _watcher(tmp_path)
        assert watcher.run_log_path("demo job") == (
            tmp_path / "run-logs" / "jobs" / "demo-job" / "run.log"
        )
        assert watcher.known_run_ids("demo") == frozenset()

    def test_known_run_ids_collects_ids(self, tmp_path: Path) -> None:
        watcher = _watcher(tmp_path)
        path = watcher.run_log_path("demo")
        _write(path, _stop_line("aaa", exit_code=1) + _stop_line("bbb"))
        assert watcher.known_run_ids("demo") == frozenset({"aaa", "bbb"})

    def test_wait_returns_new_stop_immediately(self, tmp_path: Path) -> None:
        watcher = _watcher(tmp_path)
        path = watcher.run_log_path("demo")
        _write(path, _stop_line("old", exit_code=1))
        baseline = watcher.known_run_ids("demo")
        _write(path, _stop_line("new", exit_code=0, duration=2.5))
        result = watcher.wait_for_new_stop(
            "demo", baseline, timeout=10.0, poll_interval=0.1,
            now=lambda: 0.0, sleep=lambda _s: None,
        )
        assert result is not None
        assert (result.run_id, result.exit_code, result.duration_seconds) == ("new", 0, 2.5)
        assert result.status == "exited" and result.stopped_at == "2026-01-01T00:00:00+00:00"

    def test_wait_skips_known_and_returns_later_new_run(self, tmp_path: Path) -> None:
        watcher = _watcher(tmp_path)
        path = watcher.run_log_path("demo")
        _write(path, _stop_line("first", exit_code=0))
        baseline = watcher.known_run_ids("demo")
        _write(path, _stop_line("second", exit_code=1))
        result = watcher.wait_for_new_stop(
            "demo", baseline, timeout=10.0, poll_interval=0.1,
            now=lambda: 0.0, sleep=lambda _s: None,
        )
        assert result is not None and result.run_id == "second" and result.exit_code == 1

    def test_wait_times_out_when_no_new_run(self, tmp_path: Path) -> None:
        watcher = _watcher(tmp_path)
        path = watcher.run_log_path("demo")
        _write(path, _stop_line("known", exit_code=0))
        baseline = watcher.known_run_ids("demo")
        ticks = [0.0]

        def now() -> float:
            ticks[0] += 1.0
            return ticks[0]

        assert watcher.wait_for_new_stop(
            "demo", baseline, timeout=0.5, poll_interval=0.1,
            now=now, sleep=lambda _s: None,
        ) is None
