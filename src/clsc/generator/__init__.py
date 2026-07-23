"""CLSC instance generator (Tautenhain-based benchmark sampler).

Role modules:
  config     — GeneratorConfig, ArcConnectivityConfig, constants, tax helper
  models     — GeneratedInstance
  geometry   — coordinate + arc/network builders
  sampling   — demand / BOM / profile / capacity sampling (uses tautenhain_data)
  instance   — generate_instance() + write_instance()
  benchmark  — STD benchmark set building
  cli        — argparse parsers + main
  tautenhain_data — sampling rules/constants
  feasibility — generate_feasible_instance(): retries generate_instance() with a perturbed seed
                until the follower's network-flow relaxation is feasible. Not imported here
                (it depends on clsc.models/Gurobi) -- import it explicitly when needed.
"""
from __future__ import annotations

from .benchmark import (
    BenchmarkSpec,
    BenchmarkSummary,
    apply_prefix_override,
    build_base_benchmark_specs,
    entity_split,
    generate_benchmark,
)
from .cli import (
    build_benchmark_parser,
    build_instance_parser,
    build_parser,
    generate_instances_from_args,
    main,
    main_benchmark,
    main_instance,
)
from .config import (
    SCALE_FACTOR,
    DEFAULT_AIRPLANES,
    DEFAULT_BOATS,
    DEFAULT_TRANSPORT_MODES,
    DEFAULT_TRUCKS,
    ArcConnectivityConfig,
    GeneratorConfig,
)
from .instance import generate_instance, write_instance
from .models import GeneratedInstance

__all__ = [
    "ArcConnectivityConfig",
    "BenchmarkSpec",
    "BenchmarkSummary",
    "SCALE_FACTOR",
    "DEFAULT_AIRPLANES",
    "DEFAULT_BOATS",
    "DEFAULT_TRANSPORT_MODES",
    "DEFAULT_TRUCKS",
    "GeneratedInstance",
    "GeneratorConfig",
    "apply_prefix_override",
    "build_base_benchmark_specs",
    "build_benchmark_parser",
    "build_instance_parser",
    "build_parser",
    "entity_split",
    "generate_benchmark",
    "generate_instance",
    "generate_instances_from_args",
    "main",
    "main_benchmark",
    "main_instance",
    "write_instance",
]
