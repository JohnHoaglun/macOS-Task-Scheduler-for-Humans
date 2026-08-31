# macOS Task Scheduler for Humans

## Purpose
A human-friendly macOS task scheduler built on top of Apple's `launchd`. The goal is to make scheduled jobs easier to create, understand, test, and troubleshoot without requiring users to manually write plist files or memorize `launchctl` commands.

## Architecture
- **Language:** Python 3.12+
- **GUI:** PySide6 / Qt Widgets
- **CLI:** Typer
- **Testing:** pytest + pytest-cov
- **Linting:** Ruff + mypy
- **Domain Model:** Pydantic 2.x
- **plist handling:** Python standard library `plistlib`
- **Platform:** macOS (user LaunchAgents, system LaunchDaemons planned for Run phase)
- **Packaging:** PySide6 deployment tooling → macOS `.app` bundle

### Architectural Layers
```
GUI (PySide6)          CLI (Typer)
        └──────── Application Services
                       Domain (Job/Schedule/Command/Environment)
              Platform Adapters (macOS plist/launchctl/filesystem)
                       launchd
```

## Status
**Version:** 0.0.12
**Phase:** Crawl — Increment 12 complete (GUI diagnostics/logs: direct tests of managed tasks and validated editor drafts with structured diagnostics, direct/persisted stdout/stderr with Refresh, name-only environment comparison, Python interpreter recommendations, `mactask-gui`); Increment 13 (packaging) planned and detailed in PLAN.md

## Repository
Source of truth: https://github.com/JohnHoaglun/macOS-Task-Scheduler-for-Humans/tree/sched_dev_opencode
Branch: `sched_dev_opencode`

## Credentials
N/A - no credentials required
