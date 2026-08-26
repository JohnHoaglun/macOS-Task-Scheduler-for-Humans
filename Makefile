PYTHON ?= .venv/bin/python

.PHONY: test lint format typecheck check

test:
	$(PYTHON) -m pytest tests/

lint:
	$(PYTHON) -m ruff check src/task_scheduler/ tests/

format:
	$(PYTHON) -m ruff format src/task_scheduler/ tests/

typecheck:
	$(PYTHON) -m mypy src/task_scheduler/

check: lint typecheck test
