"""The audit engine: three arms, and the honest accounting of what each one can reach.

Arm one is static. The referee resolves every key from its event multiset, and any key whose
declaration ties on different row states is order dependent with certainty. No permutation is
run and the answer is exact.

Arm two is constructive. For every key, the reachable arrival orders are searched for two
that leave the implementation holding different rows. This produces a witness: two concrete
orders a reviewer can replay. Exhaustive for small groups, sampled above that, and the
result records which it was.

Arm three is the control. The re-run idempotency test is actually executed rather than
assumed to pass, because the claim the README leads with is about that test and a claim about
code belongs in code.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from mos.events import ChangeEvent, group_by_key
from mos.implementations import (
    ORDER_SAFE_BY_CONSTRUCTION,
    MergeImpl,
    Table,
    get_implementation,
)
from mos.permute import (
    global_orders,
    reachable_order_count,
    rerun_order,
    total_order_count,
    within_batch_orders,
)
from mos.semantics import Ambiguous, MergeSpec, resolve

DEFAULT_SEARCH_LIMIT = 512


def _state_key(state: dict[str, Any] | None) -> Any:
    """A hashable projection of a row state, for comparing two runs."""
    return None if state is None else tuple(sorted(state.items()))


@dataclass(frozen=True)
class Witness:
    """Two arrival orders of one key's events that leave different rows in the table."""

    order_a: tuple[int, ...]
    order_b: tuple[int, ...]
    state_a: dict[str, Any] | None
    state_b: dict[str, Any] | None
    within_batch: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "order_a": list(self.order_a),
            "order_b": list(self.order_b),
            "state_a": self.state_a,
            "state_b": self.state_b,
            "within_batch": self.within_batch,
        }


@dataclass(frozen=True)
class KeyFinding:
    """Everything the audit established about one primary key."""

    key: str
    event_count: int
    batch_count: int
    spec_ambiguous: bool
    declared_outcomes: int
    tied_ids: tuple[int, ...]
    order_dependent_global: bool
    order_dependent_within_batch: bool
    matches_referee_on_observed_order: bool
    reachable_orders: int
    total_orders: int
    search_was_exhaustive: bool
    witness: Witness | None = None

    @property
    def cross_batch_only(self) -> bool:
        """Order dependent, and not by any reordering a real pipeline could produce.

        These keys are the repository's headline. They are wrong, they are provably wrong,
        and no permutation harness built on top of a real pipeline will ever show it.
        """
        return self.order_dependent_global and not self.order_dependent_within_batch

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "event_count": self.event_count,
            "batch_count": self.batch_count,
            "spec_ambiguous": self.spec_ambiguous,
            "declared_outcomes": self.declared_outcomes,
            "tied_ids": list(self.tied_ids),
            "order_dependent_global": self.order_dependent_global,
            "order_dependent_within_batch": self.order_dependent_within_batch,
            "cross_batch_only": self.cross_batch_only,
            "matches_referee_on_observed_order": self.matches_referee_on_observed_order,
            "reachable_orders": self.reachable_orders,
            "total_orders": self.total_orders,
            "search_was_exhaustive": self.search_was_exhaustive,
            "witness": self.witness.as_dict() if self.witness else None,
        }


@dataclass(frozen=True)
class AuditResult:
    """The outcome of one audit, with every published rate derived rather than stored."""

    implementation: str
    spec: MergeSpec
    findings: tuple[KeyFinding, ...]
    rerun_test_passed: bool
    rerun_keys_flagged: int
    event_count: int
    batch_count: int
    search_limit: int
    observed_table: Table = field(default_factory=dict, repr=False)

    @property
    def key_count(self) -> int:
        return len(self.findings)

    @property
    def order_dependent(self) -> tuple[KeyFinding, ...]:
        return tuple(f for f in self.findings if f.order_dependent_global)

    @property
    def order_dependent_within_batch(self) -> tuple[KeyFinding, ...]:
        return tuple(f for f in self.findings if f.order_dependent_within_batch)

    @property
    def cross_batch_only(self) -> tuple[KeyFinding, ...]:
        return tuple(f for f in self.findings if f.cross_batch_only)

    @property
    def spec_ambiguous(self) -> tuple[KeyFinding, ...]:
        return tuple(f for f in self.findings if f.spec_ambiguous)

    @property
    def implementation_defects(self) -> tuple[KeyFinding, ...]:
        """Order dependent although the declaration decides the key without ambiguity.

        A different defect class from an ambiguous declaration, and the one that is actually
        fixable in the job: the spec already says which row wins and the code does not agree.
        """
        return tuple(f for f in self.findings if f.order_dependent_global and not f.spec_ambiguous)

    @property
    def disagrees_with_referee(self) -> tuple[KeyFinding, ...]:
        """Keys where the row currently in the table is not the row the declaration names."""
        return tuple(f for f in self.findings if not f.matches_referee_on_observed_order)

    def rate(self, subset: Sequence[KeyFinding]) -> float:
        """Percentage of audited keys in a subset, to one decimal place."""
        if not self.findings:
            return 0.0
        return round(100.0 * len(subset) / len(self.findings), 1)

    def summary(self) -> dict[str, Any]:
        return {
            "implementation": self.implementation,
            "spec": {
                "ordering": list(self.spec.ordering),
                "delete_wins_ties": self.spec.delete_wins_ties,
            },
            "events": self.event_count,
            "batches": self.batch_count,
            "keys": self.key_count,
            "rerun_test_passed": self.rerun_test_passed,
            "rerun_keys_flagged": self.rerun_keys_flagged,
            "order_dependent_keys": len(self.order_dependent),
            "order_dependent_within_batch_keys": len(self.order_dependent_within_batch),
            "cross_batch_only_keys": len(self.cross_batch_only),
            "spec_ambiguous_keys": len(self.spec_ambiguous),
            "implementation_defect_keys": len(self.implementation_defects),
            "disagrees_with_referee_keys": len(self.disagrees_with_referee),
            "order_dependent_pct": self.rate(self.order_dependent),
            "cross_batch_only_pct": self.rate(self.cross_batch_only),
        }


