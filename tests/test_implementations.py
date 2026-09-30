"""Each implementation's order behaviour, asserted rather than described in a docstring."""

from __future__ import annotations

import itertools

import pytest

from mos.errors import ConfigError
from mos.implementations import (
    IMPLEMENTATIONS,
    ORDER_SAFE_BY_CONSTRUCTION,
    get_implementation,
)
from mos.semantics import MergeSpec
from tests.conftest import make_event

SPEC = MergeSpec()
ALL_NAMES = sorted(IMPLEMENTATIONS)
UNSAFE_NAMES = [n for n in ALL_NAMES if n not in ORDER_SAFE_BY_CONSTRUCTION]


def _state(table, key="k1"):
    return table.get(key)


@pytest.mark.parametrize("name", ALL_NAMES)
def test_every_implementation_returns_one_row_per_key(name, ordered_pair):
    table = IMPLEMENTATIONS[name](ordered_pair, SPEC)
    assert set(table) == {"k1"}


@pytest.mark.parametrize("name", ALL_NAMES)
def test_every_implementation_is_deterministic_for_a_fixed_order(name, small_stream):
    first = IMPLEMENTATIONS[name](small_stream, SPEC)
    second = IMPLEMENTATIONS[name](small_stream, SPEC)
    assert first == second


@pytest.mark.parametrize("name", ALL_NAMES)
def test_every_implementation_handles_a_single_event_key(name):
    table = IMPLEMENTATIONS[name]([make_event(1, seq=4, status="x")], SPEC)
    assert _state(table) == {"status": "x"}


@pytest.mark.parametrize("name", ALL_NAMES)
def test_every_implementation_leaves_a_tombstoned_key_absent_from_the_row(name):
    events = [make_event(1, seq=1, status="x"), make_event(2, seq=2, op="delete")]
    assert _state(IMPLEMENTATIONS[name](events, SPEC)) is None


@pytest.mark.parametrize("name", UNSAFE_NAMES)
def test_every_unsafe_implementation_flips_on_a_tie(name, tied_pair):
    forward = _state(IMPLEMENTATIONS[name](tied_pair, SPEC))
    backward = _state(IMPLEMENTATIONS[name](list(reversed(tied_pair)), SPEC))
    assert forward != backward


@pytest.mark.parametrize("name", ALL_NAMES)
def test_no_implementation_flips_when_the_maximum_is_unique(name, ordered_pair):
    forward = _state(IMPLEMENTATIONS[name](ordered_pair, SPEC))
    backward = _state(IMPLEMENTATIONS[name](list(reversed(ordered_pair)), SPEC))
    if name == "arrival-lww":
        pytest.skip("arrival-lww never reads seq, so a unique maximum does not protect it")
    assert forward == backward


def test_arrival_last_write_wins_flips_even_when_the_maximum_is_unique(ordered_pair):
    """The defect class that has nothing to do with ties.

    A merge that applies events in arrival order is wrong the moment delivery reorders two
    events whose sequence numbers already say which is later. No tie is involved, and the
    declaration is completely unambiguous, which is why a tie-focused review misses it.
    """
    forward = _state(IMPLEMENTATIONS["arrival-lww"](ordered_pair, SPEC))
    backward = _state(IMPLEMENTATIONS["arrival-lww"](list(reversed(ordered_pair)), SPEC))
    assert forward == {"status": "settled"}
    assert backward == {"status": "pending"}


def test_total_order_merge_is_stable_across_every_permutation_of_a_group():
    group = [make_event(i, seq=10, status=f"s{i}") for i in range(1, 6)]
    results = {
        tuple(sorted(IMPLEMENTATIONS["total-order"](list(order), SPEC)["k1"].items()))
        for order in itertools.permutations(group)
    }
    assert len(results) == 1


@pytest.mark.parametrize("name", UNSAFE_NAMES)
def test_every_unsafe_implementation_has_more_than_one_outcome_over_all_permutations(name):
    group = [make_event(i, seq=10, status=f"s{i}") for i in range(1, 5)]
    results = {
        tuple(sorted((IMPLEMENTATIONS[name](list(order), SPEC)["k1"] or {}).items()))
        for order in itertools.permutations(group)
    }
    assert len(results) > 1


