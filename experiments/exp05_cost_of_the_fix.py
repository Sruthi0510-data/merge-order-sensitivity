"""What declaring a total order actually changes, priced in rows rather than in adjectives.

The fix this repository recommends is to append a unique field to the ordering so the maximum
is unique. It is cheap and it works, and it is not free: the tie is now broken by something
with no business meaning, so some keys end up holding a different row than they hold today.
The experiment counts those keys, because a recommendation that does not publish its own
blast radius is a slogan.
"""

from __future__ import annotations

from mos.audit import audit
from mos.events import load_events
from mos.implementations import IMPLEMENTATIONS
from mos.semantics import MergeSpec

from _common import FIXTURE, print_table, write_result

SEQ_ONLY = MergeSpec(ordering=("seq",))
TOTAL = MergeSpec(ordering=("seq", "event_id"))
BASELINE_IMPL = "dedupe-last-max"


def _differences(left, right) -> int:
    return sum(1 for key in left if left[key] != right[key])


def main() -> None:
    events = load_events(FIXTURE)
    current = IMPLEMENTATIONS[BASELINE_IMPL](events, SEQ_ONLY)
    fixed = IMPLEMENTATIONS["total-order"](events, TOTAL)
    other_reading = IMPLEMENTATIONS["dedupe-first-max"](events, SEQ_ONLY)
    delete_wins = IMPLEMENTATIONS["delete-wins"](events, SEQ_ONLY)

    before = audit(events, SEQ_ONLY, BASELINE_IMPL)
    after = audit(events, TOTAL, BASELINE_IMPL)

    rows = [
        ["order-dependent keys before the fix", len(before.order_dependent)],
        ["order-dependent keys after the fix", len(after.order_dependent)],
        ["rows that change when the fix lands", _differences(current, fixed)],
        ["rows that differ between the two dedupe readings", _differences(current, other_reading)],
        ["rows the tombstone rule alone would change", _differences(current, delete_wins)],
    ]
    print_table(["quantity", "keys"], rows, [52, 10])
    print()
    print(
        "the fix removes every finding and rewrites "
        f"{_differences(current, fixed)} rows, which is the migration nobody budgets for"
    )
    payload = {
        "order_dependent_before": len(before.order_dependent),
        "order_dependent_after": len(after.order_dependent),
        "rows_changed_by_fix": _differences(current, fixed),
        "rows_differing_between_dedupe_readings": _differences(current, other_reading),
        "rows_changed_by_delete_rule": _differences(current, delete_wins),
        "keys_total": len(current),
    }
    write_result("exp05_cost_of_the_fix", payload)


if __name__ == "__main__":
    main()
