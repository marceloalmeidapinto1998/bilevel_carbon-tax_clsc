"""`morris` subcommands for the sensitivity orchestrator: design | analyze."""
from __future__ import annotations

import argparse
from pathlib import Path

from tools.experiments.sensitivity.factors import DEFAULT_MORRIS_FACTORS
from . import analyze as morris_analyze
from . import design as morris_design


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("morris", help="Global Morris elementary-effects screening.")
    sub = p.add_subparsers(dest="action", required=True)

    d = sub.add_parser("design", help="Sample trajectories + materialize instances + design matrix.")
    d.add_argument("source", type=Path, help="Base instance JSON (data/instances/base/<name>.json).")
    d.add_argument("--output-dir", type=Path, default=morris_design.DEFAULT_OUTPUT_DIR)
    d.add_argument("--factors", nargs="*", default=list(DEFAULT_MORRIS_FACTORS))
    d.add_argument("-N", "--trajectories", type=int, default=10)
    d.add_argument("--num-levels", type=int, default=4)
    d.add_argument("--seed", type=int, default=0)
    d.add_argument("--overwrite", action="store_true")
    d.set_defaults(func=_run_design)

    a = sub.add_parser("analyze", help="Compute mu*, sigma from solved screening runs.")
    a.add_argument("base_instance", help="Base instance name, e.g. STD_I17_M4_T3.")
    a.add_argument("--results-root", type=Path, default=None)
    a.set_defaults(func=_run_analyze)


def _run_design(args: argparse.Namespace) -> int:
    info = morris_design.generate(
        args.source, output_dir=args.output_dir, factors=tuple(args.factors),
        N=args.trajectories, num_levels=args.num_levels, seed=args.seed, overwrite=args.overwrite)
    print(f"Morris design ({info['engine']}): {info['n_points']} points "
          f"({info['n_trajectories']} trajectories x {len(info['factors'])}+1 factors)")
    print(f"  instances:     {info['output_dir']}")
    print(f"  design matrix: {info['design_matrix']}")
    return 0


def _run_analyze(args: argparse.Namespace) -> int:
    kwargs = {} if args.results_root is None else {"results_root": args.results_root}
    morris_analyze.analyze(args.base_instance, **kwargs)
    return 0
