"""The claims the README makes, asserted over the shipped fixture.

Every number in the README is produced by `tools/collect_metrics.py` and guarded by
`tools/check_numbers.py`. These tests guard the shape of the claims instead: that the
re-run test cannot fail, that the reachable harness saturates below the truth, and that the
gap is exactly the cross-batch population rather than a sampling shortfall.
"""

from __future__ import annotations

import pytest

from mos.audit import audit, simulate_permutation_harness
from mos.implementations import IMPLEMENTATIONS
from mos.semantics import MergeSpec

SPEC = MergeSpec()
UNSAFE = [name for name in sorted(IMPLEMENTATIONS) if name != "total-order"]


@pytest.fixture(scope="module")
def baseline(shipped_fixture):
    return audit(shipped_fixture, SPEC, "dedupe-last-max")


def test_the_rerun_test_flags_nothing_while_the_audit_proves_a_defect(baseline):
    """The headline, as one assertion.

    The control passes on every key. The audit proves that some of those keys hold a row
    chosen by delivery accident. Both statements are true at once, which is the entire
    argument of the repository.
    """
    assert baseline.rerun_keys_flagged == 0
    assert len(baseline.order_dependent) > 0


def test_every_order_dependent_key_passed_the_rerun_test(baseline):
    assert baseline.rerun_test_passed is True


def test_some_order_dependent_keys_are_unreachable_by_any_realistic_harness(baseline):
    assert len(baseline.cross_batch_only) > 0


def test_the_harness_saturates_below_the_truth(shipped_fixture, baseline):
    """Not a budget problem. Four hundred times the draws finds nothing more."""
    truth = {finding.key for finding in baseline.order_dependent}
    at_five = simulate_permutation_harness(shipped_fixture, SPEC, "dedupe-last-max", 5)
    at_two_thousand = simulate_permutation_harness(
        shipped_fixture, SPEC, "dedupe-last-max", 2000
    )
    assert truth - at_five
    assert (truth & at_five) == (truth & at_two_thousand)


def test_the_keys_the_harness_can_never_reach_are_exactly_the_cross_batch_ones(
    shipped_fixture, baseline
):
    truth = {finding.key for finding in baseline.order_dependent}
    unreachable = {finding.key for finding in baseline.cross_batch_only}
    flagged = simulate_permutation_harness(shipped_fixture, SPEC, "dedupe-last-max", 2000)
    assert truth - flagged == unreachable


def test_detection_is_monotone_in_the_number_of_draws(shipped_fixture):
    counts = [
        len(simulate_permutation_harness(shipped_fixture, SPEC, "dedupe-last-max", draws))
        for draws in (1, 2, 5, 10, 25)
    ]
    assert counts == sorted(counts)


@pytest.mark.parametrize("name", UNSAFE)
def test_every_unsafe_implementation_has_findings_on_the_shipped_fixture(name, shipped_fixture):
    assert audit(shipped_fixture, SPEC, name).order_dependent


def test_the_order_safe_implementation_has_none(shipped_fixture):
    assert audit(shipped_fixture, SPEC, "total-order").order_dependent == ()


def test_arrival_lww_is_the_worst_implementation_in_the_set(shipped_fixture):
    counts = {
        name: len(audit(shipped_fixture, SPEC, name).order_dependent)
        for name in sorted(IMPLEMENTATIONS)
    }
    assert counts["arrival-lww"] == max(counts.values())


def test_delete_wins_is_a_partial_fix_not_a_complete_one(shipped_fixture):
    """It resolves the tombstone ties and leaves every upsert tie exactly where it was."""
    plain = len(audit(shipped_fixture, SPEC, "dedupe-last-max").order_dependent)
    fixed = len(audit(shipped_fixture, SPEC, "delete-wins").order_dependent)
    assert 0 < fixed < plain


def test_declaring_a_total_order_removes_every_finding(shipped_fixture):
    total = MergeSpec(ordering=("seq", "event_id"))
    assert audit(shipped_fixture, total, "dedupe-last-max").order_dependent == ()


def test_the_two_spark_dedupe_readings_disagree_on_the_shipped_fixture(shipped_fixture):
    first = IMPLEMENTATIONS["dedupe-first-max"](shipped_fixture, SPEC)
    last = IMPLEMENTATIONS["dedupe-last-max"](shipped_fixture, SPEC)
    differing = [key for key in first if first[key] != last[key]]
    assert differing


def test_every_witness_in_the_shipped_audit_replays_to_two_different_rows(
    shipped_fixture, baseline
):
    by_id = {event.event_id: event for event in shipped_fixture}
    impl = IMPLEMENTATIONS["dedupe-last-max"]
    for finding in baseline.order_dependent:
        witness = finding.witness
        assert witness is not None
        left = impl([by_id[i] for i in witness.order_a], SPEC)[finding.key]
        right = impl([by_id[i] for i in witness.order_b], SPEC)[finding.key]
        assert left != right


def test_no_stable_key_carries_a_witness(baseline):
    for finding in baseline.findings:
        if not finding.order_dependent_global:
            assert finding.witness is None
