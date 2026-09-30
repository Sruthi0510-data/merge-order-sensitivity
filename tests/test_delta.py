"""The optional Delta path, and the import-ordering invariant CI would otherwise hide."""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from mos.delta import read_delta_keys, table_to_records, write_delta
from mos.errors import ConfigError

deltalake = pytest.importorskip("deltalake", reason="needs the optional delta extra")

TABLE = {
    "acct-1": {"status": "settled", "amount_cents": 100},
    "acct-2": None,
    "acct-3": {"status": "pending", "amount_cents": 250},
}


def test_records_carry_the_key_column():
    assert [record["key"] for record in table_to_records(TABLE)] == ["acct-1", "acct-3"]


def test_a_tombstoned_key_is_absent_rather_than_present_with_nulls():
    """A MERGE with WHEN MATCHED THEN DELETE leaves no row, not a row full of nulls."""
    assert all(record["key"] != "acct-2" for record in table_to_records(TABLE))


def test_records_are_emitted_in_sorted_key_order():
    keys = [record["key"] for record in table_to_records(TABLE)]
    assert keys == sorted(keys)


def test_an_empty_table_produces_no_records():
    assert table_to_records({}) == []


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


def test_an_unsupported_write_mode_is_refused(tmp_path: Path):
    with pytest.raises(ConfigError, match="unsupported delta write mode"):
        write_delta(TABLE, tmp_path / "t", mode="upsert")


def test_writing_an_all_tombstone_table_is_refused_rather_than_silently_empty(tmp_path: Path):
    with pytest.raises(ConfigError, match="empty Delta table"):
        write_delta({"acct-1": None}, tmp_path / "t")


def test_a_path_that_is_a_file_is_refused(tmp_path: Path):
    path = tmp_path / "t"
    path.write_text("not a table", encoding="utf-8")
    with pytest.raises(ConfigError, match="not a directory"):
        write_delta(TABLE, path)


def test_reading_a_missing_table_names_the_path(tmp_path: Path):
    with pytest.raises(ConfigError, match="no Delta table"):
        read_delta_keys(tmp_path / "absent")


def test_validation_runs_before_the_optional_import(monkeypatch, tmp_path: Path):
    """Trap 1 from the build notes, pinned so it cannot regress.

    A heavy optional dependency installed on the developer machine masks a broken ordering
    in the job that installs without it. Here the failure would be worse than a
    ModuleNotFoundError: a caller who passed an unsupported write mode would get an import
    error about deltalake and go install a package they did not need. Making the module
    unimportable and asserting the ConfigError still fires pins the ordering whether or not
    the extra is present.
    """
    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name.startswith(("deltalake", "pyarrow")):
            raise ModuleNotFoundError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.raises(ConfigError, match="unsupported delta write mode"):
        write_delta(TABLE, tmp_path / "t", mode="upsert")


def test_a_missing_extra_is_reported_as_a_config_error_with_the_install_hint(
    monkeypatch, tmp_path: Path
):
    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name.startswith(("deltalake", "pyarrow")):
            raise ModuleNotFoundError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.raises(ConfigError, match="pip install"):
        write_delta(TABLE, tmp_path / "t")