def _search_group(
    group: Sequence[ChangeEvent],
    spec: MergeSpec,
    impl: MergeImpl,
    orders_factory,
    limit: int,
    seed: int,
) -> tuple[bool, Witness | None, bool]:
    """Search one key's reachable orders for a pair that disagree.

    Returns (found, witness, exhaustive). `exhaustive` records whether every reachable order
    was tried, because a negative result from a sampled search is not a proof and the report
    must not present it as one.
    """
    key = group[0].key
    baseline_order: tuple[int, ...] | None = None
    baseline_state: Any = None
    baseline_raw: dict[str, Any] | None = None
    tried = 0
    for order in orders_factory(group, limit=limit, seed=seed):
        table = impl(list(order), spec)
        state = _state_key(table.get(key))
        tried += 1
        if baseline_order is None:
            baseline_order = tuple(event.event_id for event in order)
            baseline_state, baseline_raw = state, table.get(key)
            continue
        if state != baseline_state:
            witness = Witness(
                order_a=baseline_order,
                order_b=tuple(event.event_id for event in order),
                state_a=baseline_raw,
                state_b=table.get(key),
                within_batch=orders_factory is within_batch_orders,
            )
            return True, witness, False
    reachable = (
        reachable_order_count(group)
        if orders_factory is within_batch_orders
        else total_order_count(group)
    )
    return False, None, tried >= reachable


def audit(
    events: Sequence[ChangeEvent],
    spec: MergeSpec | None = None,
    implementation: str = "dedupe-last-max",
    search_limit: int = DEFAULT_SEARCH_LIMIT,
    seed: int = 0,
) -> AuditResult:
    """Run all three arms over a stream and return the finding set.

    `events` is taken in the order given, which is the observed arrival order. Nothing in
    this function sorts the input, because sorting it would destroy the only evidence the
    audit has about what actually happened.
    """
    spec = spec or MergeSpec()
    impl = get_implementation(implementation)
    grouped = group_by_key(events)

    observed = impl(rerun_order(events), spec)
    second_pass = impl(rerun_order(events), spec)
    rerun_flagged = sum(
        1 for key in observed if _state_key(observed.get(key)) != _state_key(second_pass.get(key))
    )

    findings: list[KeyFinding] = []
    for key in sorted(grouped):
        group = grouped[key]
        resolution = resolve(spec, group)
        ambiguous = isinstance(resolution, Ambiguous)
        declared_outcomes = resolution.conflict_size if ambiguous else 1

        dep_global, witness_global, exhaustive = _search_group(
            group, spec, impl, global_orders, search_limit, seed
        )
        dep_within, witness_within, _ = _search_group(
            group, spec, impl, within_batch_orders, search_limit, seed
        )

        referee_state = None if ambiguous else resolution.state
        matches = (not ambiguous) and _state_key(observed.get(key)) == _state_key(referee_state)

        findings.append(
            KeyFinding(
                key=key,
                event_count=len(group),
                batch_count=len({event.batch for event in group}),
                spec_ambiguous=ambiguous,
                declared_outcomes=declared_outcomes,
                tied_ids=resolution.tied_ids,
                order_dependent_global=dep_global,
                order_dependent_within_batch=dep_within,
                matches_referee_on_observed_order=matches,
                reachable_orders=reachable_order_count(group),
                total_orders=total_order_count(group),
                search_was_exhaustive=exhaustive,
                witness=witness_within or witness_global,
            )
        )

    return AuditResult(
        implementation=implementation,
        spec=spec,
        findings=tuple(findings),
        rerun_test_passed=rerun_flagged == 0,
        rerun_keys_flagged=rerun_flagged,
        event_count=len(events),
        batch_count=len({event.batch for event in events}),
        search_limit=search_limit,
        observed_table=observed,
    )


def simulate_permutation_harness(
    events: Sequence[ChangeEvent],
    spec: MergeSpec,
    implementation: str,
    draws: int,
    seed: int = 0,
) -> set[str]:
    """Model the harness a team would actually build, and return the keys it flags.

    It permutes the whole stream inside batch boundaries `draws` times, reruns the job, and
    flags any key whose row moved. This is the realistic competitor to the audit above, and
    the experiments measure the audit against it rather than against a straw man.
    """
    impl = get_implementation(implementation)
    baseline = impl(rerun_order(events), spec)
    flagged: set[str] = set()
    by_batch: dict[int, list[ChangeEvent]] = {}
    for event in events:
        by_batch.setdefault(event.batch, []).append(event)
    batch_ids = sorted(by_batch)
    import random as _random

    rng = _random.Random(seed)
    for _ in range(draws):
        order: list[ChangeEvent] = []
        for batch_id in batch_ids:
            chunk = by_batch[batch_id][:]
            rng.shuffle(chunk)
            order.extend(chunk)
        table = impl(order, spec)
        for key in baseline:
            if _state_key(table.get(key)) != _state_key(baseline.get(key)):
                flagged.add(key)
    return flagged


def is_order_safe_by_construction(implementation: str) -> bool:
    """Whether an implementation is one the repository claims cannot be order dependent."""
    return implementation in ORDER_SAFE_BY_CONSTRUCTION
