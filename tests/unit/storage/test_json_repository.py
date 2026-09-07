"""Tests for the JSON job repository."""

import json
from datetime import time as Time
from pathlib import Path

from task_scheduler.domain import (
    CalendarSchedule,
    Weekday,
)
from task_scheduler.storage import JsonJobRepository


def test_load_migrates_v1_calendar_schedule(tmp_path: Path) -> None:
    path = tmp_path / "v1.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "12345678-1234-5678-1234-567812345678",
                "name": "Daily Backup",
                "label": "io.github.macos-task-scheduler.user.daily-backup",
                "enabled": True,
                "command": {
                    "type": "python",
                    "interpreter": "/Users/example/project/.venv/bin/python",
                    "script": "/Users/example/project/main.py",
                    "arguments": ["--mode", "daily"],
                },
                "schedule": {"time": "07:30", "weekdays": ["monday", "friday"]},
            }
        ),
        "utf-8",
    )
    job = JsonJobRepository().load(path)
    assert isinstance(job.schedule, CalendarSchedule)
    assert job.schedule.times == [Time(7, 30)]
    assert job.schedule.weekdays == {Weekday.MONDAY, Weekday.FRIDAY}
    assert job.schedule.run_at_load is False

