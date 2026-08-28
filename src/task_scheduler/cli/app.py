"""mactask CLI: Typer app factory and production composition root (Increment 8).

``create_app(services)`` binds every command to an injected
:class:`TaskCommandService`, so unit tests can drive the whole CLI with
fakes. ``build_services()`` is the only place that constructs production
platform adapters (store, backend, subprocess runner).
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import typer
from pydantic import ValidationError

from task_scheduler.application import (
    JobConflictError,
    JobNotFoundError,
    TaskCommandService,
)
from task_scheduler.application.job_service import JobService
from task_scheduler.application.log_service import LogService
from task_scheduler.application.test_service import DirectTestService
from task_scheduler.cli import render
from task_scheduler.platform.macos import (
    LaunchAgentBackend,
    LaunchAgentStore,
    PlistCodec,
    ProcessResult,
    SubprocessRunner,
)
from task_scheduler.storage import JsonJobRepository

__all__ = ["EXIT_FAILURE", "EXIT_SUCCESS", "EXIT_USAGE", "build_services", "create_app", "main"]

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2


def _fail(message: str, code: int) -> NoReturn:
    """Write *message* to stderr and terminate with exit code *code*."""
    typer.secho(message, err=True)
    raise typer.Exit(code)


def _format_validation_error(exc: Exception) -> str:
    """Render a job-file problem as a stable, human-readable message."""
    if isinstance(exc, ValidationError):
        lines = ["invalid job definition:"]
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"])
            lines.append(f"  {location}: {error['msg']}")
        return "\n".join(lines)
    return f"invalid job definition: {exc}"


def build_services() -> TaskCommandService:
    """Construct the production application services (the only real wiring)."""
    store = LaunchAgentStore()
    return TaskCommandService(
        repository=JsonJobRepository(),
        jobs=JobService(),
        store=store,
        backend=LaunchAgentBackend(store, SubprocessRunner()),
        codec=PlistCodec(),
        test=DirectTestService(SubprocessRunner()),
        logs=LogService(),
    )


def create_app(services: TaskCommandService) -> typer.Typer:
    """Build the mactask CLI bound to *services*."""
    app = typer.Typer(
        name="mactask",
        help="macOS Task Scheduler for Humans: manage user LaunchAgents.",
        no_args_is_help=True,
    )

    def fail_lifecycle(label: str, action: str, process: ProcessResult) -> NoReturn:
        """Exit 1 on a failed lifecycle action, showing launchctl's stderr."""
        typer.secho(
            f"{action} failed for {label}: exit code {process.exit_code}",
            err=True,
        )
        if process.stderr:
            typer.secho(process.stderr.rstrip("\n"), err=True)
        raise typer.Exit(EXIT_FAILURE)

    @app.command("list")
    def list_command() -> None:
        """List all user LaunchAgents with their parse status."""
        agents = services.list_agents()
        if not agents:
            typer.echo("No LaunchAgents found.")
            return
        for agent in agents:
            typer.echo(render.format_list(agent))

    @app.command("inspect")
    def inspect_command(
        label: str = typer.Argument(..., help="Managed job label."),
    ) -> None:
        """Show a managed job's definition, plist, and launchd status."""
        try:
            report = services.inspect(label)
        except JobNotFoundError as exc:
            _fail(str(exc), EXIT_USAGE)
        typer.echo(render.format_inspect(report))

    @app.command("validate")
    def validate_command(
        path: Path = typer.Argument(
            ..., exists=True, dir_okay=False, help="Job JSON file to validate."
        ),
    ) -> None:
        """Validate a job JSON file."""
        try:
            job = services.validate_json(path)
        except Exception as exc:
            _fail(_format_validation_error(exc), EXIT_USAGE)
        typer.echo(f"OK: {job.label}")
        typer.echo(render.format_job_summary(job))

    @app.command("generate")
    def generate_command(
        path: Path = typer.Argument(
            ..., exists=True, dir_okay=False, help="Job JSON file to generate from."
        ),
    ) -> None:
        """Print the LaunchAgent XML plist for a job JSON file."""
        try:
            xml = services.generate_plist(path)
        except Exception as exc:
            _fail(_format_validation_error(exc), EXIT_USAGE)
        typer.echo(xml, nl=False)

    @app.command("install")
    def install_command(
        path: Path = typer.Argument(
            ..., exists=True, dir_okay=False, help="Job JSON file to install."
        ),
    ) -> None:
        """Install a job: import it into the catalog and bootstrap the plist."""
        try:
            result = services.install_json(path)
        except JobConflictError as exc:
            _fail(str(exc), EXIT_USAGE)
        except FileExistsError as exc:
            _fail(
                f"install refused (managed plist already exists): {exc}",
                EXIT_USAGE,
            )
        except Exception as exc:
            _fail(_format_validation_error(exc), EXIT_USAGE)
        if result.process.exit_code != EXIT_SUCCESS:
            typer.secho(
                f"install failed for {result.job.label}: "
                f"bootstrap returned exit code {result.process.exit_code}",
                err=True,
            )
            if result.process.stderr:
                typer.secho(result.process.stderr.rstrip("\n"), err=True)
            raise typer.Exit(EXIT_FAILURE)
        typer.echo(f"installed {result.job.label} -> {result.plist_path}")

    @app.command("uninstall")
    def uninstall_command(
        label: str = typer.Argument(..., help="Managed job label."),
    ) -> None:
        """Uninstall a job: boot it out, then remove plist and catalog record."""
        try:
            result = services.uninstall(label)
        except ValueError as exc:
            _fail(str(exc), EXIT_USAGE)
        if result.process.exit_code != EXIT_SUCCESS:
            fail_lifecycle(label, "uninstall", result.process)
        suffix = " and catalog record" if result.catalog_removed else ""
        typer.echo(f"uninstalled {result.label}{suffix}")

    @app.command("enable")
    def enable_command(
        label: str = typer.Argument(..., help="Managed job label."),
    ) -> None:
        """Re-enable a disabled job."""
        try:
            result = services.enable(label)
        except ValueError as exc:
            _fail(str(exc), EXIT_USAGE)
        if result.process.exit_code != EXIT_SUCCESS:
            fail_lifecycle(label, "enable", result.process)
        typer.echo(f"enabled {label}")

    @app.command("disable")
    def disable_command(
        label: str = typer.Argument(..., help="Managed job label."),
    ) -> None:
        """Disable a job."""
        try:
            result = services.disable(label)
        except ValueError as exc:
            _fail(str(exc), EXIT_USAGE)
        if result.process.exit_code != EXIT_SUCCESS:
            fail_lifecycle(label, "disable", result.process)
        typer.echo(f"disabled {label}")

    @app.command("status")
    def status_command(
        label: str = typer.Argument(..., help="Managed job label."),
    ) -> None:
        """Show whether a job is loaded in launchd."""
        try:
            status = services.status(label)
        except ValueError as exc:
            _fail(str(exc), EXIT_USAGE)
        if status.loaded is None:
            typer.secho(
                f"status unknown for {label}: launchctl could not be run",
                err=True,
            )
            if status.process.stderr:
                typer.secho(status.process.stderr.rstrip("\n"), err=True)
            raise typer.Exit(EXIT_FAILURE)
        typer.echo(f"{label}: {render.format_status(status)}")

    @app.command("run")
    def run_command(
        label: str = typer.Argument(..., help="Managed job label."),
    ) -> None:
        """Run a job now via launchd (kickstart -k)."""
        try:
            result = services.run_now(label)
        except ValueError as exc:
            _fail(str(exc), EXIT_USAGE)
        if result.process.exit_code != EXIT_SUCCESS:
            fail_lifecycle(label, "run", result.process)
        typer.echo(f"requested run of {label}")

    @app.command("test")
    def test_command(
        label: str = typer.Argument(..., help="Managed job label."),
    ) -> None:
        """Run the managed job's command directly (Mode A) and report it."""
        try:
            result = services.test(label)
        except JobNotFoundError as exc:
            _fail(str(exc), EXIT_USAGE)
        typer.echo(render.format_test(result))
        if result.process.exit_code != EXIT_SUCCESS:
            raise typer.Exit(EXIT_FAILURE)

    @app.command("logs")
    def logs_command(
        label: str = typer.Argument(..., help="Managed job label."),
    ) -> None:
        """Print a managed job's configured stdout and stderr logs."""
        try:
            logs = services.read_logs(label)
        except JobNotFoundError as exc:
            _fail(str(exc), EXIT_USAGE)
        streams = (logs.stdout, logs.stderr)
        typer.echo(render.format_logs(logs))
        if any(stream.error is not None for stream in streams):
            raise typer.Exit(EXIT_USAGE)
        if all(stream.path is None for stream in streams):
            raise typer.Exit(EXIT_USAGE)

    return app


def main() -> None:
    """Console-script entry point for ``mactask``."""
    create_app(build_services())()
