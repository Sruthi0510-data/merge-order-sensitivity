"""How much of the arrival-order space a real pipeline can never visit, per key.

The audit's blind-spot claim rests on an arithmetic fact rather than on a measurement: the
orders reachable by shuffling inside micro-batches are the product of the per-batch
factorials, and the orders that exist are the factorial of the group. When a key's events
straddle a boundary the first number is smaller than the second, and every order in the gap
is one no retry, no reader parallelism and no rebalance can produce.

The experiment also prices the harness's silence honestly. Where the harness found nothing
across the cross-batch population, the rate is not reported as zero: the rule of three turns
a run of zero hits into an upper bound set by the sample size.
"""

from __future__ import annotations

from mos.audit import audit, simulate_permutation_harness
from mos.detection import DetectionPoint
from mos.events import group_by_key, load_events
from mos.permute import reachable_order_count, total_order_count
from mos.semantics import MergeSpec

from _common import FIXTURE, print_table, write_result

IMPLEMENTATION = "dedupe-last-max"
PROBE_DRAWS = 2000


def main() -> None:
    events = load_events(FIXTURE)
    spec = MergeSpec()
    grouped = group_by_key(events)
    result = audit(events, spec, IMPLEMENTATION)

    spanning = 0
    reachable_total = 0
    existing_total = 0
    for group in grouped.values():
        reachable = reachable_order_count(group)
        existing = total_order_count(group)
        reachable_total += reachable
        existing_total += existing
        if reachable < existing:
            spanning += 1

    unreachable_keys = [finding.key for finding in result.cross_batch_only]
    flagged = simulate_permutation_harness(events, spec, IMPLEMENTATION, PROBE_DRAWS, seed=0)
    hits = len(set(unreachable_keys) & flagged)
    point = DetectionPoint(draws=PROBE_DRAWS, detected=hits, detectable=len(unreachable_keys))

    rows = [
        ["keys audited", len(grouped)],
        ["keys whose events span batches", spanning],
        ["arrival orders that exist", existing_total],
        ["arrival orders a pipeline can reach", reachable_total],
        ["orders in the unreachable gap", existing_total - reachable_total],
        ["order-dependent keys", len(result.order_dependent)],
        ["of those, unreachable by any shuffle", len(unreachable_keys)],
    ]
    print_table(["quantity", "value"], rows, [40, 14])
    print()
    print(f"harness hits on the unreachable population at {PROBE_DRAWS} draws: {hits}")
    if point.upper_bound_when_zero is not None:
        print(
            f"zero hits in {len(unreachable_keys)} keys bounds the detection rate below "
            f"{point.upper_bound_when_zero}% at 95% confidence, which is not the same claim as zero"
        )
    payload = {
        "keys_audited": len(grouped),
        "keys_spanning_batches": spanning,
        "orders_that_exist": existing_total,
        "orders_reachable": reachable_total,
        "orders_in_gap": existing_total - reachable_total,
        "order_dependent_keys": len(result.order_dependent),
        "unreachable_keys": len(unreachable_keys),
        "probe_draws": PROBE_DRAWS,
        "probe": point.as_dict(),
    }
    write_result("exp03_unreachable_space", payload)


if __name__ == "__main__":
    main()
