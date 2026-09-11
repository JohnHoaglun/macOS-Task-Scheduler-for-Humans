"""Unit tests for external-plist direct-edit service methods.

Covers per-gate preview rejections, preview success, commit rejections,
and the full commit transaction (loaded/unloaded/bootout-fail/bootstrap-fail).
Uses FakeProcessRunner results queues for scripted lifecycle tests.
"""

from __future__ import annotations

import plistlib
from datetime import timedelta
from pathlib import Path

import pytest
from tests.conftest import make_job
from tests.fakes import OK_PROCESS, FakeProcessRunner, FakeTaskWorld

from task_scheduler.application.external_edit_models import ExternalEditPreview


def write_plist(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(payload))


def supported_job(label: str = "com.external.task") -> dict[str, object]:
    return {
        "Label": label,
        "ProgramArguments": ["/usr/local/bin/cleanup.sh"],
        "StartCalendarInterval": [{"Hour": 3, "Minute": 0, "Weekday": 1}],
    }


def _loaded_result() -> FakeProcessRunner:
    return FakeProcessRunner(result=OK_PROCESS)


# -- preview rejection gates ------------------------------------------------


def test_preview_outside_root(tmp_path: Path) -> None:
    la = tmp_path / "launchagents"
    la.mkdir()
    write_plist(la / "x.plist", supported_job())
    world = FakeTaskWorld(tmp_path)
    with pytest.raises(ValueError):
        world.services.preview_external_plist_edit(la.parent / "elsewhere" / "x.plist")
    assert [f.name for f in la.glob("*.plist")] == ["x.plist"]
    assert world.launch_runner.specs == []


def test_preview_symlink(tmp_path: Path) -> None:
    la = tmp_path / "launchagents"
    la.mkdir()
    write_plist(la / "x.plist", supported_job())
    sym = la / "link.plist"
    sym.symlink_to(la / "x.plist")
    world = FakeTaskWorld(tmp_path)
    with pytest.raises(ValueError):
        world.services.preview_external_plist_edit(sym)
    assert world.launch_runner.specs == []


def test_preview_directory(tmp_path: Path) -> None:
    la = tmp_path / "launchagents"
    la.mkdir()
    (la / "adir").mkdir()
    world = FakeTaskWorld(tmp_path)
    with pytest.raises(ValueError):
        world.services.preview_external_plist_edit(la / "adir")
    assert world.launch_runner.specs == []


def test_preview_missing(tmp_path: Path) -> None:
    la = tmp_path / "launchagents"
    la.mkdir()
    world = FakeTaskWorld(tmp_path)
    with pytest.raises(ValueError):
        world.services.preview_external_plist_edit(la / "missing.plist")
    assert world.launch_runner.specs == []


def test_preview_partial(tmp_path: Path) -> None:
    la = tmp_path / "launchagents"
    la.mkdir()
    payload = supported_job()
    payload["WatchPaths"] = ["/tmp"]
    write_plist(la / "com.external.task.plist", payload)
    world = FakeTaskWorld(tmp_path)
    with pytest.raises(ValueError) as exc:
        world.services.preview_external_plist_edit(la / "com.external.task.plist")
    assert "cannot edit" in str(exc.value)
    assert world.launch_runner.specs == []


def test_preview_invalid(tmp_path: Path) -> None:
    la = tmp_path / "launchagents"
    la.mkdir()
    p = la / "bad.plist"
    p.write_bytes(b"not a plist\x00\xff")
    world = FakeTaskWorld(tmp_path)
    with pytest.raises(ValueError) as exc:
        world.services.preview_external_plist_edit(p)
    assert "cannot edit" in str(exc.value)


def test_preview_managed_label(tmp_path: Path) -> None:
    la = tmp_path / "launchagents"
    la.mkdir()
    label = "com.external.managed"
    job = make_job(label=label)
    world = FakeTaskWorld(tmp_path)
    world.manage(job)
    write_plist(la / f"{label}.plist", supported_job(label))
    with pytest.raises(ValueError) as exc:
        world.services.preview_external_plist_edit(la / f"{label}.plist")
    assert f"label is already managed: {label}" in str(exc.value)
    assert world.launch_runner.specs == []


def test_preview_status_unknown(tmp_path: Path) -> None:
    la = tmp_path / "launchagents"
    la.mkdir()
    label = "com.external.task"
    write_plist(la / f"{label}.plist", supported_job(label))
    status_none = type("", (), {
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "duration": timedelta(),
    })()
    world = FakeTaskWorld(tmp_path)
    runner = FakeProcessRunner(result=status_none)
    world.launch_runner = runner
    world.backend._runner = runner
    with pytest.raises(ValueError) as exc:
        world.services.preview_external_plist_edit(la / f"{label}.plist")
    assert "launchd status is unknown" in str(exc.value)


