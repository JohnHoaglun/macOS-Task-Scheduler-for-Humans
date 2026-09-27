#!/usr/bin/python3
"""launchd run wrapper: guaranteed START/STOP logging for managed job runs.

This file is deployed as a standalone, stdlib-only script (a byte copy is
written to the app's local ``bin`` directory and referenced from the managed
plist's ``ProgramArguments``). launchd execs it instead of the job command; it
forks the real command, waits for its exit, and writes a ``START``/``STOP``
pair around every run.

Log layout (one folder per job, all append-only):

* ``<job-logs>/jobs/<label>/run.log`` — the canonical run record. Always
  receives a START/STOP pair with the run's exit code and duration. This is
  the file the LaunchD test (Mode B) watches for a fresh STOP.
* ``<job-logs>/jobs/<label>/stdout.log`` and ``stderr.log`` — the command's
  own output, written by launchd via ``StandardOutPath``/``StandardErrorPath``
  (both point here). Because the per-job folder lives on local disk and is
  created when the job is installed, launchd never has to open a network
  (SMB/NFS) volume path, which it cannot do (the run would abort with exit 78).

The wrapper only ever writes the run record, so it never contends with the
file handles launchd holds for the job's stdout/stderr streams.

Usage (as invoked from the managed plist)::

  run_wrapper.py [--label LABEL] [--run-id ID] -- COMMAND [ARGS...]

The wrapper exits with the command's exit code, so launchd's last exit status
always reflects the job itself.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import signal
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

WRAPPER_BASENAME = "run_wrapper.py"


def default_job_logs_root() -> Path:
    """Return the per-user directory that holds every application log.

    This is the single on-disk home for the app's logs: the app's own debug
    log (``app.log``) and each managed job's per-run logs (``jobs/<label>/``)
    both live here.
    """
    return Path.home() / "Library" / "Logs" / "macOS Task Scheduler for Humans"


def _sanitize(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "-", label) or "job"


def job_log_dir(label: str, root: Path | None = None) -> Path:
    """Return the per-job log directory (one folder per job, always local)."""
    base = root if root is not None else default_job_logs_root()
    return base / "jobs" / _sanitize(label)


def run_log_path(label: str, root: Path | None = None) -> Path:
    """Return the canonical per-job run record (``jobs/<label>/run.log``)."""
    return job_log_dir(label, root) / "run.log"


def stdout_log_path(label: str, root: Path | None = None) -> Path:
    """Return the job's stdout log (``jobs/<label>/stdout.log``)."""
    return job_log_dir(label, root) / "stdout.log"


def stderr_log_path(label: str, root: Path | None = None) -> Path:
    """Return the job's stderr log (``jobs/<label>/stderr.log``)."""
    return job_log_dir(label, root) / "stderr.log"


def ensure_job_log_dir(label: str, root: Path | None = None) -> Path:
    """Create (idempotently) the job's log directory and return it.

    launchd opens ``StandardOutPath``/``StandardErrorPath`` before it execs
    the wrapper, so the folder must exist by install time.
    """
    directory = job_log_dir(label, root)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _open_for_append(path: Path) -> int | None:
    """Open *path* for appending (creating its directory); None when impossible."""
    try:
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    except OSError:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        try:
            return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        except OSError:
            return None


def _write_line(fd: int | None, text: str) -> None:
    if fd is None:
        return
    with contextlib.suppress(OSError):
        os.write(fd, text.encode("utf-8"))
        os.fsync(fd)


def _close(fd: int | None) -> None:
    if fd is not None:
        with contextlib.suppress(OSError):
            os.close(fd)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=WRAPPER_BASENAME,
        description="Run a command under launchd with guaranteed START/STOP logging.",
    )
    parser.add_argument("--label", default="job", help="job label (for log file names)")
    parser.add_argument(
        "--run-id", default=None, help="unique id for this run (generated when absent)"
    )
    parser.add_argument("command", nargs="+", metavar="COMMAND", help="command to run")
    args = parser.parse_args(argv)

    label = _sanitize(args.label)
    run_id = args.run_id or uuid.uuid4().hex
    command = args.command
    started_monotonic = time.monotonic()

    runlog_fd = _open_for_append(run_log_path(label))
    start_line = (
        f"=== START {_timestamp()} run={run_id} label={label} "
        f"cmd={' '.join(command)} ===\n"
    )
    _write_line(runlog_fd, start_line)

    pid = os.fork()
    if pid == 0:
        # -- child: become the job command ---------------------------------
        # launchd already points the child's stdout/stderr at the job's
        # stdout.log/stderr.log (StandardOutPath/StandardErrorPath); we only
        # drop our own run-record handle so it is not inherited by the job.
        _close(runlog_fd)
        try:
            os.execv(command[0], command)
        except OSError as exc:
            with contextlib.suppress(OSError):
                os.write(
                    2,
                    f"run_wrapper: failed to exec {command[0]}: {exc}\n".encode(),
                )
            os._exit(127)

    # -- parent: wait, record the stop, propagate the exit code ------------
    def _forward(signum: int, _frame: object) -> None:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signum)

    watched = (signal.SIGTERM, signal.SIGINT)
    previous_handlers = {sig: signal.getsignal(sig) for sig in watched}
    for sig in watched:
        with contextlib.suppress(OSError, ValueError):
            signal.signal(sig, _forward)

    try:
        _pid, status = os.waitpid(pid, 0)
    finally:
        for sig, handler in previous_handlers.items():
            with contextlib.suppress(OSError, ValueError):
                signal.signal(sig, handler)
        duration = time.monotonic() - started_monotonic
        if os.WIFEXITED(status):
            exit_code = os.WEXITSTATUS(status)
            status_text = "exited"
        elif os.WIFSIGNALED(status):
            exit_code = 128 + os.WTERMSIG(status)
            status_text = f"killed-by-signal-{os.WTERMSIG(status)}"
        else:
            exit_code = 1
            status_text = "unknown"
        stop_line = (
            f"=== STOP  {_timestamp()} run={run_id} exit={exit_code} "
            f"duration={duration:.1f}s status={status_text} ===\n"
        )
        _write_line(runlog_fd, stop_line)
        _close(runlog_fd)
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
