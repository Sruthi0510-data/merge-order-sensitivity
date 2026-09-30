"""The command line surface, with the exit codes treated as the interface they are."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from mos import exit_codes
from mos.cli import main
from tests.conftest import FIXTURE_PATH


def run(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    code = main(list(argv), out=out)
    return code, out.getvalue()


def test_generate_writes_a_fixture_and_reports_the_counts(tmp_path: Path):
    target = tmp_path / "f.jsonl"
    code, text = run("generate", "--out", str(target), "--keys", "12", "--seed", "3")
    assert code == exit_codes.OK
    assert target.exists()
    assert "12 keys" in text


def test_generate_is_reproducible_from_the_command_line(tmp_path: Path):
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    run("generate", "--out", str(first), "--keys", "10", "--seed", "5")
    run("generate", "--out", str(second), "--keys", "10", "--seed", "5")
    assert first.read_text() == second.read_text()


def test_generate_rejects_an_out_of_range_rate(tmp_path: Path):
    code, text = run("generate", "--out", str(tmp_path / "f.jsonl"), "--tie-rate", "4")
    assert code == exit_codes.USAGE
    assert "between 0 and 1" in text


def test_audit_returns_the_finding_code_when_keys_are_order_dependent():
    code, text = run("audit", "--fixture", str(FIXTURE_PATH), "--impl", "dedupe-last-max")
    assert code == exit_codes.FINDING
    assert json.loads(text)["order_dependent_keys"] > 0


def test_audit_returns_ok_when_the_implementation_is_order_safe():
    code, text = run("audit", "--fixture", str(FIXTURE_PATH), "--impl", "total-order")
    assert code == exit_codes.OK
    assert json.loads(text)["order_dependent_keys"] == 0


def test_a_finding_and_a_failure_to_answer_have_different_exit_codes(tmp_path: Path):
    """The distinction the codes exist for.

    A CI step that treats every non-zero code as a crash would report a genuine finding as a
    broken tool, and the fix a team reaches for is to stop running the tool.
    """
    finding, _ = run("audit", "--fixture", str(FIXTURE_PATH))
    failure, _ = run("audit", "--fixture", str(tmp_path / "absent.jsonl"))
    assert finding == exit_codes.FINDING
    assert failure == exit_codes.USAGE
    assert finding != failure


def test_audit_reports_a_missing_fixture_by_path(tmp_path: Path):
    code, text = run("audit", "--fixture", str(tmp_path / "absent.jsonl"))
    assert code == exit_codes.USAGE
    assert "fixture not found" in text


def test_audit_writes_the_full_finding_set_to_json_when_asked(tmp_path: Path):
    target = tmp_path / "nested" / "audit.json"
    run("audit", "--fixture", str(FIXTURE_PATH), "--json", str(target))
    payload = json.loads(target.read_text())
    assert payload["summary"]["keys"] == len(payload["findings"])


def test_audit_accepts_a_multi_field_ordering():
    code, text = run("audit", "--fixture", str(FIXTURE_PATH), "--order-by", "seq,event_id")
    assert code == exit_codes.OK
    assert json.loads(text)["spec"]["ordering"] == ["seq", "event_id"]


def test_audit_refuses_an_unknown_ordering_field():
    code, text = run("audit", "--fixture", str(FIXTURE_PATH), "--order-by", "nonsense")
    assert code == exit_codes.USAGE
    assert "unknown ordering field" in text


def test_audit_honours_the_delete_wins_flag():
    _, text = run("audit", "--fixture", str(FIXTURE_PATH), "--delete-wins")
    assert json.loads(text)["spec"]["delete_wins_ties"] is True


def test_delete_wins_reduces_the_ambiguous_key_count():
    _, plain = run("audit", "--fixture", str(FIXTURE_PATH))
    _, flagged = run("audit", "--fixture", str(FIXTURE_PATH), "--delete-wins")
    assert json.loads(flagged)["spec_ambiguous_keys"] < json.loads(plain)["spec_ambiguous_keys"]


def test_requiring_confidence_beyond_the_budget_returns_the_underpowered_code():
    code, text = run(
        "audit",
        "--fixture", str(FIXTURE_PATH),
        "--search-limit", "2",
        "--require-confidence", "0.95",
    )
    assert code == exit_codes.UNDERPOWERED
    assert "below the 5 draws" in text


def test_requiring_confidence_within_the_budget_does_not_change_the_verdict():
    code, _ = run(
        "audit",
        "--fixture", str(FIXTURE_PATH),
        "--search-limit", "64",
        "--require-confidence", "0.95",
    )
    assert code == exit_codes.FINDING


def test_the_underpowered_check_is_opt_in():
    """A check wired to fail by default gets weakened within a week, then nothing is checked."""
    code, _ = run("audit", "--fixture", str(FIXTURE_PATH), "--search-limit", "2")
    assert code == exit_codes.FINDING


SPEC_FILE = FIXTURE_PATH.parents[1] / "specs" / "payments.toml"


def test_audit_accepts_a_reviewed_spec_file():
    code, text = run("audit", "--fixture", str(FIXTURE_PATH), "--spec", str(SPEC_FILE))
    assert code == exit_codes.FINDING
    assert json.loads(text)["spec"]["ordering"] == ["seq"]


def test_a_spec_file_and_flags_together_are_refused_rather_than_resolved():
    """Two sources for one declaration is how a team audits something it did not review."""
    code, text = run(
        "audit", "--fixture", str(FIXTURE_PATH),
        "--spec", str(SPEC_FILE), "--order-by", "seq,event_id",
    )
    assert code == exit_codes.USAGE
    assert "cannot be combined" in text


def test_a_spec_file_with_delete_wins_flag_is_also_refused():
    code, text = run(
        "audit", "--fixture", str(FIXTURE_PATH), "--spec", str(SPEC_FILE), "--delete-wins"
    )
    assert code == exit_codes.USAGE


def test_a_missing_spec_file_is_a_usage_error(tmp_path: Path):
    code, text = run("audit", "--fixture", str(FIXTURE_PATH), "--spec", str(tmp_path / "x.toml"))
    assert code == exit_codes.USAGE
    assert "merge spec not found" in text


def test_every_subcommand_that_audits_accepts_a_spec_file(tmp_path: Path):
    for argv in (
        ("compare", "--fixture", str(FIXTURE_PATH), "--spec", str(SPEC_FILE)),
        ("harness", "--fixture", str(FIXTURE_PATH), "--spec", str(SPEC_FILE), "--draws", "2"),
        ("report", "--fixture", str(FIXTURE_PATH), "--spec", str(SPEC_FILE),
         "--out", str(tmp_path / "r.html")),
    ):
        code, _ = run(*argv)
        assert code in (exit_codes.OK, exit_codes.FINDING), argv


def test_compare_tabulates_every_bundled_implementation():
    code, text = run("compare", "--fixture", str(FIXTURE_PATH))
    assert code == exit_codes.FINDING
    for name in ("arrival-lww", "dedupe-first-max", "total-order"):
        assert name in text


def test_compare_shows_total_order_finding_nothing():
    _, text = run("compare", "--fixture", str(FIXTURE_PATH))
    row = next(line for line in text.splitlines() if line.startswith("total-order"))
    assert row.split()[1:] == ["0", "0", "0", "0"]


def test_compare_writes_its_rows_to_json_when_asked(tmp_path: Path):
    target = tmp_path / "compare.json"
    run("compare", "--fixture", str(FIXTURE_PATH), "--json", str(target))
    rows = json.loads(target.read_text())["rows"]
    assert {row["implementation"] for row in rows} == {
        "arrival-lww",
        "dedupe-first-max",
        "dedupe-last-max",
        "delete-wins",
        "total-order",
    }


def _first_order_dependent_key() -> str:
    from mos.audit import audit
    from mos.events import load_events
    from mos.semantics import MergeSpec

    result = audit(load_events(FIXTURE_PATH), MergeSpec(), "dedupe-last-max")
    return result.order_dependent[0].key


def test_witness_prints_two_orders_and_two_states():
    key = _first_order_dependent_key()
    code, text = run("witness", key, "--fixture", str(FIXTURE_PATH))
    assert code == exit_codes.FINDING
    assert "order A" in text
    assert "order B" in text


def test_witness_says_whether_the_swap_it_found_was_reachable():
    key = _first_order_dependent_key()
    _, text = run("witness", key, "--fixture", str(FIXTURE_PATH))
    assert ("reachable inside one batch" in text) or ("needs a cross-batch swap" in text)


def test_witness_reports_a_cross_batch_key_as_needing_an_unreachable_swap():
    """The CLI must not present an unreachable witness as something a rerun could produce."""
    from mos.audit import audit
    from mos.events import load_events
    from mos.semantics import MergeSpec

    result = audit(load_events(FIXTURE_PATH), MergeSpec(), "dedupe-last-max")
    key = result.cross_batch_only[0].key
    _, text = run("witness", key, "--fixture", str(FIXTURE_PATH))
    assert "needs a cross-batch swap" in text


def test_witness_on_an_unknown_key_says_so():
    code, text = run("witness", "acct-99999", "--fixture", str(FIXTURE_PATH))
    assert code == exit_codes.USAGE
    assert "not present" in text


def test_witness_on_an_order_safe_implementation_reports_no_finding():
    code, text = run(
        "witness", "acct-00000", "--fixture", str(FIXTURE_PATH), "--impl", "total-order"
    )
    assert code == exit_codes.OK
    assert "no order-dependent behaviour" in text


def test_report_writes_a_self_contained_html_file(tmp_path: Path):
    target = tmp_path / "nested" / "report.html"
    code, text = run("report", "--fixture", str(FIXTURE_PATH), "--out", str(target))
    assert code == exit_codes.FINDING
    assert "400 keys" in text
    body = target.read_text()
    assert body.startswith("<!doctype html>")
    assert "<link" not in body


def test_report_returns_ok_for_an_order_safe_implementation(tmp_path: Path):
    code, _ = run(
        "report",
        "--fixture", str(FIXTURE_PATH),
        "--impl", "total-order",
        "--out", str(tmp_path / "r.html"),
    )
    assert code == exit_codes.OK


def test_report_refuses_an_unknown_ordering_field(tmp_path: Path):
    code, text = run(
        "report",
        "--fixture", str(FIXTURE_PATH),
        "--order-by", "nonsense",
        "--out", str(tmp_path / "r.html"),
    )
    assert code == exit_codes.USAGE
    assert "unknown ordering field" in text


def test_harness_reports_the_keys_it_missed():
    code, text = run("harness", "--fixture", str(FIXTURE_PATH), "--draws", "20")
    assert code == exit_codes.FINDING
    assert "keys the harness missed" in text


def test_harness_misses_nothing_for_an_order_safe_implementation():
    code, text = run("harness", "--fixture", str(FIXTURE_PATH), "--impl", "total-order")
    assert code == exit_codes.OK
    assert "keys the harness missed: 0" in text


def test_more_harness_draws_never_find_fewer_keys():
    def missed(draws: int) -> int:
        _, text = run("harness", "--fixture", str(FIXTURE_PATH), "--draws", str(draws))
        prefix = "keys the harness missed"
        line = next(one for one in text.splitlines() if one.startswith(prefix))
        return int(line.split(":")[1])

    assert missed(20) <= missed(1)


def test_no_subcommand_is_a_usage_error():
    with pytest.raises(SystemExit):
        main([])


def test_an_unknown_subcommand_is_a_usage_error():
    with pytest.raises(SystemExit):
        main(["frobnicate"])
