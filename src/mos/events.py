"""The change event, and the only two things an audit needs to know about arrival.

Two fields here carry the whole argument of the repository. `arrival_index` is the position
the event occupied in the stream as it was received, which is the thing a re-run test holds
fixed. `batch` is the micro-batch it was delivered in, which is the thing a realistic
permutation harness cannot cross, because a batch is the unit of delivery and you cannot
shuffle an event into a batch that has already been committed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from mos.errors import FixtureError

REQUIRED_FIELDS = ("event_id", "key", "seq", "op", "source", "batch")


class Op(str, Enum):
    """A change event either asserts a row state or removes the row. Nothing else."""

    UPSERT = "upsert"
    DELETE = "delete"


@dataclass(frozen=True)
class ChangeEvent:
    """One row-level change as delivered by a CDC source.

    `payload` is frozen into a tuple of items at construction so the event is hashable and
    so two events built from equal dicts compare equal. An earlier draft kept the dict and
    the deduplication in the referee silently failed, because dicts are unhashable.
    """

    event_id: int
    key: str
    seq: int
    op: Op
    source: str
    batch: int
    arrival_index: int = 0
    payload_items: tuple[tuple[str, Any], ...] = field(default=())

    @property
    def payload(self) -> dict[str, Any]:
        """The payload as a plain dict. Rebuilt per access; events are small."""
        return dict(self.payload_items)

    @property
    def state(self) -> dict[str, Any] | None:
        """The row state this event asserts. None means the row is gone."""
        return None if self.op is Op.DELETE else self.payload

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], arrival_index: int) -> ChangeEvent:
        """Build an event from a decoded JSON object, validating the schema first."""
        missing = [f for f in REQUIRED_FIELDS if f not in raw]
        if missing:
            raise FixtureError(f"event at arrival index {arrival_index} missing {missing}")
        try:
            op = Op(raw["op"])
        except ValueError as exc:
            raise FixtureError(
                f"event at arrival index {arrival_index} has unknown op {raw['op']!r}"
            ) from exc
        payload = raw.get("payload") or {}
        if not isinstance(payload, Mapping):
            raise FixtureError(f"event at arrival index {arrival_index} has a non-object payload")
        return cls(
            event_id=int(raw["event_id"]),
            key=str(raw["key"]),
            seq=int(raw["seq"]),
            op=op,
            source=str(raw["source"]),
            batch=int(raw["batch"]),
            arrival_index=arrival_index,
            payload_items=tuple(sorted(payload.items())),
        )

    def to_mapping(self) -> dict[str, Any]:
        """The inverse of `from_mapping`, minus `arrival_index` which is positional."""
        return {
            "event_id": self.event_id,
            "key": self.key,
            "seq": self.seq,
            "op": self.op.value,
            "source": self.source,
            "batch": self.batch,
            "payload": self.payload,
        }


def load_events(path: Path) -> list[ChangeEvent]:
    """Read a JSONL fixture. Arrival index is the file order, which is the point."""
    if not path.exists():
        raise FixtureError(f"fixture not found: {path}")
    events: list[ChangeEvent] = []
    with path.open(encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise FixtureError(f"line {index + 1} of {path} is not valid JSON: {exc}") from exc
            events.append(ChangeEvent.from_mapping(raw, arrival_index=len(events)))
    if not events:
        raise FixtureError(f"fixture {path} contains no events")
    _reject_duplicate_event_ids(events)
    return events


def _reject_duplicate_event_ids(events: Iterable[ChangeEvent]) -> None:
    """Event ids identify an event across permutations, so duplicates break every witness."""
    seen: set[int] = set()
    for event in events:
        if event.event_id in seen:
            raise FixtureError(f"duplicate event_id {event.event_id}")
        seen.add(event.event_id)


def write_events(path: Path, events: Iterable[ChangeEvent]) -> int:
    """Write a JSONL fixture and return the number of events written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_mapping(), sort_keys=True) + "\n")
            count += 1
    return count


def group_by_key(events: Iterable[ChangeEvent]) -> dict[str, list[ChangeEvent]]:
    """Partition a stream by primary key, preserving arrival order inside each group."""
    grouped: dict[str, list[ChangeEvent]] = {}
    for event in events:
        grouped.setdefault(event.key, []).append(event)
    return grouped


def iter_batches(events: Iterable[ChangeEvent]) -> Iterator[tuple[int, list[ChangeEvent]]]:
    """Yield (batch_id, events) in ascending batch order, arrival order preserved within."""
    grouped: dict[int, list[ChangeEvent]] = {}
    for event in events:
        grouped.setdefault(event.batch, []).append(event)
    for batch_id in sorted(grouped):
        yield batch_id, grouped[batch_id]
