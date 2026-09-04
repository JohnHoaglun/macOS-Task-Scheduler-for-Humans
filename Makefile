PYTHON ?= .venv/bin/python

.PHONY: test integration lint format typecheck check run-gui package

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

# Development startup of the GUI through the project virtual environment.
run-gui:
	$(PYTHON) -m task_scheduler.gui.app

# Builds the standalone macOS .app bundle into dist/ via pyside6-deploy.
package:
	.venv/bin/pyside6-deploy -c pysidedeploy.spec -f
	@echo "Patching Info.plist identity fields..."
	plutil -replace CFBundleIdentifier -string "io.github.macos-task-scheduler" \
		"dist/macOS Task Scheduler for Humans.app/Contents/Info.plist"
	plutil -replace CFBundleName -string "macOS Task Scheduler for Humans" \
		"dist/macOS Task Scheduler for Humans.app/Contents/Info.plist"
	plutil -replace CFBundleDisplayName -string "macOS Task Scheduler for Humans" \
		"dist/macOS Task Scheduler for Humans.app/Contents/Info.plist"
	@echo "Re-signing bundle..."
	codesign --force --sign - "dist/macOS Task Scheduler for Humans.app"
	@echo "Done."
