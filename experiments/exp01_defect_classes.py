"""How many keys each implementation gets wrong, split by which defect class it is.

The question the README asks: is order sensitivity a tie problem or a code problem? The
answer is that it is both, and the two have different fixes. A tie is a defect in the
declaration and no implementation can be correct about it. A key the declaration decides and
the code still flips is a defect in the code, and that class is invisible to any review that
starts by looking for duplicate sequence numbers.
"""

from __future__ import annotations

from mos.audit import audit
from mos.events import load_events
from mos.implementations import IMPLEMENTATIONS
from mos.semantics import MergeSpec

from _common import FIXTURE, print_table, write_result


def main() -> None:
    events = load_events(FIXTURE)
    spec = MergeSpec()
    rows = []
    payload = {"fixture": {"events": len(events), "keys": len({e.key for e in events})}}
    results = {}
    for name in sorted(IMPLEMENTATIONS):
        result = audit(events, spec, name)
        results[name] = {
            "order_dependent_keys": len(result.order_dependent),
            "spec_ambiguous_keys": len(result.spec_ambiguous),
            "implementation_defect_keys": len(result.implementation_defects),
            "cross_batch_only_keys": len(result.cross_batch_only),
            "rerun_keys_flagged": result.rerun_keys_flagged,
            "order_dependent_pct": result.rate(result.order_dependent),
        }
        rows.append(
            [
                name,
                len(result.order_dependent),
                len(result.spec_ambiguous),
                len(result.implementation_defects),
                result.rerun_keys_flagged,
            ]
        )
    payload["implementations"] = results
    print_table(
        ["implementation", "order-dep", "declaration", "code", "rerun flags"],
        rows,
        [20, 12, 14, 8, 12],
    )
    print()
    print(f"keys audited: {payload['fixture']['keys']}")
    write_result("exp01_defect_classes", payload)


if __name__ == "__main__":
    main()
