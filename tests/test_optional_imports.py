"""Validation ordering around the optional Delta extra, asserted without the extra installed.

This file exists separately from test_delta.py because of trap one: a heavy optional
dependency installed on the build machine masks a broken ordering in the job that installs
without it. test_delta.py opens with an importorskip, so on a no-extras runner every test in
it is skipped, including the one that pins the ordering. Putting the ordering tests here,
where nothing is skipped, means the CI job that installs no extras is the job that checks
them.

Nothing here imports deltalake or pyarrow, and two of the tests actively make those modules
unimportable to prove the validation fires first.
"""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from mos.delta import table_to_records, write_delta
from mos.errors import ConfigError

TABLE = {
    "acct-1": {"status": "settled", "amount_cents": 100},
    "acct-2": None,
    "acct-3": {"status": "pending", "amount_cents": 250},
}


@pytest.fixture
def no_delta(monkeypatch):
    """Make deltalake and pyarrow unimportable for the duration of one test."""
    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name.startswith(("deltalake", "pyarrow")):
            raise ModuleNotFoundError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)


def test_flattening_a_table_needs_no_optional_dependency():
    assert [record["key"] for record in table_to_records(TABLE)] == ["acct-1", "acct-3"]


def test_a_tombstoned_key_is_dropped_rather_than_written_as_nulls():
    assert all(record["key"] != "acct-2" for record in table_to_records(TABLE))


def test_records_are_emitted_in_sorted_key_order():
    keys = [record["key"] for record in table_to_records(TABLE)]
    assert keys == sorted(keys)


def test_an_empty_table_produces_no_records():
    assert table_to_records({}) == []


def test_an_unsupported_write_mode_is_refused_before_the_import(no_delta, tmp_path: Path):
    """The ordering invariant, checked on a runner that has no extra to hide behind.

    If the import ran first, a caller who passed a bad mode would be told to install a package
    they do not need, and would go and install it.
    """
    with pytest.raises(ConfigError, match="unsupported delta write mode"):
        write_delta(TABLE, tmp_path / "t", mode="upsert")


def test_a_non_directory_path_is_refused_before_the_import(no_delta, tmp_path: Path):
    path = tmp_path / "t"
    path.write_text("not a table", encoding="utf-8")
    with pytest.raises(ConfigError, match="not a directory"):
        write_delta(TABLE, path)


def test_an_all_tombstone_table_is_refused_before_the_import(no_delta, tmp_path: Path):
    with pytest.raises(ConfigError, match="empty Delta table"):
        write_delta({"acct-1": None}, tmp_path / "t")


def test_a_genuinely_missing_extra_reports_the_install_hint(no_delta, tmp_path: Path):
    with pytest.raises(ConfigError, match="pip install"):
        write_delta(TABLE, tmp_path / "t")


def test_the_audit_engine_imports_without_the_optional_extra(no_delta):
    """The core must never reach for Delta. A regression here breaks every no-extras install."""
    import importlib

    for module in ("mos.audit", "mos.semantics", "mos.permute", "mos.implementations"):
        assert importlib.import_module(module) is not None
