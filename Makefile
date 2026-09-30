# Every target here runs offline. `make verify` is the one the README promises a reviewer,
# so it is the one that must never be broken.

PYTHON ?= python3
COVERAGE_FLOOR ?= 95

.PHONY: help install lint test experiments receipts diagrams rendering report screenshots \
	verify fixture clean

help:
	@echo "install      editable install with the dev extra"
	@echo "lint         ruff over src, tests, tools and experiments"
	@echo "test         pytest with junit and coverage reports"
	@echo "experiments  re-run every experiment and rewrite its JSON"
	@echo "receipts     re-measure every published figure and check it against the prose"
	@echo "diagrams     re-render the committed SVGs from docs/metrics.json"
	@echo "rendering    render the README as GitHub does and assert the images load"
	@echo "report       write docs/report.html from the shipped fixture"
	@echo "screenshots  capture the README evidence from that report"
	@echo "verify       lint, test, receipts. Offline, from a fresh clone"

install:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(PYTHON) -m ruff check .

test:
	$(PYTHON) -m pytest -q --cov=mos --cov-report=json:coverage.json \
		--cov-report=term-missing --junitxml=junit.xml
	@$(PYTHON) -c "import json,sys; \
pct=json.load(open('coverage.json'))['totals']['percent_covered']; \
floor=float('$(COVERAGE_FLOOR)'); \
print(f'coverage {pct:.1f}% against a floor of {floor:.0f}%'); \
sys.exit(0 if pct >= floor else 1)"

experiments:
	@for script in experiments/exp*.py; do \
		echo "--- $$script"; PYTHONPATH=experiments $(PYTHON) $$script || exit 1; echo; \
	done

# Depends on test rather than running pytest itself. Trap four: a red test that surfaces as a
# CalledProcessError from inside a metrics script costs an hour to attribute, so the suite runs
# as its own step and the collector reads the reports it left behind.
receipts: test
	$(PYTHON) tools/collect_metrics.py --skip-tests
	$(PYTHON) tools/check_numbers.py

diagrams:
	$(PYTHON) tools/render_diagrams.py

rendering:
	$(PYTHON) tools/verify_rendering.py

report:
	-$(PYTHON) -m mos.cli report --out docs/report.html

screenshots: report
	$(PYTHON) tools/capture_screenshots.py

fixture:
	$(PYTHON) -m mos.cli generate --out fixtures/cdc_events.jsonl --keys 400 --seed 20260930

verify: lint receipts

clean:
	rm -rf .pytest_cache .ruff_cache htmlcov coverage.json coverage.xml junit.xml .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
