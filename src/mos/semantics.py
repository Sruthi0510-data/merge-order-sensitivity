"""The referee: what the declared merge semantics say the answer is, without running anything.

This module is the third implementation the audit needs. A permutation harness compares an
implementation against itself under a different arrival order, which is symmetric: when the
two runs disagree it knows something is wrong and cannot say which run was right. The
referee breaks that symmetry by computing the answer from the event multiset alone, never
from its order, so it can be wrong only if the declaration is wrong.

It has a third verdict that neither the harness nor the implementation can produce.
`Ambiguous` means the declaration itself does not determine an answer: two events tie on
every ordering field the spec names and assert different row states. No implementation can
be correct for that key, because there is nothing to be correct about. Finding those keys
needs no permutations at all, which is why the static arm of the audit is both exhaustive
and cheap.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mos.errors import ConfigError
from mos.events import ChangeEvent, Op

if TYPE_CHECKING:  # pragma: no cover
    from pathlib import Path

ORDERABLE_FIELDS = ("seq", "batch", "source", "event_id")
"""Fields a declaration may order by.

`arrival_index` is deliberately absent. Ordering by arrival is not a declaration about the
data, it is a restatement of the delivery accident, and permitting it here would let a spec
declare itself unambiguous by fiat while remaining exactly as order dependent as before.
"""


def _state_token(event: ChangeEvent) -> tuple[str, tuple[tuple[str, Any], ...]] | None:
    """A hashable stand-in for the row state an event asserts, for distinctness tests."""
    if event.op is Op.DELETE:
        return None
    return ("row", event.payload_items)


@dataclass(frozen=True)
class MergeSpec:
    """The declared semantics of a MERGE, as a total-or-not ordering plus a tie policy.

    `ordering` names the fields that decide which event wins. `delete_wins_ties` encodes the
    common CDC convention that a tombstone beats a concurrent upsert, which resolves some
    ties and, importantly, does not resolve ties between two upserts.
    """

    ordering: tuple[str, ...] = ("seq",)
    delete_wins_ties: bool = False
    name: str = "declared"

    def __post_init__(self) -> None:
        if not self.ordering:
            raise ConfigError("a merge spec must order by at least one field")
        unknown = [f for f in self.ordering if f not in ORDERABLE_FIELDS]
        if unknown:
            raise ConfigError(
                f"unknown ordering field(s) {unknown}; allowed: {list(ORDERABLE_FIELDS)}"
            )
        if len(set(self.ordering)) != len(self.ordering):
            raise ConfigError(f"ordering field repeated in {self.ordering}")

    @classmethod
    def from_file(cls, path: Path) -> MergeSpec:
        """Load a declaration from a TOML file.

        Reading the spec from a file rather than from flags is the whole argument of ADR-001:
        the declaration is the thing a team has never written down, and a flag leaves no record
        for anyone to disagree with in review. Unknown keys are refused rather than ignored, so
        a typo in a reviewed file cannot silently mean the default.
        """
        import tomllib

        if not path.exists():
            raise ConfigError(f"merge spec not found: {path}")
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path} is not valid TOML: {exc}") from exc

        allowed = {"name", "ordering", "delete_wins_ties"}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ConfigError(f"{path} has unknown key(s) {unknown}; allowed: {sorted(allowed)}")
        ordering = raw.get("ordering")
        if not isinstance(ordering, list) or not all(isinstance(f, str) for f in ordering):
            raise ConfigError(f"{path} must set ordering to a list of field names")
        delete_wins = raw.get("delete_wins_ties", False)
        if not isinstance(delete_wins, bool):
            raise ConfigError(f"{path} must set delete_wins_ties to true or false")
        return cls(
            ordering=tuple(ordering),
            delete_wins_ties=delete_wins,
            name=str(raw.get("name", "declared")),
        )

    def rank(self, event: ChangeEvent) -> tuple[Any, ...]:
        """The ordering key for one event. Later rank wins."""
        return tuple(getattr(event, field) for field in self.ordering)

    @property
    def is_total_by_construction(self) -> bool:
        """True when the ordering includes a field unique per event, so ties are impossible.

        Only `event_id` is unique by the fixture's own contract, which `load_events` enforces.
        """
        return "event_id" in self.ordering


@dataclass(frozen=True)
class Decided:
    """The declaration determines exactly one final row state for this key."""

    state: dict[str, Any] | None
    winner_ids: tuple[int, ...]
    tied_ids: tuple[int, ...]

    @property
    def ambiguous(self) -> bool:
        return False


@dataclass(frozen=True)
class Ambiguous:
    """The declaration ties, and the tied events assert different row states.

    `candidate_states` holds one representative state per distinct outcome, so a report can
    show a reader the two tables the same declaration permits.
    """

    tied_ids: tuple[int, ...]
    candidate_states: tuple[dict[str, Any] | None, ...]

    @property
    def ambiguous(self) -> bool:
        return True

    @property
    def conflict_size(self) -> int:
        """How many distinct outcomes the declaration permits for this key."""
        return len(self.candidate_states)


Resolution = Decided | Ambiguous


def resolve(spec: MergeSpec, events: Sequence[ChangeEvent]) -> Resolution:
    """Resolve one key's events under the declared semantics, ignoring their order.

    Raises ConfigError on an empty event list rather than returning a deleted row, because
    "no events" and "a tombstone" are different facts and conflating them hides a bug in the
    caller's grouping.
    """
    if not events:
        raise ConfigError("resolve() needs at least one event")
    ranked = [(spec.rank(event), event) for event in events]
    top = max(rank for rank, _ in ranked)
    tied = [event for rank, event in ranked if rank == top]
    if spec.delete_wins_ties and len(tied) > 1:
        tombstones = [event for event in tied if event.op is Op.DELETE]
        if tombstones:
            tied = tombstones
    tied_ids = tuple(sorted(event.event_id for event in tied))

    distinct: dict[Any, ChangeEvent] = {}
    for event in tied:
        distinct.setdefault(_state_token(event), event)
    if len(distinct) == 1:
        winner = next(iter(distinct.values()))
        return Decided(state=winner.state, winner_ids=tied_ids, tied_ids=tied_ids)
    return Ambiguous(
        tied_ids=tied_ids,
        candidate_states=tuple(event.state for event in distinct.values()),
    )


def resolve_all(spec: MergeSpec, grouped: dict[str, list[ChangeEvent]]) -> dict[str, Resolution]:
    """Resolve every key. Returned in sorted key order so reports are stable across runs."""
    return {key: resolve(spec, grouped[key]) for key in sorted(grouped)}


def declared_table(spec: MergeSpec, grouped: dict[str, list[ChangeEvent]]) -> dict[str, Any]:
    """The table the declaration determines, with ambiguous keys marked rather than guessed.

    A reader of this function sometimes expects it to just return rows. It cannot, and that
    is the finding: for an ambiguous key there is no row the declaration entitles you to.
    """
    table: dict[str, Any] = {}
    for key, resolution in resolve_all(spec, grouped).items():
        table[key] = resolution.state if isinstance(resolution, Decided) else AMBIGUOUS_MARKER
    return table


AMBIGUOUS_MARKER = "<ambiguous>"
"""Sentinel written into a declared table where the declaration does not determine a row."""


def ambiguous_keys(spec: MergeSpec, grouped: dict[str, list[ChangeEvent]]) -> list[str]:
    """Keys the declaration cannot decide. Exhaustive and exact: no permutations involved."""
    return [
        key
        for key, resolution in resolve_all(spec, grouped).items()
        if isinstance(resolution, Ambiguous)
    ]


def spans_batches(events: Iterable[ChangeEvent], event_ids: Iterable[int]) -> bool:
    """True when the named events did not all arrive in the same micro-batch.

    This is the predicate behind the blind spot the README leads with. A permutation harness
    that shuffles within a batch, which is the only shuffle a real pipeline can perform,
    cannot produce any ordering that separates events already delivered in different batches.
    """
    wanted = set(event_ids)
    batches = {event.batch for event in events if event.event_id in wanted}
    return len(batches) > 1
