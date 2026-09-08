"""Unit tests for external plist import (Stage 0 shared service surface).

Covers the read-only preview, the acknowledgement gate, the fresh-UUID catalog
commit, label-conflict rejection, and the create-only ``import_job`` guard.
Every case proves the source plist is untouched and nothing is deployed.
"""

from __future__ import annotations

import plistlib
from pathlib import Path
from uuid import UUID

import pytest
from tests.conftest import FIXED_JOB_ID, make_job
from tests.fakes import FakeTaskWorld

from task_scheduler.application import ExternalPlistImportPreview, JobConflictError
from task_scheduler.application.job_service import JobService


def write_plist(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(payload))


def supported_plist() -> dict[str, object]:
    return {
        "Label": "com.example.cleanup",
        "ProgramArguments": ["/usr/local/bin/cleanup.sh"],
        "StartCalendarInterval": [{"Hour": 3, "Minute": 0, "Weekday": 1}],
    }


def partial_plist() -> dict[str, object]:
    payload = supported_plist()
    payload["KeepAlive"] = True
    return payload


def test_preview_supported(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    src = tmp_path / "external" / "com.example.cleanup.plist"
    write_plist(src, supported_plist())
    preview = world.services.preview_external_plist(src)
    assert isinstance(preview, ExternalPlistImportPreview)
    assert preview.source_path == src
    assert preview.candidate.label == "com.example.cleanup"
    assert preview.warnings == ()
    assert preview.unsupported_keys == ()
    assert preview.requires_acknowledgement is False


def test_preview_partial_flags_acknowledgement(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    src = tmp_path / "external" / "com.example.cleanup.plist"
    write_plist(src, partial_plist())
    preview = world.services.preview_external_plist(src)
    assert preview.unsupported_keys == ("KeepAlive",)
    assert preview.requires_acknowledgement is True


def test_preview_invalid_raises(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    src = tmp_path / "external" / "bad.plist"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"not a plist")
    with pytest.raises(ValueError):
        world.services.preview_external_plist(src)


def test_preview_unrepresentable_raises(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    src = tmp_path / "external" / "boot.plist"
    write_plist(
        src,
        {
            "Label": "com.example.boot",
            "ProgramArguments": ["/usr/local/bin/boot.sh"],
            "RunAtLoad": True,
        },
    )
    with pytest.raises(ValueError):
        world.services.preview_external_plist(src)


def test_commit_supported_is_catalog_only(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    src = tmp_path / "external" / "com.example.cleanup.plist"
    write_plist(src, supported_plist())
    before = src.read_bytes()
    preview = world.services.preview_external_plist(src)
    candidate_id = preview.candidate.id

    job = world.services.import_external_plist(preview, acknowledge_partial=False)

    assert job.id != candidate_id
    assert job.label == "com.example.cleanup"
    assert [f.name for f in world.catalog_root.glob("*.json")] == [f"{job.id}.json"]
    # source plist untouched; nothing deployed; no launchctl or direct test
    assert src.read_bytes() == before
    assert not list(world.la_root.glob("*.plist"))
    assert world.launch_runner.specs == []
    assert world.test_runner.specs == []


def test_commit_partial_requires_acknowledgement(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    src = tmp_path / "external" / "com.example.cleanup.plist"
    write_plist(src, partial_plist())
    preview = world.services.preview_external_plist(src)
    with pytest.raises(ValueError):
        world.services.import_external_plist(preview, acknowledge_partial=False)
    assert not list(world.catalog_root.glob("*.json"))


def test_commit_partial_with_acknowledgement(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    src = tmp_path / "external" / "com.example.cleanup.plist"
    write_plist(src, partial_plist())
    preview = world.services.preview_external_plist(src)
    job = world.services.import_external_plist(preview, acknowledge_partial=True)
    assert job.label == "com.example.cleanup"
    assert (world.catalog_root / f"{job.id}.json").is_file()


def test_commit_label_conflict_raises(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    world.jobs.import_job(make_job(id=FIXED_JOB_ID, label="com.example.cleanup"))
    src = tmp_path / "external" / "com.example.cleanup.plist"
    write_plist(src, supported_plist())
    preview = world.services.preview_external_plist(src)
    with pytest.raises(JobConflictError):
        world.services.import_external_plist(preview, acknowledge_partial=False)


def test_import_job_rejects_duplicate_label(tmp_path: Path) -> None:
    """The create-only guard: a different id claiming an existing label fails."""
    jobs = JobService(tmp_path)
    jobs.import_job(make_job())
    second = make_job(id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"))
    with pytest.raises(JobConflictError):
        jobs.import_job(second)
