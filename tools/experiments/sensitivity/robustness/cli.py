"""`robustness` subcommands: aggregate | censoring | tolerance."""
from __future__ import annotations

import argparse
from pathlib import Path

from . import aggregate as rob_aggregate
from . import censoring as rob_censoring
from . import tolerance as rob_tolerance


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("robustness", help="Solver robustness, censoring, tolerance sweep.")
    sub = p.add_subparsers(dest="action", required=True)

    sub.add_parser("aggregate", help="solver_robustness.csv from master_runs.csv.").set_defaults(func=_run_aggregate)
    sub.add_parser("censoring", help="censoring_flags.csv from master_runs.csv.").set_defaults(func=_run_censoring)

    t = sub.add_parser("tolerance", help="Re-solve one instance under a tolerance grid.")
    t.add_argument("source", nargs="?", help="Base instance JSON to re-solve.")
    t.add_argument("--time-limit", type=float, default=None)
    t.add_argument("--smoke", action="store_true", help="Verify injection plumbing only (no solve).")
    t.set_defaults(func=_run_tolerance)


def _run_aggregate(args: argparse.Namespace) -> int:
    rob_aggregate.aggregate()
    return 0


def _run_censoring(args: argparse.Namespace) -> int:
    rob_censoring.censoring_flags()
    return 0


def _run_tolerance(args: argparse.Namespace) -> int:
    if args.smoke or not args.source:
        return rob_tolerance.smoke()
    rob_tolerance.run(args.source, time_limit=args.time_limit)
    return 0
