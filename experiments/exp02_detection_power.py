"""What a permutation harness finds as its budget grows, and where it stops finding more.

A sampling harness is the honest competitor to this tool, so the experiment measures against
it rather than against a straw man. The number that matters is not the detection rate at a
given budget, it is the budget at which the rate stops moving. After that point every extra
draw costs compute and buys nothing, and the keys still missing are missing for a reason no
budget addresses.
"""

from __future__ import annotations

from mos.audit import audit, simulate_permutation_harness
from mos.detection import DetectionPoint
from mos.events import load_events
from mos.semantics import MergeSpec

from _common import FIXTURE, print_table, write_result

DRAW_SCHEDULE = (1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2000)
IMPLEMENTATION = "dedupe-last-max"


def main() -> None:
    events = load_events(FIXTURE)
    spec = MergeSpec()
    result = audit(events, spec, IMPLEMENTATION)
    truth = {finding.key for finding in result.order_dependent}
    unreachable = {finding.key for finding in result.cross_batch_only}

    rows, points = [], []
    saturation_draws = None
    previous = None
    for draws in DRAW_SCHEDULE:
        flagged = simulate_permutation_harness(events, spec, IMPLEMENTATION, draws, seed=0)
        detected = len(truth & flagged)
        point = DetectionPoint(draws=draws, detected=detected, detectable=len(truth))
        points.append(point.as_dict())
        rows.append([draws, detected, len(truth) - detected, f"{point.rate}%"])
        if previous is not None and detected == previous and saturation_draws is None:
            saturation_draws = DRAW_SCHEDULE[DRAW_SCHEDULE.index(draws) - 1]
        previous = detected

    ceiling = points[-1]["detected"]
    missed_at_ceiling = len(truth) - ceiling
    payload = {
        "implementation": IMPLEMENTATION,
        "order_dependent_keys": len(truth),
        "cross_batch_only_keys": len(unreachable),
        "points": points,
        "saturation_draws": saturation_draws,
        "ceiling_detected": ceiling,
        "missed_at_ceiling": missed_at_ceiling,
        "missed_equals_cross_batch": missed_at_ceiling == len(unreachable),
        "max_draws": DRAW_SCHEDULE[-1],
    }
    print_table(["draws", "detected", "missed", "rate"], rows, [10, 12, 10, 10])
    print()
    print(f"order-dependent keys the audit proves: {len(truth)}")
    print(
        f"harness ceiling: {ceiling} detected, {missed_at_ceiling} missed "
        f"at {DRAW_SCHEDULE[-1]} draws"
    )
    print(f"detection stops improving after {saturation_draws} draws")
    write_result("exp02_detection_power", payload)


if __name__ == "__main__":
    main()
