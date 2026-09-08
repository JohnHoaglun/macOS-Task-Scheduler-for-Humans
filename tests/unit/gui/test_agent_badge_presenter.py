"""Tests for the agent badge presenter (tooltips + badge descriptors)."""

from __future__ import annotations

from pathlib import Path

from conftest import make_job
from task_scheduler.application.task_command_service import ListingKind, TaskListing
from task_scheduler.domain import ExecutableCommand, ShellCommand
from task_scheduler.gui.presenters.agent_badge_presenter import agent_badges
from task_scheduler.platform.macos import ParsedLaunchAgent, ParseSupport

TEST_PATH = Path("/Users/example/Library/LaunchAgents/com.example.plist")


def _parsed(**overrides: object) -> ParsedLaunchAgent:
    kwargs: dict[str, object] = {"status": ParseSupport.SUPPORTED}
    kwargs.update(overrides)
    return ParsedLaunchAgent(**kwargs)  # type: ignore[arg-type]


def _mk(job=None, *, managed=True, parsed=None, loaded=None, kind=ListingKind.DISCOVERED):
    path = None if kind is ListingKind.SAVED else TEST_PATH
    return TaskListing(kind=kind, path=path, parsed=parsed, job=job, managed=managed, loaded=loaded)


INVALID = _parsed(status=ParseSupport.INVALID, raw={"Label": "x"})
NO_JOB = _parsed(
    status=ParseSupport.PARTIALLY_SUPPORTED, raw={"ProgramArguments": ["/bin/zsh", "-c", "echo"]}
)


def test_descriptors_and_managed_tooltips() -> None:
    badges = agent_badges(_mk(job=make_job(), parsed=_parsed(), loaded=True))
    expected = {
        "state": ("Managed", "State: Managed", "Managed by the task catalog"),
        "installed": (
            "installed",
            "Installed: installed",
            "Plist discovered in the LaunchAgents directory",
        ),
        "enabled": ("enabled", "Enabled: enabled", "Job is configured to run"),
        "loaded": ("loaded", "Loaded: loaded", "Job is currently loaded in launchd"),
        "command": ("python", "Command: python", "Python script command"),
    }
    for field, (text, name, tip) in expected.items():
        badge = getattr(badges, field)
        assert (badge.text, badge.accessible_name, badge.tooltip) == (text, name, tip)


def test_remaining_tooltips() -> None:
    shell = make_job(command=ShellCommand(executable="/bin/zsh"))
    exe = make_job(command=ExecutableCommand(executable="/usr/bin/ls"))
    tips = {
        "state": agent_badges(_mk(managed=False, job=make_job(), parsed=_parsed())).state,
        "invalid": agent_badges(_mk(managed=False, parsed=INVALID)).state,
        "saved": agent_badges(_mk(kind=ListingKind.SAVED, job=make_job())).installed,
        "disabled": agent_badges(_mk(job=make_job(enabled=False), parsed=_parsed())).enabled,
        "not_loaded": agent_badges(_mk(job=make_job(), parsed=_parsed(), loaded=False)).loaded,
        "shell": agent_badges(_mk(job=shell, parsed=_parsed())).command,
        "exe": agent_badges(_mk(job=exe, parsed=_parsed())).command,
    }
    unknowns = agent_badges(_mk(managed=False, parsed=NO_JOB))
    expected = {
        "state": "Third-party LaunchAgent, not managed by the catalog",
        "invalid": "Invalid or unrecognized agent",
        "saved": "Job saved in the catalog but not deployed as a plist",
        "disabled": "Job is configured but disabled",
        "not_loaded": "Job is installed but not loaded in launchd",
        "shell": "Shell command",
        "exe": "Direct executable command",
    }
    for key, tip in expected.items():
        assert tips[key].tooltip == tip
    assert unknowns.enabled.tooltip == "Enabled state could not be determined"
    assert unknowns.loaded.tooltip == "Load status is unknown"
    assert unknowns.command.tooltip == "Command type could not be determined"