# -- preview success ---------------------------------------------------------


def test_preview_success(tmp_path: Path) -> None:
    la = tmp_path / "launchagents"
    la.mkdir()
    label = "com.external.task"
    write_plist(la / f"{label}.plist", supported_job(label))
    world = FakeTaskWorld(tmp_path)
    preview = world.services.preview_external_plist_edit(la / f"{label}.plist")
    assert isinstance(preview, ExternalEditPreview)
    assert preview.source_path == la / f"{label}.plist"
    assert preview.label == label
    assert preview.nonce and len(preview.nonce) == 32
    assert preview.loaded is True
    assert len(preview.sha256) == 64
    assert preview.candidate is not None


# -- commit rejection gates --------------------------------------------------


@pytest.mark.parametrize(
    "nonce",
    ["wrongnonce", "a" * 32],
    ids=["short-wrong", "32char-wrong"],
)
def test_commit_reject_nonce(tmp_path: Path, nonce: str) -> None:
    la = tmp_path / "launchagents"
    la.mkdir()
    label = "com.external.task"
    write_plist(la / f"{label}.plist", supported_job(label))
    world = FakeTaskWorld(tmp_path)
    preview = world.services.preview_external_plist_edit(la / f"{label}.plist")
    before_count = len(world.launch_runner.specs)
    edited = preview.candidate.model_copy()
    with pytest.raises(ValueError) as exc:
        world.services.commit_external_plist_edit(preview, edited, nonce=nonce)
    assert "preview nonce does not match" in str(exc.value)
    assert len(world.launch_runner.specs) == before_count
    assert list(la.glob("*.plist")) == [la / f"{label}.plist"]


def test_commit_reject_label_change(tmp_path: Path) -> None:
    la = tmp_path / "launchagents"
    la.mkdir()
    label = "com.external.task"
    write_plist(la / f"{label}.plist", supported_job(label))
    world = FakeTaskWorld(tmp_path)
    preview = world.services.preview_external_plist_edit(la / f"{label}.plist")
    edited = preview.candidate.model_copy(update={"label": "com.other.task"})
    with pytest.raises(ValueError) as exc:
        world.services.commit_external_plist_edit(preview, edited, nonce=preview.nonce)
    assert f"label cannot change in an external edit: {label} -> com.other.task" in str(
        exc.value
    )


def test_commit_reject_source_changed(tmp_path: Path) -> None:
    la = tmp_path / "launchagents"
    la.mkdir()
    label = "com.external.task"
    p = la / f"{label}.plist"
    write_plist(p, supported_job(label))
    world = FakeTaskWorld(tmp_path)
    preview = world.services.preview_external_plist_edit(p)
    p.write_bytes(b"changed bytes\x00")
    edited = preview.candidate.model_copy()
    with pytest.raises(ValueError) as exc:
        world.services.commit_external_plist_edit(preview, edited, nonce=preview.nonce)
    assert "the source plist changed" in str(exc.value)


# -- loaded success ----------------------------------------------------------


def test_commit_loaded_success(tmp_path: Path) -> None:
    la = tmp_path / "launchagents"
    la.mkdir()
    label = "com.external.task"
    write_plist(la / f"{label}.plist", supported_job(label))
    world = FakeTaskWorld(tmp_path)
    preview = world.services.preview_external_plist_edit(la / f"{label}.plist")
    assert preview.loaded is True
    before_count = len(list(la.glob("*.plist")))
    edited = preview.candidate.model_copy()
    result = world.services.commit_external_plist_edit(
        preview, edited, nonce=preview.nonce
    )
    assert result.replaced is True
    assert result.reloaded is True
    assert result.process is not None and result.process.exit_code == 0
    assert len(result.phases) == 2
    assert result.phases[0].name == "bootout"
    assert result.phases[1].name == "bootstrap"
    assert result.completed_phases == ("bootout", "bootstrap")
    assert len(result.retained_artifacts) == 1
    assert ".backup." in result.retained_artifacts[0].name
    # staged file was removed; backup remains but doesn't match *.plist glob
    assert len(list(la.glob("*.plist"))) == before_count
    specs = world.launch_runner.specs
    assert len(specs) == 3
    assert specs[0].argv[1] == "print"
    assert specs[1].argv[1] == "bootout"
    assert specs[2].argv[1] == "bootstrap"
    assert str(la / f"{label}.plist") in specs[2].argv[3]


