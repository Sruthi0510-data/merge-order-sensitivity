"""The audit engine, including the control arm the whole README is about."""

from __future__ import annotations

import pytest

from mos.audit import (
    AuditResult,
    audit,
    is_order_safe_by_construction,
    simulate_permutation_harness,
)
from mos.errors import ConfigError
from mos.implementations import IMPLEMENTATIONS
from mos.semantics import MergeSpec
from tests.conftest import make_event

SPEC = MergeSpec()
ALL_NAMES = sorted(IMPLEMENTATIONS)


def _finding(result: AuditResult, key: str):
    return next(f for f in result.findings if f.key == key)


@pytest.mark.parametrize("name", ALL_NAMES)
def test_the_rerun_idempotency_test_passes_for_every_implementation(name, small_stream):
    """The control arm, and the claim the README leads with.

    Re-running the batch in the order it arrived reproduces the table exactly, for every
    implementation here including the one that is wrong on 80 percent of its keys. The test
    is not weak, it is measuring a different property: idempotency, not order independence.
    """
    result = audit(small_stream, SPEC, name)
    assert result.rerun_test_passed is True
    assert result.rerun_keys_flagged == 0


@pytest.mark.parametrize("name", ALL_NAMES)
def test_the_rerun_test_passes_on_the_shipped_fixture_too(name, shipped_fixture):
    assert audit(shipped_fixture, SPEC, name).rerun_keys_flagged == 0


def test_a_tie_in_one_batch_is_found_by_both_arms(tied_pair):
    finding = _finding(audit(tied_pair, SPEC, "dedupe-last-max"), "k1")
    assert finding.order_dependent_global is True
    assert finding.order_dependent_within_batch is True
    assert finding.cross_batch_only is False


def test_a_tie_split_across_batches_is_found_only_by_the_unreachable_arm(
    tied_pair_across_batches,
):
    """The headline finding, in its smallest possible form.

    The key is order dependent. A harness that models a real pipeline cannot show it,
    because producing the other outcome requires moving an event into a batch that was
    already committed.
    """
    finding = _finding(audit(tied_pair_across_batches, SPEC, "dedupe-last-max"), "k1")
    assert finding.order_dependent_global is True
    assert finding.order_dependent_within_batch is False
    assert finding.cross_batch_only is True


def test_an_unambiguous_key_is_reported_as_stable(ordered_pair):
    finding = _finding(audit(ordered_pair, SPEC, "dedupe-last-max"), "k1")
    assert finding.order_dependent_global is False
    assert finding.spec_ambiguous is False


def test_the_total_order_implementation_finds_nothing_anywhere(small_stream):
    assert audit(small_stream, SPEC, "total-order").order_dependent == ()


def test_arrival_lww_is_order_dependent_on_a_key_the_declaration_decides(ordered_pair):
    """Separates the two defect classes.

    The declaration says seq 11 wins and is not ambiguous. The implementation still flips,
    because it never reads seq. That is an implementation defect, and it is the fixable one.
    """
    result = audit(ordered_pair, SPEC, "arrival-lww")
    finding = _finding(result, "k1")
    assert finding.spec_ambiguous is False
    assert finding.order_dependent_global is True
    assert result.implementation_defects == (finding,)


def test_an_ambiguous_key_is_not_counted_as_an_implementation_defect(tied_pair):
    result = audit(tied_pair, SPEC, "dedupe-last-max")
    assert result.spec_ambiguous
    assert result.implementation_defects == ()


def test_a_witness_replays_to_the_two_states_it_claims(tied_pair):
    result = audit(tied_pair, SPEC, "dedupe-last-max")
    witness = _finding(result, "k1").witness
    by_id = {event.event_id: event for event in tied_pair}
    impl = IMPLEMENTATIONS["dedupe-last-max"]
    assert impl([by_id[i] for i in witness.order_a], SPEC)["k1"] == witness.state_a
    assert impl([by_id[i] for i in witness.order_b], SPEC)["k1"] == witness.state_b


def test_a_witness_names_two_different_states(tied_pair):
    witness = _finding(audit(tied_pair, SPEC, "dedupe-last-max"), "k1").witness
    assert witness.state_a != witness.state_b


def test_a_stable_key_has_no_witness(ordered_pair):
    assert _finding(audit(ordered_pair, SPEC, "dedupe-last-max"), "k1").witness is None


def test_a_witness_records_whether_its_swap_was_reachable(tied_pair, tied_pair_across_batches):
    reachable = _finding(audit(tied_pair, SPEC, "dedupe-last-max"), "k1").witness
    unreachable = _finding(
        audit(tied_pair_across_batches, SPEC, "dedupe-last-max"), "k1"
    ).witness
    assert reachable.within_batch is True
    assert unreachable.within_batch is False


