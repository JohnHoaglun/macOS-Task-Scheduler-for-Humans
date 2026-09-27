"""Job-log retention and the visible home-directory log symlink.

The app's per-job logs live under ``<logs-root>/jobs/<label>/`` (one
append-only folder per job, written by the run wrapper and launchd). The
application debug log (``app.log``) is bounded separately by
:mod:`task_scheduler.application.app_logging`; this module bounds the
per-job tree so it cannot grow without limit:

* **Age** — files not modified within ``max_age`` (30 days) are removed.
* **Per-file rotation** — a file larger than ``max_file_bytes`` (10 MiB) is
  rotated to ``<name>.1`` .. ``<name>.N``; the oldest rotation is dropped.
* **Total cap** — when the whole ``jobs`` tree exceeds ``total_bytes``
  (500 MiB) the oldest files are removed first until it fits.
* **Empty folders** — a job folder left with no files is dropped.

Retention is app-driven: :func:`prepare_job_logs` runs at startup (see
:func:`task_scheduler.bootstrap.build_services`). It also maintains a
convenience symlink ``~/macOS Task Scheduler for Humans`` so the user can
reach the logs without knowing the Library path.
"""

from __future__ import annotations

import os
import re
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from task_scheduler.application.job_service import default_job_logs_root

__all__ = [
    "APP_DISPLAY_NAME",
    "DEFAULT_MAX_AGE_DAYS",
    "DEFAULT_MAX_FILE_BYTES",
    "DEFAULT_ROTATIONS",
    "DEFAULT_TOTAL_BYTES",
    "JOBS_SUBDIR",
    "RetentionPolicy",
    "RetentionReport",
    "ensure_log_symlink",
    "prune_job_logs",
    "prepare_job_logs",
    "visible_log_symlink",
]

APP_DISPLAY_NAME = "macOS Task Scheduler for Humans"
JOBS_SUBDIR = "jobs"
DEFAULT_MAX_AGE_DAYS = 30
DEFAULT_MAX_FILE_BYTES = 10 * 1024 * 1024
DEFAULT_TOTAL_BYTES = 500 * 1024 * 1024
DEFAULT_ROTATIONS = 3


@dataclass(frozen=True)
class RetentionPolicy:
    """Bounds applied when pruning the per-job logs tree."""

    max_age: timedelta = timedelta(days=DEFAULT_MAX_AGE_DAYS)
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    total_bytes: int = DEFAULT_TOTAL_BYTES
    rotations: int = DEFAULT_ROTATIONS


@dataclass
class RetentionReport:
    """A mutable summary of the filesystem changes a prune makes."""

    files_removed: int = 0
    files_rotated: int = 0
    empty_dirs_removed: int = 0
    bytes_freed: int = 0


def visible_log_symlink(home: Path | None = None) -> Path:
    """Return the user-visible symlink path (``~/macOS Task Scheduler for Humans``)."""
    base = home if home is not None else Path.home()
    return base / APP_DISPLAY_NAME


def ensure_log_symlink(link: Path, target: Path) -> Path:
    """Create or repair the *link* -> *target* convenience symlink.

    An existing link that already points at *target* is left alone. A link
    pointing elsewhere, or a regular file occupying the name, is replaced. A
    real directory in the way is refused (raising :class:`FileExistsError`)
    so user data is never clobbered.
    """
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    link = Path(link)
    if link.is_symlink():
        if Path(os.readlink(link)) == target:
            return link
        link.unlink()
    elif link.is_dir():
        raise FileExistsError(f"cannot create log symlink: {link} is a directory")
    elif link.exists():
        link.unlink()
    link.symlink_to(target)
    return link


def _is_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _is_dir(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink()


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _iter_files(base: Path) -> list[Path]:
    files: list[Path] = []
    for path in base.rglob("*"):
        if _is_file(path):
            files.append(path)
    return files


_GENERATION_RE = re.compile(r".+\.(?P<n>\d+)$")


def _is_generation(name: str, rotations: int) -> bool:
    m = _GENERATION_RE.fullmatch(name)
    if m is None:
        return False
    return 1 <= int(m.group("n")) <= rotations


def _remove_aged(base: Path, policy: RetentionPolicy, report: RetentionReport, now: float) -> None:
    limit = policy.max_age.total_seconds()
    for path in _iter_files(base):
        mtime = _file_mtime(path)
        if mtime <= 0 or now - mtime <= limit:
            continue
        report.files_removed += 1
        report.bytes_freed += _file_size(path)
        with suppress(OSError):
            path.unlink()


def _rotate_file(path: Path, policy: RetentionPolicy, report: RetentionReport) -> bool:
    if _file_size(path) <= policy.max_file_bytes:
        return False
    oldest = path.with_name(f"{path.name}.{policy.rotations}")
    if oldest.exists():
        report.bytes_freed += _file_size(oldest)
        with suppress(OSError):
            oldest.unlink()
    for i in range(policy.rotations - 1, 0, -1):
        src = path.with_name(f"{path.name}.{i}")
        if src.exists():
            with suppress(OSError):
                src.rename(path.with_name(f"{path.name}.{i + 1}"))
    one = path.with_name(f"{path.name}.1")
    with suppress(OSError):
        one.unlink()
    with suppress(OSError):
        path.rename(one)
    report.files_rotated += 1
    return True


def _enforce_total_cap(base: Path, policy: RetentionPolicy, report: RetentionReport) -> None:
    entries = _iter_files(base)
    total = sum(_file_size(path) for path in entries)
    if total <= policy.total_bytes:
        return
    for path in sorted(entries, key=_file_mtime):
        if total <= policy.total_bytes:
            break
        size = _file_size(path)
        with suppress(OSError):
            path.unlink()
        total -= size
        report.files_removed += 1
        report.bytes_freed += size


def _remove_empty_dirs(base: Path, report: RetentionReport) -> None:
    dirs = sorted(
        (p for p in base.rglob("*") if _is_dir(p)), key=lambda p: len(p.parts), reverse=True
    )
    for directory in dirs:
        try:
            if not any(directory.iterdir()):
                directory.rmdir()
                report.empty_dirs_removed += 1
        except OSError:
            continue


def prune_job_logs(
    root: Path | None = None, policy: RetentionPolicy | None = None
) -> RetentionReport:
    """Enforce *policy* on the per-job logs tree under *root* (default logs root)."""
    policy = policy if policy is not None else RetentionPolicy()
    base = (root if root is not None else default_job_logs_root()) / JOBS_SUBDIR
    if not base.is_dir():
        return RetentionReport()
    report = RetentionReport()
    now = time.time()
    _remove_aged(base, policy, report, now)
    for path in _iter_files(base):
        if _is_generation(path.name, policy.rotations):
            continue
        _rotate_file(path, policy, report)
    _enforce_total_cap(base, policy, report)
    _remove_empty_dirs(base, report)
    return report


def prepare_job_logs(
    root: Path | None = None, home: Path | None = None, policy: RetentionPolicy | None = None
) -> RetentionReport:
    """App-driven startup prep: create the logs root, prune it, and fix the symlink.

    Best-effort throughout: an uncreatable root yields an empty report and a
    symlink that cannot be established (e.g. a directory in the way) does not
    stop the prune from applying.
    """
    policy = policy if policy is not None else RetentionPolicy()
    base = root if root is not None else default_job_logs_root()
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        return RetentionReport()
    report = prune_job_logs(base, policy)
    with suppress(OSError):
        ensure_log_symlink(visible_log_symlink(home), base)
    return report
