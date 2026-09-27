"""Unit tests for the external-control DTOs (Stage 0 shared contract): the frozen, typed shapes each
lane builds against (preview, session, and result fields, incl. nonce, phase ordering, retained
artifacts, replaced/reloaded flags, and quarantine/remove extensions)."""

from __future__ import annotations

import base64
import plistlib
from pathlib import Path

from tests.conftest import make_job

from task_scheduler.application import ExternalEditSession
from task_scheduler.application.external_edit_models import RawPlistRead, read_raw_plist
from task_scheduler.platform.macos import ParseSupport

RAW_SOURCE = {"Label": "com.example.raw", "ProgramArguments": ["/bin/true"]}

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

def test_read_raw_plist_returns_utf8_text(tmp_path: Path) -> None:
    path = tmp_path / "agent.plist"
    text = plistlib.dumps(RAW_SOURCE, fmt=plistlib.FMT_XML).decode("utf-8")
    path.write_text(text)
    assert read_raw_plist(path) == RawPlistRead(text, False, None)

def test_read_raw_plist_base64_encodes_binary_source(tmp_path: Path) -> None:
    path = tmp_path / "agent.plist"
    data = plistlib.dumps(RAW_SOURCE, fmt=plistlib.FMT_BINARY)
    path.write_bytes(data)
    read = read_raw_plist(path)
    assert read.text == base64.b64encode(data).decode("ascii")
    assert read.binary_mode is True
    assert read.error is None

def test_read_raw_plist_missing_file_sets_error(tmp_path: Path) -> None:
    read = read_raw_plist(tmp_path / "missing.plist")
    assert read.text is None
    assert read.binary_mode is False
    assert read.error is not None