def test_a_witness_serialises_every_field_a_report_needs(tied_pair):
    payload = _finding(audit(tied_pair, SPEC, "dedupe-last-max"), "k1").witness.as_dict()
    assert set(payload) == {"order_a", "order_b", "state_a", "state_b", "within_batch"}


def test_an_exhaustively_searched_stable_key_says_so(ordered_pair):
    assert _finding(audit(ordered_pair, SPEC, "dedupe-last-max"), "k1").search_was_exhaustive


def test_a_sampled_search_does_not_claim_to_be_exhaustive():
    """A negative result from a sample is not a proof and must not be presented as one."""
    group = [make_event(i, seq=i) for i in range(12)]
    finding = _finding(audit(group, SPEC, "total-order", search_limit=5), "k1")
    assert finding.search_was_exhaustive is False


def test_findings_are_returned_in_sorted_key_order(small_stream):
    keys = [f.key for f in audit(small_stream, SPEC, "dedupe-last-max").findings]
    assert keys == sorted(keys)


def test_the_audit_does_not_reorder_the_stream_it_was_given(small_stream):
    before = [event.event_id for event in small_stream]
    audit(small_stream, SPEC, "dedupe-last-max")
    assert [event.event_id for event in small_stream] == before


def test_the_observed_table_matches_a_direct_run_of_the_implementation(small_stream):
    result = audit(small_stream, SPEC, "dedupe-last-max")
    assert result.observed_table == IMPLEMENTATIONS["dedupe-last-max"](small_stream, SPEC)


def test_a_key_whose_observed_row_is_not_the_declared_row_is_flagged(ordered_pair):
    result = audit(list(reversed(ordered_pair)), SPEC, "arrival-lww")
    assert _finding(result, "k1").matches_referee_on_observed_order is False


def test_an_ambiguous_key_never_claims_to_match_the_referee(tied_pair):
    finding = _finding(audit(tied_pair, SPEC, "dedupe-last-max"), "k1")
    assert finding.matches_referee_on_observed_order is False


def test_the_summary_reports_every_rate_the_readme_quotes(small_stream):
    summary = audit(small_stream, SPEC, "dedupe-last-max").summary()
    for field in (
        "rerun_keys_flagged",
        "order_dependent_keys",
        "cross_batch_only_keys",
        "implementation_defect_keys",
        "order_dependent_pct",
    ):
        assert field in summary


def test_a_rate_over_an_empty_finding_set_is_zero_rather_than_a_division_error():
    empty = AuditResult(
        implementation="total-order",
        spec=SPEC,
        findings=(),
        rerun_test_passed=True,
        rerun_keys_flagged=0,
        event_count=0,
        batch_count=0,
        search_limit=1,
    )
    assert empty.rate(()) == 0.0
    assert empty.key_count == 0


def test_a_finding_serialises_every_field_the_json_output_publishes(tied_pair):
    payload = _finding(audit(tied_pair, SPEC, "dedupe-last-max"), "k1").as_dict()
    assert payload["cross_batch_only"] is False
    assert payload["key"] == "k1"
    assert "witness" in payload


def test_an_unknown_implementation_is_refused_before_any_work_happens(small_stream):
    with pytest.raises(ConfigError):
        audit(small_stream, SPEC, "not-a-merge")


def test_the_default_spec_orders_by_seq_alone(small_stream):
    assert audit(small_stream, implementation="total-order").spec.ordering == ("seq",)


def test_the_harness_flags_a_tie_that_shares_a_batch(tied_pair):
    flagged = simulate_permutation_harness(tied_pair, SPEC, "dedupe-last-max", draws=30)
    assert flagged == {"k1"}


def test_the_harness_never_flags_a_tie_split_across_batches(tied_pair_across_batches):
    """At any budget. This is the structural ceiling, not a sampling shortfall."""
    flagged = simulate_permutation_harness(
        tied_pair_across_batches, SPEC, "dedupe-last-max", draws=2000
    )
    assert flagged == set()


def test_the_harness_flags_nothing_for_an_order_safe_implementation(small_stream):
    assert simulate_permutation_harness(small_stream, SPEC, "total-order", draws=50) == set()


def test_the_harness_is_reproducible_for_a_fixed_seed(small_stream):
    first = simulate_permutation_harness(small_stream, SPEC, "dedupe-last-max", 5, seed=3)
    second = simulate_permutation_harness(small_stream, SPEC, "dedupe-last-max", 5, seed=3)
    assert first == second


def test_zero_draws_flag_nothing(small_stream):
    assert simulate_permutation_harness(small_stream, SPEC, "dedupe-last-max", 0) == set()


def test_only_total_order_is_reported_order_safe_by_construction():
    assert is_order_safe_by_construction("total-order") is True
    assert is_order_safe_by_construction("delete-wins") is False
