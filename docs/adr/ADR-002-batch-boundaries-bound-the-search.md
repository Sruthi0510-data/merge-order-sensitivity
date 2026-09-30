# ADR-002: Batch boundaries bound the search, and that bound is the product

Status: accepted
Date: 2026-09-25

## Context

An early version searched every permutation of a key's events and reported anything that
flipped. The findings were correct and partly useless, because some of them described arrival
orders the pipeline cannot produce. Reporting a defect that requires an impossible delivery is
how a tool gets a reputation for noise.

The constraint is concrete. A micro-batch is the unit of delivery. Once a batch commits, no
retry, no reader parallelism and no consumer rebalance can place one of its events after an
event from a later batch. Inside a batch, order is up for grabs.

## Decision

Split the search into two arms with different meanings, and report both.

The reachable arm permutes within each batch and concatenates the batches in order. The size
of that space is the product of the per-batch factorials. The unreachable arm ignores batch
boundaries; the size of that space is the factorial of the group. On the committed fixture the
two differ by 3,403 orders out of 13,449.

A key found by the unreachable arm and not the reachable one is reported as its own category
rather than merged into a single order-dependent count. It is a real defect and no harness
built on a real pipeline can demonstrate it.

## Alternatives considered

**Report only the reachable arm.** Honest about what a harness can show and silent about 14
genuinely wrong keys. Under-reporting a defect because it is inconvenient to demonstrate is
the failure mode this repository was built to argue against.

**Report only the total space.** Simpler and it inflates the finding count with orders that
cannot occur. A reviewer who checks one and finds it unreproducible discounts the whole report.

**Ask the user for a delivery model.** The right answer eventually. It is deferred because
the batch field is already in the event schema, so the common case needs no new configuration,
and a wrong declared model would be worse than an observed one.

## Consequences

The blind spot becomes a headline rather than a footnote. Detection saturates at 56.2% after
five draws and stays there at 2,000, and that number is a property of the delivery model
rather than of the budget.

The tool inherits an assumption: batches commit in order and an event cannot migrate between
them. A pipeline with overlapping batches, or a source that redelivers an old batch wholesale,
has a larger reachable space and a smaller blind spot, and the audit will under-report the
harness's reach. The assumption is stated in the README rather than detected.

Diagrams are hand-emitted SVG for a related reason: the arithmetic in them is read from
`docs/metrics.json`, so the picture cannot drift from the prose. Mermaid was rejected after its
lazily loaded renderer failed on a valid fence on GitHub, its HTML labels produced XML that
fails silently as an `img src`, its root element carried a percentage width with no height, and
its transparent background rendered edge labels dark grey on near black under a dark theme.
