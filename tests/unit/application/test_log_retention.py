"""Unit tests for application/log_retention.py."""

from __future__ import annotations

import os
import time
from datetime import timedelta
from pathlib import Path

from task_scheduler.application.log_retention import (
    APP_DISPLAY_NAME,
    RetentionPolicy,
    RetentionReport,
    _file_mtime,
    _file_size,
    _is_generation,
    _remove_empty_dirs,
    ensure_log_symlink,
    prepare_job_logs,
    prune_job_logs,
    visible_log_symlink,
)

_DEFAULT = RetentionPolicy()
_NOW = time.time()
_OLD = _NOW - 40 * 86400  # 40 days ago -> aged out


def _raise_oserror(*_args, **_kwargs) -> None:
    raise OSError("simulated")


def _base(tmp: Path) -> Path:
    (tmp / "jobs").mkdir()
    return tmp


def _job_file(root: Path, label: str, name: str, content: str, mtime: float) -> Path:
    job = root / "jobs" / label
    job.mkdir(parents=True, exist_ok=True)
    p = job / name
    p.write_text(content)
    os.utime(p, (mtime, mtime))
    return p


def test_visible_log_symlink_explicit_home(tmp_path: Path) -> None:
    assert visible_log_symlink(tmp_path) == tmp_path / APP_DISPLAY_NAME


def test_visible_log_symlink_default_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert visible_log_symlink() == tmp_path / APP_DISPLAY_NAME


def test_prune_missing_dir_returns_empty(tmp_path: Path) -> None:
    report = prune_job_logs(tmp_path / "does-not-exist")
    assert (
        report.files_removed == 0
        and report.files_rotated == 0
        and report.empty_dirs_removed == 0
        and report.bytes_freed == 0
    )


def test_prune_within_bounds_is_noop(tmp_path: Path) -> None:
    root = _base(tmp_path)
    p = _job_file(root, "A", "stdout.log", "x" * 10, mtime=_NOW)
    report = prune_job_logs(root)
    assert p.exists()
    assert report.files_removed == 0 and report.files_rotated == 0


def test_prune_removes_aged_files(tmp_path: Path) -> None:
    root = _base(tmp_path)
    old = _job_file(root, "A", "stdout.log", "old", mtime=_OLD)
    recent = _job_file(root, "A", "stderr.log", "new", mtime=_NOW)
    unknown = _job_file(root, "B", "run.log", "unknown-age", mtime=0.0)
    report = prune_job_logs(root)
    assert not old.exists()
    assert recent.exists()
    assert unknown.exists()  # mtime <= 0 -> unknown age, left alone
    assert report.files_removed == 1
    assert report.bytes_freed == len("old")


def test_prune_rotates_oversized_file_and_shifts(tmp_path: Path) -> None:
    root = _base(tmp_path)
    policy = RetentionPolicy(max_age=timedelta(days=30), max_file_bytes=10, total_bytes=10**9)
    p = _job_file(root, "A", "stdout.log", "a" * 20, mtime=_NOW)
    first = prune_job_logs(root, policy)
    assert (root / "jobs" / "A" / "stdout.log.1").read_text() == "a" * 20
    assert first.files_rotated == 1
    p.write_text("b" * 20)
    prune_job_logs(root, policy)
    assert (root / "jobs" / "A" / "stdout.log.1").read_text() == "b" * 20
    assert (root / "jobs" / "A" / "stdout.log.2").read_text() == "a" * 20
    p.write_text("c" * 20)
    prune_job_logs(root, policy)
    assert (root / "jobs" / "A" / "stdout.log.1").read_text() == "c" * 20
    assert (root / "jobs" / "A" / "stdout.log.2").read_text() == "b" * 20
    assert (root / "jobs" / "A" / "stdout.log.3").read_text() == "a" * 20
    p.write_text("d" * 20)
    prune_job_logs(root, policy)  # oldest generation ("a") is dropped
    assert (root / "jobs" / "A" / "stdout.log.1").read_text() == "d" * 20
    assert (root / "jobs" / "A" / "stdout.log.2").read_text() == "c" * 20
    assert (root / "jobs" / "A" / "stdout.log.3").read_text() == "b" * 20


def test_prune_enforces_total_cap_oldest_first(tmp_path: Path) -> None:
    root = _base(tmp_path)
    policy = RetentionPolicy(max_age=timedelta(days=30), max_file_bytes=10**9, total_bytes=100)
    oldest = _job_file(root, "A", "stdout.log", "a" * 60, mtime=_NOW - 3000)
    mid = _job_file(root, "B", "stdout.log", "b" * 60, mtime=_NOW - 2000)
    newest = _job_file(root, "C", "stdout.log", "c" * 60, mtime=_NOW - 1000)
    report = prune_job_logs(root, policy)
    assert not oldest.exists()
    assert not mid.exists()
    assert newest.exists()
    assert report.files_removed == 2
    assert report.bytes_freed == 120


def test_prune_removes_empty_job_dirs(tmp_path: Path) -> None:
    root = _base(tmp_path)
    _job_file(root, "A", "stdout.log", "old", mtime=_OLD)
    report = prune_job_logs(root)
    assert not (root / "jobs" / "A").exists()
    assert report.empty_dirs_removed == 1
    assert (root / "jobs").exists()


def test_prune_ignores_stat_oserror(monkeypatch, tmp_path: Path) -> None:
    root = _base(tmp_path)
    p = _job_file(root, "A", "stdout.log", "x", mtime=_NOW)
    real = Path.stat

    def boom(self: Path) -> os.stat_result:
        if self == p:
            raise OSError("gone")
        return real(self)

    monkeypatch.setattr(Path, "stat", boom)
    report = prune_job_logs(root)
    assert report.files_removed == 0 and report.files_rotated == 0


