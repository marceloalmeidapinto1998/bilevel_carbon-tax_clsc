from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from .config import ArcConnectivityConfig, DEFAULT_AIRPLANES, DEFAULT_BOATS, DEFAULT_TRUCKS, GeneratorConfig
from .instance_builder import generate_instance, write_instance
from .benchmark import generate_benchmark, generate_escalation_bases

def build_instance_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate Tautenhain-based closed-loop supply chain instances for the carbon-tax model.",
    )
    parser.add_argument("--name", default="base_case", help="Instance name used in metadata and default output naming.")
    parser.add_argument("--output", help="Output path. Defaults to data/instances/base/<name>.json")
    parser.add_argument("--output-dir", default="data/instances/base", help="Directory used when generating multiple instances.")
    parser.add_argument("--count", type=int, default=1, help="Number of instances to generate. Each instance increments the seed by 1.")
    parser.add_argument("--seed", type=int, default=0, help="Random seed.")
    parser.add_argument("--suppliers", type=int, default=3)
    parser.add_argument("--factories", type=int, default=2)
    parser.add_argument("--warehouses", type=int, default=3)
    parser.add_argument("--retailers", type=int, default=4)
    parser.add_argument("--airports", type=int, default=2)
    parser.add_argument("--seaports", type=int, default=2)
    parser.add_argument("--products", type=int, default=2)
    parser.add_argument("--raw-materials", type=int, default=2)
    parser.add_argument("--production-technologies", type=int, default=2)
    parser.add_argument("--remanufacturing-technologies", type=int, default=2)
    parser.add_argument("--periods", type=int, default=4)
    parser.add_argument("--coordinate-span-km", type=float, default=750.0)
    parser.add_argument("--trucks", type=int, default=DEFAULT_TRUCKS)
    parser.add_argument("--airplanes", type=int, default=DEFAULT_AIRPLANES)
    parser.add_argument("--boats", type=int, default=DEFAULT_BOATS)
    parser.add_argument("--tax-lower", type=float, default=0.0)
    parser.add_argument("--tax-upper", type=float, default=0.2)
    parser.add_argument("--sf-neighbors", type=int, default=2)
    parser.add_argument("--fw-neighbors", type=int, default=2)
    parser.add_argument("--wr-neighbors", type=int, default=2)
    parser.add_argument("--rf-neighbors", type=int, default=2)
    return parser


def generate_instances_from_args(args: argparse.Namespace) -> list[Path]:
    if args.count <= 0:
        raise ValueError("--count must be positive")

    written_paths: list[Path] = []
    for instance_index in range(args.count):
        instance_name = args.name if args.count == 1 else f"{args.name}_{instance_index + 1:03d}"
        config = GeneratorConfig(
            suppliers=args.suppliers,
            factories=args.factories,
            warehouses=args.warehouses,
            retailers=args.retailers,
            airports=args.airports,
            seaports=args.seaports,
            products=args.products,
            raw_materials=args.raw_materials,
            production_technologies=args.production_technologies,
            remanufacturing_technologies=args.remanufacturing_technologies,
            periods=args.periods,
            seed=args.seed + instance_index,
            instance_name=instance_name,
            coordinate_span_km=args.coordinate_span_km,
            trucks=args.trucks,
            airplanes=args.airplanes,
            boats=args.boats,
            tax_lower=args.tax_lower,
            tax_upper=args.tax_upper,
            connectivity=ArcConnectivityConfig(
                sf_neighbors=args.sf_neighbors,
                fw_neighbors=args.fw_neighbors,
                wr_neighbors=args.wr_neighbors,
                rf_neighbors=args.rf_neighbors,
            ),
        )
        instance = generate_instance(config)
        if args.output and args.count == 1:
            output_path = Path(args.output)
        else:
            output_path = Path(args.output_dir) / f"{instance_name}.json"
        written_paths.append(write_instance(instance, output_path))

    return written_paths


def main_instance(argv: Sequence[str] | None = None) -> None:
    args = build_instance_parser().parse_args(argv)
    for written_path in generate_instances_from_args(args):
        print(f"Wrote {written_path}")


def build_benchmark_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate STD benchmark base instances.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/instances/base",
        help="Output directory where STD base instance files are written directly.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "yaml"),
        default="json",
        help="Serialized instance format.",
    )
    parser.add_argument(
        "--seed-base",
        type=int,
        default=0,
        help="Deterministic offset used when deriving each base-instance seed from prefix + suffix.",
    )
    return parser


def main_benchmark(argv: Sequence[str] | None = None) -> None:
    parser = build_benchmark_parser()
    args = parser.parse_args(argv)

    summary = generate_benchmark(
        args.output_dir,
        include_base=True,
        seed_base=args.seed_base,
        file_format=args.format,
    )

    print(f"Base specs created: {summary.base_specs}")
    print(f"Base instances generated: {summary.base_instances}")
    print(f"Total files written: {summary.total_files}")
    print(f"Output location: {summary.output_dir.resolve()}")


def build_escalation_parser() -> argparse.ArgumentParser:
    parser = build_benchmark_parser()
    parser.description = (
        "Generate the three escalation instances (STD_I25_M12_T6, STD_I25_M16_T6, STD_I33_M8_T6), "
        "which extend the benchmark past its standard range and are not written by `benchmark`."
    )
    return parser


def main_escalation(argv: Sequence[str] | None = None) -> None:
    parser = build_escalation_parser()
    args = parser.parse_args(argv)

    summary = generate_escalation_bases(
        args.output_dir,
        seed_base=args.seed_base,
        file_format=args.format,
    )

    print(f"Escalation instances generated: {summary.base_instances}")
    print(f"Output location: {summary.output_dir.resolve()}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate single-instance data, the STD benchmark base dataset, or the escalation instances.",
    )
    subparsers = parser.add_subparsers(dest="command")

    instance_parser = subparsers.add_parser("instance", help="Generate one or more standalone instances.")
    for action in build_instance_parser()._actions:
        if action.dest != "help":
            instance_parser._add_action(action)

    benchmark_parser = subparsers.add_parser("benchmark", help="Generate the STD benchmark base instances.")
    for action in build_benchmark_parser()._actions:
        if action.dest != "help":
            benchmark_parser._add_action(action)

    escalation_parser = subparsers.add_parser(
        "escalation", help="Generate the three escalation instances (not part of `benchmark`).",
    )
    for action in build_escalation_parser()._actions:
        if action.dest != "help":
            escalation_parser._add_action(action)

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(raw_argv)

    if args.command == "instance":
        main_instance(raw_argv[1:])
        return
    if args.command == "benchmark":
        main_benchmark(raw_argv[1:])
        return
    if args.command == "escalation":
        main_escalation(raw_argv[1:])
        return

    parser.print_help()
    raise SystemExit(2)
