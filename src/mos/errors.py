"""One exception type per failure mode the CLI needs to map onto a distinct exit code.

The distinction the exit codes encode is the one that matters operationally: a tool that
answered "no order sensitivity" is not the same as a tool that could not answer, and a tool
that answered without enough permutations to support the answer is a third thing again.
"""


class MosError(Exception):
    """Base class. Anything raised deliberately by this package is a subclass."""


class ConfigError(MosError):
    """The audit was not runnable as specified: bad spec, bad flags, contradictory options."""


class FixtureError(MosError):
    """The event fixture could not be read or did not satisfy the event schema."""


class UnderpoweredError(MosError):
    """The audit ran but the permutation budget cannot support the confidence requested.

    Raised only when the caller asks for a guarantee (--require-confidence) that the budget
    cannot deliver. Without that flag the shortfall is reported, not raised, because a check
    that always fails gets deleted within a week.
    """
