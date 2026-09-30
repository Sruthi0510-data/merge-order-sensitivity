"""The command line surface. Exit codes are an interface here, not an afterthought.

`audit` returns 3 when it finds order-dependent keys. That is the tool working, not the tool
failing, and it is a separate code from 2 so a CI step can tell a finding from a crash
without parsing output. `--require-confidence` is the only way to get code 4, because a check
that fails by default gets weakened within a week and then nothing is checked at all.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from mos import exit_codes
from mos.audit import audit, simulate_permutation_harness
from mos.detection import draws_for_confidence
from mos.errors import ConfigError, FixtureError, MosError
from mos.events import load_events, write_events
from mos.generator import GeneratorConfig, generate
from mos.implementations import IMPLEMENTATIONS
from mos.semantics import MergeSpec

DEFAULT_FIXTURE = Path("fixtures/cdc_events.jsonl")
DEFAULT_ORDER_BY = "seq"


def _spec_from_args(args: argparse.Namespace) -> MergeSpec:
    """Build the declaration, from a reviewed file when one is given and from flags otherwise.

    A file and flags together is refused rather than silently resolved. Two sources for one
    declaration is how a team ends up auditing something other than what it reviewed.
    """
    spec_path = getattr(args, "spec", None)
    if spec_path is not None:
        if args.order_by != DEFAULT_ORDER_BY or args.delete_wins:
            raise ConfigError(
                "--spec cannot be combined with --order-by or --delete-wins; "
                "put the ordering in the spec file"
            )
        return MergeSpec.from_file(spec_path)
    ordering = tuple(field.strip() for field in args.order_by.split(",") if field.strip())
    return MergeSpec(ordering=ordering, delete_wins_ties=args.delete_wins)


def _add_spec_arguments(parser: argparse.ArgumentParser) -> None:
    """The three ways to state a declaration, on every subcommand that needs one."""
    parser.add_argument(
        "--spec", type=Path, default=None, help="a reviewed merge declaration, as TOML"
    )
    parser.add_argument("--order-by", default=DEFAULT_ORDER_BY)
    parser.add_argument("--delete-wins", action="store_true")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mos",
        description=(
            "Audit a MERGE for order sensitivity, the property a re-run idempotency test "
            "holds constant instead of varying."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="write a deterministic CDC fixture")
    gen.add_argument("--out", type=Path, default=DEFAULT_FIXTURE)
    gen.add_argument("--keys", type=int, default=400)
    gen.add_argument("--batches", type=int, default=6)
    gen.add_argument("--seed", type=int, default=20260930)
    gen.add_argument("--tie-rate", type=float, default=0.22)
    gen.add_argument("--cross-batch-rate", type=float, default=0.35)

    aud = sub.add_parser("audit", help="run the three-arm audit over a fixture")
    aud.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    aud.add_argument("--impl", default="dedupe-last-max", choices=sorted(IMPLEMENTATIONS))
    _add_spec_arguments(aud)
    aud.add_argument("--search-limit", type=int, default=512)
    aud.add_argument("--seed", type=int, default=0)
    aud.add_argument("--json", type=Path, default=None, help="write the full finding set here")
    aud.add_argument(
        "--require-confidence",
        type=float,
        default=None,
        help="exit 4 when the permutation budget cannot support this confidence (0 to 1)",
    )

    cmp_ = sub.add_parser("compare", help="audit every bundled implementation and tabulate")
    cmp_.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    _add_spec_arguments(cmp_)
    cmp_.add_argument("--json", type=Path, default=None)

    wit = sub.add_parser("witness", help="print the two arrival orders that disagree for one key")
    wit.add_argument("key")
    wit.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    wit.add_argument("--impl", default="dedupe-last-max", choices=sorted(IMPLEMENTATIONS))
    _add_spec_arguments(wit)

    rep = sub.add_parser("report", help="write a self-contained HTML report")
    rep.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    rep.add_argument("--impl", default="dedupe-last-max", choices=sorted(IMPLEMENTATIONS))
    _add_spec_arguments(rep)
    rep.add_argument("--out", type=Path, default=Path("docs/report.html"))

    har = sub.add_parser("harness", help="simulate the permutation harness a team would build")
    har.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    har.add_argument("--impl", default="dedupe-last-max", choices=sorted(IMPLEMENTATIONS))
    _add_spec_arguments(har)
    har.add_argument("--draws", type=int, default=20)
    har.add_argument("--seed", type=int, default=0)
    return parser


def _cmd_generate(args: argparse.Namespace, out) -> int:
    config = GeneratorConfig(
        keys=args.keys,
        batches=args.batches,
        seed=args.seed,
        tie_rate=args.tie_rate,
        cross_batch_rate=args.cross_batch_rate,
    )
    events = generate(config)
    written = write_events(args.out, events)
    keys = len({event.key for event in events})
    print(f"wrote {written} events across {keys} keys to {args.out}", file=out)
    return exit_codes.OK


def _cmd_audit(args: argparse.Namespace, out) -> int:
    events = load_events(args.fixture)
    result = audit(
        events,
        spec=_spec_from_args(args),
        implementation=args.impl,
        search_limit=args.search_limit,
        seed=args.seed,
    )
    summary = result.summary()
    print(json.dumps(summary, indent=2), file=out)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                {"summary": summary, "findings": [f.as_dict() for f in result.findings]},
                indent=2,
            ),
            encoding="utf-8",
        )
    if args.require_confidence is not None:
        needed = draws_for_confidence(0.5, args.require_confidence)
        if args.search_limit < needed:
            print(
                f"search limit {args.search_limit} is below the {needed} draws a two-outcome "
                f"key needs for confidence {args.require_confidence}",
                file=out,
            )
            return exit_codes.UNDERPOWERED
    return exit_codes.FINDING if result.order_dependent else exit_codes.OK


def _cmd_compare(args: argparse.Namespace, out) -> int:
    events = load_events(args.fixture)
    spec = _spec_from_args(args)
    rows = []
    header = (
        f"{'implementation':<18}{'order-dep':>10}{'cross-batch':>13}"
        f"{'impl-defect':>13}{'rerun':>8}"
    )
    print(header, file=out)
    print("-" * len(header), file=out)
    for name in sorted(IMPLEMENTATIONS):
        result = audit(events, spec=spec, implementation=name)
        row = {
            "implementation": name,
            "order_dependent_keys": len(result.order_dependent),
            "cross_batch_only_keys": len(result.cross_batch_only),
            "implementation_defect_keys": len(result.implementation_defects),
            "rerun_keys_flagged": result.rerun_keys_flagged,
        }
        rows.append(row)
        print(
            f"{name:<18}{row['order_dependent_keys']:>10}{row['cross_batch_only_keys']:>13}"
            f"{row['implementation_defect_keys']:>13}{row['rerun_keys_flagged']:>8}",
            file=out,
        )
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")
    return exit_codes.FINDING if any(r["order_dependent_keys"] for r in rows) else exit_codes.OK


def _cmd_witness(args: argparse.Namespace, out) -> int:
    events = load_events(args.fixture)
    result = audit(events, spec=_spec_from_args(args), implementation=args.impl)
    matches = [f for f in result.findings if f.key == args.key]
    if not matches:
        raise ConfigError(f"key {args.key!r} is not present in {args.fixture}")
    finding = matches[0]
    if finding.witness is None:
        print(f"{args.key}: no order-dependent behaviour found", file=out)
        return exit_codes.OK
    witness = finding.witness
    reach = "reachable inside one batch" if witness.within_batch else "needs a cross-batch swap"
    print(f"{args.key}: order dependent ({reach})", file=out)
    print(f"  order A {list(witness.order_a)} leaves {witness.state_a}", file=out)
    print(f"  order B {list(witness.order_b)} leaves {witness.state_b}", file=out)
    return exit_codes.FINDING


def _cmd_harness(args: argparse.Namespace, out) -> int:
    events = load_events(args.fixture)
    spec = _spec_from_args(args)
    result = audit(events, spec=spec, implementation=args.impl)
    flagged = simulate_permutation_harness(events, spec, args.impl, args.draws, args.seed)
    truth = {f.key for f in result.order_dependent}
    missed = sorted(truth - flagged)
    print(f"harness draws: {args.draws}", file=out)
    print(f"keys flagged by the harness: {len(flagged)}", file=out)
    print(f"order-dependent keys the audit proves: {len(truth)}", file=out)
    print(f"keys the harness missed: {len(missed)}", file=out)
    return exit_codes.FINDING if missed else exit_codes.OK


def _cmd_report(args: argparse.Namespace, out) -> int:
    from mos.report import build_report

    events = load_events(args.fixture)
    result = audit(events, spec=_spec_from_args(args), implementation=args.impl)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build_report(result), encoding="utf-8")
    print(f"wrote {args.out} for {result.key_count} keys", file=out)
    return exit_codes.FINDING if result.order_dependent else exit_codes.OK


HANDLERS = {
    "generate": _cmd_generate,
    "report": _cmd_report,
    "audit": _cmd_audit,
    "compare": _cmd_compare,
    "witness": _cmd_witness,
    "harness": _cmd_harness,
}


def main(argv: Sequence[str] | None = None, out=None) -> int:
    """Entry point. Returns an exit code rather than calling sys.exit, so tests can drive it."""
    out = out or sys.stdout
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return HANDLERS[args.command](args, out)
    except (ConfigError, FixtureError) as exc:
        print(f"error: {exc}", file=out)
        return exit_codes.USAGE
    except MosError as exc:  # pragma: no cover - defensive, no current path reaches it
        print(f"error: {exc}", file=out)
        return exit_codes.USAGE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
