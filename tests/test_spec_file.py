"""Loading a merge declaration from a reviewed file.

ADR-001 argues that the declaration's value is that somebody writes it down where a colleague
can disagree with it in review. A tool that only takes the declaration as a command line flag
does not support its own argument, which is why this path exists and why unknown keys are
refused rather than ignored: a typo in a reviewed file must not silently mean the default.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mos.errors import ConfigError
from mos.semantics import MergeSpec

SHIPPED = Path(__file__).resolve().parents[1] / "specs" / "payments.toml"


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "spec.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_the_shipped_spec_loads():
    assert MergeSpec.from_file(SHIPPED).ordering == ("seq",)


def test_the_shipped_spec_carries_a_name():
    assert MergeSpec.from_file(SHIPPED).name == "payments-cdc"


def test_the_shipped_spec_documents_the_fix_without_enabling_it():
    """The commented total ordering is guidance, not configuration that silently applies."""
    body = SHIPPED.read_text()
    assert '#   ordering = ["seq", "event_id"]' in body
    assert MergeSpec.from_file(SHIPPED).is_total_by_construction is False


def test_a_multi_field_ordering_loads_in_order(tmp_path: Path):
    spec = MergeSpec.from_file(write(tmp_path, 'ordering = ["seq", "event_id"]\n'))
    assert spec.ordering == ("seq", "event_id")


def test_delete_wins_ties_defaults_to_false(tmp_path: Path):
    assert MergeSpec.from_file(write(tmp_path, 'ordering = ["seq"]\n')).delete_wins_ties is False


def test_delete_wins_ties_is_read_when_present(tmp_path: Path):
    body = 'ordering = ["seq"]\ndelete_wins_ties = true\n'
    assert MergeSpec.from_file(write(tmp_path, body)).delete_wins_ties is True


def test_a_missing_file_names_the_path(tmp_path: Path):
    with pytest.raises(ConfigError, match="merge spec not found"):
        MergeSpec.from_file(tmp_path / "absent.toml")


def test_invalid_toml_is_reported_as_such(tmp_path: Path):
    with pytest.raises(ConfigError, match="not valid TOML"):
        MergeSpec.from_file(write(tmp_path, "ordering = [\n"))


def test_an_unknown_key_is_refused_rather_than_ignored(tmp_path: Path):
    body = 'ordering = ["seq"]\ndelete_wins_tise = true\n'
    with pytest.raises(ConfigError, match="unknown key"):
        MergeSpec.from_file(write(tmp_path, body))


def test_a_missing_ordering_is_refused(tmp_path: Path):
    with pytest.raises(ConfigError, match="list of field names"):
        MergeSpec.from_file(write(tmp_path, 'name = "x"\n'))


def test_an_ordering_that_is_not_a_list_is_refused(tmp_path: Path):
    with pytest.raises(ConfigError, match="list of field names"):
        MergeSpec.from_file(write(tmp_path, 'ordering = "seq"\n'))


def test_an_ordering_of_non_strings_is_refused(tmp_path: Path):
    with pytest.raises(ConfigError, match="list of field names"):
        MergeSpec.from_file(write(tmp_path, "ordering = [1, 2]\n"))


def test_a_non_boolean_delete_wins_ties_is_refused(tmp_path: Path):
    body = 'ordering = ["seq"]\ndelete_wins_ties = "yes"\n'
    with pytest.raises(ConfigError, match="true or false"):
        MergeSpec.from_file(write(tmp_path, body))


def test_ordering_by_arrival_index_is_still_refused_through_a_file(tmp_path: Path):
    """The refusal belongs to the spec, not to the flag parser, so a file cannot route round it."""
    with pytest.raises(ConfigError, match="unknown ordering field"):
        MergeSpec.from_file(write(tmp_path, 'ordering = ["arrival_index"]\n'))


def test_an_empty_ordering_is_refused_through_a_file(tmp_path: Path):
    with pytest.raises(ConfigError, match="at least one field"):
        MergeSpec.from_file(write(tmp_path, "ordering = []\n"))
