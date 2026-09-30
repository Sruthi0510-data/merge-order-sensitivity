"""Generator properties, including the pin for the bug that left an implementation untested."""

from __future__ import annotations

import pytest

from mos.errors import ConfigError
from mos.events import Op, group_by_key
from mos.generator import GeneratorConfig, generate
from mos.semantics import Ambiguous, MergeSpec, resolve


def test_the_same_seed_produces_an_identical_stream():
    left = generate(GeneratorConfig(keys=50, seed=99))
    right = generate(GeneratorConfig(keys=50, seed=99))
    assert [e.to_mapping() for e in left] == [e.to_mapping() for e in right]


def test_a_different_seed_produces_a_different_stream():
    left = generate(GeneratorConfig(keys=50, seed=1))
    right = generate(GeneratorConfig(keys=50, seed=2))
    assert [e.to_mapping() for e in left] != [e.to_mapping() for e in right]


def test_every_requested_key_appears():
    events = generate(GeneratorConfig(keys=25, seed=4))
    assert len({event.key for event in events}) == 25


def test_event_ids_are_unique_across_the_stream():
    events = generate(GeneratorConfig(keys=80, seed=6))
    assert len({event.event_id for event in events}) == len(events)


def test_arrival_index_is_contiguous_from_zero():
    events = generate(GeneratorConfig(keys=30, seed=8))
    assert [event.arrival_index for event in events] == list(range(len(events)))


def test_events_are_delivered_in_ascending_batch_order():
    events = generate(GeneratorConfig(keys=40, seed=12))
    batches = [event.batch for event in events]
    assert batches == sorted(batches)


def test_no_event_lands_outside_the_requested_batch_range():
    events = generate(GeneratorConfig(keys=40, batches=3, seed=13))
    assert max(event.batch for event in events) <= 2


def test_a_single_batch_configuration_puts_everything_in_batch_zero():
    events = generate(GeneratorConfig(keys=20, batches=1, seed=14))
    assert {event.batch for event in events} == {0}


def test_a_zero_cross_batch_rate_keeps_every_key_inside_one_batch():
    events = generate(GeneratorConfig(keys=60, cross_batch_rate=0.0, seed=15))
    for group in group_by_key(events).values():
        assert len({event.batch for event in group}) == 1


def test_a_zero_tie_rate_leaves_no_ambiguous_keys():
    events = generate(GeneratorConfig(keys=60, tie_rate=0.0, seed=16))
    spec = MergeSpec()
    for group in group_by_key(events).values():
        assert not isinstance(resolve(spec, group), Ambiguous)


def test_a_zero_delete_rate_produces_no_tombstones():
    events = generate(GeneratorConfig(keys=40, delete_rate=0.0, seed=17))
    assert all(event.op is Op.UPSERT for event in events)


def test_a_tombstone_is_only_ever_the_last_event_for_its_key():
    events = generate(GeneratorConfig(keys=80, seed=18))
    for group in group_by_key(events).values():
        by_seq = sorted(group, key=lambda event: event.seq)
        for event in by_seq[:-1]:
            assert event.op is Op.UPSERT


def test_the_generator_produces_at_least_one_tombstone_tie():
    """Pins the bug that made delete-wins look like a no-op.

    Before tombstone_tie_rate existed, a tie was placed at a uniformly random position and a
    tombstone only ever landed at the last one, so the two draws had to coincide. The shipped
    fixture contained zero tombstone ties and the implementation whose only job is resolving
    them measured as identical to the one it was supposed to improve on. Without this test,
    nothing stops that from happening again the next time the generator is tuned.
    """
    events = generate(GeneratorConfig(keys=400, seed=20260930))
    spec = MergeSpec()
    tombstone_ties = 0
    for group in group_by_key(events).values():
        resolution = resolve(spec, group)
        if isinstance(resolution, Ambiguous):
            tied = {event.event_id for event in group} & set(resolution.tied_ids)
            if any(e.op is Op.DELETE for e in group if e.event_id in tied):
                tombstone_ties += 1
    assert tombstone_ties > 0


def test_the_shipped_fixture_also_contains_a_tombstone_tie(shipped_fixture):
    spec = MergeSpec()
    found = False
    for group in group_by_key(shipped_fixture).values():
        resolution = resolve(spec, group)
        if isinstance(resolution, Ambiguous):
            tied = set(resolution.tied_ids)
            if any(e.op is Op.DELETE for e in group if e.event_id in tied):
                found = True
    assert found is True


def test_the_shipped_fixture_contains_keys_that_span_batches(shipped_fixture):
    spanning = [
        group
        for group in group_by_key(shipped_fixture).values()
        if len({event.batch for event in group}) > 1
    ]
    assert spanning


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("keys", 0),
        ("batches", 0),
        ("max_events_per_key", 0),
    ],
)
def test_a_non_positive_size_is_refused(field, value):
    with pytest.raises(ConfigError, match="at least 1"):
        GeneratorConfig(**{field: value})


@pytest.mark.parametrize(
    "field",
    ["tie_rate", "cross_batch_rate", "delete_rate", "tombstone_tie_rate", "reorder_rate"],
)
@pytest.mark.parametrize("value", [-0.1, 1.5])
def test_a_rate_outside_zero_to_one_is_refused(field, value):
    with pytest.raises(ConfigError, match="between 0 and 1"):
        GeneratorConfig(**{field: value})


def test_generate_with_no_config_uses_the_documented_defaults():
    events = generate()
    assert len({event.key for event in events}) == GeneratorConfig().keys


def test_max_events_per_key_is_respected():
    events = generate(GeneratorConfig(keys=50, max_events_per_key=2, seed=21))
    for group in group_by_key(events).values():
        assert len(group) <= 2
