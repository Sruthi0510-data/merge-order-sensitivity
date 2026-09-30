"""Properties of the referee, especially the two verdicts people expect it to collapse."""

from __future__ import annotations

import pytest

from mos.errors import ConfigError
from mos.semantics import (
    AMBIGUOUS_MARKER,
    ORDERABLE_FIELDS,
    Ambiguous,
    Decided,
    MergeSpec,
    ambiguous_keys,
    declared_table,
    resolve,
    resolve_all,
    spans_batches,
)
from tests.conftest import make_event


def test_a_key_with_one_event_is_decided_by_that_event():
    resolution = resolve(MergeSpec(), [make_event(1, seq=5, status="settled")])
    assert isinstance(resolution, Decided)
    assert resolution.state == {"status": "settled"}


def test_the_highest_sequence_number_wins_when_it_is_unique(ordered_pair):
    resolution = resolve(MergeSpec(), ordered_pair)
    assert isinstance(resolution, Decided)
    assert resolution.state == {"status": "settled"}


def test_the_result_does_not_depend_on_the_order_the_events_are_passed_in(ordered_pair):
    forward = resolve(MergeSpec(), ordered_pair)
    backward = resolve(MergeSpec(), list(reversed(ordered_pair)))
    assert forward.state == backward.state


def test_a_tie_on_different_row_states_is_ambiguous(tied_pair):
    resolution = resolve(MergeSpec(), tied_pair)
    assert isinstance(resolution, Ambiguous)
    assert resolution.conflict_size == 2


def test_a_tie_on_identical_row_states_is_decided_not_ambiguous():
    """A tie is only a problem when the tied events disagree about the row.

    Two redeliveries of the same change tie on every ordering field and assert exactly the
    same row, so there is nothing undetermined. Reporting those as findings would bury the
    real ones, which is the failure mode of every duplicate detector that counts rows
    instead of comparing them.
    """
    events = [make_event(1, seq=10, status="settled"), make_event(2, seq=10, status="settled")]
    assert isinstance(resolve(MergeSpec(), events), Decided)


def test_a_tie_between_an_upsert_and_a_tombstone_is_ambiguous_by_default():
    events = [make_event(1, seq=10, status="settled"), make_event(2, seq=10, op="delete")]
    assert isinstance(resolve(MergeSpec(), events), Ambiguous)


def test_delete_wins_ties_resolves_a_tombstone_tie():
    events = [make_event(1, seq=10, status="settled"), make_event(2, seq=10, op="delete")]
    resolution = resolve(MergeSpec(delete_wins_ties=True), events)
    assert isinstance(resolution, Decided)
    assert resolution.state is None


def test_delete_wins_ties_does_not_resolve_a_tie_between_two_upserts():
    events = [make_event(1, seq=10, status="a"), make_event(2, seq=10, status="b")]
    assert isinstance(resolve(MergeSpec(delete_wins_ties=True), events), Ambiguous)


def test_delete_wins_ties_leaves_a_unique_maximum_alone():
    events = [make_event(1, seq=10, op="delete"), make_event(2, seq=11, status="settled")]
    resolution = resolve(MergeSpec(delete_wins_ties=True), events)
    assert resolution.state == {"status": "settled"}


def test_two_tombstones_tied_together_are_decided_because_they_agree():
    events = [make_event(1, seq=10, op="delete"), make_event(2, seq=10, op="delete")]
    assert isinstance(resolve(MergeSpec(), events), Decided)


def test_adding_event_id_to_the_ordering_removes_every_tie(tied_pair):
    spec = MergeSpec(ordering=("seq", "event_id"))
    assert isinstance(resolve(spec, tied_pair), Decided)


def test_a_spec_that_orders_by_event_id_is_total_by_construction():
    assert MergeSpec(ordering=("seq", "event_id")).is_total_by_construction is True


def test_a_spec_that_orders_by_seq_alone_is_not_total_by_construction():
    assert MergeSpec().is_total_by_construction is False


def test_ordering_by_arrival_index_is_refused_because_it_declares_nothing():
    """arrival_index is not in ORDERABLE_FIELDS on purpose.

    A spec allowed to order by arrival could declare itself unambiguous while remaining
    exactly as order dependent as before, which would let the tool certify the defect it
    exists to find.
    """
    with pytest.raises(ConfigError, match="unknown ordering field"):
        MergeSpec(ordering=("arrival_index",))


def test_arrival_index_is_absent_from_the_orderable_field_list():
    assert "arrival_index" not in ORDERABLE_FIELDS


def test_an_empty_ordering_is_refused():
    with pytest.raises(ConfigError, match="at least one field"):
        MergeSpec(ordering=())


def test_a_repeated_ordering_field_is_refused():
    with pytest.raises(ConfigError, match="repeated"):
        MergeSpec(ordering=("seq", "seq"))


@pytest.mark.parametrize("field", ORDERABLE_FIELDS)
def test_every_advertised_orderable_field_is_actually_usable(field):
    spec = MergeSpec(ordering=(field,))
    assert spec.rank(make_event(1, seq=3)) is not None


def test_resolving_an_empty_event_list_is_an_error_not_a_tombstone():
    with pytest.raises(ConfigError, match="at least one event"):
        resolve(MergeSpec(), [])


def test_resolve_all_returns_keys_in_sorted_order_so_reports_are_stable():
    grouped = {"z": [make_event(1, key="z")], "a": [make_event(2, key="a")]}
    assert list(resolve_all(MergeSpec(), grouped)) == ["a", "z"]


def test_a_declared_table_marks_ambiguous_keys_rather_than_guessing(tied_pair):
    table = declared_table(MergeSpec(), {"k1": tied_pair})
    assert table["k1"] == AMBIGUOUS_MARKER


def test_a_declared_table_carries_the_row_for_a_decided_key(ordered_pair):
    table = declared_table(MergeSpec(), {"k1": ordered_pair})
    assert table["k1"] == {"status": "settled"}


def test_ambiguous_keys_lists_only_the_undetermined_ones(tied_pair, ordered_pair):
    grouped = {"tied": tied_pair, "fine": ordered_pair}
    assert ambiguous_keys(MergeSpec(), grouped) == ["tied"]


def test_the_tied_id_set_is_reported_in_sorted_order(tied_pair):
    resolution = resolve(MergeSpec(), list(reversed(tied_pair)))
    assert resolution.tied_ids == (1, 2)


def test_a_decided_key_reports_its_winner_ids(ordered_pair):
    resolution = resolve(MergeSpec(), ordered_pair)
    assert resolution.winner_ids == (2,)


def test_spans_batches_is_true_when_the_tied_events_arrived_separately(
    tied_pair_across_batches,
):
    assert spans_batches(tied_pair_across_batches, [1, 2]) is True


def test_spans_batches_is_false_when_the_tied_events_shared_a_batch(tied_pair):
    assert spans_batches(tied_pair, [1, 2]) is False


def test_spans_batches_ignores_events_outside_the_named_set(tied_pair_across_batches):
    assert spans_batches(tied_pair_across_batches, [1]) is False


def test_the_ambiguous_flag_distinguishes_the_two_resolution_types(tied_pair, ordered_pair):
    assert resolve(MergeSpec(), tied_pair).ambiguous is True
    assert resolve(MergeSpec(), ordered_pair).ambiguous is False
