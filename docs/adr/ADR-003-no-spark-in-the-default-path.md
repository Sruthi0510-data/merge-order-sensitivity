# ADR-003: No Spark in the default path

Status: accepted
Date: 2026-09-26

## Context

The defect this repository is about lives in Spark and Databricks jobs. The two deduplication
readings it models are the two ways `row_number() over (partition by key order by seq desc) = 1`
resolves a tie. The obvious implementation is pyspark, so that a reviewer sees the real thing.

## Decision

The default path uses the standard library and nothing else. Spark appears nowhere in the
audit engine, the experiments or the test suite.

This is the boring choice and it is made on purpose. The property under audit is a property of
an ordering and a tie policy. A JVM, a shuffle and a physical plan do not change whether two
events tied on a sequence column determine a row; they change which of the two permitted rows
you happen to observe. Putting a cluster in the path would buy realism and cost the one thing
the repository actually sells, which is that a reviewer can clone it and reproduce every figure
on the README with one command and no network.

The optional `delta` extra is the concession. It writes an audited table to a real Delta table
through delta-rs, which needs no JVM, and exists for exactly one claim the in-memory model
cannot make on its own: that the two tables a witness produces are two different Delta tables
rather than two different Python dicts.

## Alternatives considered

**pyspark as a required dependency.** A JVM, a multi-minute cold start, a test suite nobody
runs locally, and a CI matrix that spends most of its time starting executors. The failure mode
is worse than slow: a heavy optional dependency installed on the developer machine masks import
ordering bugs in the job that installs without it, which is why `mos/delta.py` validates its
inputs before importing anything optional and a test pins that ordering by making the module
unimportable.

**pyspark behind an optional extra, with the audit able to use either.** Attractive, and it
doubles the surface that has to agree. Two implementations of the same audit that can disagree
is a second correctness problem, and this repository already has opinions about tools that
detect a difference and cannot attribute it.

**A Spark plan fixture, captured once and committed.** Rejected because a captured plan is a
fact about one Spark version on one cluster, presented as a general claim. Worse than no
evidence.

## Consequences

The claim that survives the fixture is that both readings are legitimate implementations of the
same SQL and that they disagree on 32 rows. The claim that would need a real cluster is which
reading a given physical plan produces, and this repository does not make it. The README says
so in its own section rather than in a footnote.

A reviewer can run `make verify` on a laptop with no cluster, no credentials and no network,
and reproduce every number. That was worth more than realism here.
