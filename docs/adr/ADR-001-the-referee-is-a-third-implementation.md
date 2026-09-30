# ADR-001: The referee is a third implementation, not a second opinion

Status: accepted
Date: 2026-09-24

## Context

The audit needs to decide whether a key's row is wrong. The obvious way is to run the merge
twice under different arrival orders and compare. That comparison detects a difference and is
symmetric: when run A and run B disagree it knows something is wrong and has no basis for
saying which run was right, because both are the same code and the same data.

Symmetry is not a nuisance here, it is the reason a permutation harness produces findings that
nobody acts on. "These two runs differ" is a bug report with no owner.

## Decision

Resolve each key a third time, from the event multiset alone, under a declared ordering the
user writes down. That resolution never reads arrival order, so it cannot be wrong in the way
the two runs can be wrong, and the comparison against it is asymmetric: an implementation that
disagrees with the referee is the thing that is wrong.

The referee carries a verdict neither run can produce. When the tied events assert different
rows, the declaration determines nothing, and the referee returns `Ambiguous` rather than
picking. That is not an error state. It is the finding: no implementation can be correct about
that key because there is nothing to be correct about.

## Alternatives considered

**Take the first run as the baseline.** This is what a harness does implicitly. It makes the
observed arrival order authoritative, which is exactly the assumption under audit, so the tool
would certify the defect it exists to find.

**Sort by sequence and call that the answer.** Correct for keys with a unique maximum and
silently arbitrary for the rest, since a stable sort resolves a tie by input order. It would
report zero ambiguous keys on a fixture containing 32 of them.

**Require a total order up front and refuse to audit without one.** Defensible, and it
declines the job people actually have. Teams arrive with a partial ordering and no idea it is
partial. Measuring that is the point.

## Consequences

The audit now needs a declaration as input, which is a real cost: someone must write the merge
semantics into a file where a colleague can disagree with it. That is the step teams skip, and
it is what makes everything downstream possible.

`arrival_index` is rejected as an ordering field. A specification allowed to order by arrival
could declare itself unambiguous while remaining exactly as order dependent as before.

A referee is only as right as its declaration. If the ordering is wrong about the business,
the referee is confidently wrong in the same direction and no amount of permuting reveals it.
ADR-005 records that boundary.
