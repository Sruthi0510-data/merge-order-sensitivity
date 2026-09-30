"""A seeded CDC event generator, because a fixture nobody can regenerate proves nothing.

The generator exists to produce the four situations that matter, in controlled proportions:
a key whose events all sit in one batch, a key whose events straddle two, a key with a
genuine sequence tie, and a key with a tombstone. Every draw comes from one `random.Random`
seeded by the caller, so the same seed produces byte-identical JSONL on any machine.

Three of the knobs deliberately overlap. A key can be both tied and cross-batch, and those
are exactly the keys the repository's headline is about, so the generator does not partition
the population into tidy disjoint groups the way a synthetic benchmark would.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from mos.errors import ConfigError
from mos.events import ChangeEvent, Op

STATUSES = ("pending", "authorised", "settled", "reversed", "disputed")


@dataclass(frozen=True)
class GeneratorConfig:
    """Shape of the stream to produce. Every field is documented in the README fixture table."""

    keys: int = 400
    batches: int = 6
    seed: int = 20260930
    max_events_per_key: int = 5
    tie_rate: float = 0.22
    cross_batch_rate: float = 0.35
    delete_rate: float = 0.12
    reorder_rate: float = 0.30

    def __post_init__(self) -> None:
        if self.keys < 1:
            raise ConfigError("keys must be at least 1")
        if self.batches < 1:
            raise ConfigError("batches must be at least 1")
        if self.max_events_per_key < 1:
            raise ConfigError("max_events_per_key must be at least 1")
        for name in ("tie_rate", "cross_batch_rate", "delete_rate", "reorder_rate"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ConfigError(f"{name} must be between 0 and 1, got {value}")


def generate(config: GeneratorConfig | None = None) -> list[ChangeEvent]:
    """Build a deterministic CDC stream and return it in delivery order.

    Delivery order is built batch by batch: events are assigned to batches first, then the
    contents of each batch are jittered. That ordering matters. Jittering the whole stream
    and then slicing it into batches would let an event drift into a batch it was never
    assigned to, and the cross-batch population the audit measures would be silently wrong.
    """
    config = config or GeneratorConfig()
    rng = random.Random(config.seed)
    staged: list[tuple[int, dict]] = []
    event_id = 0

    for index in range(config.keys):
        key = f"acct-{index:05d}"
        count = rng.randint(1, config.max_events_per_key)
        base_seq = rng.randint(1000, 9000)
        home_batch = rng.randrange(config.batches)
        spans = rng.random() < config.cross_batch_rate and config.batches > 1
        tie = rng.random() < config.tie_rate and count > 1

        seqs = [base_seq + step for step in range(count)]
        if tie:
            collide = rng.randrange(1, count)
            seqs[collide] = seqs[collide - 1]

        for position in range(count):
            batch = home_batch
            if spans and position > 0:
                batch = min(config.batches - 1, home_batch + rng.randint(1, 2))
            is_delete = position == count - 1 and rng.random() < config.delete_rate
            payload = (
                {}
                if is_delete
                else {
                    "status": rng.choice(STATUSES),
                    "amount_cents": rng.randrange(500, 900000),
                    "revision": position,
                }
            )
            staged.append(
                (
                    batch,
                    {
                        "event_id": event_id,
                        "key": key,
                        "seq": seqs[position],
                        "op": Op.DELETE.value if is_delete else Op.UPSERT.value,
                        "source": f"shard-{index % 4}",
                        "batch": batch,
                        "payload": payload,
                    },
                )
            )
            event_id += 1

    by_batch: dict[int, list[dict]] = {}
    for batch, raw in staged:
        by_batch.setdefault(batch, []).append(raw)

    ordered: list[ChangeEvent] = []
    for batch in sorted(by_batch):
        chunk = by_batch[batch]
        for position in range(len(chunk) - 1, 0, -1):
            if rng.random() < config.reorder_rate:
                swap = rng.randrange(position + 1)
                chunk[position], chunk[swap] = chunk[swap], chunk[position]
        for raw in chunk:
            ordered.append(ChangeEvent.from_mapping(raw, arrival_index=len(ordered)))
    return ordered
