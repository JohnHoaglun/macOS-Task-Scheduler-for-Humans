"""Tests for the production composition root (service wiring)."""

from __future__ import annotations

from pathlib import Path

import pytest

from task_scheduler import bootstrap
from task_scheduler.platform.macos import PlistCodec


class _FakeRepository:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.calls = 0


class _RecordingCodec:
    """Wraps the real codec and records the wrapper path it was given."""

    def __init__(self) -> None:
        self.wrapper_path: object = "unset"

    def __call__(self, wrapper_path: object = None) -> PlistCodec:
        self.wrapper_path = wrapper_path
        return PlistCodec(wrapper_path=wrapper_path)


def _build_without_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the real wiring, but fake every constructor with side effects."""
    monkeypatch.setattr(bootstrap, "LaunchAgentStore", _FakeRepository)
    monkeypatch.setattr(bootstrap, "JsonJobRepository", _FakeRepository)
    monkeypatch.setattr(bootstrap, "ExecutionHistoryRepository", _FakeRepository)
    monkeypatch.setattr(bootstrap, "default_history_path", lambda: Path("/tmp/history"))
    codec = _RecordingCodec()
    monkeypatch.setattr(bootstrap, "PlistCodec", codec)
    return codec


class TestBuildServices:
    def test_deploys_wrapper_and_wires_codec(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wrapper = tmp_path / "run_wrapper.py"
        monkeypatch.setattr(bootstrap, "ensure_run_wrapper", lambda: wrapper)
        codec = _build_without_side_effects(monkeypatch)
        bootstrap.build_services()
        assert codec.wrapper_path == wrapper

    def test_missing_wrapper_falls_back_to_raw_codec(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise() -> Path:
            raise OSError("no local disk")

        monkeypatch.setattr(bootstrap, "ensure_run_wrapper", _raise)
        codec = _build_without_side_effects(monkeypatch)
        bootstrap.build_services()
        assert codec.wrapper_path is None
