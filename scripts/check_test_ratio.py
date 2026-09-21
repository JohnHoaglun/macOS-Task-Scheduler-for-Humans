"""Fail when hand-maintained test lines exceed 75% of production source lines."""

from __future__ import annotations

from pathlib import Path

MAX_RATIO = 0.75


def count_lines(paths: list[Path]) -> int:
    return sum(len(path.read_text().splitlines()) for path in paths)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    source = sorted((root / "src" / "task_scheduler").rglob("*.py"))
    tests = sorted((root / "tests").rglob("*.py"))
    source_lines = count_lines(source)
    test_lines = count_lines(tests)
    ratio = test_lines / source_lines
    print(f"test/source ratio: {test_lines}:{source_lines} = {ratio:.4%}")
    if ratio > MAX_RATIO:
        raise SystemExit(f"test/source ratio {ratio:.2%} exceeds the 75% cap")


if __name__ == "__main__":
    main()