def test_dedupe_first_max_keeps_the_earliest_arriving_tied_event(tied_pair):
    assert _state(IMPLEMENTATIONS["dedupe-first-max"](tied_pair, SPEC)) == {"status": "authorised"}


def test_dedupe_last_max_keeps_the_latest_arriving_tied_event(tied_pair):
    assert _state(IMPLEMENTATIONS["dedupe-last-max"](tied_pair, SPEC)) == {"status": "settled"}


def test_the_two_dedupe_readings_disagree_on_the_same_input(tied_pair):
    """Which reading a Spark job gets is a property of the physical plan, not of the query.

    Both are legitimate implementations of `row_number() over (partition by key order by
    seq desc) = 1`. They differ on every tie, and nothing in the SQL says which you get.
    """
    first = _state(IMPLEMENTATIONS["dedupe-first-max"](tied_pair, SPEC))
    last = _state(IMPLEMENTATIONS["dedupe-last-max"](tied_pair, SPEC))
    assert first != last


def test_delete_wins_prefers_a_tombstone_over_a_tied_upsert():
    events = [make_event(1, seq=10, status="settled"), make_event(2, seq=10, op="delete")]
    assert _state(IMPLEMENTATIONS["delete-wins"](events, SPEC)) is None


def test_delete_wins_prefers_a_tombstone_regardless_of_which_arrived_first():
    events = [make_event(1, seq=10, op="delete"), make_event(2, seq=10, status="settled")]
    assert _state(IMPLEMENTATIONS["delete-wins"](events, SPEC)) is None


def test_delete_wins_still_flips_between_two_tied_upserts(tied_pair):
    """The partial fix, shown to be partial.

    Removing every tie that contains a tombstone leaves every upsert-versus-upsert tie
    exactly as undetermined as it was, which is what makes this implementation worth
    auditing: it looks finished.
    """
    forward = _state(IMPLEMENTATIONS["delete-wins"](tied_pair, SPEC))
    backward = _state(IMPLEMENTATIONS["delete-wins"](list(reversed(tied_pair)), SPEC))
    assert forward != backward


def test_delete_wins_respects_a_strictly_higher_upsert_over_an_earlier_tombstone():
    events = [make_event(1, seq=10, op="delete"), make_event(2, seq=11, status="settled")]
    assert _state(IMPLEMENTATIONS["delete-wins"](events, SPEC)) == {"status": "settled"}


@pytest.mark.parametrize("name", ALL_NAMES)
def test_implementations_do_not_mutate_the_event_sequence_they_are_given(name, small_stream):
    before = [event.event_id for event in small_stream]
    IMPLEMENTATIONS[name](small_stream, SPEC)
    assert [event.event_id for event in small_stream] == before


@pytest.mark.parametrize("name", ALL_NAMES)
def test_implementations_are_key_independent_on_the_shipped_fixture(name, shipped_fixture):
    """Verified rather than assumed, because the audit's fast path relies on it.

    The audit searches permutations of one key's events at a time. That is only equivalent
    to permuting the whole stream if no implementation lets one key influence another. All
    five bundled implementations satisfy it. A user-supplied implementation might not, and
    the ADR records that boundary.
    """
    from mos.events import group_by_key

    whole = IMPLEMENTATIONS[name](shipped_fixture, SPEC)
    per_key = {}
    for group in group_by_key(shipped_fixture).values():
        per_key.update(IMPLEMENTATIONS[name](group, SPEC))
    assert whole == per_key


def test_an_unknown_implementation_name_lists_the_valid_ones():
    with pytest.raises(ConfigError, match="total-order"):
        get_implementation("no-such-merge")


def test_get_implementation_returns_the_registered_callable():
    assert get_implementation("total-order") is IMPLEMENTATIONS["total-order"]


def test_total_order_is_the_only_implementation_claimed_order_safe():
    assert set(ORDER_SAFE_BY_CONSTRUCTION) == {"total-order"}
