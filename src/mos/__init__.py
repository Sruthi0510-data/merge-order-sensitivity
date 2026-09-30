"""mos: an order-sensitivity auditor for lakehouse MERGE logic.

The package exists because the test everyone writes for a MERGE, re-run the batch and
assert the table is unchanged, replays the arrival order it should be varying. Idempotency
and order independence are different properties and that test only checks the first one.
"""

from mos.events import ChangeEvent, Op
from mos.semantics import Ambiguous, Decided, MergeSpec, resolve

__all__ = ["Ambiguous", "ChangeEvent", "Decided", "MergeSpec", "Op", "resolve"]
__version__ = "0.1.0"
