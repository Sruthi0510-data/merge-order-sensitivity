"""Writing an audited result to a real Delta Lake table, behind an optional extra.

The audit itself never needs Delta. It reasons about arrival orders and row states, and a
transaction log neither adds nor removes an order dependence. This module exists for one
narrow claim the in-memory model cannot make on its own: that the two tables a witness
produces are two different Delta tables, not two different Python dicts.

The import of `deltalake` sits below the input validation on purpose. A caller who passes a
bad path should get the error immediately rather than after an import, and the ordering is
pinned by a test that makes the module unimportable and asserts the validation still fires.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mos.errors import ConfigError
from mos.implementations import Table

DELTA_EXTRA_HINT = "install the optional extra: pip install 'merge-order-sensitivity[delta]'"


def table_to_records(table: Table) -> list[dict[str, Any]]:
    """Flatten an audited table into Delta-shaped records, dropping tombstoned keys.

    A deleted key is absent from the target table rather than present with nulls, which is
    what a MERGE with WHEN MATCHED THEN DELETE leaves behind.
    """
    records: list[dict[str, Any]] = []
    for key in sorted(table):
        state = table[key]
        if state is None:
            continue
        record: dict[str, Any] = {"key": key}
        record.update({str(k): v for k, v in sorted(state.items())})
        records.append(record)
    return records


def write_delta(table: Table, path: Path, mode: str = "overwrite") -> int:
    """Write an audited table to a Delta table and return the row count written."""
    if mode not in {"overwrite", "append"}:
        raise ConfigError(f"unsupported delta write mode {mode!r}; use overwrite or append")
    if path.exists() and not path.is_dir():
        raise ConfigError(f"delta path exists and is not a directory: {path}")
    records = table_to_records(table)
    if not records:
        raise ConfigError("refusing to write an empty Delta table; the audit produced no rows")

    try:
        import pyarrow as pa
        from deltalake import write_deltalake
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised via monkeypatch in tests
        message = f"Delta output needs the optional dependencies; {DELTA_EXTRA_HINT}"
        raise ConfigError(message) from exc

    columns = sorted({name for record in records for name in record})
    arrays = {name: [record.get(name) for record in records] for name in columns}
    write_deltalake(str(path), pa.table(arrays), mode=mode)
    return len(records)


def read_delta_keys(path: Path) -> list[str]:
    """Read back the key column of a Delta table, for round-trip verification."""
    if not path.is_dir():
        raise ConfigError(f"no Delta table at {path}")
    try:
        from deltalake import DeltaTable
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised via monkeypatch in tests
        message = f"Delta input needs the optional dependencies; {DELTA_EXTRA_HINT}"
        raise ConfigError(message) from exc
    keys = DeltaTable(str(path)).to_pyarrow_table()["key"].to_pylist()
    return sorted(str(value) for value in keys)
