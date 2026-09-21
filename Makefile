PYTHON ?= .venv/bin/python

.PHONY: test integration lint format typecheck check coverage ratio run-gui package

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

coverage:
	$(PYTHON) -m pytest --cov=task_scheduler --cov-report=term tests/

ratio:
	$(PYTHON) scripts/check_test_ratio.py

check: lint typecheck coverage ratio

# Development startup of the GUI through the project virtual environment.
run-gui:
	$(PYTHON) -m task_scheduler.gui.app

# Builds the standalone macOS .app bundle into dist/ via pyside6-deploy.
# macOS-only: requires the Xcode command-line tools (plutil, codesign) and the
# project .venv's pyside6-deploy. Fails early on other hosts or missing tools.
# Deploys against a transient copy in the gitignored deployment/ directory so
# tool-generated values never mutate the tracked pysidedeploy.spec.
package:
	@case "$$(uname -s)" in Darwin) ;; *) \
		echo "error: 'make package' is macOS-only (requires Darwin + Xcode command-line tools)" >&2; exit 1;; esac
	@[ -x .venv/bin/pyside6-deploy ] || { \
		echo "error: .venv/bin/pyside6-deploy not found; (re)create the .venv first" >&2; exit 1; }
	@command -v plutil >/dev/null 2>&1 || { \
		echo "error: plutil not found; install the Xcode command-line tools (xcode-select --install)" >&2; exit 1; }
	@command -v codesign >/dev/null 2>&1 || { \
		echo "error: codesign not found; install the Xcode command-line tools (xcode-select --install)" >&2; exit 1; }
	@mkdir -p deployment
	@cp pysidedeploy.spec deployment/pysidedeploy.spec
	@shasum -a 256 pysidedeploy.spec > deployment/.spec.before.sha256
	.venv/bin/pyside6-deploy -c deployment/pysidedeploy.spec -f
	@echo "Patching Info.plist identity fields..."
	plutil -replace CFBundleIdentifier -string "io.github.macos-task-scheduler" \
		"dist/macOS Task Scheduler for Humans.app/Contents/Info.plist"
	plutil -replace CFBundleName -string "macOS Task Scheduler for Humans" \
		"dist/macOS Task Scheduler for Humans.app/Contents/Info.plist"
	plutil -replace CFBundleDisplayName -string "macOS Task Scheduler for Humans" \
		"dist/macOS Task Scheduler for Humans.app/Contents/Info.plist"
	@echo "Re-signing bundle..."
	codesign --force --sign - "dist/macOS Task Scheduler for Humans.app"
	@echo "Verifying the tracked pysidedeploy.spec is unchanged..."
	@shasum -a 256 pysidedeploy.spec > deployment/.spec.after.sha256
	@cmp -s deployment/.spec.before.sha256 deployment/.spec.after.sha256 || { \
		echo "error: deployment modified the tracked pysidedeploy.spec" >&2; exit 1; }
	@echo "Done."
