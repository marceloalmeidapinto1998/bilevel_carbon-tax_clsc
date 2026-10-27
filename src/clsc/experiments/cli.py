"""python -m clsc.experiments: list, run and report the paper's experiments (see docs/experiments.md)."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

from .plan import EXPERIMENTS
from .report import TABLES, write_tables
from .runner import expand, run_experiment

DEFAULT_ROOT = Path("results") / "experiments"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m clsc.experiments", description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help=f"Where the experiments' files go (default {DEFAULT_ROOT.as_posix()}).")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list", help="The experiments, with their number of jobs and how many are done.")

    run = commands.add_parser("run", help="Run the jobs of one or more experiments that are not done yet.")
    run.add_argument("experiments", nargs="+", choices=sorted(EXPERIMENTS))
    run.add_argument("--instances", nargs="+", help="Only the instances whose file name contains one of these strings.")
    run.add_argument("--threads", type=int, help="Gurobi threads (default: the method's default).")
    run.add_argument("--dry-run", action="store_true", help="Print the jobs that would run, and run none.")

    report = commands.add_parser("report", help="Write the tables to <root>/tables/ from the files that exist.")
    report.add_argument("tables", nargs="*", choices=sorted(TABLES), help="Tables to write (default: all).")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stderr)
    if args.command == "list":
        for experiment in EXPERIMENTS.values():
            jobs = expand(experiment)
            done = sum(job.is_done(args.root) for job in jobs)
            print(f"{experiment.key:3} {experiment.task:9} {done:3}/{len(jobs):<3} {experiment.title}")
        return 0
    if args.command == "run":
        failed = 0
        for key in args.experiments:
            records = run_experiment(EXPERIMENTS[key], args.root, instances=args.instances, threads=args.threads, dry_run=args.dry_run)
            failed += sum(record["status"] != "ok" for record in records)
        return 1 if failed else 0
    print(json.dumps(write_tables(args.root, args.tables or None), indent=2))
    return 0
