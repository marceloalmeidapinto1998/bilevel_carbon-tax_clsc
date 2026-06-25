"""Orchestrator CLI for the sensitivity package: `python -m tools.experiments.sensitivity <command>`.

Each method subpackage registers its own subcommands; this module wires them together and adds the
standalone `report` and `analyze-all` commands. (Tax-range extension is an OAT spec:
tax_range_max040 / tax_range_max080, not a separate command.)
"""
from __future__ import annotations

import argparse

from . import report as report_mod
from .morris import cli as morris_cli
from .oat import cli as oat_cli
from .robustness import cli as robustness_cli


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.experiments.sensitivity",
        description="Sensitivity & robustness analysis for the bilevel CLSC model.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    oat_cli.add_subparser(sub)
    morris_cli.add_subparser(sub)
    robustness_cli.add_subparser(sub)

    sub.add_parser("report", help="Assemble results/analysis/reports/SENSITIVITY_REPORT.md.").set_defaults(func=_run_report)
    sub.add_parser("analyze-all",
                   help="Re-analyze from existing results (aggregate + oat + robustness + report).") \
        .set_defaults(func=_run_analyze_all)
    return parser


def _run_report(args: argparse.Namespace) -> int:
    report_mod.build()
    return 0


def _run_analyze_all(args: argparse.Namespace) -> int:
    from tools.analysis.aggregate import main as aggregate_results
    from .oat import analyze as oat_analyze
    from .robustness import aggregate, censoring

    aggregate_results()        # generic tidy tables (master_runs, tax_response_long, scenario_2x2)
    oat_analyze.analyze()      # sensitivity_matrix.csv
    aggregate.aggregate()      # solver_robustness.csv
    censoring.censoring_flags()  # censoring_flags.csv
    report_mod.build()         # SENSITIVITY_REPORT.md
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
