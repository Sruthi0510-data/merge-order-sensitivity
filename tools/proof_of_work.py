"""Capture this repository's own commands and commit the transcript.

The command list is the README's claims, in the order the README makes them. If
a claim changes, the list changes with it, and the capture fails the build when
a command does not exit the way the README says it does. The four documented
exit codes are therefore demonstrated rather than asserted.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from capture_terminal import Step, capture  # noqa: E402

PY = sys.executable

STEPS = [
    Step(
        label="the suite, with branch coverage",
        argv=[PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--cov=mos",
              "--cov-branch", "--cov-report=term-missing", "--cov-fail-under=100"],
        max_lines=16,
        tail_lines=4,
    ),
    Step(
        label="the audit against the reviewed declaration: a finding, not a failure",
        argv=[PY, "-m", "mos.cli", "audit"],
        expect=3,
        max_lines=16,
        tail_lines=6,
    ),
    Step(
        label="one key, and the two orders that leave it in two different states",
        argv=[PY, "-m", "mos.cli", "witness", "acct-00055"],
        expect=3,
        max_lines=8,
    ),
    Step(
        label="every bundled implementation, side by side",
        argv=[PY, "-m", "mos.cli", "compare"],
        expect=3,
        max_lines=12,
    ),
    Step(
        label="a total ordering removes the ambiguity entirely",
        argv=[PY, "-m", "mos.cli", "audit", "--impl", "total-order"],
        expect=0,
        max_lines=12,
        tail_lines=5,
    ),
    Step(
        label="a budget that cannot support the confidence asked for: a refusal",
        argv=[PY, "-m", "mos.cli", "audit", "--require-confidence", "0.99999999",
              "--search-limit", "4"],
        expect=4,
        max_lines=6,
        tail_lines=3,
    ),
    Step(
        label="an unreadable fixture",
        argv=[PY, "-m", "mos.cli", "audit", "--fixture", "does-not-exist.jsonl"],
        expect=2,
        max_lines=3,
    ),
    Step(
        label="every published figure re-checked against the prose",
        argv=[PY, "tools/check_numbers.py"],
        max_lines=3,
    ),
]


def main() -> int:
    return capture(
        STEPS,
        title="merge-order-sensitivity: captured by tools/proof_of_work.py, exit codes as returned",
        out_svg=ROOT / "docs" / "img" / "proof-of-work.svg",
        out_json=ROOT / "docs" / "proof-of-work.json",
    )


if __name__ == "__main__":
    raise SystemExit(main())
