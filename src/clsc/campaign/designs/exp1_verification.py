"""Experiment 1 - Verification and Solution Validation (docs/Experimental_Plan.md §1).

A validation battery (not a factorial): 6 toy instances, all 12 base cells at seed 0, a
structural-invariant probe (fixed-tax follower solves at 2 tax points on 2 cells), and a
Gurobi-seed invariance probe on 1 fast cell. The certified-exact rate on the base cells is the
hard gate for the rest of the campaign.
"""
from __future__ import annotations

from clsc.campaign.designs._cells import ALL_CELLS, FAST_CELLS, HARD_CELLS, time_limits
from clsc.campaign.designs._common import DesignPoint, fine_index
from clsc.campaign.toy import TOY_SPECS

EXPERIMENT_ID = "exp1"

# Structural-invariant probe: 1 fast + 1 hard cell, each solved at 2 tax points (0 and the grid
# ceiling) on the campaign's fine grid. Stated as a RATE (USD/kg CO2e) and converted, so these
# probes sit on the same grid as the bilevel tau* they are compared against.
INVARIANT_CELLS = (FAST_CELLS[0], HARD_CELLS[0])
INVARIANT_TAX_RATES_USD_PER_KG = (0.0, 0.2)
INVARIANT_TAX_INDICES = tuple(fine_index(rate) for rate in INVARIANT_TAX_RATES_USD_PER_KG)

# Gurobi-seed invariance probe: 1 fast cell at seed in {1, 2} (seed 0 is the base-cell run).
SEED_PROBE_CELLS = (FAST_CELLS[0],)
SEED_PROBE_SEEDS = (1, 2)


def build_design_matrix() -> list[DesignPoint]:
    points: list[DesignPoint] = []

    # 6 hand-verifiable toy instances (bilevel, tiny reduced dimensions).
    for spec in TOY_SPECS:
        points.append(DesignPoint(
            experiment_id=EXPERIMENT_ID, design_point_id=f"exp1-toy-{spec.name}",
            run_code=f"toy_{spec.name}", base_instance_id=spec.name,
            execution_mode="bilevel", is_toy=True,
            per_subproblem_time_limit_seconds=600.0, per_run_wall_clock_cap_seconds=3600.0,
            notes="Hand-verifiable toy instance (H1.2).",
        ))

    # All 12 base structural cells, seed 0 -> certified-exact rate (H1.1, the hard gate).
    for cell in ALL_CELLS:
        sub, wall = time_limits(cell)
        points.append(DesignPoint(
            experiment_id=EXPERIMENT_ID, design_point_id=f"exp1-base-{cell}",
            run_code="base", base_instance_id=cell, execution_mode="bilevel",
            per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
            notes="Base-cell certified-exact gate (H1.1).",
        ))

    # Structural-invariant probes: direct follower solves at 4 tax points per cell (H1.3).
    for cell in INVARIANT_CELLS:
        sub, wall = time_limits(cell)
        for tax_index in INVARIANT_TAX_INDICES:
            points.append(DesignPoint(
                experiment_id=EXPERIMENT_ID,
                design_point_id=f"exp1-invariant-{cell}-tau{tax_index:04d}",
                run_code=f"invariant_tau{tax_index:04d}", base_instance_id=cell,
                execution_mode="fixed_tax", fixed_tax_index=tax_index,
                invariant_tax_indices=INVARIANT_TAX_INDICES,
                per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
                notes="Structural-invariant probe (H1.3).",
            ))

    # Gurobi-seed invariance probes: 2 fast cells at seed in {1, 2} (H1.4 seed-invariance witness).
    for cell in SEED_PROBE_CELLS:
        sub, wall = time_limits(cell)
        for gurobi_seed in SEED_PROBE_SEEDS:
            points.append(DesignPoint(
                experiment_id=EXPERIMENT_ID,
                design_point_id=f"exp1-seedprobe-{cell}-s{gurobi_seed}",
                run_code=f"seedprobe_s{gurobi_seed}", base_instance_id=cell,
                execution_mode="bilevel", gurobi_seed=gurobi_seed,
                per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
                notes="Gurobi-seed invariance probe (H1.4).",
            ))

    return points
