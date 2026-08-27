"""Opt-in launchctl integration tests (Increment 7).

These tests touch the real ``~/Library/LaunchAgents`` directory and the real
``/bin/launchctl``, and only run when explicitly requested:

    MACTASK_ALLOW_SYSTEM_TESTS=1 make integration

Plain ``pytest`` excludes them through the ``integration`` marker
(pyproject addopts), and ``make integration`` without the environment
variable skips every test. Test jobs use unique UUID labels and cleanup is
unconditional, touching only the test-owned plist.
"""

from __future__ import annotations

import contextlib
import os
import uuid

import pytest
from tests.conftest import make_job

from task_scheduler.domain import ShellCommand
from task_scheduler.platform.macos import (
    LaunchAgentBackend,
    LaunchAgentStore,
    LaunchctlAction,
    SubprocessRunner,
)

pytestmark = pytest.mark.integration


def _opted_in() -> bool:
    return os.environ.get("MACTASK_ALLOW_SYSTEM_TESTS") == "1"


@pytest.fixture()
def test_label():
    """Yield a unique label with a real backend; clean up unconditionally."""
    if not _opted_in():
        pytest.skip(
            "set MACTASK_ALLOW_SYSTEM_TESTS=1 to run launchctl integration tests"
        )
    label = f"io.github.mactaskscheduler.test.{uuid.uuid4()}"
    store = LaunchAgentStore()
    backend = LaunchAgentBackend(store, SubprocessRunner())
    yield label
    with contextlib.suppress(Exception):
        backend.uninstall(label)
    store.remove(label)


def _echo_job(label: str):
    return make_job(
        label=label,
        command=ShellCommand(executable="/bin/echo", arguments=["mactask-integration"]),
    )


def test_lifecycle_roundtrip(test_label: str) -> None:
    store = LaunchAgentStore()
    backend = LaunchAgentBackend(store, SubprocessRunner())
    job = _echo_job(test_label)

    installed = backend.install(job)
    assert installed.action is LaunchctlAction.INSTALL
    assert installed.process.exit_code == 0, installed.process.stderr

    assert backend.status(test_label).loaded is True

    disabled = backend.disable(test_label)
    assert disabled.process.exit_code == 0, disabled.process.stderr

    enabled = backend.enable(test_label)
    assert enabled.process.exit_code == 0, enabled.process.stderr

    triggered = backend.trigger(test_label)
    assert triggered.process.exit_code == 0, triggered.process.stderr

    uninstalled = backend.uninstall(test_label)
    assert uninstalled.process.exit_code == 0, uninstalled.process.stderr

    assert backend.status(test_label).loaded is False
    assert not store.destination_for(test_label).exists()


def test_uninstall_never_installed_is_structured_failure(test_label: str) -> None:
    backend = LaunchAgentBackend(LaunchAgentStore(), SubprocessRunner())

    result = backend.uninstall(test_label)

    assert result.action is LaunchctlAction.UNINSTALL
    assert result.process.exit_code is not None
    assert result.process.exit_code != 0
    assert not LaunchAgentStore().destination_for(test_label).exists()
