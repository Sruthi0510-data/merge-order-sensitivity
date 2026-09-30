"""Shared builders. Every test that needs an event builds it here, so the schema lives once."""

from __future__ import annotations

from pathlib import Path

import pytest

from mos.events import ChangeEvent, Op, load_events
from mos.generator import GeneratorConfig, generate

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "cdc_events.jsonl"


def make_event(
    event_id: int,
    key: str = "k1",
    seq: int = 1,
    op: str = "upsert",
    source: str = "shard-0",
    batch: int = 0,
    arrival_index: int | None = None,
    **payload: object,
) -> ChangeEvent:
    """Build one event. Keyword payload keeps the call sites readable at a glance."""
    return ChangeEvent.from_mapping(
        {
            "event_id": event_id,
            "key": key,
            "seq": seq,
            "op": op,
            "source": source,
            "batch": batch,
            "payload": payload,
        },
        arrival_index=event_id if arrival_index is None else arrival_index,
    )


@pytest.fixture
def tied_pair() -> list[ChangeEvent]:
    """Two events tied on seq asserting different rows, both in batch 0."""
    return [
        make_event(1, seq=10, status="authorised"),
        make_event(2, seq=10, status="settled"),
    ]


@pytest.fixture
def tied_pair_across_batches() -> list[ChangeEvent]:
    """The same tie, delivered one event per micro-batch. No shuffle can swap these."""
    return [
        make_event(1, seq=10, batch=0, status="authorised"),
        make_event(2, seq=10, batch=1, status="settled"),
    ]


@pytest.fixture
def ordered_pair() -> list[ChangeEvent]:
    """Two events with distinct sequence numbers. The declaration decides this key."""
    return [
        make_event(1, seq=10, status="pending"),
        make_event(2, seq=11, status="settled"),
    ]


@pytest.fixture
def small_stream() -> list[ChangeEvent]:
    """A deterministic 40-key stream, small enough for exhaustive searches in tests."""
    return generate(GeneratorConfig(keys=40, seed=11, batches=3))


@pytest.fixture(scope="session")
def shipped_fixture() -> list[ChangeEvent]:
    """The committed fixture the README quotes. Session scoped: it is read once."""
    return load_events(FIXTURE_PATH)


@pytest.fixture
def delete_event() -> ChangeEvent:
    return make_event(9, seq=10, op=Op.DELETE.value)