# -- unloaded success --------------------------------------------------------


def test_commit_unloaded_success(tmp_path: Path) -> None:
    la = tmp_path / "launchagents"
    la.mkdir()
    label = "com.external.task"
    write_plist(la / f"{label}.plist", supported_job(label))
    not_loaded = type("", (), {
        "exit_code": 1,
        "stdout": "",
        "stderr": "",
        "duration": timedelta(),
    })()
    world = FakeTaskWorld(tmp_path)
    runner = FakeProcessRunner(result=not_loaded)
    world.launch_runner = runner
    world.backend._runner = runner
    preview = world.services.preview_external_plist_edit(la / f"{label}.plist")
    assert preview.loaded is False
    edited = preview.candidate.model_copy()
    result = world.services.commit_external_plist_edit(
        preview, edited, nonce=preview.nonce
    )
    assert result.replaced is True
    assert result.reloaded is False
    assert result.process is None
    assert result.phases == ()
    assert result.completed_phases == ()
    assert len(result.retained_artifacts) == 1
    assert len(world.launch_runner.specs) == 1  # just the status print from preview


# -- bootout failure ---------------------------------------------------------


def test_commit_bootout_failure(tmp_path: Path) -> None:
    la = tmp_path / "launchagents"
    la.mkdir()
    label = "com.external.task"
    original = plistlib.dumps(supported_job(label))
    p = la / f"{label}.plist"
    p.write_bytes(original)
    bootout_fail = type("", (), {
        "exit_code": 1,
        "stdout": "err",
        "stderr": "error",
        "duration": timedelta(),
    })()
    runner = FakeProcessRunner(results=[OK_PROCESS, bootout_fail])
    world = FakeTaskWorld(tmp_path)
    world.launch_runner = runner
    world.backend._runner = runner
    preview = world.services.preview_external_plist_edit(p)
    assert preview.loaded is True
    edited = preview.candidate.model_copy()
    result = world.services.commit_external_plist_edit(
        preview, edited, nonce=preview.nonce
    )
    assert result.replaced is False
    assert result.reloaded is False
    assert result.process.exit_code == 1
    assert len(result.phases) == 1
    assert result.phases[0].name == "bootout"
    assert result.completed_phases == ()
    assert len(result.retained_artifacts) == 1
    assert ".staged." in result.retained_artifacts[0].name
    assert p.read_bytes() == original


# -- bootstrap failure -------------------------------------------------------


def test_commit_bootstrap_failure(tmp_path: Path) -> None:
    la = tmp_path / "launchagents"
    la.mkdir()
    label = "com.external.task"
    original = plistlib.dumps(supported_job(label))
    p = la / f"{label}.plist"
    p.write_bytes(original)
    ok_result = OK_PROCESS
    boot_fail = type("", (), {
        "exit_code": 1,
        "stdout": "",
        "stderr": "bootstrap error",
        "duration": timedelta(),
    })()
    runner = FakeProcessRunner(results=[ok_result, ok_result, boot_fail])
    world = FakeTaskWorld(tmp_path)
    world.launch_runner = runner
    world.backend._runner = runner
    preview = world.services.preview_external_plist_edit(p)
    assert preview.loaded is True
    edited = preview.candidate.model_copy()
    result = world.services.commit_external_plist_edit(
        preview, edited, nonce=preview.nonce
    )
    assert result.replaced is True
    assert result.reloaded is False
    assert result.process.exit_code == 1
    assert len(result.phases) == 2
    assert result.completed_phases == ("bootout",)
    assert len(result.retained_artifacts) == 1
    assert ".backup." in result.retained_artifacts[0].name


# -- catalog never touched ---------------------------------------------------


def test_catalog_untouched_in_commit(tmp_path: Path) -> None:
    """External edit never writes or changes catalog JSON files."""
    la = tmp_path / "launchagents"
    la.mkdir()
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    label = "com.external.task"
    write_plist(la / f"{label}.plist", supported_job(label))
    world = FakeTaskWorld(tmp_path)
    preview = world.services.preview_external_plist_edit(la / f"{label}.plist")
    before_files = {f.name for f in catalog.glob("*.json")}
    result = world.services.commit_external_plist_edit(
        preview, preview.candidate.model_copy(), nonce=preview.nonce
    )
    after_files = {f.name for f in catalog.glob("*.json")}
    assert before_files == after_files
    assert result.replaced is True
