"""Exit codes, kept in one place because the README publishes them as an interface.

The important pair is OK versus FINDING. Both mean the tool did its job. A CI step that
treats any non-zero code as a crash will misreport a genuine finding as a broken tool, so
the codes are spread out and documented rather than reusing 1 for everything.
"""

OK = 0
"""The audit completed and found no order-dependent keys."""

FINDING = 3
"""The audit completed and found at least one order-dependent key. Not an error."""

USAGE = 2
"""The tool could not answer: bad arguments, unreadable fixture, contradictory spec."""

UNDERPOWERED = 4
"""The audit completed but the permutation budget cannot support the requested confidence."""

NAMES = {
    OK: "OK",
    USAGE: "USAGE",
    FINDING: "FINDING",
    UNDERPOWERED: "UNDERPOWERED",
}
