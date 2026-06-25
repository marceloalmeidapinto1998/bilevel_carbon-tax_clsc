"""Command-line interface for the network analysis package."""

from __future__ import annotations

import argparse
import logging
from dataclasses import replace
from pathlib import Path

from . import io as ts_io
from .io import DEFAULT, AnalysisConfig, ensure_stream_handler
from .pipeline import run_instance


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools.analysis.network",
        description="Per-instance network analysis.",
    )
    p.add_argument("instances", nargs="*", help="Instance name(s) (e.g. STD_I17_M4_T3).")
    p.add_argument("--all", dest="run_all", action="store_true",
                   help="Discover and analyze every instance under results_base.")
    p.add_argument("--results-base", type=Path, default=DEFAULT.results_base)
    p.add_argument("--scenario", type=str, default=None,
                   help="Optional scenario name. When set, outputs go to "
                        "results/base/scenarios/<scenario>/<instance>/lf_lex_exact/network/.")
    p.add_argument("--eps", type=float, default=DEFAULT.eps)
    p.add_argument("--baseline-tau", type=int, default=DEFAULT.baseline_tau)
    p.add_argument("--log-level", default=DEFAULT.log_level,
                   choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return p


def _config_from_args(args: argparse.Namespace) -> AnalysisConfig:
    return replace(
        DEFAULT,
        results_base=args.results_base,
        scenario=args.scenario,
        eps=args.eps,
        baseline_tau=args.baseline_tau,
        log_level=args.log_level,
    )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    cfg = _config_from_args(args)
    ensure_stream_handler(cfg.log_level)
    log = logging.getLogger("network.cli")

    if args.run_all:
        instances = ts_io.discover_instances(cfg)
        if not instances:
            log.error("no instances discovered under %s", cfg.results_base)
            return 2
    else:
        instances = list(args.instances)

    if not instances:
        parser.print_usage()
        return 2

    failures = 0
    for inst in instances:
        try:
            run_instance(inst, cfg)
        except FileNotFoundError as exc:
            log.error("instance=%s failed: %s", inst, exc)
            failures += 1

    if failures == 0:
        return 0
    if failures == len(instances):
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())  # pragma: no cover

