"""A self-contained HTML report, built as a string rather than through a template engine.

The report is the artefact a reviewer looks at, so two things about it are deliberate.

Every section carries a stable `id` on its `h2`. The screenshot tool frames its captures by
scrolling to a named heading and clipping to the next one, because a hard coded pixel crop
drifts silently the first time a paragraph gets longer and then the README shows half a table.
Renaming a heading here breaks the capture loudly, which is the correct failure.

Every CSS class used in the markup is declared in CLASSES and has a rule in STYLESHEET, and a
test asserts the two agree. That test exists because a verdict badge and a table cell sharing
a class at equal specificity is a real way to render a headline green on green: the Python is
correct, the HTML is correct, the tests pass, and the number nobody can read is the one the
whole page is about.
"""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from mos.audit import AuditResult

CLASSES = frozenset(
    {
        "page",
        "masthead",
        "subtitle",
        "verdict-finding",
        "verdict-clear",
        "section",
        "grid",
        "cell",
        "cell-label",
        "cell-value",
        "cell-note",
        "data-table",
        "numeric",
        "witness",
        "witness-order",
        "witness-row",
        "flag-unreachable",
        "footnote",
    }
)
"""Every class the markup may use. Kept beside the stylesheet so the test can compare them."""

STYLESHEET = """
:root { color-scheme: light; }
body { margin: 0; background: #f6f7f6; color: #1f2328;
       font-family: -apple-system, Helvetica, Arial, sans-serif; }
.page { max-width: 860px; margin: 0 auto; padding: 32px 24px 64px; }
.masthead { font-size: 26px; font-weight: 700; margin: 0 0 6px; }
.subtitle { color: #57606a; font-size: 14px; margin: 0 0 20px; }
.verdict-finding { display: inline-block; padding: 8px 16px; border-radius: 999px;
                   background: #b42318; color: #ffffff; font-weight: 700; font-size: 15px;
                   letter-spacing: 0.02em; }
.verdict-clear { display: inline-block; padding: 8px 16px; border-radius: 999px;
                 background: #0b6b5a; color: #ffffff; font-weight: 700; font-size: 15px;
                 letter-spacing: 0.02em; }
.section { margin-top: 36px; }
.section h2 { font-size: 18px; margin: 0 0 12px; padding-bottom: 6px;
              border-bottom: 1px solid #d8dee4; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.cell { background: #ffffff; border: 1px solid #d8dee4; border-radius: 8px; padding: 14px 16px; }
.cell-label { color: #57606a; font-size: 12px; text-transform: uppercase;
              letter-spacing: 0.04em; }
.cell-value { font-size: 24px; font-weight: 700; margin-top: 4px; }
.cell-note { color: #57606a; font-size: 12px; margin-top: 4px; }
.data-table { width: 100%; border-collapse: collapse; background: #ffffff;
              border: 1px solid #d8dee4; border-radius: 8px; font-size: 14px; }
.data-table th { text-align: left; padding: 10px 12px; border-bottom: 1px solid #d8dee4;
                 color: #57606a; font-weight: 600; font-size: 12px; text-transform: uppercase; }
.data-table td { padding: 10px 12px; border-bottom: 1px solid #eaeef2; }
.numeric { text-align: right; font-variant-numeric: tabular-nums; }
.witness { background: #ffffff; border: 1px solid #d8dee4; border-radius: 8px;
           padding: 14px 16px; margin-bottom: 10px; }
.witness-order { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 13px;
                 color: #1f2328; margin-top: 6px; }
.witness-row { color: #57606a; font-size: 13px; }
.flag-unreachable { color: #b42318; font-weight: 700; font-size: 12px; }
.footnote { color: #57606a; font-size: 12px; margin-top: 28px; line-height: 1.6; }
"""


def _cell(label: str, value: str, note: str) -> str:
    return (
        f'<div class="cell"><div class="cell-label">{escape(label)}</div>'
        f'<div class="cell-value">{escape(value)}</div>'
        f'<div class="cell-note">{escape(note)}</div></div>'
    )


