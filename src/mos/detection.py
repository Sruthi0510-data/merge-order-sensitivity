"""How many permutations a sampling harness needs, and what a run of zero hits is worth.

Two pieces of arithmetic, and the second one is the reason this module exists. A harness that
draws permutations and finds nothing has not established that there is nothing. It has
established an upper bound, and the bound is set by the number of draws rather than by the
code under test. Publishing the detection rate without publishing that bound is how a tool
ends up certifying a pipeline it never actually examined.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from mos.errors import ConfigError


def miss_probability(baseline_probability: float, draws: int) -> float:
    """Chance that `draws` independent permutations all reproduce the baseline row.

    `baseline_probability` is the chance a single random reachable order leaves the key
    holding the row it already holds. A key with two equally likely outcomes has 0.5.
    """
    if not 0.0 < baseline_probability <= 1.0:
        raise ConfigError("baseline_probability must be in (0, 1]")
    if draws < 0:
        raise ConfigError("draws cannot be negative")
    return baseline_probability**draws


def draws_for_confidence(baseline_probability: float, confidence: float = 0.95) -> int:
    """Smallest number of draws whose miss probability falls at or below 1 - confidence.

    Returns 0 when the key cannot be missed, and raises when the key cannot be caught at all,
    which is the honest answer for a baseline probability of exactly 1.
    """
    if not 0.0 < confidence < 1.0:
        raise ConfigError("confidence must be in (0, 1)")
    if baseline_probability >= 1.0:
        raise ConfigError(
            "a key that always reproduces its baseline is unreachable by sampling at any budget"
        )
    if baseline_probability <= 0.0:
        return 1
    return math.ceil(math.log(1.0 - confidence) / math.log(baseline_probability))


def rule_of_three_upper_bound(trials: int) -> float:
    """Upper bound on a rate that was observed zero times in `trials`, at 95% confidence.

    The standard rule of three. It is here so that a measured zero is never published as
    zero: zero hits in 34 attempts bounds the rate below 8.8%, which is a different claim
    from "the rate is nought" and the only one the sample supports.
    """
    if trials < 1:
        raise ConfigError("rule of three needs at least one trial")
    return 3.0 / trials


@dataclass(frozen=True)
class DetectionPoint:
    """One measured point on a detection curve."""

    draws: int
    detected: int
    detectable: int

    @property
    def rate(self) -> float:
        if self.detectable == 0:
            return 0.0
        return round(100.0 * self.detected / self.detectable, 1)

    @property
    def upper_bound_when_zero(self) -> float | None:
        """When nothing was detected, the 95% upper bound on what the rate could be."""
        if self.detected or self.detectable == 0:
            return None
        return round(100.0 * rule_of_three_upper_bound(self.detectable), 1)

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "draws": self.draws,
            "detected": self.detected,
            "detectable": self.detectable,
            "rate_pct": self.rate,
            "upper_bound_pct_when_zero": self.upper_bound_when_zero,
        }
