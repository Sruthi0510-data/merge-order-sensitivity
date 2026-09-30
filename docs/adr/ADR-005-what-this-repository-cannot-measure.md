# ADR-005: What this repository cannot measure, and what it would take

Status: accepted
Date: 2026-09-29

## Context

Every figure here is produced by a seeded generator and a deterministic engine running offline.
That buys reproducibility, which is the right trade for a portfolio artefact a reviewer clones
and runs in two minutes. It does not buy realism, and the difference has to be written down
somewhere a reader will find it rather than discovered by a reviewer who then discounts
everything else.

This record exists so that the boundary is a design decision with alternatives rather than an
omission.

## Decision

State the boundary explicitly, claim by claim, and give the README a section of its own for it.

**Claims that survive the fixture unchanged.** That a re-run idempotency test replays arrival
order and therefore cannot measure order independence. That a declaration tying on different
row states entitles you to no row. That the orders reachable inside batch boundaries are the
product of the per-batch factorials, which is smaller than the factorial of the group whenever
a key straddles a boundary. These are arithmetic and logic; a real cluster would produce the
same answers.

**Claims that are about this fixture and not about anybody's pipeline.** Every rate: 32 keys,
8.0% of keys, 14 unreachable, a ceiling of 56.2%. They are a function of the tie rate and the
cross-batch rate the generator was given. They demonstrate that the phenomenon has a size; they
do not predict yours. The generator knobs are in the README so a reader can set them to their
own and re-measure.

**The one claim that genuinely needs the real thing.** Which of the two deduplication readings
a given Spark physical plan produces. The repository shows both are legitimate and that they
disagree on 32 rows. It does not and cannot say which one your job is currently running. That
needs pyspark against a cluster, and ADR-003 explains why it is not in the default path.

**A measured zero is never published as zero.** The harness found nothing across the
unreachable population. Reported as a rate that would be nought, which would imply certainty
from a sample of 14. The rule of three bounds it below 21.4% at 95% confidence, and that is
what the README prints.

**A sampled search proves nothing negative.** Above seven events per key the search samples.
Every finding records whether its search was exhaustive, and a stable verdict from a sampled
search is an absence of evidence rather than evidence of absence.

**Key independence is verified rather than assumed.** The audit permutes one key's events at a
time, which is equivalent to permuting the whole stream only if no implementation lets one key
influence another. All five bundled implementations satisfy that and a test asserts it on the
shipped fixture. A user-supplied implementation that aggregates across keys would be
under-reported, and the audit does not detect that condition.

## Alternatives considered

**Ship a fixture captured from a production CDC feed.** More convincing and not distributable,
not reproducible by a reviewer, and impossible to vary. A seeded generator with the knobs
exposed is worth more than one anonymised snapshot.

**Quietly present the fixture rates as general.** The standard move, and the reason most
portfolio numbers get discounted on sight.

**Omit the section.** Leaves the reviewer to discover the boundary themselves, at which point
they are auditing the author rather than the tool.

## Consequences

The README leads with what the tool cannot do, which costs some of the first screen and buys
the only thing that makes the rest of it worth reading.

A future pyspark extra has a well defined job: settle the one claim named above. Its first
metric is whether a real physical plan ever disagrees with both bundled readings, because that
would mean the model has a third case in it.
