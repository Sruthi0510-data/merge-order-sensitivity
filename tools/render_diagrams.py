"""Render the committed SVG diagrams from a declarative spec, with the numbers read live.

Mermaid was the obvious choice and it is not the one taken here. Four of its failure modes
land squarely on a repository that embeds diagrams in a README: GitHub's lazily loaded
renderer can fail on a valid fence with an error that has nothing to fix in the source; HTML
labels put unclosed tags inside a foreignObject so the file is not well formed XML and fails
silently as an <img src>; the emitted root element carries a percentage width with no height
so a browser has no aspect ratio to work from; and a transparent background renders edge
labels dark grey on near black in a dark theme.

Emitting the SVG directly avoids all four by construction and removes a three megabyte
JavaScript dependency from the build. The cost is that layout is done by hand here rather
than by a solver, which is affordable for two diagrams and would not be for twenty.

Every figure in the diagrams is read from docs/metrics.json, so a diagram cannot drift away
from the numbers the rest of the documents quote.
"""

from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "docs" / "metrics.json"
OUT = ROOT / "docs" / "diagrams"

BACKGROUND = "#fbfbfa"
INK = "#1f2328"
MUTED = "#57606a"
LINE = "#8c959f"
BOX = "#ffffff"
ACCENT = "#0b6b5a"
WARN = "#8a3b12"
BLOCKED = "#b42318"


def _text(x: int, y: int, content: str, size: int = 13, fill: str = INK, weight: str = "normal",
          anchor: str = "start") -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="Helvetica,Arial,sans-serif" font-size="{size}" '
        f'fill="{fill}" font-weight="{weight}" text-anchor="{anchor}">{escape(content)}</text>'
    )


def _box(x: int, y: int, w: int, h: int, stroke: str = LINE, dash: str = "") -> str:
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{BOX}" '
        f'stroke="{stroke}" stroke-width="1.5"{dash_attr}/>'
    )


MARKER_FOR = {LINE: "line", ACCENT: "accent", BLOCKED: "blocked"}


def _arrow(x1: int, y1: int, x2: int, y2: int, stroke: str = LINE, dash: str = "") -> str:
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    marker = MARKER_FOR.get(stroke, "line")
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="1.5" '
        f'marker-end="url(#head-{marker})"{dash_attr}/>'
    )


def _rail(points: list[tuple[int, int]]) -> str:
    """A plain polyline with no arrowhead, used as the spine of a fan-out."""
    path = " ".join(f"{x},{y}" for x, y in points)
    return (
        f'<polyline points="{path}" fill="none" stroke="{LINE}" stroke-width="1.5" '
        f'stroke-linejoin="round"/>'
    )


def _document(width: int, height: int, body: str) -> str:
    """Wrap a body in an SVG with intrinsic dimensions and a painted background.

    Both details matter for an <img src> embed. A percentage width with no height leaves a
    browser with no aspect ratio to work from, and a transparent background renders muted
    label text dark grey on near black under a dark theme.
    """
    markers = "".join(
        f'<marker id="head-{name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        f'markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{colour}"/></marker>'
        for name, colour in (("line", LINE), ("accent", ACCENT), ("blocked", BLOCKED))
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">'
        f"<defs>{markers}</defs>"
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="{BACKGROUND}"/>'
        f"{body}</svg>"
    )


