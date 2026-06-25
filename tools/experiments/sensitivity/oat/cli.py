"""`oat` subcommands for the sensitivity orchestrator: design | analyze."""
from __future__ import annotations

import argparse
from pathlib import Path

from . import analyze as oat_analyze
from . import design as oat_design
from .specs import SENSITIVITY_SPECS, canonical_code


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("oat", help="Local one-at-a-time perturbations + elasticities.")
    sub = p.add_subparsers(dest="action", required=True)

    d = sub.add_parser("design", help="Generate OAT instances + design_matrix.csv.")
    d.add_argument("source", type=Path, help="Base instance JSON (data/instances/base/<name>.json).")
    d.add_argument("--output-dir", type=Path, default=oat_design.DEFAULT_OUTPUT_DIR)
    d.add_argument("--scenario-name", default=oat_design.DEFAULT_SCENARIO_NAME)
    d.add_argument("--codes", nargs="*", metavar="CODE",
                   help="Subset of spec codes (default: all).")
    d.add_argument("--overwrite", action="store_true")
    d.set_defaults(func=_run_design)

    a = sub.add_parser("analyze", help="Elasticities from master_runs.csv.")
    a.set_defaults(func=_run_analyze)


def _run_design(args: argparse.Namespace) -> int:
    specs = SENSITIVITY_SPECS
    if getattr(args, "codes", None):
        code_set = {canonical_code(code) for code in args.codes}
        unknown = code_set - {s.code for s in SENSITIVITY_SPECS}
        if unknown:
            print(f"Unknown spec codes: {', '.join(sorted(unknown))}")
            return 1
        specs = tuple(s for s in SENSITIVITY_SPECS if s.code in code_set)
    written = oat_design.create_sensitivity_scenarios(
        args.source, args.output_dir, specs=specs,
        scenario_name=args.scenario_name, overwrite=args.overwrite)
    print(f"Wrote {len(written)} OAT instance(s) under {Path(args.output_dir)}")
    return 0


def _run_analyze(args: argparse.Namespace) -> int:
    oat_analyze.analyze()
    return 0
