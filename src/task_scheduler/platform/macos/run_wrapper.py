#!/usr/bin/python3
"""launchd run wrapper: guaranteed START/STOP logging for managed job runs.

This file is deployed as a standalone, stdlib-only script (a byte copy is
written to the app's local ``bin`` directory and referenced from the
managed plist's ``ProgramArguments``). launchd execs it instead of the job
command; it forks the real command, waits for its exit, and writes
``START``/``STOP`` markers around every run.

Why it exists: launchd cannot open ``StandardOutPath``/``StandardErrorPath``
on network (SMB/NFS) volumes and aborts the whole run with exit 78 before
the job command ever starts. The wrapper runs as an ordinary user process,
so it can open the user's configured log paths on any mounted volume, and
it guarantees a start/stop record on local disk for every run.

Log layout (all append-only):

* the canonical run log, ``<run-logs>/<label>.run.log``, always receives a
  START/STOP pair (local disk, always writable);
* the job's configured stdout/stderr paths (when openable) receive the
  command's output plus the same START/STOP markers;
* when a configured path cannot be opened (for example its volume is not
  mounted), that stream falls back to the local spool
  ``<run-logs>/<label>.stdout.log`` / ``.stderr.log``;
* the plist's own ``StandardOutPath``/``StandardErrorPath`` point at the
  same spool files, so wrapper-level failures are captured locally too.

Usage (as invoked from the managed plist)::

  run_wrapper.py [--label LABEL] [--run-id ID] [--out PATH] [--err PATH] -- COMMAND [ARGS...]

The wrapper exits with the command's exit code, so launchd's last exit
status always reflects the job itself.
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


def default_run_logs_root() -> Path:
    """Return the local per-user run-log/spool directory."""
    return Path.home() / "Library" / "Logs" / "macOS Task Scheduler for Humans" / "run-logs"


def _sanitize(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "-", label) or "job"


def run_log_path(label: str, root: Path | None = None) -> Path:
    """Return the canonical per-label run-log file (always local)."""
    base = root if root is not None else default_run_logs_root()
    return base / f"{_sanitize(label)}.run.log"


def spool_out_path(label: str, root: Path | None = None) -> Path:
    """Return the local stdout spool file for *label*."""
    base = root if root is not None else default_run_logs_root()
    return base / f"{_sanitize(label)}.stdout.log"


def spool_err_path(label: str, root: Path | None = None) -> Path:
    """Return the local stderr spool file for *label*."""
    base = root if root is not None else default_run_logs_root()
    return base / f"{_sanitize(label)}.stderr.log"


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
    parser.add_argument("--out", type=Path, default=None, help="configured stdout log path")
    parser.add_argument("--err", type=Path, default=None, help="configured stderr log path")
    parser.add_argument("command", nargs="+", metavar="COMMAND", help="command to run")
    args = parser.parse_args(argv)

    label = _sanitize(args.label)
    run_id = args.run_id or uuid.uuid4().hex
    command = args.command
    started_monotonic = time.monotonic()

    runlog_fd = _open_for_append(run_log_path(label))
    out_fd = _open_for_append(args.out) if args.out is not None else None
    err_fd = _open_for_append(args.err) if args.err is not None else None
    notes: list[str] = []
    if args.out is not None and out_fd is None:
        out_fd = _open_for_append(spool_out_path(label))
        notes.append("stdout_fallback")
    if args.err is not None and err_fd is None:
        err_fd = _open_for_append(spool_err_path(label))
        notes.append("stderr_fallback")

    note_text = f" notes={','.join(notes)}" if notes else ""
    start_line = (
        f"=== START {_timestamp()} run={run_id} label={label} "
        f"cmd={' '.join(command)}{note_text} ===\n"
    )
    for fd in (runlog_fd, out_fd, err_fd):
        _write_line(fd, start_line)

    pid = os.fork()
    if pid == 0:
        # -- child: become the job command ---------------------------------
        if out_fd is not None:
            os.dup2(out_fd, 1)
        if err_fd is not None:
            os.dup2(err_fd, 2)
        for fd in (out_fd, err_fd, runlog_fd):
            _close(fd)
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
        for fd in (runlog_fd, out_fd, err_fd):
            _write_line(fd, stop_line)
        for fd in (runlog_fd, out_fd, err_fd):
            _close(fd)
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
