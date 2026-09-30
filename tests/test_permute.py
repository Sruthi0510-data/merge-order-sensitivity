"""The batch boundary constraint, which is where the repository's blind spot comes from."""

from __future__ import annotations

import math

import pytest

from mos.permute import (
    EXHAUSTIVE_LIMIT,
    global_orders,
    reachable_order_count,
    rerun_order,
    total_order_count,
    within_batch_orders,
)
from tests.conftest import make_event


def _ids(orders):
    return [tuple(event.event_id for event in order) for order in orders]


def test_the_rerun_order_is_the_order_that_already_happened(ordered_pair):
    assert rerun_order(ordered_pair) == list(ordered_pair)


def test_the_rerun_order_is_a_copy_so_a_caller_cannot_corrupt_the_stream(ordered_pair):
    copy = rerun_order(ordered_pair)
    copy.reverse()
    assert [event.event_id for event in ordered_pair] == [1, 2]


def test_the_original_order_is_always_yielded_first(tied_pair):
    assert _ids(global_orders(tied_pair))[0] == (1, 2)


def test_a_single_event_group_has_exactly_one_order():
    assert len(_ids(global_orders([make_event(1)]))) == 1


def test_global_orders_enumerates_every_permutation_of_a_small_group():
    group = [make_event(i) for i in range(1, 5)]
    assert len(set(_ids(global_orders(group)))) == math.factorial(4)


def test_within_batch_orders_cannot_swap_events_from_different_batches(
    tied_pair_across_batches,
):
    """The structural claim, stated as a test.

    Two events tied on seq, one in each micro-batch. There is exactly one arrival order a
    real pipeline could have produced, so a harness restricted to reality has nothing to
    sample and will report the key as stable at any budget.
    """
    assert _ids(within_batch_orders(tied_pair_across_batches)) == [(1, 2)]


def test_global_orders_does_swap_events_from_different_batches(tied_pair_across_batches):
    assert set(_ids(global_orders(tied_pair_across_batches))) == {(1, 2), (2, 1)}


def test_within_batch_orders_equals_global_orders_when_a_group_shares_one_batch(tied_pair):
    assert set(_ids(within_batch_orders(tied_pair))) == set(_ids(global_orders(tied_pair)))


def test_within_batch_orders_permutes_inside_each_batch_independently():
    group = [
        make_event(1, batch=0),
        make_event(2, batch=0),
        make_event(3, batch=1),
        make_event(4, batch=1),
    ]
    orders = set(_ids(within_batch_orders(group)))
    assert orders == {(1, 2, 3, 4), (1, 2, 4, 3), (2, 1, 3, 4), (2, 1, 4, 3)}


def test_within_batch_orders_always_lists_batches_in_ascending_order():
    group = [make_event(1, batch=3), make_event(2, batch=1)]
    assert _ids(within_batch_orders(group)) == [(2, 1)]


def test_reachable_order_count_is_the_product_of_per_batch_factorials():
    group = [
        make_event(1, batch=0),
        make_event(2, batch=0),
        make_event(3, batch=0),
        make_event(4, batch=1),
    ]
    assert reachable_order_count(group) == math.factorial(3) * math.factorial(1)


def test_total_order_count_ignores_batches():
    group = [make_event(1, batch=0), make_event(2, batch=1), make_event(3, batch=2)]
    assert total_order_count(group) == 6


def test_the_reachable_space_is_strictly_smaller_whenever_a_group_spans_batches():
    group = [make_event(1, batch=0), make_event(2, batch=1)]
    assert reachable_order_count(group) < total_order_count(group)


def test_the_two_spaces_coincide_when_a_group_sits_in_one_batch():
    group = [make_event(1, batch=0), make_event(2, batch=0)]
    assert reachable_order_count(group) == total_order_count(group)


def test_a_group_above_the_exhaustive_limit_is_sampled_not_enumerated():
    group = [make_event(i) for i in range(EXHAUSTIVE_LIMIT + 3)]
    assert len(_ids(global_orders(group, limit=12))) == 13


def test_sampling_is_reproducible_for_a_fixed_seed():
    group = [make_event(i) for i in range(EXHAUSTIVE_LIMIT + 3)]
    first = _ids(global_orders(group, limit=8, seed=5))
    second = _ids(global_orders(group, limit=8, seed=5))
    assert first == second


def test_a_different_seed_gives_a_different_sample():
    group = [make_event(i) for i in range(EXHAUSTIVE_LIMIT + 4)]
    first = _ids(global_orders(group, limit=8, seed=1))
    second = _ids(global_orders(group, limit=8, seed=2))
    assert first != second


@pytest.mark.parametrize("size", [1, 2, 3, 4, 5, 6, 7])
def test_small_groups_are_enumerated_exactly(size):
    group = [make_event(i) for i in range(size)]
    assert len(set(_ids(global_orders(group)))) == math.factorial(size)


def test_within_batch_orders_respects_its_budget_when_a_group_spans_batches():
    group = [make_event(i, batch=i % 2) for i in range(10)]
    assert len(_ids(within_batch_orders(group, limit=5))) <= 5


def test_every_yielded_order_is_a_permutation_of_the_input():
    group = [make_event(i, batch=i % 2) for i in range(6)]
    original = {event.event_id for event in group}
    for order in within_batch_orders(group, limit=20):
        assert {event.event_id for event in order} == original
