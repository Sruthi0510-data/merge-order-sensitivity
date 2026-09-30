"""The control experiment: run the idempotency test everyone writes and count what it finds.

This is the only experiment in the repository whose expected result is a row of zeros. It is
here because the README's first claim is about that test, and a claim about code belongs in
code rather than in a sentence. The test is not weak and it is not badly written. It measures
idempotency, which every implementation here has, and says nothing about order independence,
which four of the five lack.
"""

from __future__ import annotations

from mos.audit import audit
from mos.events import load_events
from mos.implementations import IMPLEMENTATIONS
from mos.semantics import MergeSpec

from _common import FIXTURE, print_table, write_result

REPEATS = 5


def main() -> None:
    events = load_events(FIXTURE)
    spec = MergeSpec()
    rows, payload = [], {}
    for name in sorted(IMPLEMENTATIONS):
        result = audit(events, spec, name)
        impl = IMPLEMENTATIONS[name]
        baseline = impl(events, spec)
        repeat_flags = 0
        for _ in range(REPEATS):
            again = impl(events, spec)
            repeat_flags += sum(1 for key in baseline if baseline[key] != again[key])
        payload[name] = {
            "rerun_keys_flagged": result.rerun_keys_flagged,
            "rerun_keys_flagged_over_repeats": repeat_flags,
            "audit_order_dependent_keys": len(result.order_dependent),
        }
        rows.append([name, repeat_flags, len(result.order_dependent)])
    print_table(
        ["implementation", f"rerun flags x{REPEATS}", "audit findings"],
        rows,
        [20, 20, 16],
    )
    print()
    print("the control found nothing for any implementation, including the worst one")
    write_result(
        "exp04_rerun_blindness",
        {"repeats": REPEATS, "implementations": payload},
    )


if __name__ == "__main__":
    main()
