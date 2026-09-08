"""Unit tests for managed-JSON transfer (Increment 22, Stage 0).

Covers the strict closed-schema decoder (v1→v2, unknown-field rejection,
unsupported versions), the identity-preserving export/import façades,
conflict preview, create-only commit re-check, and the GUI Finder reveal.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
from tests.conftest import FIXED_JOB_ID, make_job
from tests.fakes import FakeTaskWorld

from task_scheduler.application import (
    JobConflictError,
    JobNotFoundError,
    ManagedJsonImportPreview,
    StrictJsonDecodeError,
)
from task_scheduler.application.job_service import JobService
from task_scheduler.application.managed_json_transfer import (
    strict_decode_job_json,
)

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


# -- strict decoder --------------------------------------------------------


def test_decode_valid_v2_preserves_identity() -> None:
    job = strict_decode_job_json(json.dumps(v2_payload()))
    assert job.id == FIXED_JOB_ID
    assert job.label == _LABEL
    assert job.schema_version == 2


def test_decode_valid_v1_migrates_to_calendar() -> None:
    job = strict_decode_job_json(json.dumps(v1_payload()))
    assert job.schema_version == 2
    assert job.schedule.kind == "calendar"
    assert job.schedule.times[0].hour == 7
    assert job.schedule.run_at_load is False


@pytest.mark.parametrize(
    ("raw", "err"),
    [
        ("{not json", "malformed JSON"),
        ("[1, 2, 3]", "object"),
    ],
)
def test_decode_malformed_or_non_object_raises(raw: str, err: str) -> None:
    with pytest.raises(StrictJsonDecodeError, match=err):
        strict_decode_job_json(raw)


@pytest.mark.parametrize(
    ("base", "patch"),
    [
        (lambda: v2_payload(), lambda p: p.update(bogus=1)),
        (lambda: v2_payload(), lambda p: p["command"].update(bogus=True)),  # type: ignore[index]
        (lambda: v2_payload(), lambda p: p["environment"].update(bogus=True)),  # type: ignore[index]
        (lambda: v2_payload(), lambda p: p["logging"].update(bogus=True)),  # type: ignore[index]
        (lambda: v2_payload(), lambda p: p["schedule"].update(bogus=True)),  # type: ignore[index]
        (lambda: v1_payload(), lambda p: p["schedule"].update(bogus=True)),  # type: ignore[index]
        (
            lambda: v2_payload(),
            lambda p: p.update(
                schedule={"kind": "interval", "seconds": 300, "run_at_load": False, "bogus": 1}
            ),
        ),
    ],
)
def test_decode_unknown_field_raises(base, patch) -> None:
    payload = base()
    patch(payload)
    with pytest.raises(StrictJsonDecodeError, match="bogus"):
        strict_decode_job_json(json.dumps(payload))


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


def test_strict_error_is_value_error() -> None:
    assert issubclass(StrictJsonDecodeError, ValueError)


# -- JobService.transfer_conflicts ----------------------------------------


def test_transfer_conflicts_none_when_free(tmp_path: Path) -> None:
    jobs = JobService(tmp_path)
    job = make_job()
    assert jobs.transfer_conflicts(job) == (None, None)


def test_transfer_conflicts_reports_id_path(tmp_path: Path) -> None:
    jobs = JobService(tmp_path)
    jobs.import_job(make_job())  # writes {_ID}.json
    other = make_job(id=FIXED_JOB_ID, label="com.example.other")
    id_conflict, label_conflict = jobs.transfer_conflicts(other)
    assert id_conflict == tmp_path / f"{_ID}.json"
    assert label_conflict is None


def test_transfer_conflicts_reports_label_path(tmp_path: Path) -> None:
    jobs = JobService(tmp_path)
    jobs.import_job(make_job())  # {_ID}.json with the default label
    other = make_job(id=UUID(_OTHER_ID), label=_LABEL)
    id_conflict, label_conflict = jobs.transfer_conflicts(other)
    assert id_conflict is None
    assert label_conflict == tmp_path / f"{_ID}.json"


# -- service façades -------------------------------------------------------


def test_export_writes_canonical_and_is_catalog_only(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.jobs.import_job(job)
    dest = tmp_path / "export" / "daily.json"
    written = world.services.export_managed_json(_LABEL, dest)
    assert written == dest
    # canonical render, byte-identical to the catalog record
    assert dest.read_text("utf-8") == (world.catalog_root / f"{job.id}.json").read_text("utf-8")
    # export touches nothing else: catalog record intact, nothing deployed
    assert (world.catalog_root / f"{job.id}.json").is_file()
    assert not list(world.la_root.glob("*.plist"))
    assert world.launch_runner.specs == []


def test_export_refuses_existing_destination(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    world.jobs.import_job(make_job())
    dest = tmp_path / "existing.json"
    dest.write_text("{}", "utf-8")
    with pytest.raises(FileExistsError):
        world.services.export_managed_json(_LABEL, dest)


def test_export_unknown_label_raises(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    with pytest.raises(JobNotFoundError):
        world.services.export_managed_json("com.example.missing", tmp_path / "x.json")


def test_preview_no_conflict_is_importable(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    src = write_json(tmp_path / "src.json", v2_payload())
    preview = world.services.preview_managed_json_import(src)
    assert isinstance(preview, ManagedJsonImportPreview)
    assert preview.source_path == src
    assert preview.candidate.id == FIXED_JOB_ID
    assert preview.normalized_schema_version == 2
    assert preview.id_conflict_path is None
    assert preview.label_conflict_path is None
    assert preview.can_import is True
    assert world.launch_runner.specs == []


def test_preview_v1_source_is_normalized(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    src = write_json(tmp_path / "v1.json", v1_payload())
    preview = world.services.preview_managed_json_import(src)
    assert preview.normalized_schema_version == 2
    assert preview.candidate.schedule.kind == "calendar"
    assert preview.can_import is True


def test_preview_reports_id_conflict(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    world.jobs.import_job(make_job())  # claims {_ID}.json
    src = write_json(tmp_path / "src.json", v2_payload())
    preview = world.services.preview_managed_json_import(src)
    assert preview.id_conflict_path == world.catalog_root / f"{_ID}.json"
    assert preview.label_conflict_path is None
    assert preview.can_import is False


def test_preview_reports_label_conflict(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    world.jobs.import_job(make_job())  # {_ID}.json claims _LABEL
    payload = v2_payload()
    payload["id"] = _OTHER_ID
    src = write_json(tmp_path / "src.json", payload)
    preview = world.services.preview_managed_json_import(src)
    assert preview.id_conflict_path is None
    assert preview.label_conflict_path == world.catalog_root / f"{_ID}.json"
    assert preview.can_import is False


def test_preview_invalid_payload_raises(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    src = write_json(tmp_path / "bad.json", "{not json")
    with pytest.raises(StrictJsonDecodeError):
        world.services.preview_managed_json_import(src)


def test_import_preserves_identity_and_writes_one_file(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    src = write_json(tmp_path / "src.json", v2_payload())
    preview = world.services.preview_managed_json_import(src)
    job = world.services.import_managed_json(preview)
    assert job.id == FIXED_JOB_ID
    assert [f.name for f in world.catalog_root.glob("*.json")] == [f"{_ID}.json"]
    # catalog-only: nothing deployed, no launchctl, no direct test
    assert not list(world.la_root.glob("*.plist"))
    assert world.launch_runner.specs == []
    assert world.test_runner.specs == []


def test_import_rechecks_conflict_at_commit(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    src = write_json(tmp_path / "src.json", v2_payload())
    preview = world.services.preview_managed_json_import(src)  # clean at preview
    world.jobs.import_job(make_job())  # concurrent import claims the id
    with pytest.raises(JobConflictError):
        world.services.import_managed_json(preview)


# -- reveal_path -----------------------------------------------------------


def test_reveal_existing_returns_none_and_records(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    target = tmp_path / "target.txt"
    target.write_text("x", "utf-8")
    assert world.services.reveal_path(target) is None
    assert world.finder_revealer.revealed == [target]


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


# -- eager loaded status in list_agents -----------------------------------


def test_list_agents_eager_loaded_for_discovered_and_saved(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)  # sticky exit 0 -> discovered rows loaded
    discovered_job = make_job(name="Discovered", label="com.example.discovered")
    world.manage(discovered_job)
    saved_job = make_job(
        id=UUID(_OTHER_ID),
        name="Saved",
        label="com.example.saved",
    )
    world.jobs.import_job(saved_job)
    listings = world.services.list_agents()
    by_label = {listing.job.label: listing for listing in listings if listing.job}
    assert by_label["com.example.discovered"].loaded is True
    assert by_label["com.example.saved"].loaded is None


def test_loaded_status(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)  # sticky exit 0 -> loaded True
    assert world.services._loaded_status(None) is None
    assert world.services._loaded_status("com.example/bad") is None
    assert world.services._loaded_status("com.example.ok") is True
