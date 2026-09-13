"""Unit tests for the external-control DTOs (Stage 0 shared contract).

Pins the frozen, typed shapes every lane builds against: preview fields
(path, label, candidate, sha256, identity, loaded, nonce), session
fields (original, label/loaded optional, status, job, edit_mode), and
result fields (process optional when unloaded, phase ordering, retained
artifacts, replaced/reloaded flags, quarantine/remove extensions).
"""

from __future__ import annotations

from pathlib import Path

from tests.conftest import make_job

from task_scheduler.application import (
    ExternalEditSession,
)
from task_scheduler.platform.macos import ParseSupport


def make_session(**overrides: object) -> ExternalEditSession:
    kwargs: dict[str, object] = {
        "source_path": Path("/Users/example/Library/LaunchAgents/com.example.job.plist"),
        "sha256": "b" * 64,
        "identity": (1, 43),
        "nonce": "session-1",
        "label": "com.example.job",
        "loaded": True,
        "original": {"Label": "com.example.job"},
        "status": ParseSupport.SUPPORTED,
        "job": make_job(label="com.example.job"),
    }
    kwargs.update(overrides)
    return ExternalEditSession(**kwargs)  # type: ignore[arg-type]


def test_session_structured_edit_mode() -> None:
    session = make_session()
    assert session.edit_mode() == "structured"
    assert session.label == "com.example.job"
    assert session.loaded is True
    assert session.original == {"Label": "com.example.job"}
