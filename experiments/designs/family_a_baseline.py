"""Family A - Baseline benchmark (RQ2, RQ7).

No factors varied: solves the bilevel leader-follower procedure on each of the 9 regenerated
base instances (8 structural I/M/T classes + the I17_M4_T12 tractability probe) at its native
parameters. Establishes the per-class optimal-tax band, cost/emissions, network structure, and
solve time that every other family's perturbations are read relative to.
"""
from __future__ import annotations

from experiments.designs._common import DesignPoint

FAMILY_ID = "A"
EXECUTION_MODE = "bilevel"

BASE_INSTANCES: tuple[str, ...] = (
    "STD_I17_M4_T3", "STD_I17_M4_T6",
    "STD_I17_M8_T3", "STD_I17_M8_T6",
    "STD_I25_M4_T3", "STD_I25_M4_T6",
    "STD_I25_M8_T3", "STD_I25_M8_T6",
    "STD_I17_M4_T12",  # tractability probe, RQ7
)

# Two-tier time-limit scheme (2026-07-01), replacing the ad-hoc per-family caps grown in
# response to individual censored runs. Standard tier mirrors Tautenhain et al. (2021)'s stated
# CPLEX cap for a single mono-objective MILP (3,600 s / 1 h); hard tier mirrors their exceptional
# cap for their computationally harder case study (10,800 s / 3 h). Wall-clock caps keep this
# project's existing ~8x per-subproblem multiplier. Applied to STD_I25_M8_T6 (largest I/M/T
# combination in the campaign) and the T12 tractability probe (most periods), both of which are
# expected to need the full budget; every other class gets the standard tier.
STANDARD_SUBPROBLEM_SECONDS = 3600.0
STANDARD_WALL_CLOCK_SECONDS = 28800.0
HARD_SUBPROBLEM_SECONDS = 10800.0
HARD_WALL_CLOCK_SECONDS = 50400.0

HARD_TIER_INSTANCES: frozenset[str] = frozenset({"STD_I25_M8_T6", "STD_I17_M4_T12"})


def build_design_matrix() -> list[DesignPoint]:
    points = []
    for index, instance_id in enumerate(BASE_INSTANCES, start=1):
        is_hard = instance_id in HARD_TIER_INSTANCES
        is_t12_probe = instance_id.endswith("_T12")
        subproblem_cap = HARD_SUBPROBLEM_SECONDS if is_hard else STANDARD_SUBPROBLEM_SECONDS
        wall_clock_cap = HARD_WALL_CLOCK_SECONDS if is_hard else STANDARD_WALL_CLOCK_SECONDS
        points.append(
            DesignPoint(
                family_id=FAMILY_ID,
                design_point_id=f"A-{index:02d}",
                run_code="baseline",
                base_instance_id=instance_id,
                execution_mode=EXECUTION_MODE,
                per_subproblem_time_limit_seconds=subproblem_cap,
                per_run_wall_clock_cap_seconds=wall_clock_cap,
                notes="tractability probe" if is_t12_probe else "",
            )
        )
    return points
