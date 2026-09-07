"""Tests for the pure diagnostic probes: protected paths and Mach-O headers.

Mach-O fixtures are struct-packed byte buffers written to temp files, so the
parsing logic is tested in isolation — including the fat-header endianness
regression (a little-endian fat header must be parsed as little-endian).
"""

from __future__ import annotations

import struct
from pathlib import Path

from task_scheduler.platform.macos.diagnostic_probes import (
    ArchitectureFinding,
    probe_executable_architecture,
    probe_protected_paths,
)

ARM64 = 0x0100000C
X86_64 = 0x07000003
X86_32 = 7

THIN_64_MAGIC = 0xFEEDFACF
THIN_32_MAGIC = 0xFEEDFACE
THIN_BE_MAGIC = 0xCEFAEDFE
FAT_BE_MAGIC = 0xCAFEBABE
FAT_LE_MAGIC = 0xBEBAFECA

def _thin(cputype: int, magic: int = THIN_64_MAGIC, little_endian: bool = True) -> bytes:
    """Header bytes: magic read big-endian, cputype in *little_endian* order."""
    return struct.pack(">I", magic) + struct.pack("<I" if little_endian else ">I", cputype)

def _fat(cputypes: list[int], little_endian: bool) -> bytes:
    """Fat header bytes.

    The four magic bytes are always read big-endian by parsers: a
    big-endian fat holds 0xCAFEBABE (bytes CA FE BA BE), a little-endian
    fat holds 0xBEBAFECA (bytes BE BA FE CA). The nfat count and entry
    fields follow the file's own endianness.
    """
    fmt = "<I" if little_endian else ">I"
    parts = [
        struct.pack(">I", FAT_LE_MAGIC if little_endian else FAT_BE_MAGIC),
        struct.pack(fmt, len(cputypes)),
    ]
    for cputype in cputypes:
        parts.append(struct.pack(fmt, cputype) + b"\x00" * 16)
    return b"".join(parts)

def _write(tmp_path: Path, data: bytes, name: str = "tool") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path

class TestProbeProtectedPaths:

    def test_duplicate_inputs_deduplicated_preserving_order(self) -> None:
        home = Path("/Users/test")
        a = home / "Desktop" / "a.py"
        b = home / "Music" / "b.py"
        findings = probe_protected_paths([a, a, b, a], home=home)
        assert [finding.path for finding in findings] == [a, b]

class TestProbeExecutableArchitecture:

    def test_thin_be_magic(self, tmp_path: Path) -> None:
        executable = _write(tmp_path, _thin(X86_64, magic=THIN_BE_MAGIC, little_endian=False))
        finding = probe_executable_architecture(executable, machine="arm64")
        assert finding == ArchitectureFinding(path=executable, declared=(X86_64,), host=ARM64)

    def test_thin_32_bit_x86(self, tmp_path: Path) -> None:
        executable = _write(tmp_path, _thin(X86_32, magic=THIN_32_MAGIC))
        finding = probe_executable_architecture(executable, machine="arm64")
        assert finding == ArchitectureFinding(path=executable, declared=(X86_32,), host=ARM64)

    def test_fat_le_host_match_silent(self, tmp_path: Path) -> None:
        executable = _write(tmp_path, _fat([ARM64], little_endian=True))
        assert probe_executable_architecture(executable, machine="arm64") is None

    def test_fat_truncated_before_any_entry_silent(self, tmp_path: Path) -> None:
        # A valid fat magic and nfat count, but the file ends before a
        # complete first fat_arch entry fits the 32-byte read.
        executable = _write(tmp_path, _fat([X86_64], little_endian=False)[:12])
        assert probe_executable_architecture(executable, machine="arm64") is None

    def test_unknown_machine_silent(self, tmp_path: Path) -> None:
        executable = _write(tmp_path, _thin(X86_64))
        assert probe_executable_architecture(executable, machine="riscv64") is None

    def test_short_file_silent(self, tmp_path: Path) -> None:
        executable = _write(tmp_path, b"mach")
        assert probe_executable_architecture(executable, machine="arm64") is None

    def test_non_macho_silent(self, tmp_path: Path) -> None:
        executable = _write(tmp_path, b"\x7fELF\x02\x01\x01\x00")
        assert probe_executable_architecture(executable, machine="arm64") is None
