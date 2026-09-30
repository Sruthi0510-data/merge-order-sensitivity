"""The arithmetic that keeps a measured zero from being published as zero."""

from __future__ import annotations

import pytest

from mos.detection import (
    DetectionPoint,
    draws_for_confidence,
    miss_probability,
    rule_of_three_upper_bound,
)
from mos.errors import ConfigError


def test_a_single_draw_misses_a_two_outcome_key_half_the_time():
    assert miss_probability(0.5, 1) == 0.5


def test_miss_probability_falls_geometrically_with_draws():
    assert miss_probability(0.5, 4) == pytest.approx(0.0625)


def test_zero_draws_miss_everything():
    assert miss_probability(0.5, 0) == 1.0


def test_a_key_that_always_reproduces_its_baseline_is_never_caught():
    assert miss_probability(1.0, 1000) == 1.0


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.1])
def test_an_out_of_range_baseline_probability_is_refused(bad):
    with pytest.raises(ConfigError, match="baseline_probability"):
        miss_probability(bad, 1)


def test_a_negative_draw_count_is_refused():
    with pytest.raises(ConfigError, match="negative"):
        miss_probability(0.5, -1)


def test_five_draws_reach_95_percent_confidence_on_a_two_outcome_key():
    assert draws_for_confidence(0.5, 0.95) == 5


def test_a_three_outcome_key_needs_fewer_draws_than_a_two_outcome_key():
    assert draws_for_confidence(1 / 3, 0.95) < draws_for_confidence(0.5, 0.95)


def test_higher_confidence_costs_more_draws():
    assert draws_for_confidence(0.5, 0.99) > draws_for_confidence(0.5, 0.95)


def test_a_key_that_cannot_be_missed_needs_one_draw():
    assert draws_for_confidence(1e-300, 0.95) == 1


def test_a_baseline_probability_of_zero_short_circuits_to_one_draw():
    """Guards against log(0). A key that never reproduces its baseline is caught first try."""
    assert draws_for_confidence(0.0, 0.95) == 1


def test_a_negative_baseline_probability_also_short_circuits_rather_than_raising():
    assert draws_for_confidence(-0.0, 0.99) == 1


def test_an_unreachable_key_is_reported_as_unreachable_rather_than_given_a_budget():
    """The honest answer for a key no budget can catch is a refusal, not a large number."""
    with pytest.raises(ConfigError, match="unreachable by sampling"):
        draws_for_confidence(1.0, 0.95)


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.5, 2.0])
def test_an_out_of_range_confidence_is_refused(bad):
    with pytest.raises(ConfigError, match="confidence"):
        draws_for_confidence(0.5, bad)


def test_the_rule_of_three_bounds_a_zero_observation():
    assert rule_of_three_upper_bound(34) == pytest.approx(3 / 34)


def test_the_bound_tightens_as_the_sample_grows():
    assert rule_of_three_upper_bound(100) < rule_of_three_upper_bound(10)


def test_the_rule_of_three_needs_at_least_one_trial():
    with pytest.raises(ConfigError, match="at least one trial"):
        rule_of_three_upper_bound(0)


def test_a_detection_point_reports_its_rate_as_a_percentage():
    assert DetectionPoint(draws=5, detected=18, detectable=32).rate == 56.2


def test_a_detection_point_with_nothing_detectable_reports_zero_rather_than_dividing():
    assert DetectionPoint(draws=5, detected=0, detectable=0).rate == 0.0


def test_a_zero_detection_reports_an_upper_bound_instead_of_a_bare_zero():
    point = DetectionPoint(draws=5, detected=0, detectable=40)
    assert point.rate == 0.0
    assert point.upper_bound_when_zero == 7.5


def test_a_non_zero_detection_has_no_upper_bound_field():
    assert DetectionPoint(draws=5, detected=1, detectable=40).upper_bound_when_zero is None


def test_a_detection_point_serialises_every_published_field():
    payload = DetectionPoint(draws=2, detected=0, detectable=10).as_dict()
    assert set(payload) == {
        "draws",
        "detected",
        "detectable",
        "rate_pct",
        "upper_bound_pct_when_zero",
    }
