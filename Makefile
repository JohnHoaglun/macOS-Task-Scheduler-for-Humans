PYTHON ?= .venv/bin/python

.PHONY: test integration lint format typecheck check

test:
	$(PYTHON) -m pytest tests/

# Runs only integration tests; they skip unless MACTASK_ALLOW_SYSTEM_TESTS=1.
integration:
	$(PYTHON) -m pytest -m integration

lint:
	$(PYTHON) -m ruff check src/task_scheduler/ tests/

format:
	$(PYTHON) -m ruff format src/task_scheduler/ tests/

typecheck:
	$(PYTHON) -m mypy src/task_scheduler/

check: lint typecheck test
