"""Properties of the event model, including the hashability bug that cost an afternoon."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mos.errors import FixtureError
from mos.events import (
    ChangeEvent,
    Op,
    group_by_key,
    iter_batches,
    load_events,
    write_events,
)
from tests.conftest import make_event


def test_an_upsert_event_asserts_its_payload_as_the_row_state():
    assert make_event(1, status="settled").state == {"status": "settled"}


def test_a_delete_event_asserts_that_the_row_is_absent():
    assert make_event(1, op="delete").state is None


def test_two_events_built_from_equal_payload_dicts_compare_equal():
    assert make_event(1, a=1, b=2) == make_event(1, b=2, a=1)


def test_an_event_is_hashable_so_the_referee_can_deduplicate_states():
    """Pins the bug that made the referee silently collapse: dicts are unhashable.

    The first draft stored `payload` as a dict on a frozen dataclass. Construction
    succeeded, equality worked, and the moment the referee put events in a set to count
    distinct outcomes it raised TypeError from inside a comprehension three frames down.
    Freezing the payload into a tuple of sorted items at construction fixes it for good.
    """
    assert len({make_event(1, a=1), make_event(1, a=1)}) == 1


def test_payload_access_returns_a_plain_dict():
    assert make_event(1, a=1).payload == {"a": 1}


def test_mutating_the_returned_payload_does_not_affect_the_event():
    event = make_event(1, a=1)
    event.payload["a"] = 99
    assert event.payload == {"a": 1}


@pytest.mark.parametrize("field", ["event_id", "key", "seq", "op", "source", "batch"])
def test_a_missing_required_field_is_rejected_by_name(field):
    raw = {
        "event_id": 1,
        "key": "k",
        "seq": 1,
        "op": "upsert",
        "source": "s",
        "batch": 0,
        "payload": {},
    }
    raw.pop(field)
    with pytest.raises(FixtureError, match=field):
        ChangeEvent.from_mapping(raw, 0)


def test_an_unknown_op_is_rejected_rather_than_coerced():
    raw = {"event_id": 1, "key": "k", "seq": 1, "op": "merge", "source": "s", "batch": 0}
    with pytest.raises(FixtureError, match="unknown op"):
        ChangeEvent.from_mapping(raw, 0)


def test_a_non_object_payload_is_rejected():
    raw = {
        "event_id": 1,
        "key": "k",
        "seq": 1,
        "op": "upsert",
        "source": "s",
        "batch": 0,
        "payload": [1, 2],
    }
    with pytest.raises(FixtureError, match="non-object payload"):
        ChangeEvent.from_mapping(raw, 0)


def test_a_missing_payload_key_is_treated_as_an_empty_payload():
    raw = {"event_id": 1, "key": "k", "seq": 1, "op": "upsert", "source": "s", "batch": 0}
    assert ChangeEvent.from_mapping(raw, 0).payload == {}


def test_a_null_payload_is_treated_as_an_empty_payload():
    raw = {
        "event_id": 1,
        "key": "k",
        "seq": 1,
        "op": "upsert",
        "source": "s",
        "batch": 0,
        "payload": None,
    }
    assert ChangeEvent.from_mapping(raw, 0).payload == {}


def test_arrival_index_is_the_file_position_not_a_field_in_the_file(tmp_path: Path):
    path = tmp_path / "f.jsonl"
    write_events(path, [make_event(7, seq=3), make_event(4, seq=1)])
    events = load_events(path)
    assert [event.arrival_index for event in events] == [0, 1]
    assert [event.event_id for event in events] == [7, 4]


def test_a_round_trip_through_jsonl_preserves_every_event(tmp_path: Path):
    original = [make_event(1, seq=5, status="a"), make_event(2, seq=6, op="delete")]
    path = tmp_path / "f.jsonl"
    assert write_events(path, original) == 2
    reloaded = load_events(path)
    assert [event.to_mapping() for event in reloaded] == [e.to_mapping() for e in original]


def test_blank_lines_in_a_fixture_are_skipped(tmp_path: Path):
    path = tmp_path / "f.jsonl"
    body = json.dumps(make_event(1).to_mapping())
    path.write_text(f"{body}\n\n\n{json.dumps(make_event(2).to_mapping())}\n", encoding="utf-8")
    assert len(load_events(path)) == 2


def test_an_invalid_json_line_names_its_line_number(tmp_path: Path):
    path = tmp_path / "f.jsonl"
    path.write_text(json.dumps(make_event(1).to_mapping()) + "\n{not json\n", encoding="utf-8")
    with pytest.raises(FixtureError, match="line 2"):
        load_events(path)


def test_a_missing_fixture_names_the_path(tmp_path: Path):
    with pytest.raises(FixtureError, match="fixture not found"):
        load_events(tmp_path / "absent.jsonl")


def test_an_empty_fixture_is_an_error_rather_than_an_empty_audit(tmp_path: Path):
    path = tmp_path / "f.jsonl"
    path.write_text("\n\n", encoding="utf-8")
    with pytest.raises(FixtureError, match="no events"):
        load_events(path)


def test_duplicate_event_ids_are_rejected_because_every_witness_names_events_by_id(
    tmp_path: Path,
):
    path = tmp_path / "f.jsonl"
    write_events(path, [make_event(1, seq=1), make_event(1, seq=2)])
    with pytest.raises(FixtureError, match="duplicate event_id 1"):
        load_events(path)


def test_grouping_by_key_preserves_arrival_order_inside_each_group():
    events = [
        make_event(1, key="a"),
        make_event(2, key="b"),
        make_event(3, key="a"),
    ]
    grouped = group_by_key(events)
    assert [event.event_id for event in grouped["a"]] == [1, 3]
    assert [event.event_id for event in grouped["b"]] == [2]


def test_iterating_batches_yields_them_in_ascending_batch_order():
    events = [make_event(1, batch=2), make_event(2, batch=0), make_event(3, batch=1)]
    assert [batch for batch, _ in iter_batches(events)] == [0, 1, 2]


def test_iterating_batches_preserves_arrival_order_inside_a_batch():
    events = [make_event(5, batch=0), make_event(3, batch=0)]
    _, first = next(iter(iter_batches(events)))
    assert [event.event_id for event in first] == [5, 3]


def test_op_values_round_trip_through_their_string_form():
    assert Op("upsert") is Op.UPSERT
    assert Op("delete") is Op.DELETE


def test_writing_events_creates_missing_parent_directories(tmp_path: Path):
    path = tmp_path / "nested" / "deeper" / "f.jsonl"
    assert write_events(path, [make_event(1)]) == 1
    assert path.exists()
