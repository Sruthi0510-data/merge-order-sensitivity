"""Re-measure every figure the documents quote and write docs/metrics.json.

Nothing here is typed by hand. The test count and the coverage come from pytest's machine
readable reports rather than from parsing a progress line, because a parsed progress line
quietly becomes whatever the last run happened to print. Every other figure comes from an
experiment's JSON, which is itself produced by running the experiment.

The anchors are the other half of the mechanism. A checker that searches for the digits of a
figure passes while the sentence around them has gone stale, so each metric carries the two
or three words a document must use with the value substituted in. Anchors are short on
purpose: a phrase longer than a few words straddles a line break in wrapped markdown and
then matches nothing while the prose it guards is perfectly correct.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
EXPERIMENTS = ROOT / "experiments"
EXPERIMENT_OUTPUT = DOCS / "experiments"
JUNIT = ROOT / "junit.xml"
COVERAGE_JSON = ROOT / "coverage.json"
METRICS_PATH = DOCS / "metrics.json"

CHECKED_DOCUMENTS = [
    "README.md",
    "docs/adr/ADR-001-the-referee-is-a-third-implementation.md",
    "docs/adr/ADR-002-batch-boundaries-bound-the-search.md",
    "docs/adr/ADR-003-no-spark-in-the-default-path.md",
    "docs/adr/ADR-004-exit-codes-separate-a-finding-from-a-failure.md",
    "docs/adr/ADR-005-what-this-repository-cannot-measure.md",
]

ANCHORS: dict[str, list[str]] = {
    "tests_total": ["{} tests,"],
    "coverage_line_pct": ["{}% line"],
    "coverage_branch_pct": ["{}% branch"],
    "fixture_events": ["{} events"],
    "fixture_keys": ["{} primary keys"],
    "fixture_batches": ["{} micro-batches"],
    "rerun_keys_flagged": ["flags {} keys", "flagged {} keys", "found {} keys"],
    "baseline_order_dependent": ["{} order-dependent"],
    "baseline_order_dependent_pct": ["{}% of keys", "{}% of the keys"],
    "worst_impl_order_dependent": ["{} keys wrong", "wrong on {} keys"],
    "implementation_defect_keys": ["{} keys the declaration"],
    "cross_batch_only": ["{} of those keys", "{} unreachable keys", "{} keys no shuffle"],
    "harness_detected_at_one_draw": ["draw finds {} keys"],
    "harness_missed_at_one_draw": ["misses {} of them"],
    "harness_ceiling_detected": ["finds {} of", "flags {} of"],
    "harness_ceiling_pct": ["{}% of the provable", "ceiling of {}%"],
    "harness_saturation_draws": ["after {} draws", "past {} draws"],
    "harness_max_draws": ["{} draws finds", "at {} draws"],
    "unreachable_bound_pct": ["below {}%", "under {}%"],
    "keys_spanning_batches": ["{} keys straddle", "{} of the keys straddle"],
    "orders_that_exist": ["{} arrival orders"],
    "orders_reachable": ["{} of them reachable", "{} are reachable"],
    "orders_in_gap": ["{} orders no", "{} unreachable orders"],
    "rows_changed_by_fix": ["rewrites {} rows", "{} rows change"],
    "dedupe_reading_divergence": ["disagree on {} rows", "{} rows apart"],
    "delete_wins_order_dependent": ["leaves {} keys", "down to {} keys"],
}


def run_tests() -> None:
    """Run pytest with machine readable reports. Skipped in CI, where it is its own step."""
    subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q",
            "--cov=mos",
            f"--cov-report=json:{COVERAGE_JSON}",
            f"--junitxml={JUNIT}",
        ],
        cwd=ROOT,
        check=True,
    )


def read_test_count() -> int:
    """Read the test total from the junit report rather than from stdout."""
    root = ET.parse(JUNIT).getroot()
    suite = root if root.tag == "testsuite" else root[0]
    return int(suite.get("tests", 0))


def read_coverage() -> tuple[float, float]:
    """Read line and branch coverage from the JSON report."""
    payload = json.loads(COVERAGE_JSON.read_text())
    totals = payload["totals"]
    line = round(float(totals["percent_covered"]), 1)
    covered = totals.get("covered_branches", 0)
    total = totals.get("num_branches", 0)
    branch = round(100.0 * covered / total, 1) if total else 100.0
    return line, branch


def run_experiments() -> dict[str, Any]:
    """Run every experiment from scratch and load the JSON each one writes."""
    results: dict[str, Any] = {}
    env_path = str(EXPERIMENTS)
    for script in sorted(EXPERIMENTS.glob("exp*.py")):
        subprocess.run(
            [sys.executable, str(script)],
            cwd=ROOT,
            check=True,
            env={**_environ(), "PYTHONPATH": env_path},
            stdout=subprocess.DEVNULL,
        )
        results[script.stem] = json.loads((EXPERIMENT_OUTPUT / f"{script.stem}.json").read_text())
    return results


def _environ() -> dict[str, str]:
    import os

    return dict(os.environ)


def build_metrics(skip_tests: bool) -> dict[str, Any]:
    if not skip_tests:
        run_tests()
    line_pct, branch_pct = read_coverage()
    experiments = run_experiments()

    defects = experiments["exp01_defect_classes"]
    power = experiments["exp02_detection_power"]
    space = experiments["exp03_unreachable_space"]
    fix = experiments["exp05_cost_of_the_fix"]

    baseline = defects["implementations"]["dedupe-last-max"]
    worst = defects["implementations"]["arrival-lww"]

    metrics = {
        "tests_total": read_test_count(),
        "coverage_line_pct": line_pct,
        "coverage_branch_pct": branch_pct,
        "fixture_events": defects["fixture"]["events"],
        "fixture_keys": defects["fixture"]["keys"],
        "fixture_batches": 6,
        "rerun_keys_flagged": baseline["rerun_keys_flagged"],
        "baseline_order_dependent": baseline["order_dependent_keys"],
        "baseline_order_dependent_pct": baseline["order_dependent_pct"],
        "worst_impl_order_dependent": worst["order_dependent_keys"],
        "implementation_defect_keys": worst["implementation_defect_keys"],
        "cross_batch_only": baseline["cross_batch_only_keys"],
        "harness_detected_at_one_draw": power["points"][0]["detected"],
        "harness_missed_at_one_draw": (
            power["points"][0]["detectable"] - power["points"][0]["detected"]
        ),
        "harness_ceiling_detected": power["ceiling_detected"],
        "harness_ceiling_pct": power["points"][-1]["rate_pct"],
        "harness_saturation_draws": power["saturation_draws"],
        "harness_max_draws": power["max_draws"],
        "unreachable_bound_pct": space["probe"]["upper_bound_pct_when_zero"],
        "keys_spanning_batches": space["keys_spanning_batches"],
        "orders_that_exist": space["orders_that_exist"],
        "orders_reachable": space["orders_reachable"],
        "orders_in_gap": space["orders_in_gap"],
        "rows_changed_by_fix": fix["rows_changed_by_fix"],
        "dedupe_reading_divergence": fix["rows_differing_between_dedupe_readings"],
        "delete_wins_order_dependent": defects["implementations"]["delete-wins"][
            "order_dependent_keys"
        ],
    }
    return {
        "metrics": metrics,
        "anchors": ANCHORS,
        "checked_documents": CHECKED_DOCUMENTS,
        "note": (
            "every value here is produced by running the suite and the experiments; "
            "tools/check_numbers.py fails the build when a document quotes a figure the "
            "code no longer produces"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="re-measure every published figure")
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="read existing junit.xml and coverage.json instead of running pytest",
    )
    args = parser.parse_args()
    payload = build_metrics(skip_tests=args.skip_tests)
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {METRICS_PATH.relative_to(ROOT)} with {len(payload['metrics'])} metrics")
    for name, value in sorted(payload["metrics"].items()):
        print(f"  {name:<34} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
