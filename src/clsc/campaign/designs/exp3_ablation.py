"""Experiment 3 - Ablation Study of the DBP Algorithm (docs/Experimental_Plan.md §8.1).

M0 (full DBP) on all 12 cells with the seed policy of §2.1 (27 solves), plus weakened variants:
A1 (no Phase-2 bisection) and A4 (coarse grid) on 6 representative instances each, and A2/A3/A5
(efficiency-only) on 2 fast instances each. Every variant is compared paired against M0 on the
same instance.
"""
from __future__ import annotations

from clsc.campaign.designs._cells import (
    FAST_CELLS, HARD_TIER_CELLS, REPRESENTATIVE_CELLS, STANDARD_TIER_CELLS, cell_id, time_limits,
)
from clsc.campaign.designs._common import COARSE_SCALE_FACTOR, DesignPoint

EXPERIMENT_ID = "exp3"

# Standard-tier seed policy: 3 seeds; hard-tier: seed 0 only, plus a single spot-check on I25-M8-T6.
STANDARD_SEEDS = (0, 1, 2)
SPOT_CHECK_CELL = cell_id(25, 8, 6)
SPOT_CHECK_SEED = 1

# A4's coarse tax-grid step (the base instances' native grid, index 0..20) comes from _common so
# that both campaign grids have exactly one definition.

CLAIM_CARRYING_VARIANTS = ("A1", "A4")      # change the certified guarantee -> 6 representative cells
EFFICIENCY_VARIANTS = ("A2", "A3", "A5")    # efficiency only -> 2 fast cells


def _bilevel(cell: str, *, run_code: str, dpid: str, variant: str = "M0",
             seed_offset: int = 0, scale_factor: float | None = None, note: str = "") -> DesignPoint:
    sub, wall = time_limits(cell)
    return DesignPoint(
        experiment_id=EXPERIMENT_ID, design_point_id=dpid, run_code=run_code,
        base_instance_id=cell, execution_mode="bilevel", algorithm_variant=variant,
        seed_offset=seed_offset, scale_factor=scale_factor,
        per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall, notes=note,
    )


def build_design_matrix() -> list[DesignPoint]:
    points: list[DesignPoint] = []

    # M0 reference. Standard cells: 3 seeds. Hard cells: seed 0 (+ spot-check on I25-M8-T6).
    for cell in STANDARD_TIER_CELLS:
        for seed in STANDARD_SEEDS:
            points.append(_bilevel(
                cell, run_code=f"M0_seed{seed}", dpid=f"exp3-M0-{cell}-s{seed}",
                seed_offset=seed, note="M0 reference (leader value P3 / scalability core).",
            ))
    for cell in sorted(HARD_TIER_CELLS):
        points.append(_bilevel(
            cell, run_code="M0_seed0", dpid=f"exp3-M0-{cell}-s0", seed_offset=0,
            note="M0 reference, hard tier.",
        ))
    points.append(_bilevel(
        SPOT_CHECK_CELL, run_code=f"M0_seed{SPOT_CHECK_SEED}",
        dpid=f"exp3-M0-{SPOT_CHECK_CELL}-s{SPOT_CHECK_SEED}", seed_offset=SPOT_CHECK_SEED,
        note="Hard-tier stability spot-check (§2.1).",
    ))

    # A1 / A4 (claim-carrying): 6 representative instances, seed 0.
    for cell in REPRESENTATIVE_CELLS:
        points.append(_bilevel(
            cell, run_code="A1", dpid=f"exp3-A1-{cell}", variant="A1",
            note="A1: no Phase-2 min-tax bisection (H3.1).",
        ))
        points.append(_bilevel(
            cell, run_code="A4", dpid=f"exp3-A4-{cell}", variant="A4",
            scale_factor=COARSE_SCALE_FACTOR, note="A4: coarse tax grid (H3.4).",
        ))

    # A2 / A3 / A5 (efficiency): 2 fast instances, seed 0.
    for cell in FAST_CELLS:
        for variant in EFFICIENCY_VARIANTS:
            points.append(_bilevel(
                cell, run_code=variant, dpid=f"exp3-{variant}-{cell}", variant=variant,
                note=f"{variant}: efficiency ablation (H3.2/H3.3/H3.5).",
            ))

    return points
