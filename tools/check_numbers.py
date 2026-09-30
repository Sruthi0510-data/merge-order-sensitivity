"""Fail the build when a document quotes a figure the code no longer produces.

The checker matches anchor phrases rather than bare digits. Searching for digits passes
happily while the sentence around them has gone stale: "10 keys" is found in a document that
now says "10 events". An anchor pairs the value with two or three words of its context, and
any one of a metric's anchors matching is enough, because the same figure reads differently
in a table and in a paragraph.

Whitespace in every document is collapsed before matching. Without that, an anchor whose
words happen to straddle a line break in wrapped markdown matches nothing while the prose it
guards is correct, and the first thing anyone learns is to pass --no-verify.

Two directions are checked. Forwards: every metric must appear, with its current value,
somewhere in the checked documents. Backwards: every number in the README must correspond to
a metric, so a figure nothing re-measures cannot quietly appear. Code fences, inline code
spans and HTML attributes are excluded from the backward check, because an example
invocation is allowed to contain a made-up row count and flagging it trains the reader to
ignore the section.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
METRICS_PATH = ROOT / "docs" / "metrics.json"

FENCE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE = re.compile(r"`[^`]*`")
HTML_ATTR = re.compile(r'\w+="[^"]*"')
LINK_TARGET = re.compile(r"\]\([^)]*\)")
NUMBER = re.compile(r"(?<![\w.-])\d[\d,]*(?:\.\d+)?(?![\w-])")

ALLOWED_BARE_NUMBERS = {
    "0", "1", "2", "3", "4", "5", "7", "10", "100", "2026", "3.10", "3.11", "3.12", "3.13",
}
"""Numbers a document may contain without a metric behind them.

Version numbers, exit codes, ADR indices and small structural counts. Everything else must be
a figure the collector re-measures.
"""


def collapse(text: str) -> str:
    """Collapse whitespace so an anchor never fails because markdown wrapped a line."""
    return re.sub(r"\s+", " ", text)


def strip_code(text: str) -> str:
    """Remove fenced blocks, inline spans, HTML attributes and link targets."""
    for pattern in (FENCE, INLINE_CODE, HTML_ATTR, LINK_TARGET):
        text = pattern.sub(" ", text)
    return text


def format_value(value: Any) -> list[str]:
    """Render a metric the ways a document might legitimately write it."""
    if isinstance(value, float):
        rendered = [f"{value:g}", f"{value:.1f}"]
    else:
        rendered = [f"{value:,}", str(value)]
    seen: list[str] = []
    for candidate in rendered:
        if candidate not in seen:
            seen.append(candidate)
    return seen


def check_forward(payload: dict[str, Any], documents: dict[str, str]) -> list[str]:
    """Every metric must appear with its current value in at least one checked document."""
    corpus = collapse(" ".join(documents.values()))
    failures: list[str] = []
    for name, value in sorted(payload["metrics"].items()):
        anchors = payload["anchors"].get(name)
        if not anchors:
            failures.append(f"GAP     {name}: no anchor phrase, so nothing guards this figure")
            continue
        if any(
            collapse(anchor.format(rendered)) in corpus
            for anchor in anchors
            for rendered in format_value(value)
        ):
            continue
        stale = _stale_variant(anchors, corpus)
        detail = f"found a stale variant: {stale!r}" if stale else "not quoted anywhere"
        failures.append(f"FAIL    {name} = {value}: {detail}")
    return failures


def _stale_variant(anchors: list[str], corpus: str) -> str | None:
    """Find an anchor whose wording is present with some other number in it."""
    for anchor in anchors:
        pattern = re.escape(collapse(anchor)).replace(r"\{\}", r"([\d,.]+)")
        match = re.search(pattern, corpus)
        if match:
            return collapse(anchor).replace("{}", match.group(1))
    return None


def check_backward(payload: dict[str, Any], readme: str) -> list[str]:
    """Every number in the README prose must be a figure something re-measures."""
    known = set()
    for value in payload["metrics"].values():
        known.update(format_value(value))
    prose = strip_code(readme)
    unguarded: list[str] = []
    for match in NUMBER.finditer(prose):
        token = match.group(0)
        if token in known or token in ALLOWED_BARE_NUMBERS or token.replace(",", "") in known:
            continue
        context = collapse(prose[max(0, match.start() - 40) : match.end() + 40]).strip()
        unguarded.append(f"UNGUARDED {token}: nothing re-measures this. context: ...{context}...")
    return unguarded


def main() -> int:
    if not METRICS_PATH.exists():
        print("docs/metrics.json is missing; run tools/collect_metrics.py first")
        return 2
    payload = json.loads(METRICS_PATH.read_text())

    documents: dict[str, str] = {}
    missing: list[str] = []
    for relative in payload["checked_documents"]:
        path = ROOT / relative
        if not path.exists():
            missing.append(relative)
            continue
        documents[relative] = path.read_text(encoding="utf-8")

    problems = [f"MISSING {name}: listed as a checked document and not present" for name in missing]
    problems += check_forward(payload, documents)
    problems += check_backward(payload, documents.get("README.md", ""))

    if problems:
        print(f"number check failed with {len(problems)} problem(s):")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(
        f"number check passed: {len(payload['metrics'])} metrics verified against "
        f"{len(documents)} documents"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