def test_file_size_ignores_stat_oserror(monkeypatch, tmp_path: Path) -> None:
    p = tmp_path / "f.log"
    p.write_text("12345")
    monkeypatch.setattr(Path, "stat", _raise_oserror)
    assert _file_size(p) == 0


def test_file_mtime_ignores_stat_oserror(monkeypatch, tmp_path: Path) -> None:
    p = tmp_path / "f.log"
    p.write_text("12345")
    monkeypatch.setattr(Path, "stat", _raise_oserror)
    assert _file_mtime(p) == 0.0


def test_remove_empty_dirs_ignores_rmdir_oserror(monkeypatch, tmp_path: Path) -> None:
    base = tmp_path / "jobs"
    (base / "A").mkdir(parents=True)
    monkeypatch.setattr(Path, "rmdir", _raise_oserror)
    report = RetentionReport()
    _remove_empty_dirs(base, report)
    assert report.empty_dirs_removed == 0
    assert (base / "A").exists()


def test_is_generation_detection() -> None:
    assert _is_generation("stdout.log", 3) is False
    assert _is_generation("run.log", 3) is False
    assert _is_generation("stdout.log.1", 3) is True
    assert _is_generation("stdout.log.3", 3) is True
    assert _is_generation("stdout.log.4", 3) is False
    assert _is_generation("run.log.0", 3) is False


def test_ensure_symlink_creates_and_makes_target(tmp_path: Path) -> None:
    link = tmp_path / APP_DISPLAY_NAME
    target = tmp_path / "deep" / "logs"
    ensure_log_symlink(link, target)
    assert link.is_symlink()
    assert Path(os.readlink(link)) == target
    assert target.is_dir()


def test_ensure_symlink_idempotent_when_correct(tmp_path: Path) -> None:
    link = tmp_path / APP_DISPLAY_NAME
    target = tmp_path / "logs"
    target.mkdir()
    link.symlink_to(target)
    assert ensure_log_symlink(link, target) == link


def test_ensure_symlink_repoints_when_wrong(tmp_path: Path) -> None:
    link = tmp_path / APP_DISPLAY_NAME
    wrong = tmp_path / "wrong"
    target = tmp_path / "right"
    wrong.mkdir()
    target.mkdir()
    link.symlink_to(wrong)
    ensure_log_symlink(link, target)
    assert Path(os.readlink(link)) == target


def test_ensure_symlink_replaces_regular_file(tmp_path: Path) -> None:
    link = tmp_path / APP_DISPLAY_NAME
    link.write_text("a plain file")
    target = tmp_path / "logs"
    ensure_log_symlink(link, target)
    assert link.is_symlink()
    assert Path(os.readlink(link)) == target


def test_ensure_symlink_refuses_directory(tmp_path: Path) -> None:
    link = tmp_path / APP_DISPLAY_NAME
    link.mkdir()
    target = tmp_path / "logs"
    try:
        ensure_log_symlink(link, target)
    except FileExistsError:
        pass
    else:
        raise AssertionError("expected FileExistsError")
    assert link.is_dir()


def test_prepare_creates_root_prunes_and_links(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    root = tmp_path / "Library" / "Logs" / APP_DISPLAY_NAME
    (root / "jobs" / "A").mkdir(parents=True)
    aged = root / "jobs" / "A" / "stdout.log"
    aged.write_text("old")
    os.utime(aged, (_OLD, _OLD))
    report = prepare_job_logs(root, home)
    assert report.files_removed == 1
    assert not aged.exists()
    link = home / APP_DISPLAY_NAME
    assert link.is_symlink()
    assert Path(os.readlink(link)) == root


def test_prepare_repoints_wrong_symlink(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    wrong = home / "elsewhere"
    wrong.mkdir()
    (home / APP_DISPLAY_NAME).symlink_to(wrong)
    root = tmp_path / "Library" / "Logs" / APP_DISPLAY_NAME
    root.mkdir(parents=True)
    prepare_job_logs(root, home)
    assert Path(os.readlink(home / APP_DISPLAY_NAME)) == root


def test_prepare_uncreatable_root_returns_empty(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    blocker = tmp_path / "blocker"
    blocker.write_text("file")
    report = prepare_job_logs(blocker / "sub" / "logs", home)
    assert report.files_removed == 0
    assert not (home / APP_DISPLAY_NAME).exists()


def test_prepare_symlink_refused_still_prunes(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / APP_DISPLAY_NAME).mkdir()  # a real directory blocks the symlink
    root = tmp_path / "Library" / "Logs" / APP_DISPLAY_NAME
    (root / "jobs" / "A").mkdir(parents=True)
    aged = root / "jobs" / "A" / "stdout.log"
    aged.write_text("old")
    os.utime(aged, (_OLD, _OLD))
    report = prepare_job_logs(root, home)
    assert report.files_removed == 1  # pruning happened
    assert (home / APP_DISPLAY_NAME).is_dir()  # symlink refused, dir kept


def test_prepare_default_policy_and_home(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(
        "task_scheduler.application.log_retention.default_job_logs_root",
        lambda: tmp_path / "default-logs",
    )
    report = prepare_job_logs()
    assert (tmp_path / "default-logs").is_dir()
    assert (home / APP_DISPLAY_NAME).is_symlink()
    assert report.files_removed == 0


def test_default_policy_values() -> None:
    p = _DEFAULT
    assert p.max_age == timedelta(days=30)
    assert p.max_file_bytes == 10 * 1024 * 1024
    assert p.total_bytes == 500 * 1024 * 1024
    assert p.rotations == 3
