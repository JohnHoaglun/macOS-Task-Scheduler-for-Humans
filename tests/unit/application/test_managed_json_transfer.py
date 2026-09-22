"""Unit tests for managed-JSON transfer (Increment 22, Stage 0).

Covers the strict closed-schema decoder (v1→v2, unknown-field rejection,
unsupported versions), the identity-preserving export/import façades,
conflict preview, create-only commit re-check, and the GUI Finder reveal.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import make_job
from tests.fakes import FakeTaskWorld

from task_scheduler.application import JobConflictError, StrictJsonDecodeError
from task_scheduler.application.managed_json_transfer import strict_decode_job_json

_ID = "12345678-1234-5678-1234-567812345678"
_OTHER_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"
_LABEL = "io.github.macos-task-scheduler.user.daily-backup"


def v2_payload() -> dict[str, object]:
    return {
        "schema_version": 2,
        "id": _ID,
        "name": "Daily Backup",
        "label": _LABEL,
        "enabled": True,
        "command": {
            "type": "python",
            "interpreter": "/Users/example/project/.venv/bin/python",
            "script": "/Users/example/project/main.py",
            "arguments": ["--mode", "daily"],
        },
        "schedule": {
            "kind": "calendar",
            "times": ["07:30"],
            "weekdays": ["monday"],
            "run_at_load": False,
        },
        "environment": {"variables": {}},
        "working_directory": None,
        "logging": {"stdout_path": None, "stderr_path": None},
    }


def v1_payload() -> dict[str, object]:
    payload = v2_payload()
    payload["schema_version"] = 1
    payload["schedule"] = {"time": "07:30", "weekdays": ["monday", "friday"]}
    return payload


def write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (str, bytes)):
        data: str | bytes = payload
    else:
        data = json.dumps(payload)
    path.write_text(data, "utf-8")
    return path


def test_decode_valid_v1_migrates_to_calendar() -> None:
    job = strict_decode_job_json(json.dumps(v1_payload()))
    assert job.schema_version == 2
    assert job.schedule.kind == "calendar"
    assert job.schedule.times[0].hour == 7
    assert job.schedule.run_at_load is False


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(schema_version=3),
        lambda p: p.__delitem__("schema_version"),
    ],
)
def test_decode_unsupported_version_raises(mutate) -> None:
    payload = v2_payload()
    mutate(payload)
    with pytest.raises(StrictJsonDecodeError, match="unsupported schema version"):
        strict_decode_job_json(json.dumps(payload))


def test_decode_semantic_validation_error_raises() -> None:
    payload = v2_payload()
    payload["schedule"]["times"] = ["25:99"]  # type: ignore[index]
    with pytest.raises(StrictJsonDecodeError, match="invalid job definition"):
        strict_decode_job_json(json.dumps(payload))


@pytest.mark.parametrize(
    ("base", "patch"),
    [
        (lambda: v2_payload(), lambda p: p.update(command="echo hi")),
        (lambda: v2_payload(), lambda p: p.update(command={"type": "bogus", "whatever": 1})),
        (lambda: v2_payload(), lambda p: p.update(schedule={"kind": "bogus", "whatever": 1})),
        (lambda: v1_payload(), lambda p: p.update(schedule="07:30")),
    ],
)
def test_decode_skips_key_check_when_shape_unknown(base, patch) -> None:
    payload = base()
    patch(payload)
    with pytest.raises(StrictJsonDecodeError, match="invalid job definition"):
        strict_decode_job_json(json.dumps(payload))


def test_export_refuses_existing_destination(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    world.jobs.import_job(make_job())
    dest = tmp_path / "existing.json"
    dest.write_text("{}", "utf-8")
    with pytest.raises(FileExistsError):
        world.services.export_managed_json(_LABEL, dest)


def test_import_rechecks_conflict_at_commit(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    src = write_json(tmp_path / "src.json", v2_payload())
    preview = world.services.preview_managed_json_import(src)  # clean at preview
    world.jobs.import_job(make_job())  # concurrent import claims the id
    with pytest.raises(JobConflictError):
        world.services.import_managed_json(preview)


def test_reveal_missing_path_returns_message(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    message = world.services.reveal_path(tmp_path / "nope.txt")
    assert message == f"path does not exist: {tmp_path / 'nope.txt'}"
    assert world.finder_revealer.revealed == []


def test_reveal_failure_message_passthrough(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    world.finder_revealer.result = "open failed"
    target = tmp_path / "target.txt"
    target.write_text("x", "utf-8")
    assert world.services.reveal_path(target) == "open failed"


def test_reveal_without_finder_reports_unavailable(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    world.services._finder = None  # a service wired without a revealer
    target = tmp_path / "target.txt"
    target.write_text("x", "utf-8")
    assert world.services.reveal_path(target) == "reveal in Finder is not available"


def test_loaded_status(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)  # sticky exit 0 -> loaded True
    assert world.services._loaded_status(None) is None
    assert world.services._loaded_status("com.example/bad") is None
    assert world.services._loaded_status("com.example.ok") is True
