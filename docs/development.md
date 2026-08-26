# Development — macOS Task Scheduler for Humans

## Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## Install Dependencies

```bash
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

This installs the package in editable mode plus all development
dependencies (pytest, pytest-cov, ruff, mypy).

## Makefile Targets

All targets use `.venv/bin/python`, so create the virtual environment
first.

| Command | Description |
|---|---|
| `make test` | Run unit tests |
| `make lint` | Run Ruff lint checks |
| `make format` | Format the codebase with Ruff |
| `make typecheck` | Run mypy on the source package |
| `make check` | Run lint, typecheck, and tests (the completion gate) |

## Running Tests with Coverage

```bash
pytest --cov=task_scheduler --cov-report=term-missing
```

The core modules (domain, JSON persistence, plist encoder, plist parser)
target at least 90% coverage.

## Current State

This cycle (Crawl increments 0–3) establishes the core:

- project/tooling foundation
- normalized job domain model with Pydantic validation
- schema-versioned JSON persistence (storage layer)
- LaunchAgent plist generation and parsing (macOS platform layer)

No GUI, no CLI commands, no `launchctl` calls, and no writes to
`~/Library/LaunchAgents`, `/Library/LaunchAgents`, or
`/Library/LaunchDaemons` exist in this cycle. Unit tests run against
synthetic fixtures and never touch the live filesystem outside temporary
directories.
