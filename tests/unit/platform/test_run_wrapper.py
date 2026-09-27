"""Tests for the launchd run wrapper. ``main`` runs in-process on a scripted fake ``os`` so the fork
parent and child paths execute, and the per-job run.log is genuinely written. The wrapper writes
``jobs/<label>/run.log``; launchd writes the job's stdout/stderr (no wrapper redirection)."""

from __future__ import annotations

import os as real_os
import re
import runpy
import signal as signal_mod
import sys
from pathlib import Path

import pytest

from task_scheduler.platform.macos import run_wrapper
from task_scheduler.platform.macos.run_wrapper import (
    _close,
    _open_for_append,
    _sanitize,
    _timestamp,
    _write_line,
    default_job_logs_root,
    ensure_job_log_dir,
    job_log_dir,
    run_log_path,
    stderr_log_path,
    stdout_log_path,
)

BASE_NAME = "job-logs"

class _FakeExit(BaseException):
    def __init__(self, code: object = None) -> None:
        super().__init__(code)
        self.code = code

class _ExecCompleted(_FakeExit):
    pass

class FakeOs:
    """Scripts fork/execv/waitpid/kill/_exit; file ops pass through."""

    def __init__(
        self,
        fork_results: list[int] | None = None,
        wait_status: int = 0,
        exec_error: Exception | None = None,
        unopenable: set[str] | None = None,
    ) -> None:
        self._fork_results = list(fork_results) if fork_results is not None else [4242]
        self._wait_status = wait_status
        self._exec_error = exec_error
        self._unopenable = set(unopenable) if unopenable is not None else set()
        self.fds: dict[str, int] = {}
        self.unopenable_hits: list[str] = []
        self.dup2s: list[tuple[int, int]] = []
        self.closed: list[int] = []
        self.kills: list[tuple[int, int]] = []
        self.fork_calls = 0
        self.exit_codes: list[int] = []
        self.exec_path: str | None = None
        self.exec_args: list[str] | None = None

    def open(self, path: object, flags: int, mode: object = None) -> int:
        key = str(path)
        if key in self._unopenable:
            self.unopenable_hits.append(key)
            raise PermissionError(13, "fake: unopenable", key)
        fd = real_os.open(path, flags, mode if mode is not None else 0o644)
        self.fds[key] = fd
        return fd

    def write(self, fd: int, data: object) -> int:
        return real_os.write(fd, data)

    def fsync(self, fd: int) -> None:
        real_os.fsync(fd)

    def close(self, fd: int) -> None:
        self.closed.append(fd)
        real_os.close(fd)

    def dup2(self, src: int, dst: int) -> None:
        self.dup2s.append((src, dst))

    def fork(self) -> int:
        self.fork_calls += 1
        if self._fork_results:
            return self._fork_results.pop(0)
        return 4242

    def execv(self, path: str, argv: list[str]) -> None:
        self.exec_path = path
        self.exec_args = list(argv)
        if self._exec_error is not None:
            raise self._exec_error
        raise _ExecCompleted()

    def waitpid(self, pid: int, flags: int) -> tuple[int, int]:
        return (pid, self._wait_status)

    def kill(self, pid: int, sig: int) -> None:
        self.kills.append((pid, sig))

    def _exit(self, code: int) -> None:  # noqa: A003 - mirrors os._exit
        self.exit_codes.append(code)
        raise _FakeExit(code)

    def __getattr__(self, name: str) -> object:
        return getattr(real_os, name)

