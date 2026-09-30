"""Shared plumbing for the experiments: one fixture path, one JSON writer, one table printer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "cdc_events.jsonl"
OUTPUT_DIR = ROOT / "docs" / "experiments"


def write_result(name: str, payload: dict[str, Any]) -> Path:
    """Write one experiment's JSON and return where it went."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def print_table(headers: list[str], rows: list[list[Any]], widths: list[int] | None = None) -> None:
    """Print a fixed-width table. Deliberately plain: this output is captured for the demo."""
    widths = widths or [max(len(str(headers[i])), 12) for i in range(len(headers))]
    line = "".join(str(h).ljust(w) for h, w in zip(headers, widths, strict=True))
    print(line)
    print("-" * len(line))
    for row in rows:
        print("".join(str(cell).ljust(w) for cell, w in zip(row, widths, strict=True)))
