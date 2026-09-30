"""The MERGE implementations under audit, written the way they get written in practice.

Each of these is a real pattern. The first is what a pipeline does before anyone has thought
about late data. The next two are the two ways a Spark deduplication window resolves a tie,
and which one you get depends on the physical plan rather than on anything in your code. The
last two are the fixes, and only one of them is a complete fix.

An implementation takes the stream in arrival order and returns the whole table, because
that is the shape a real job has and because a per-key signature would hide any bug that
crosses keys.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from mos.errors import ConfigError
from mos.events import ChangeEvent, Op, group_by_key
from mos.semantics import MergeSpec

Table = dict[str, dict[str, Any] | None]
MergeImpl = Callable[[Sequence[ChangeEvent], MergeSpec], Table]


def arrival_last_write_wins(events: Sequence[ChangeEvent], spec: MergeSpec) -> Table:
    """Apply every event in the order it arrived. The sequence column is never read.

    This is the merge you write when the source looks ordered. It is order dependent for any
    key that receives more than one event, not only for ties, because a redelivery or a
    partition-parallel read is enough to swap two events whose sequence numbers already say
    which one is later.
    """
    del spec
    table: Table = {}
    for event in events:
        table[event.key] = event.state
    return table


def dedupe_keep_first_max(events: Sequence[ChangeEvent], spec: MergeSpec) -> Table:
    """Keep the first event that attains the maximum rank, in arrival order.

    The local equivalent of a `row_number() over (partition by key order by seq desc) = 1`
    deduplication. When two rows tie on seq, row_number picks one of them and which one is a
    property of the shuffle, not of the query. This function models the branch where the
    earliest-arriving tied row survives.
    """
    table: Table = {}
    for key, group in group_by_key(events).items():
        best = group[0]
        best_rank = spec.rank(best)
        for event in group[1:]:
            rank = spec.rank(event)
            if rank > best_rank:
                best, best_rank = event, rank
        table[key] = best.state
    return table


def dedupe_keep_last_max(events: Sequence[ChangeEvent], spec: MergeSpec) -> Table:
    """Keep the last event that attains the maximum rank, in arrival order.

    The other branch of the same deduplication, and the one a stable `sorted()` followed by
    taking the final element produces. Identical to `dedupe_keep_first_max` on every key
    whose maximum is unique, which is what makes the difference so hard to notice.
    """
    table: Table = {}
    for key, group in group_by_key(events).items():
        best = group[0]
        best_rank = spec.rank(best)
        for event in group[1:]:
            rank = spec.rank(event)
            if rank >= best_rank:
                best, best_rank = event, rank
        table[key] = best.state
    return table


def delete_wins_merge(events: Sequence[ChangeEvent], spec: MergeSpec) -> Table:
    """Last-max wins, except that a tombstone beats an upsert it ties with.

    A partial fix, and worth auditing precisely because it looks like a complete one. It
    removes every tie that has a tombstone in it and leaves every upsert-versus-upsert tie
    exactly as undetermined as before.
    """
    table: Table = {}
    for key, group in group_by_key(events).items():
        best = group[0]
        best_rank = spec.rank(best)
        for event in group[1:]:
            rank = spec.rank(event)
            tie_goes_to_event = event.op is Op.DELETE or best.op is not Op.DELETE
            if rank > best_rank or (rank == best_rank and tie_goes_to_event):
                best, best_rank = event, rank
        table[key] = best.state
    return table


def total_order_merge(events: Sequence[ChangeEvent], spec: MergeSpec) -> Table:
    """Order by the declared fields and then by event id, which is unique per event.

    Appending a unique field to the ordering makes the comparison a total order, so the
    maximum is unique and the result cannot depend on arrival. This is the fix, and the cost
    it carries is that the tie is now broken by something with no business meaning: event id
    ordering is arbitrary, it is merely consistent. The repository does not claim it picks
    the right row, only that it picks the same row every time.
    """
    table: Table = {}
    for key, group in group_by_key(events).items():
        best = max(group, key=lambda event: (*spec.rank(event), event.event_id))
        table[key] = best.state
    return table


IMPLEMENTATIONS: dict[str, MergeImpl] = {
    "arrival-lww": arrival_last_write_wins,
    "dedupe-first-max": dedupe_keep_first_max,
    "dedupe-last-max": dedupe_keep_last_max,
    "delete-wins": delete_wins_merge,
    "total-order": total_order_merge,
}

ORDER_SAFE_BY_CONSTRUCTION = frozenset({"total-order"})
"""Implementations whose result provably cannot depend on arrival order.

Listed so the test suite can assert the property for each of them over every fixture rather
than trusting the docstring, and so the CLI can say when an audit found nothing because
there was nothing to find.
"""


def get_implementation(name: str) -> MergeImpl:
    """Look up an implementation, failing with the list of valid names rather than a KeyError."""
    try:
        return IMPLEMENTATIONS[name]
    except KeyError as exc:
        raise ConfigError(
            f"unknown implementation {name!r}; available: {sorted(IMPLEMENTATIONS)}"
        ) from exc