class World:
    """Monkeypatched run_wrapper module over a tmp root; run() scripts os."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp = tmp_path
        self.mp = monkeypatch
        monkeypatch.setattr(run_wrapper, "default_job_logs_root", lambda: tmp_path / BASE_NAME)
        self.fake: FakeOs | None = None

    def run(
        self,
        argv: list[str],
        *,
        fork: list[int] = (777,),
        status: int = 0,
        waitpid=None,
        **fake_kw,
    ) -> int:
        self.fake = FakeOs(fork_results=list(fork), wait_status=status, **fake_kw)
        if waitpid is not None:
            self.fake.waitpid = waitpid
        self.mp.setattr(run_wrapper, "os", self.fake)
        return run_wrapper.main(argv)

    @property
    def base(self) -> Path:
        return self.tmp / BASE_NAME

@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(tmp_path, monkeypatch)

def _run_log(world: World, label: str) -> str:
    return run_log_path(label, world.base).read_text()

def _stop(log: str) -> str:
    return log.split("=== STOP ")[1]

class TestHelpers:
    def test_default_job_logs_root_is_local(self) -> None:
        assert run_wrapper.default_job_logs_root() == (
            Path.home() / "Library" / "Logs" / "macOS Task Scheduler for Humans"
        )

    @pytest.mark.parametrize(
        ("label", "expected"), [("daily brief", "daily-brief"), ("a/b:c", "a-b-c"), ("", "job")]
    )
    def test_sanitize(self, label: str, expected: str) -> None:
        assert _sanitize(label) == expected

    def test_log_paths(self) -> None:
        root = Path("/tmp/r")
        assert job_log_dir("a b", root) == root / "jobs" / "a-b"
        assert run_log_path("a b", root) == root / "jobs" / "a-b" / "run.log"
        assert stdout_log_path("a b", root) == root / "jobs" / "a-b" / "stdout.log"
        assert stderr_log_path("a b", root) == root / "jobs" / "a-b" / "stderr.log"
        # the default-root branch resolves under the real log base
        assert run_log_path("x") == default_job_logs_root() / "jobs" / "x" / "run.log"

    def test_ensure_job_log_dir_creates_and_is_idempotent(self, tmp_path: Path) -> None:
        base = tmp_path / "job-logs"
        first = ensure_job_log_dir("a b", base)
        assert first == base / "jobs" / "a-b"
        assert first.is_dir()
        assert ensure_job_log_dir("a b", base) == first

    def test_timestamp_is_isoformat(self) -> None:
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$", _timestamp())

    def test_open_for_append_creates_parent(self, tmp_path: Path) -> None:
        path = tmp_path / "a" / "b" / "x.log"
        fd = _open_for_append(path)
        assert fd is not None
        _write_line(fd, "line\n")
        _close(fd)
        assert path.read_text() == "line\n"

    def test_open_for_append_none_when_impossible(self, tmp_path: Path) -> None:
        (tmp_path / "file").write_text("x")
        assert _open_for_append(tmp_path / "file" / "sub" / "x.log") is None

    def test_write_line_and_close_accept_none_fd(self) -> None:
        _write_line(None, "ignored")
        _close(None)

class TestParentPath:
    @pytest.mark.parametrize(
        ("status", "rc", "note"),
        [
            (0, 0, "status=exited"),
            (3 << 8, 3, "status=exited"),
            (signal_mod.SIGTERM, 143, "status=killed-by-signal-15"),
            (0x7F, 1, "status=unknown"),
        ],
    )
    def test_wait_statuses(self, world: World, status: int, rc: int, note: str) -> None:
        assert world.run(["--label", "demo", "--", "/bin/x"], status=status) == rc
        stop = _stop(_run_log(world, "demo"))
        assert f"exit={rc}" in stop and note in stop

    def test_macos_signal_wait_status_encoding(self) -> None:
        # a child killed by signal N reports its wait status as N
        assert real_os.WIFSIGNALED(signal_mod.SIGTERM)
        assert real_os.WTERMSIG(signal_mod.SIGTERM) == signal_mod.SIGTERM

    def test_success_log_shape_and_handler_restore(self, world: World) -> None:
        previous = signal_mod.getsignal(signal_mod.SIGTERM)
        world.run(["--label", "demo job", "--", "/bin/echo", "hi"])
        assert world.fake.fork_calls == 1
        log = _run_log(world, "demo job")
        assert log.startswith("=== START ")
        assert "label=demo-job" in log and "cmd=/bin/echo hi" in log
        assert " notes=" not in log and "exit=0" in _stop(log)
        assert signal_mod.getsignal(signal_mod.SIGTERM) is previous

    def test_run_ids(self, world: World) -> None:
        world.run(["--label", "demo", "--", "/bin/x"])
        assert re.search(r"run=[0-9a-f]{32} ", _run_log(world, "demo"))
        world.run(["--label", "demo2", "--run-id", "abc", "--", "/bin/x"])
        assert "run=abc " in _run_log(world, "demo2")

    def test_run_log_unopenable_still_runs(self, world: World) -> None:
        bad = run_log_path("demo", world.base)
        assert world.run(["--label", "demo", "--", "/bin/x"], unopenable={str(bad)}) == 0
        # the run path was tried, then retried after mkdir; the run still happened
        assert world.fake.unopenable_hits == [str(bad)] * 2
        assert not bad.exists()

    def test_sigterm_forwarded(self, world: World) -> None:
        def waitpid(pid: int, flags: int) -> tuple[int, int]:
            real_os.kill(real_os.getpid(), signal_mod.SIGTERM)
            return (pid, 0)

        assert world.run(["--label", "demo", "--", "/bin/x"], waitpid=waitpid) == 0
        assert (777, signal_mod.SIGTERM) in world.fake.kills

class TestChildPath:
    def test_child_closes_runlog_then_execs(self, world: World) -> None:
        with pytest.raises(_ExecCompleted):
            world.run(["--label", "demo", "--", "/bin/echo", "hi"], fork=[0])
        assert world.fake.exec_path == "/bin/echo"
        assert world.fake.exec_args == ["/bin/echo", "hi"]
        # no stream redirection: the child only drops the run-record handle
        runlog_fd = world.fake.fds[str(run_log_path("demo", world.base))]
        assert world.fake.dup2s == []
        assert world.fake.closed == [runlog_fd]

    def test_child_exec_failure_127(self, world: World) -> None:
        with pytest.raises(_FakeExit) as excinfo:
            world.run(["--label", "demo", "--", "/bin/missing"], fork=[0],
                      exec_error=OSError("no such file"))
        assert excinfo.value.code == 127
        assert world.fake.exit_codes == [127]

class TestCli:
    def test_help_exits_zero(self, world: World) -> None:
        with pytest.raises(SystemExit) as excinfo:
            run_wrapper.main(["--help"])
        assert excinfo.value.code == 0

    def test_entry_point_module_main(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", [run_wrapper.__file__, "--help"])
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_path(run_wrapper.__file__, run_name="__main__")
        assert excinfo.value.code == 0
