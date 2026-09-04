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
**Version:** 0.0.14
**Phase:** Walk — started. Crawl complete (all 13 increments; 767 tests at v0.0.13). Walk plan approved 2026-09-04: increments 14–22 covering scheduling model + migration (14), next-run preview (15), calendar scheduling expansion (16), interval/login triggers (17), Python ecosystem detection (18), expanded diagnostics (19), execution history (20), external plist import (21), and UX/JSON transfer (22). Increment 14 (schema-v2 schedule variants) is in progress.

## Repository
Source of truth: https://github.com/JohnHoaglun/macOS-Task-Scheduler-for-Humans/tree/sched_dev_opencode
Branch: `sched_dev_opencode`

## Credentials
N/A - no credentials required
