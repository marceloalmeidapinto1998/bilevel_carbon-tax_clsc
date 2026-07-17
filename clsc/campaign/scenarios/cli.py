"""Command dispatcher for scenario generators."""

from __future__ import annotations

import argparse
import sys

from .combined import main as combined_main
from .technology import main as technology_main
from .transport import main as transport_main


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m clsc.campaign.scenarios",
        description="Generate scenario instance JSON files.",
    )
    parser.add_argument(
        "scenario",
        choices=("technology", "transport", "combined"),
        help="Scenario family to generate.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"technology", "transport", "combined"}:
        scenario = argv.pop(0)
        if scenario == "technology":
            return technology_main(argv)
        if scenario == "transport":
            return transport_main(argv)
        return combined_main(argv)

    parser = _build_parser()
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
