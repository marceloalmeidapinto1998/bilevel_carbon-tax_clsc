"""Family B - Tax-emissions frontier via fixed-tax parametric sweep (RQ1, RQ5).

Solves the follower's MILP at each fixed `tax_index` grid point (no leader optimization), so the
carbon-price non-identification issue cannot arise here: every point is exact for its tax,
subject only to the MILP gap. This is the family that actually answers RQ1 (the frontier
itself, not a point-estimate optimal tax).
"""
from __future__ import annotations

from experiments.designs._common import DesignPoint
from tools.experiments.doe_campaign_01.design.frontier_sweep import tax_grid

FAMILY_ID = "B"
EXECUTION_MODE = "fixed_tax"

# Smallest, mid, and largest *tractable* classes (T12 is the dedicated intractability probe in
# Family A/G, not a frontier-sweep candidate).
REPRESENTATIVE_INSTANCES: tuple[str, ...] = ("STD_I17_M4_T3", "STD_I25_M4_T6", "STD_I25_M8_T6")

OVERLINE_TAX_INDEX = 20  # all doe_campaign_01 base instances share this ceiling (overline_tau=0.20)
N_POINTS = 11
STEP = 2

# Two-tier time-limit scheme (2026-07-01), see family_a_baseline.py. fixed_tax is a single MILP
# solve (no DBP iteration), so wall-clock cap == per-subproblem cap for both tiers.
STANDARD_SUBPROBLEM_SECONDS = 3600.0
HARD_SUBPROBLEM_SECONDS = 10800.0

HARD_TIER_INSTANCES: frozenset[str] = frozenset({"STD_I25_M8_T6"})


def build_design_matrix() -> list[DesignPoint]:
    grid = tax_grid(OVERLINE_TAX_INDEX, n_points=N_POINTS, step=STEP)
    points: list[DesignPoint] = []
    index = 0
    for instance_id in REPRESENTATIVE_INSTANCES:
        cap = HARD_SUBPROBLEM_SECONDS if instance_id in HARD_TIER_INSTANCES else STANDARD_SUBPROBLEM_SECONDS
        for tax_index in grid:
            index += 1
            points.append(
                DesignPoint(
                    family_id=FAMILY_ID,
                    design_point_id=f"B-{index:02d}",
                    run_code=f"tau{tax_index:02d}",
                    base_instance_id=instance_id,
                    execution_mode=EXECUTION_MODE,
                    per_subproblem_time_limit_seconds=cap,
                    per_run_wall_clock_cap_seconds=cap,
                    fixed_tax_index=tax_index,
                )
            )
    return points