def _summary_section(result: AuditResult) -> str:
    cells = [
        _cell(
            "re-run test",
            f"{result.rerun_keys_flagged} keys",
            "the control, run on the arrival order that already happened",
        ),
        _cell(
            "order dependent",
            f"{len(result.order_dependent)} keys",
            f"{result.rate(result.order_dependent)}% of the {result.key_count} audited",
        ),
        _cell(
            "beyond any harness",
            f"{len(result.cross_batch_only)} keys",
            "a witness exists and no shuffle inside a batch can produce it",
        ),
        _cell(
            "fixable in code",
            f"{len(result.implementation_defects)} keys",
            "the declaration decides these and the implementation disagrees",
        ),
    ]
    return (
        '<section class="section"><h2 id="summary">Summary</h2>'
        f'<div class="grid">{"".join(cells)}</div></section>'
    )


def _breakdown_section(result: AuditResult) -> str:
    rows = [
        ("keys audited", result.key_count),
        ("declaration ties on different rows", len(result.spec_ambiguous)),
        ("implementation disagrees with the referee", len(result.disagrees_with_referee)),
        ("order dependent by a reachable shuffle", len(result.order_dependent_within_batch)),
        ("order dependent only across a batch boundary", len(result.cross_batch_only)),
    ]
    body = "".join(
        f"<tr><td>{escape(label)}</td><td class=\"numeric\">{value}</td></tr>"
        for label, value in rows
    )
    return (
        '<section class="section"><h2 id="breakdown">Where the findings come from</h2>'
        '<table class="data-table"><thead><tr><th>quantity</th>'
        '<th class="numeric">keys</th></tr></thead>'
        f"<tbody>{body}</tbody></table></section>"
    )


def _witness_section(result: AuditResult, limit: int = 6) -> str:
    blocks = []
    for finding in result.order_dependent[:limit]:
        witness = finding.witness
        if witness is None:  # pragma: no cover - order_dependent always carries one
            continue
        flag = (
            '<span class="flag-unreachable">needs a cross-batch swap</span>'
            if not witness.within_batch
            else ""
        )
        blocks.append(
            f'<div class="witness"><strong>{escape(finding.key)}</strong> {flag}'
            f'<div class="witness-order">order A {list(witness.order_a)}</div>'
            f'<div class="witness-row">leaves {escape(str(witness.state_a))}</div>'
            f'<div class="witness-order">order B {list(witness.order_b)}</div>'
            f'<div class="witness-row">leaves {escape(str(witness.state_b))}</div></div>'
        )
    if not blocks:
        blocks.append('<div class="witness">no order-dependent keys were found</div>')
    return (
        '<section class="section"><h2 id="witnesses">Witnesses</h2>'
        f'{"".join(blocks)}</section>'
    )


def build_report(result: AuditResult) -> str:
    """Render one audit as a self-contained HTML page."""
    finding = bool(result.order_dependent)
    verdict_class = "verdict-finding" if finding else "verdict-clear"
    verdict_text = (
        f"ORDER DEPENDENT: {len(result.order_dependent)} keys"
        if finding
        else "NO ORDER DEPENDENCE FOUND"
    )
    ordering = ", ".join(result.spec.ordering)
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>merge order sensitivity report</title>"
        f"<style>{STYLESHEET}</style></head><body><div class='page'>"
        f'<h1 class="masthead">Order sensitivity audit</h1>'
        f'<p class="subtitle">implementation {escape(result.implementation)}, '
        f"declared ordering ({escape(ordering)}), {result.event_count} events in "
        f"{result.batch_count} micro-batches</p>"
        f'<span class="{verdict_class}">{escape(verdict_text)}</span>'
        f"{_summary_section(result)}{_breakdown_section(result)}{_witness_section(result)}"
        '<p class="footnote">The re-run idempotency test replays the arrival order, so it '
        "measures idempotency and not order independence. Every witness above is two arrival "
        "orders of the same events that leave different rows in the table. A witness marked "
        "as needing a cross-batch swap describes a defect no permutation harness built on "
        "this delivery model can reproduce.</p>"
        "</div></body></html>"
    )
