"""The optional Delta path: round trips that genuinely need the extra installed.

Everything that can be checked without deltalake lives in test_optional_imports.py, which has
no importorskip, so the no-extras CI job is the one that verifies the validation ordering.
Leaving those tests here would have made them invisible on exactly the runner they exist for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mos.delta import read_delta_keys, write_delta
from mos.errors import ConfigError

deltalake = pytest.importorskip("deltalake", reason="needs the optional delta extra")

TABLE = {
    "acct-1": {"status": "settled", "amount_cents": 100},
    "acct-2": None,
    "acct-3": {"status": "pending", "amount_cents": 250},
}


def test_writing_a_table_returns_the_row_count(tmp_path: Path):
    assert write_delta(TABLE, tmp_path / "t") == 2


def test_a_written_table_reads_back_with_the_same_keys(tmp_path: Path):
    path = tmp_path / "t"
    write_delta(TABLE, path)
    assert read_delta_keys(path) == ["acct-1", "acct-3"]


def test_the_two_tables_a_witness_produces_are_two_different_delta_tables(tmp_path: Path):
    """The one claim the in-memory model cannot make on its own."""
    left = {"acct-1": {"status": "authorised"}}
    right = {"acct-1": {"status": "settled"}}
    write_delta(left, tmp_path / "left")
    write_delta(right, tmp_path / "right")
    from deltalake import DeltaTable

    left_rows = DeltaTable(str(tmp_path / "left")).to_pyarrow_table().to_pylist()
    right_rows = DeltaTable(str(tmp_path / "right")).to_pyarrow_table().to_pylist()
    assert left_rows != right_rows


def test_appending_adds_rows_to_an_existing_table(tmp_path: Path):
    path = tmp_path / "t"
    write_delta({"acct-1": {"status": "a"}}, path)
    write_delta({"acct-2": {"status": "b"}}, path, mode="append")
    assert read_delta_keys(path) == ["acct-1", "acct-2"]


def test_reading_a_missing_table_names_the_path(tmp_path: Path):
    with pytest.raises(ConfigError, match="no Delta table"):
        read_delta_keys(tmp_path / "absent")


