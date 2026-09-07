"""Best-effort, pure, local-only diagnostic probes.

Probes inspect the local machine without invoking subprocesses, resolving
symlinks, or writing anything. They never raise — instead they return
None or empty containers when a probe cannot complete.
"""

from __future__ import annotations

import platform
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

PROTECTED_HOME_DIRS: tuple[str, ...] = (
    "Desktop",
    "Documents",
    "Downloads",
    "Movies",
    "Music",
    "Pictures",
)

SHARED_PATH = Path("/Users/Shared")


@dataclass(frozen=True, slots=True)
class ProtectedPathFinding:
    """One protected-path match: a path falls under one of macOS's restricted homes."""

    path: Path
    root: Path


@dataclass(frozen=True, slots=True)
class ArchitectureFinding:
    """Mach-O header finding: declared architectures versus the host."""

    path: Path
    declared: tuple[int, ...]
    host: int


_HOST_CPU: dict[str, int] = {
    "arm64": 0x0100000C,
    "x86_64": 0x07000003,
}


def probe_protected_paths(
    paths: Sequence[Path],
    *,
    home: Path | None = None,
) -> tuple[ProtectedPathFinding, ...]:
    """Return findings for every input path that falls under a protected root.

    Roots are checked in order: home/<each PROTECTED_HOME_DIRS>, then
    home/Library/Mobile Documents, then SHARED_PATH.  home defaults to
    Path.home().

    This is pure lexical containment — no filesystem access, no resolution.
    """
    if home is None:
        home = Path.home()

    roots: list[Path] = []
    for name in PROTECTED_HOME_DIRS:
        roots.append(home / name)
    roots.append(home / "Library" / "Mobile Documents")
    roots.append(SHARED_PATH)

    seen: set[str] = set()
    findings: list[ProtectedPathFinding] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        for root in roots:
            try:
                path.relative_to(root)
            except ValueError:
                continue
            findings.append(ProtectedPathFinding(path=path, root=root))
            break

    return tuple(findings)


def probe_executable_architecture(
    executable: Path,
    *,
    machine: str | None = None,
) -> ArchitectureFinding | None:
    """Inspect the Mach-O header of an executable for architecture mismatch.

    Returns None when the executable is missing, unreadable, too short,
    non-Mach-O, when no architecture entry can be parsed, or when any
    declared cputype matches the host cputype.
    """
    host = _resolve_host(machine)
    if host is None:
        return None

    try:
        with open(executable, "rb") as f:
            header = f.read(32)
    except OSError:
        return None

    if len(header) < 8:
        return None

    return _parse_mach_o(header, executable, host)


def _resolve_host(machine: str | None) -> int | None:
    if machine is None:
        machine = platform.machine()
    return _HOST_CPU.get(machine)


def _parse_mach_o(header: bytes, executable: Path, host: int) -> ArchitectureFinding | None:
    magic = struct.unpack(">I", header[:4])[0]
    if magic in (0xFEEDFACF, 0xFEEDFACE):
        return _parse_thin(header, executable, host, little_endian=True)
    if magic == 0xCEFAEDFE:
        return _parse_thin(header, executable, host, little_endian=False)
    if magic == 0xCAFEBABE:
        return _parse_fat(header, executable, host, little_endian=False)
    if magic == 0xBEBAFECA:
        return _parse_fat(header, executable, host, little_endian=True)
    return None


def _parse_thin(
    header: bytes, executable: Path, host: int, little_endian: bool
) -> ArchitectureFinding | None:
    endian = "<" if little_endian else ">"
    fmt = endian + "I"
    cputype = struct.unpack(fmt, header[4:8])[0]
    return _report(executable, (cputype,), host)


def _parse_fat(
    header: bytes, executable: Path, host: int, little_endian: bool
) -> ArchitectureFinding | None:
    endian = "<" if little_endian else ">"

    fmt = endian + "I"
    nfat = struct.unpack(fmt, header[4:8])[0]
    arch_entries = []
    entry_size = 20
    header_len = len(header)

    for i in range(nfat):
        offset = 8 + i * entry_size
        if offset + entry_size > header_len:
            break
        cputype = struct.unpack(fmt, header[offset : offset + 4])[0]
        arch_entries.append(cputype)

    if not arch_entries:
        return None

    return _report(executable, tuple(arch_entries), host)


def _report(executable: Path, declared: tuple[int, ...], host: int) -> ArchitectureFinding | None:
    if any(cpu == host for cpu in declared):
        return None
    return ArchitectureFinding(path=executable, declared=declared, host=host)


class DiagnosticProbes(Protocol):
    """Protocol for injectable diagnostic probes."""

    def probe_protected_paths(
        self,
        paths: Sequence[Path],
        *,
        home: Path | None = None,
    ) -> tuple[ProtectedPathFinding, ...]: ...

    def probe_executable_architecture(
        self,
        executable: Path,
        *,
        machine: str | None = None,
    ) -> ArchitectureFinding | None: ...


class LocalDiagnosticProbes:
    """Default probes that resolve home and machine at call time."""

    def __init__(
        self,
        *,
        home: Path | None = None,
        machine: str | None = None,
    ) -> None:
        self._home = home
        self._machine = machine

    def probe_protected_paths(
        self,
        paths: Sequence[Path],
        *,
        home: Path | None = None,
    ) -> tuple[ProtectedPathFinding, ...]:
        return probe_protected_paths(paths, home=home or self._home)

    def probe_executable_architecture(
        self,
        executable: Path,
        *,
        machine: str | None = None,
    ) -> ArchitectureFinding | None:
        return probe_executable_architecture(executable, machine=machine or self._machine)
