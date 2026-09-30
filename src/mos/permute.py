"""Arrival orders to try, and the one a real pipeline is physically capable of producing.

The distinction this module draws is the whole blind spot the repository reports. A
micro-batch is the unit of delivery: once batch 7 has been committed, no retry, no shuffle
and no reader parallelism can place one of its events after an event from batch 8. So a
permutation harness that models a real pipeline may reorder events inside a batch and may
not move them between batches.

`global_orders` ignores that constraint. It is not a model of anything that can happen, and
it is here because the difference between what it finds and what `within_batch_orders` finds
is exactly the set of defects no permutation harness can ever reach.
"""

from __future__ import annotations

import itertools
import math
import random
from collections.abc import Iterator, Sequence

from mos.events import ChangeEvent

EXHAUSTIVE_LIMIT = 7
"""Group sizes at or below this are enumerated exactly. 7! is 5040, which is affordable."""


def rerun_order(events: Sequence[ChangeEvent]) -> list[ChangeEvent]:
    """The order the standard idempotency test uses: the one that already happened.

    A function this trivial earns its place by being named. The test everyone writes calls
    the pipeline twice on this and asserts the table is unchanged, and naming the order makes
    it obvious in the audit output that the variable under test was held constant.
    """
    return list(events)


def _permutations_or_sample(
    items: Sequence[ChangeEvent], limit: int, rng: random.Random
) -> Iterator[tuple[ChangeEvent, ...]]:
    """Every permutation for a small group, otherwise `limit` random ones plus the original.

    The original is always yielded first so a caller comparing against the observed result
    never has to special-case an empty iterator or a missing baseline.
    """
    yield tuple(items)
    if len(items) <= 1:
        return
    if math.factorial(len(items)) <= max(limit, 1) or len(items) <= EXHAUSTIVE_LIMIT:
        seen_first = True
        for candidate in itertools.permutations(items):
            if seen_first and candidate == tuple(items):
                seen_first = False
                continue
            yield candidate
        return
    pool = list(items)
    for _ in range(limit):
        shuffled = pool[:]
        rng.shuffle(shuffled)
        yield tuple(shuffled)


def global_orders(
    group: Sequence[ChangeEvent], limit: int = 512, seed: int = 0
) -> Iterator[tuple[ChangeEvent, ...]]:
    """Orders that ignore batch boundaries. Complete, and not physically realisable."""
    yield from _permutations_or_sample(group, limit, random.Random(seed))


def within_batch_orders(
    group: Sequence[ChangeEvent], limit: int = 512, seed: int = 0
) -> Iterator[tuple[ChangeEvent, ...]]:
    """Orders reachable by reordering inside micro-batches only.

    Events are partitioned by batch, each partition is permuted independently, and the
    partitions are reassembled in ascending batch order. When a group lives entirely in one
    batch this is identical to `global_orders`, which is why the blind spot is invisible on
    any fixture that does not span batches.
    """
    rng = random.Random(seed)
    by_batch: dict[int, list[ChangeEvent]] = {}
    for event in group:
        by_batch.setdefault(event.batch, []).append(event)
    batch_ids = sorted(by_batch)
    per_batch = [list(_permutations_or_sample(by_batch[b], limit, rng)) for b in batch_ids]
    budget = limit if len(batch_ids) > 1 else None
    for produced, combination in enumerate(itertools.product(*per_batch), start=1):
        order: list[ChangeEvent] = []
        for chunk in combination:
            order.extend(chunk)
        yield tuple(order)
        if budget is not None and produced >= budget:
            return


def reachable_order_count(group: Sequence[ChangeEvent]) -> int:
    """How many distinct arrival orders a real pipeline could have produced for this group.

    The product of the factorials of the per-batch sizes, which is smaller than the factorial
    of the group size whenever the group spans batches. The gap between the two is the size
    of the space no harness can search.
    """
    sizes: dict[int, int] = {}
    for event in group:
        sizes[event.batch] = sizes.get(event.batch, 0) + 1
    total = 1
    for size in sizes.values():
        total *= math.factorial(size)
    return total


def total_order_count(group: Sequence[ChangeEvent]) -> int:
    """How many orders exist if batch boundaries are ignored."""
    return math.factorial(len(group))
