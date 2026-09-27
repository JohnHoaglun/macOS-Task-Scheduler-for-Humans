"""Deployment of the launchd run wrapper to a stable local path.

The wrapper source is the stdlib-only ``run_wrapper`` module in the platform
package; deployment is a byte-identical copy to the app's local ``bin``
directory (launchd execs it directly via its shebang, so the path must live
on a local volume and stay stable across app updates). Idempotent: an
up-to-date deployment is left untouched.
"""

from __future__ import annotations

import os
from pathlib import Path

from task_scheduler.platform.macos.run_wrapper import WRAPPER_BASENAME

__all__ = ["default_wrapper_path", "ensure_run_wrapper"]


def default_wrapper_path() -> Path:
    """Return the stable local deployment path for the run wrapper."""
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "macOS Task Scheduler for Humans"
        / "bin"
        / WRAPPER_BASENAME
    )


def ensure_run_wrapper(destination: Path | str | None = None) -> Path:
    """Deploy the run wrapper and return its path.

    Copies the wrapper source over the deployment only when the bytes differ
    (or the deployment is missing), then guarantees the executable bit.
    """
    destination = Path(destination) if destination is not None else default_wrapper_path()
    source = Path(__file__).resolve().parents[1] / "platform" / "macos" / WRAPPER_BASENAME
    payload = source.read_bytes()
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        current: bytes | None = destination.read_bytes()
    except FileNotFoundError:
        current = None
    if current != payload:
        destination.write_bytes(payload)
    os.chmod(destination, 0o755)
    return destination
