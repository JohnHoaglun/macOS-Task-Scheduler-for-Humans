"""Unit tests for the external-edit DTOs (Stage 0 shared contract).

Pins the frozen, typed shapes every lane builds against: preview fields
(path, label, candidate, sha256, identity, loaded, nonce) and result
fields (process optional when unloaded, phase ordering, retained
artifacts, replaced/reloaded flags).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from tests.conftest import make_job

from task_scheduler.application import (
    ExternalEditPhase,
    ExternalEditPreview,
    ExternalEditResult,
)
from task_scheduler.platform.macos import ProcessResult


def make_preview(**overrides: object) -> ExternalEditPreview:
    kwargs: dict[str, object] = {
        "source_path": Path("/Users/example/Library/LaunchAgents/com.example.job.plist"),
        "label": "com.example.job",
        "candidate": make_job(label="com.example.job"),
        "sha256": "a" * 64,
        "identity": (1, 42),
        "loaded": True,
        "nonce": "nonce-1",
    }
    kwargs.update(overrides)
    return ExternalEditPreview(**kwargs)  # type: ignore[arg-type]


def test_preview_carries_fingerprint_and_nonce() -> None:
    preview = make_preview()
    assert preview.label == "com.example.job"
    assert preview.candidate.label == "com.example.job"
    assert preview.identity == (1, 42)
    assert preview.loaded is True
    assert preview.nonce == "nonce-1"


def test_preview_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        make_preview().label = "com.example.other"  # type: ignore[misc]


def test_preview_unloaded_state() -> None:
    assert make_preview(loaded=False).loaded is False


def test_result_loaded_success_shape() -> None:
    bootout = ProcessResult(exit_code=0)
    bootstrap = ProcessResult(exit_code=0)
    result = ExternalEditResult(
        source_path=make_preview().source_path,
        label="com.example.job",
        process=bootstrap,
        phases=(
            ExternalEditPhase("bootout", bootout),
            ExternalEditPhase("bootstrap", bootstrap),
        ),
        completed_phases=("bootout", "bootstrap"),
        retained_artifacts=(Path("/tmp/com.example.job.plist.backup.1"),),
        replaced=True,
        reloaded=True,
    )
    assert result.process is bootstrap
    assert result.completed_phases == ("bootout", "bootstrap")
    assert result.replaced is True
    assert result.reloaded is True
    assert len(result.retained_artifacts) == 1


def test_result_unloaded_success_has_no_process() -> None:
    result = ExternalEditResult(
        source_path=make_preview().source_path,
        label="com.example.job",
        process=None,
        phases=(),
        completed_phases=(),
        retained_artifacts=(Path("/tmp/com.example.job.plist.backup.1"),),
        replaced=True,
        reloaded=False,
    )
    assert result.process is None
    assert result.replaced is True
    assert result.reloaded is False


def test_result_bootout_failure_retains_staged() -> None:
    bootout = ProcessResult(exit_code=5)
    result = ExternalEditResult(
        source_path=make_preview().source_path,
        label="com.example.job",
        process=bootout,
        phases=(ExternalEditPhase("bootout", bootout),),
        completed_phases=(),
        retained_artifacts=(Path("/tmp/com.example.job.plist.staged.1"),),
        replaced=False,
        reloaded=False,
    )
    assert result.replaced is False
    assert result.completed_phases == ()


def test_result_is_frozen() -> None:
    result = ExternalEditResult(
        source_path=Path("/tmp/job.plist"),
        label="com.example.job",
        process=None,
        phases=(),
        completed_phases=(),
        retained_artifacts=(),
        replaced=True,
        reloaded=False,
    )
    with pytest.raises(FrozenInstanceError):
        result.replaced = False  # type: ignore[misc]
