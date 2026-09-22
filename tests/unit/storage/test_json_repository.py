"""Tests for the JSON job repository."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from tests.conftest import make_job

from task_scheduler.storage import JsonJobRepository


def test_save_new_creates_parent(tmp_path: Path) -> None:
    repository = JsonJobRepository()
    path = tmp_path / "nested" / "job.json"
    repository.save_new(make_job(), path, create_parent=True)
    assert repository.load(path).id == make_job().id


def test_save_new_refuses_existing(tmp_path: Path) -> None:
    repository = JsonJobRepository()
    path = tmp_path / "job.json"
    repository.save(make_job(), path)
    with pytest.raises(FileExistsError):
        repository.save_new(make_job(), path)


def test_save_failure_preserves_original_and_removes_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = JsonJobRepository()
    job = make_job()
    path = tmp_path / "job.json"
    repository.save(job, path)

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        repository.save(job, path)

    assert repository.load(path).id == job.id
    assert list(tmp_path.iterdir()) == [path]
