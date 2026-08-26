"""Smoke tests: package imports and version."""

import task_scheduler
from task_scheduler import version


def test_package_exposes_version() -> None:
    assert isinstance(task_scheduler.__version__, str)
    assert task_scheduler.__version__
    assert task_scheduler.__version__ == version.__version__