def architecture(metrics: dict) -> str:
    """The three arms, and which of them a real pipeline can actually run."""
    parts: list[str] = []
    parts.append(_text(24, 34, "Three arms over the same stream", 17, INK, "bold"))
    parts.append(
        _text(
            24, 56,
            f"{metrics['fixture_events']:,} events, {metrics['fixture_keys']} keys, "
            f"{metrics['fixture_batches']} micro-batches",
            12, MUTED,
        )
    )

    parts.append(_box(70, 80, 300, 62))
    parts.append(_text(88, 104, "CDC event stream", 13, INK, "bold"))
    parts.append(_text(88, 124, "as delivered, in arrival order", 11, MUTED))

    lanes = [
        (176, "Arm 1   control", "re-run in the same order",
         f"flags {metrics['rerun_keys_flagged']} keys", ACCENT, ""),
        (266, "Arm 2   reachable", "shuffle inside each micro-batch",
         f"finds {metrics['harness_ceiling_detected']} of "
         f"{metrics['baseline_order_dependent']} order-dependent keys", ACCENT, ""),
        (356, "Arm 3   unreachable", "swap across a batch boundary",
         f"{metrics['cross_batch_only']} keys only this arm sees", BLOCKED, "5 3"),
    ]
    parts.append(_rail([(120, 142), (120, 160), (44, 160), (44, 389)]))
    for y, title, subtitle, result, colour, dash in lanes:
        parts.append(_arrow(44, y + 33, 66, y + 33, LINE))
        parts.append(_box(70, y, 300, 70, colour, dash))
        parts.append(_text(88, y + 24, title, 13, colour, "bold"))
        parts.append(_text(88, y + 43, subtitle, 11, MUTED))
        parts.append(_text(88, y + 60, result, 11, INK))
        parts.append(_arrow(370, y + 35, 436, y + 35, colour, dash))

    parts.append(_box(440, 176, 248, 250, MUTED))
    parts.append(_text(458, 204, "referee", 14, INK, "bold"))
    parts.append(_text(458, 226, "resolves each key from the", 11, MUTED))
    parts.append(_text(458, 242, "event multiset, never its order", 11, MUTED))
    parts.append(_text(458, 274, "Decided", 11, ACCENT, "bold"))
    parts.append(_text(524, 274, "one row is entitled", 11, INK))
    parts.append(_text(458, 294, "Ambiguous", 11, WARN, "bold"))
    parts.append(_text(534, 294, "no row is entitled", 11, INK))
    parts.append(_text(458, 328, "breaks the symmetry that a", 11, MUTED))
    parts.append(_text(458, 344, "run-versus-run diff cannot", 11, MUTED))
    parts.append(
        _text(458, 382, f"{metrics['baseline_order_dependent']} order-dependent keys", 12, INK,
              "bold")
    )
    parts.append(_text(458, 400, "each with a replayable witness", 11, MUTED))

    parts.append(
        _text(24, 464,
              f"the dashed arm models nothing a pipeline can do: {metrics['orders_in_gap']:,} of "
              f"{metrics['orders_that_exist']:,} arrival orders are", 11, MUTED)
    )
    parts.append(
        _text(24, 482, "unreachable once a micro-batch has been committed", 11, MUTED)
    )
    return _document(712, 508, "".join(parts))


def order_space(metrics: dict) -> str:
    """One key's arrival-order space, split into what a shuffle reaches and what it cannot."""
    parts: list[str] = []
    parts.append(_text(24, 34, "The space a permutation harness can search", 17, INK, "bold"))
    parts.append(
        _text(24, 56,
              f"{metrics['keys_spanning_batches']} keys straddle a batch boundary in the fixture",
              12, MUTED)
    )

    total = metrics["orders_that_exist"]
    reachable = metrics["orders_reachable"]
    width = 560
    reach_width = int(width * reachable / total)

    parts.append(f'<rect x="24" y="86" width="{width}" height="52" rx="6" fill="#fdecec" '
                 f'stroke="{BLOCKED}" stroke-width="1.5"/>')
    parts.append(f'<rect x="24" y="86" width="{reach_width}" height="52" rx="6" fill="#e8f3f0" '
                 f'stroke="{ACCENT}" stroke-width="1.5"/>')
    parts.append(_text(42, 117, f"{reachable:,} are reachable", 12, ACCENT, "bold"))
    parts.append(_text(24, 160, f"{total:,} arrival orders exist across the fixture", 11, MUTED))
    parts.append(
        _text(584, 160, f"{metrics['orders_in_gap']:,} orders no shuffle can produce", 11,
              BLOCKED, "bold", anchor="end")
    )

    parts.append(_text(24, 208, "What that costs a sampling harness", 15, INK, "bold"))
    rows = [
        (f"{metrics['baseline_order_dependent']} order-dependent keys", "proved by the audit", INK),
        (f"{metrics['harness_ceiling_detected']} found by the harness",
         f"a ceiling of {metrics['harness_ceiling_pct']}% reached after "
         f"{metrics['harness_saturation_draws']} draws", ACCENT),
        (f"{metrics['cross_batch_only']} never found",
         f"still {metrics['cross_batch_only']} at {metrics['harness_max_draws']:,} draws",
         BLOCKED),
    ]
    for index, (left, right, colour) in enumerate(rows):
        y = 240 + index * 38
        parts.append(f'<rect x="24" y="{y - 19}" width="560" height="30" rx="4" fill="{BOX}" '
                     f'stroke="{LINE}" stroke-width="1"/>')
        parts.append(_text(42, y, left, 12, colour, "bold"))
        parts.append(_text(268, y, right, 11, MUTED))

    parts.append(
        _text(24, 378,
              f"zero hits across the unreachable population bounds detection below "
              f"{metrics['unreachable_bound_pct']}%, which is not zero", 11, MUTED)
    )
    return _document(608, 404, "".join(parts))


def main() -> int:
    metrics = json.loads(METRICS.read_text())["metrics"]
    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for name, builder in (("architecture", architecture), ("order-space", order_space)):
        path = OUT / f"{name}.svg"
        path.write_text(builder(metrics), encoding="utf-8")
        written.append(path)
    manifest = OUT / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "diagrams": [p.name for p in written],
                "source": "tools/render_diagrams.py",
                "note": "figures are read from docs/metrics.json so a diagram cannot go stale",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    for path in written:
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
