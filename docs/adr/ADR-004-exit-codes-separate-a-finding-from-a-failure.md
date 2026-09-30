# ADR-004: Exit codes separate a finding from a failure

Status: accepted
Date: 2026-09-27

## Context

An auditing tool has three genuinely different outcomes and the Unix convention has room for
two. "I ran and found nothing", "I ran and found something" and "I could not run" all collapse
into zero or non-zero, and the collapse has a predictable consequence: a CI step that treats
every non-zero code as a crash reports a real finding as a broken tool, someone marks the step
`continue-on-error`, and nothing is checked from then on.

There is a fourth outcome specific to a sampling tool. The audit can complete, find nothing,
and have searched too few permutations for that to mean anything.

## Decision

Four codes, documented in the README as an interface.

| code | meaning |
| --- | --- |
| 0 | ran, no order-dependent keys |
| 3 | ran, found order-dependent keys. The tool worked |
| 2 | could not answer: bad arguments, unreadable fixture, contradictory spec |
| 4 | ran, and the permutation budget cannot support the confidence requested |

Code 3 rather than 1, deliberately. One is what a crashed interpreter returns, and the gap
makes the distinction visible in a CI log rather than merely documented.

Code 4 is opt in, behind `--require-confidence`. A check wired to fail by default gets weakened
within a week and then nothing is checked, which is the same failure as above arriving by a
different road.

## Alternatives considered

**Zero for everything, findings on stdout.** Forces every caller to parse output to learn
whether to act, and a parser is the thing that breaks when the output format improves.

**Non-zero for any finding, code 1.** The common choice and the one that produces the
`continue-on-error` outcome, because 1 is indistinguishable from a traceback.

**A `--fail-on-finding` flag defaulting off.** Considered and rejected as a half measure: it
makes the useful behaviour opt in and leaves the tool silent by default, which trains people to
ignore it.

## Consequences

A CI step reads `if [ $code -eq 3 ]` and knows a finding from a crash without parsing anything.

The codes are now a compatibility surface. Changing 3 to anything else breaks callers, so the
constants live in one module with the meanings in their docstrings, and tests assert that a
finding and a failure to answer return different codes rather than asserting the literals
alone.
