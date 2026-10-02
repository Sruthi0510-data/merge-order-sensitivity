"""The HTML report, with the class collision check that a passing test suite cannot see.

The last test in this file is the one worth reading. A verdict badge and a table cell sharing
a class at equal specificity renders a headline in its own background colour: the Python is
correct, the HTML is correct, every other test passes, and the number the page exists for is
invisible. Asserting that every class in the markup is declared and styled catches it at the
source, and the screenshot tool reads the rendered contrast back as a second line of defence.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from mos.audit import audit
from mos.report import CLASSES, STYLESHEET, build_report
from mos.semantics import MergeSpec

SPEC = MergeSpec()


@pytest.fixture(scope="module")
def report(shipped_fixture) -> str:
    return build_report(audit(shipped_fixture, SPEC, "dedupe-last-max"))


@pytest.fixture(scope="module")
def clear_report(shipped_fixture) -> str:
    return build_report(audit(shipped_fixture, SPEC, "total-order"))


def _classes_used(html: str) -> set[str]:
    used: set[str] = set()
    for match in re.finditer(r"class=['\"]([^'\"]+)['\"]", html):
        used.update(match.group(1).split())
    return used


def test_the_report_is_a_complete_html_document(report):
    assert report.startswith("<!doctype html>")
    assert report.rstrip().endswith("</html>")


def test_the_report_carries_its_own_stylesheet_rather_than_a_link(report):
    assert "<style>" in report
    assert "<link" not in report


def test_a_finding_report_shows_the_finding_verdict(report):
    assert 'class="verdict-finding"' in report
    assert "ORDER DEPENDENT" in report


def test_a_clean_report_shows_the_clear_verdict(clear_report):
    assert 'class="verdict-clear"' in clear_report
    assert "NO ORDER DEPENDENCE FOUND" in clear_report


def test_the_two_verdicts_never_appear_together(report, clear_report):
    """Matched on the attribute, not the bare class name.

    The first version of this test searched for the substring "verdict-clear" and failed on a
    correct report, because both rules live in the stylesheet the page inlines. A selector
    test that does not distinguish markup from CSS will keep finding things that are not there.
    """
    assert 'class="verdict-clear"' not in report
    assert 'class="verdict-finding"' not in clear_report


@pytest.mark.parametrize("heading", ["summary", "breakdown", "witnesses"])
def test_every_heading_the_screenshot_tool_frames_by_is_present(heading, report):
    """The capture tool clips between these ids. Renaming one must fail here, loudly."""
    assert f'id="{heading}"' in report


def test_the_report_names_the_implementation_it_audited(report):
    assert "dedupe-last-max" in report


def test_the_report_names_the_declared_ordering(report):
    assert "declared ordering (seq)" in report


def test_the_report_states_the_rerun_result(report):
    assert "the control, run on the arrival order that already happened" in report


def test_witnesses_are_listed_for_a_finding_report(report):
    assert report.count('class="witness"') > 1


def test_a_clean_report_says_so_rather_than_showing_an_empty_list(clear_report):
    assert "no order-dependent keys were found" in clear_report


def test_a_cross_batch_witness_is_flagged_as_unreachable(shipped_fixture):
    result = audit(shipped_fixture, SPEC, "dedupe-last-max")
    assert result.cross_batch_only
    html = build_report(result)
    if any(f.witness and not f.witness.within_batch for f in result.order_dependent[:6]):
        assert "needs a cross-batch swap" in html


def test_key_names_are_escaped_rather_than_interpolated_raw(shipped_fixture):
    from tests.conftest import make_event

    events = [
        make_event(1, key="<script>x</script>", seq=10, status="a"),
        make_event(2, key="<script>x</script>", seq=10, status="b"),
    ]
    html = build_report(audit(events, SPEC, "dedupe-last-max"))
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_every_class_in_the_markup_is_declared_and_styled(report, clear_report):
    """Pins the collision that renders a headline in its own background colour."""
    used = _classes_used(report) | _classes_used(clear_report)
    undeclared = sorted(used - CLASSES)
    unstyled = sorted(name for name in used if f".{name}" not in STYLESHEET)
    assert undeclared == []
    assert unstyled == []


def test_every_declared_class_has_a_rule_so_the_list_cannot_rot():
    assert sorted(name for name in CLASSES if f".{name}" not in STYLESHEET) == []


def test_the_two_verdict_classes_have_different_backgrounds():
    """Equal specificity between them would make the verdict meaningless."""
    finding = re.search(r"\.verdict-finding \{[^}]*background: (#[0-9a-f]+)", STYLESHEET)
    clear = re.search(r"\.verdict-clear \{[^}]*background: (#[0-9a-f]+)", STYLESHEET)
    assert finding and clear
    assert finding.group(1) != clear.group(1)


ROOT = Path(__file__).resolve().parents[1]


def test_the_proof_of_work_transcript_exists_and_covers_several_exit_codes():
    """A transcript that only ever shows a zero proves the least interesting thing."""
    payload = json.loads((ROOT / "docs" / "proof-of-work.json").read_text())
    codes = {capture["exit_code"] for capture in payload["captures"]}
    assert len(codes) >= 3


def test_every_captured_command_exited_as_the_readme_claims():
    payload = json.loads((ROOT / "docs" / "proof-of-work.json").read_text())
    for capture in payload["captures"]:
        assert capture["exit_code"] == capture["expected_exit_code"], capture["command"]


def test_every_captured_command_carries_a_hash_of_its_untruncated_output():
    payload = json.loads((ROOT / "docs" / "proof-of-work.json").read_text())
    for capture in payload["captures"]:
        assert len(capture["output_sha256"]) == 64


def test_the_transcript_leaks_no_absolute_path():
    svg = (ROOT / "docs" / "img" / "proof-of-work.svg").read_text(encoding="utf-8")
    assert str(ROOT) not in svg
    assert "/usr/bin/python" not in svg


def test_the_transcript_is_valid_svg_with_a_title_and_description():
    import xml.etree.ElementTree as ET

    namespace = "{http://www.w3.org/2000/svg}"
    root = ET.parse(ROOT / "docs" / "img" / "proof-of-work.svg").getroot()
    assert root.find(f"{namespace}title") is not None
    assert root.find(f"{namespace}desc") is not None


def test_the_readme_embeds_the_transcript():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/img/proof-of-work.svg" in text
