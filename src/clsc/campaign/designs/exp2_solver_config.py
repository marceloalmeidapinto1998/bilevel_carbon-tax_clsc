"""Experiment 2 - Solver Configuration (docs/Experimental_Plan.md §11.2).

Full 3x3 threads x MIPFocus grid on the hardest cell (I25-M8-T6), plus 2 Gurobi-seed probes on
the expected-winning configuration = 11 bilevel solves. Fixes threads/MIPFocus for the campaign
and quantifies the seed-noise floor for later runtime comparisons.
"""
from __future__ import annotations

from clsc.campaign.designs._cells import cell_id, time_limits
from clsc.campaign.designs._common import DesignPoint

EXPERIMENT_ID = "exp2"
CONFIG_CELL = cell_id(25, 8, 6)
THREADS_LEVELS = (2, 4, 6)
MIP_FOCUS_LEVELS = (0, 1, 2)
# Seed probes run on the configuration the prior campaign found best; confirmed/updated by this
# experiment's own grid before the probes are interpreted.
WINNER_THREADS = 4
WINNER_MIP_FOCUS = 2
SEED_PROBE_SEEDS = (1, 2)


def build_design_matrix() -> list[DesignPoint]:
    sub, wall = time_limits(CONFIG_CELL)
    points: list[DesignPoint] = []

    for threads in THREADS_LEVELS:
        for mip_focus in MIP_FOCUS_LEVELS:
            points.append(DesignPoint(
                experiment_id=EXPERIMENT_ID,
                design_point_id=f"exp2-t{threads}-f{mip_focus}",
                run_code=f"threads{threads}_focus{mip_focus}", base_instance_id=CONFIG_CELL,
                execution_mode="bilevel", threads=threads, mip_focus=mip_focus,
                per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
                notes="threads x MIPFocus configuration grid (H2.1).",
            ))

    for gurobi_seed in SEED_PROBE_SEEDS:
        points.append(DesignPoint(
            experiment_id=EXPERIMENT_ID,
            design_point_id=f"exp2-seedprobe-s{gurobi_seed}",
            run_code=f"winner_seed{gurobi_seed}", base_instance_id=CONFIG_CELL,
            execution_mode="bilevel", threads=WINNER_THREADS, mip_focus=WINNER_MIP_FOCUS,
            gurobi_seed=gurobi_seed,
            per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
            notes="Gurobi-seed noise-floor probe on the winning configuration.",
        ))

    return points
