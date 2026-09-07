"""Tests for the pure diagnostic probes: protected paths and Mach-O headers.

Mach-O fixtures are struct-packed byte buffers written to temp files, so the
parsing logic is tested in isolation — including the fat-header endianness
regression (a little-endian fat header must be parsed as little-endian).
"""

from __future__ import annotations

import platform
import struct
from pathlib import Path

import pytest

from task_scheduler.platform.macos.diagnostic_probes import (
    PROTECTED_HOME_DIRS,
    ArchitectureFinding,
    LocalDiagnosticProbes,
    ProtectedPathFinding,
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
    def test_each_home_dir_root_matches(self) -> None:
        home = Path("/Users/test")
        for name in PROTECTED_HOME_DIRS:
            path = home / name / "a.py"
            finding = probe_protected_paths([path], home=home)
            assert finding == (ProtectedPathFinding(path=path, root=home / name),)

    def test_mobile_documents_root_matches(self) -> None:
        home = Path("/Users/test")
        root = home / "Library" / "Mobile Documents"
        path = root / "iCloud~md~obsidian" / "Documents" / "note.md"
        finding = probe_protected_paths([path], home=home)
        assert finding == (ProtectedPathFinding(path=path, root=root),)

    def test_shared_root_matches_without_home(self) -> None:
        path = Path("/Users/Shared/scratch/tool")
        finding = probe_protected_paths([path], home=Path("/Users/nobody"))
        assert finding == (ProtectedPathFinding(path=path, root=Path("/Users/Shared")),)

    def test_exact_root_matches(self) -> None:
        home = Path("/Users/test")
        finding = probe_protected_paths([home / "Documents"], home=home)
        assert finding == (ProtectedPathFinding(path=home / "Documents", root=home / "Documents"),)

    def test_nested_path_matches_top_root(self) -> None:
        home = Path("/Users/test")
        path = home / "Documents" / "deep" / "file.py"
        finding = probe_protected_paths([path], home=home)
        assert finding == (ProtectedPathFinding(path=path, root=home / "Documents"),)

    def test_siblings_do_not_match(self) -> None:
        home = Path("/Users/test")
        paths = [home / "DocumentsX" / "a.py", home.parent / "test2" / "Desktop" / "b.py"]
        assert probe_protected_paths(paths, home=home) == ()

    def test_non_protected_paths_do_not_match(self) -> None:
        home = Path("/Users/test")
        assert probe_protected_paths([Path("/tmp/x"), home / "src" / "main.py"], home=home) == ()

    def test_nonexistent_path_is_still_checked_lexically(self) -> None:
        path = Path("/Users/Shared/does/not/exist")
        finding = probe_protected_paths([path], home=Path("/Users/test"))
        assert finding == (ProtectedPathFinding(path=path, root=Path("/Users/Shared")),)

    def test_duplicate_inputs_deduplicated_preserving_order(self) -> None:
        home = Path("/Users/test")
        a = home / "Desktop" / "a.py"
        b = home / "Music" / "b.py"
        findings = probe_protected_paths([a, a, b, a], home=home)
        assert [finding.path for finding in findings] == [a, b]

    def test_default_home_uses_path_home(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        finding = probe_protected_paths([home / "Downloads" / "x.zip"])
        assert finding == (
            ProtectedPathFinding(path=home / "Downloads" / "x.zip", root=home / "Downloads"),
        )


class TestProbeExecutableArchitecture:
    def test_thin_le_mismatch_reported(self, tmp_path: Path) -> None:
        executable = _write(tmp_path, _thin(X86_64))
        finding = probe_executable_architecture(executable, machine="arm64")
        assert finding == ArchitectureFinding(path=executable, declared=(X86_64,), host=ARM64)

    def test_thin_le_host_match_silent(self, tmp_path: Path) -> None:
        executable = _write(tmp_path, _thin(ARM64))
        assert probe_executable_architecture(executable, machine="arm64") is None

    def test_thin_le_cputype_is_little_endian(self, tmp_path: Path) -> None:
        # x86_64 stored little-endian: a big-endian misread decodes to
        # 0x03000007 and would fabricate a mismatch finding on an x86_64 host.
        executable = _write(tmp_path, _thin(X86_64))
        assert probe_executable_architecture(executable, machine="x86_64") is None

    def test_thin_be_magic(self, tmp_path: Path) -> None:
        executable = _write(tmp_path, _thin(X86_64, magic=THIN_BE_MAGIC, little_endian=False))
        finding = probe_executable_architecture(executable, machine="arm64")
        assert finding == ArchitectureFinding(path=executable, declared=(X86_64,), host=ARM64)

    def test_thin_32_bit_x86(self, tmp_path: Path) -> None:
        executable = _write(tmp_path, _thin(X86_32, magic=THIN_32_MAGIC))
        finding = probe_executable_architecture(executable, machine="arm64")
        assert finding == ArchitectureFinding(path=executable, declared=(X86_32,), host=ARM64)

    def test_fat_be_first_entry(self, tmp_path: Path) -> None:
        executable = _write(tmp_path, _fat([X86_64], little_endian=False))
        finding = probe_executable_architecture(executable, machine="arm64")
        assert finding == ArchitectureFinding(path=executable, declared=(X86_64,), host=ARM64)

    def test_fat_be_host_in_first_entry_silent(self, tmp_path: Path) -> None:
        executable = _write(tmp_path, _fat([ARM64, X86_64], little_endian=False))
        assert probe_executable_architecture(executable, machine="arm64") is None

    def test_fat_only_first_entry_is_read(self, tmp_path: Path) -> None:
        # The probe reads 32 bytes, so a second fat entry never reaches it.
        executable = _write(tmp_path, _fat([X86_64, ARM64], little_endian=False))
        finding = probe_executable_architecture(executable, machine="arm64")
        assert finding == ArchitectureFinding(path=executable, declared=(X86_64,), host=ARM64)

    def test_fat_le_endianness_regression(self, tmp_path: Path) -> None:
        # A little-endian fat header (FAT_CIGAM) must parse its entries as
        # little-endian; a big-endian misread byte-swaps the cputype.
        executable = _write(tmp_path, _fat([X86_64], little_endian=True))
        finding = probe_executable_architecture(executable, machine="arm64")
        assert finding == ArchitectureFinding(path=executable, declared=(X86_64,), host=ARM64)

    def test_fat_le_host_match_silent(self, tmp_path: Path) -> None:
        executable = _write(tmp_path, _fat([ARM64], little_endian=True))
        assert probe_executable_architecture(executable, machine="arm64") is None

    def test_unknown_machine_silent(self, tmp_path: Path) -> None:
        executable = _write(tmp_path, _thin(X86_64))
        assert probe_executable_architecture(executable, machine="riscv64") is None

    def test_default_machine_uses_platform(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        executable = _write(tmp_path, _thin(X86_64))
        monkeypatch.setattr(platform, "machine", lambda: "arm64")
        finding = probe_executable_architecture(executable)
        assert finding == ArchitectureFinding(path=executable, declared=(X86_64,), host=ARM64)

    def test_short_file_silent(self, tmp_path: Path) -> None:
        executable = _write(tmp_path, b"mach")
        assert probe_executable_architecture(executable, machine="arm64") is None

    def test_non_macho_silent(self, tmp_path: Path) -> None:
        executable = _write(tmp_path, b"\x7fELF\x02\x01\x01\x00")
        assert probe_executable_architecture(executable, machine="arm64") is None

    def test_directory_silent(self, tmp_path: Path) -> None:
        assert probe_executable_architecture(tmp_path, machine="arm64") is None

    def test_missing_file_silent(self, tmp_path: Path) -> None:
        assert probe_executable_architecture(tmp_path / "gone", machine="arm64") is None


class TestLocalDiagnosticProbes:
    def test_configured_home_used_when_call_omits_it(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        probes = LocalDiagnosticProbes(home=home)
        path = home / "Music" / "track.mp3"
        assert probes.probe_protected_paths([path]) == (
            ProtectedPathFinding(path=path, root=home / "Music"),
        )

    def test_configured_machine_used_when_call_omits_it(self, tmp_path: Path) -> None:
        executable = _write(tmp_path, _thin(X86_64))
        probes = LocalDiagnosticProbes(machine="arm64")
        assert probes.probe_executable_architecture(executable) == ArchitectureFinding(
            path=executable, declared=(X86_64,), host=ARM64
        )

    def test_call_kwargs_override_constructor(self, tmp_path: Path) -> None:
        executable = _write(tmp_path, _thin(ARM64))
        probes = LocalDiagnosticProbes(home=tmp_path / "home", machine="x86_64")
        assert probes.probe_protected_paths([tmp_path / "x"], home=tmp_path / "other") == ()
        assert probes.probe_executable_architecture(executable, machine="arm64") is None
