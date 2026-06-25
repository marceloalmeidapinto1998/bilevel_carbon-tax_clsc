"""Command-line interface for aggregate result analysis."""

from __future__ import annotations

import argparse

from .core import main as aggregate_results


def _build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="python -m tools.analysis.aggregate",
        description="Build master analysis tables from solved result folders.",
    )


def main(argv: list[str] | None = None) -> int:
    _build_parser().parse_args(argv)
    aggregate_results()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
