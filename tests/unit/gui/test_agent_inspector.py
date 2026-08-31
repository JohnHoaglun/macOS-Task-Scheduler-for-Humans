"""Tests for the agent inspector widget (offscreen Qt)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel, QScrollArea, QTextEdit
from pytestqt.qtbot import QtBot

from conftest import make_job
from task_scheduler.application.task_command_service import (
    DiscoveredInspectReport,
    ListingKind,
    TaskListing,
)
from task_scheduler.gui.presenters.agent_presenter import (
    format_environment,
    format_schedule,
    format_warnings,
)
from task_scheduler.gui.widgets.agent_inspector import AgentInspector
from task_scheduler.platform.macos import (
    LaunchAgentStatus,
    ParsedLaunchAgent,
    ParseSupport,
    ProcessResult,
)

MANAGED_PATH = Path("/Users/example/Library/LaunchAgents/com.example.backup.plist")
EXTERNAL_PATH = Path("/Users/example/Library/LaunchAgents/com.example.external.plist")
INVALID_PATH = Path("/Users/example/Library/LaunchAgents/com.example.bad.plist")


def _managed_listing() -> TaskListing:
    job = make_job()
    parsed = ParsedLaunchAgent(
        status=ParseSupport.SUPPORTED,
        job=job,
        raw={"Label": job.label},
    )
    return TaskListing(
        kind=ListingKind.DISCOVERED,
        path=MANAGED_PATH,
        parsed=parsed,
        job=job,
        managed=True,
    )


def _disabled_listing() -> TaskListing:
    job = make_job(enabled=False)
    parsed = ParsedLaunchAgent(
        status=ParseSupport.SUPPORTED,
        job=job,
        raw={"Label": job.label},
    )
    return TaskListing(
        kind=ListingKind.DISCOVERED,
        path=MANAGED_PATH,
        parsed=parsed,
        job=job,
        managed=True,
    )


def _external_listing() -> TaskListing:
    parsed = ParsedLaunchAgent(
        status=ParseSupport.PARTIALLY_SUPPORTED,
        raw={"ProgramArguments": ["/bin/zsh", "/Users/example/scripts/x.sh"]},
        unsupported_keys=["KeepAlive"],
        warnings=["no calendar schedule found"],
    )
    return TaskListing(
        kind=ListingKind.DISCOVERED,
        path=EXTERNAL_PATH,
        parsed=parsed,
        job=None,
        managed=False,
    )


def _invalid_listing() -> TaskListing:
    parsed = ParsedLaunchAgent(
        status=ParseSupport.INVALID,
        raw={"Label": "com.example.bad"},
        warnings=["plist has no ProgramArguments"],
    )
    return TaskListing(
        kind=ListingKind.DISCOVERED,
        path=INVALID_PATH,
        parsed=parsed,
        job=None,
        managed=False,
    )


def _saved_listing() -> TaskListing:
    job = make_job()
    return TaskListing(kind=ListingKind.SAVED, path=None, parsed=None, job=job, managed=True)


def _report(
    listing: TaskListing, status: LaunchAgentStatus | None = None
) -> DiscoveredInspectReport:
    assert listing.path is not None
    assert listing.parsed is not None
    return DiscoveredInspectReport(
        path=listing.path,
        parsed=listing.parsed,
        managed=listing.managed,
        status=status,
    )


def _value_label(inspector: AgentInspector, object_name: str) -> QLabel:
    """The named value QLabel, asserted present."""
    label = inspector.findChild(QLabel, object_name)
    assert label is not None
    return label


def _message_label(inspector: AgentInspector) -> QLabel:
    """The top-level message QLabel.

    Every value QLabel is re-parented into its group box by the layouts, so
    the message is the only QLabel whose parent is the inspector itself.
    """
    direct = [
        label
        for label in inspector.findChildren(QLabel)
        if label.parent() is not None and label.parent() == inspector
    ]
    assert len(direct) == 1
    return direct[0]


def _scroll_area(inspector: AgentInspector) -> QScrollArea:
    scroll = inspector.findChild(QScrollArea)
    assert scroll is not None
    return scroll


def _advanced_text(inspector: AgentInspector) -> QTextEdit:
    text = inspector.findChild(QTextEdit, "advanced-text")
    assert text is not None
    return text


@pytest.fixture
def inspector(qtbot: QtBot) -> AgentInspector:
    widget = AgentInspector()
    qtbot.addWidget(widget)
    widget.show()
    return widget


class TestInitialState:
    def test_message_shown_and_form_hidden(self, inspector: AgentInspector) -> None:
        message = _message_label(inspector)
        assert message.text() == "Select a task to inspect its details."
        assert message.isVisible()
        assert _scroll_area(inspector).isHidden()


class TestShowAgentManaged:
    def test_supported_managed_fields(self, inspector: AgentInspector) -> None:
        listing = _managed_listing()
        inspector.show_agent(listing, _report(listing))
        assert _scroll_area(inspector).isVisible()
        assert not _message_label(inspector).isVisible()
        assert _value_label(inspector, "overview-name").text() == "Daily Backup"
        assert _value_label(inspector, "overview-label").text() == (
            "io.github.macos-task-scheduler.user.daily-backup"
        )
        assert _value_label(inspector, "overview-classification").text() == "Managed"
        assert _value_label(inspector, "overview-source").text() == str(MANAGED_PATH)
        assert _value_label(inspector, "overview-enabled").text() == "enabled"
        assert _value_label(inspector, "overview-loaded").text() == "unknown"
        assert _value_label(inspector, "overview-state").text() == "Status unknown"
        assert _value_label(inspector, "command-command").text() == (
            "/Users/example/project/.venv/bin/python /Users/example/project/main.py "
            "--mode daily"
        )
        assert _value_label(inspector, "command-working-directory").text() == "not set"
        assert _value_label(inspector, "schedule-text").text() == format_schedule(listing)
        assert (
            _value_label(inspector, "environment-text").text()
            == format_environment(listing)
        )
        assert _value_label(inspector, "environment-text").text() == "none configured"
        assert _value_label(inspector, "warnings-text").text() == "none"
        advanced = _advanced_text(inspector)
        assert (
            "io.github.macos-task-scheduler.user.daily-backup" in advanced.toPlainText()
        )
        assert advanced.isReadOnly()

    def test_status_loaded(self, inspector: AgentInspector) -> None:
        listing = _managed_listing()
        status = LaunchAgentStatus(loaded=True, process=ProcessResult(exit_code=0))
        inspector.show_agent(listing, _report(listing, status))
        assert _value_label(inspector, "overview-loaded").text() == "loaded"
        assert (
            _value_label(inspector, "overview-state").text()
            == "Installed, configured enabled (loaded)"
        )

    def test_status_not_loaded(self, inspector: AgentInspector) -> None:
        listing = _managed_listing()
        status = LaunchAgentStatus(loaded=False, process=ProcessResult(exit_code=1))
        inspector.show_agent(listing, _report(listing, status))
        assert _value_label(inspector, "overview-loaded").text() == "not loaded"
        assert (
            _value_label(inspector, "overview-state").text()
            == "Installed, configured enabled (not loaded)"
        )

    def test_state_disabled_configured(self, inspector: AgentInspector) -> None:
        listing = _disabled_listing()
        status = LaunchAgentStatus(loaded=True, process=ProcessResult(exit_code=0))
        inspector.show_agent(listing, _report(listing, status))
        assert _value_label(inspector, "overview-enabled").text() == "disabled"
        assert (
            _value_label(inspector, "overview-state").text()
            == "Installed, configured disabled (loaded)"
        )


class TestShowSaved:
    def test_saved_fields(self, inspector: AgentInspector) -> None:
        listing = _saved_listing()
        inspector.show_saved(listing)
        assert _scroll_area(inspector).isVisible()
        assert not _message_label(inspector).isVisible()
        assert _value_label(inspector, "overview-name").text() == "Daily Backup"
        assert _value_label(inspector, "overview-label").text() == (
            "io.github.macos-task-scheduler.user.daily-backup"
        )
        assert _value_label(inspector, "overview-classification").text() == "Managed"
        assert _value_label(inspector, "overview-source").text() == (
            "(task catalog — not installed)"
        )
        assert _value_label(inspector, "overview-enabled").text() == "enabled"
        assert _value_label(inspector, "overview-loaded").text() == "not installed"
        assert _value_label(inspector, "overview-state").text() == "Saved, not installed"
        assert _value_label(inspector, "command-command").text() == (
            "/Users/example/project/.venv/bin/python /Users/example/project/main.py "
            "--mode daily"
        )
        assert _value_label(inspector, "schedule-text").text() == "at 07:30:00 on Monday"
        assert _value_label(inspector, "warnings-text").text() == "none"
        assert _advanced_text(inspector).toPlainText() == (
            "(no deployed plist — saved in the task catalog)"
        )

    def test_saved_replaces_agent(self, inspector: AgentInspector) -> None:
        listing = _managed_listing()
        inspector.show_agent(listing, _report(listing))
        inspector.show_saved(_saved_listing())
        assert _value_label(inspector, "overview-source").text() == (
            "(task catalog — not installed)"
        )
        assert _value_label(inspector, "overview-loaded").text() == "not installed"


class TestShowAgentInvalid:
    def test_invalid_fields(self, inspector: AgentInspector) -> None:
        listing = _invalid_listing()
        inspector.show_agent(listing, _report(listing))
        assert _value_label(inspector, "overview-classification").text() == "Invalid"
        assert _value_label(inspector, "command-command").text() == "—"
        assert _value_label(inspector, "schedule-text").text() == "—"
        warnings = _value_label(inspector, "warnings-text").text()
        assert warnings == format_warnings(listing)
        assert warnings != "none"
        assert warnings
        assert "com.example.bad" in _advanced_text(inspector).toPlainText()


class TestShowAgentExternal:
    def test_external_partial_fields(self, inspector: AgentInspector) -> None:
        listing = _external_listing()
        inspector.show_agent(listing, _report(listing))
        assert _value_label(inspector, "overview-classification").text() == "External"
        assert _value_label(inspector, "command-command").text() == (
            "/bin/zsh /Users/example/scripts/x.sh"
        )
        warnings = _value_label(inspector, "warnings-text").text()
        assert warnings == format_warnings(listing)
        assert "no calendar schedule found" in warnings
        assert "unsupported keys: KeepAlive" in warnings


class TestShowPlaceholder:
    def test_placeholder_replaces_agent(self, inspector: AgentInspector) -> None:
        listing = _managed_listing()
        inspector.show_agent(listing, _report(listing))
        inspector.show_placeholder("No tasks found.")
        assert _scroll_area(inspector).isHidden()
        message = _message_label(inspector)
        assert message.text() == "No tasks found."
        assert message.isVisible()


class TestShowError:
    def test_error_message(self, inspector: AgentInspector) -> None:
        inspector.show_error("boom")
        assert _scroll_area(inspector).isHidden()
        message = _message_label(inspector)
        assert message.text() == "boom"
        assert message.isVisible()
