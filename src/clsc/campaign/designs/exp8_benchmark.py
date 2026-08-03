"""Experiment 8 - Benchmark against Exhaustive Grid Enumeration (docs/Experimental_Plan.md §7).

The leader controls one integer on a finite grid, so solving the follower at every grid point is
exact by construction -- no cuts, no relaxation master, no theory beyond "try them all". It is the
natural competitor a referee would propose, and the comparison against DBP's own (E*, tau*) and
follower-solve count is what this experiment supplies.

2 fast cells (I17-M4-T3, I17-M4-T6) + 2 medium cells (I17-M8-T6, I25-M4-T6), seed 0, each a single
`enumeration` design point.

Fast cells use DBP's own tier caps (a fair budget-matched comparison against exp3's M0 arm on the
same cell): a direct timing on I17-M4-T3 measured ~5.5 s/grid point, so the full 2001-point grid
(~3.1 h) fits comfortably inside the fast tier's 8 h wall cap -- these are expected to reach
`termination_reason="exhausted"`, a true exact certificate, not a projection.

Medium cells get an EXPLICIT, tighter cap (`MEDIUM_CELL_WALL_CLOCK_CAP_SECONDS`) instead of
inheriting DBP's tier caps (which run 8-14 h and, at any per-point cost above ~14 s, would run to
their full length without exhausting the grid). The comparison's core quantity -- the measured
follower-solve-count ratio, reported as a lower bound on the speed-up when censored -- does not
improve with additional grid coverage once a stable average is established, so there is no
scientific reason to let a medium cell run for half a day past that point.
"""
from __future__ import annotations

from clsc.campaign.designs._cells import FAST_CELLS, MEDIUM_CELLS, time_limits
from clsc.campaign.designs._common import DesignPoint

EXPERIMENT_ID = "exp8"
BENCHMARK_CELLS = FAST_CELLS + MEDIUM_CELLS

MEDIUM_CELL_SUBPROBLEM_TIME_LIMIT_SECONDS = 1800.0   # 30 min: generous for one fixed-tax follower MILP
MEDIUM_CELL_WALL_CLOCK_CAP_SECONDS = 7200.0          # 2 h: bounds the tail without weakening the ratio


def build_design_matrix() -> list[DesignPoint]:
    points: list[DesignPoint] = []
    for cell in BENCHMARK_CELLS:
        if cell in MEDIUM_CELLS:
            sub, wall = MEDIUM_CELL_SUBPROBLEM_TIME_LIMIT_SECONDS, MEDIUM_CELL_WALL_CLOCK_CAP_SECONDS
        else:
            sub, wall = time_limits(cell)
        points.append(DesignPoint(
            experiment_id=EXPERIMENT_ID, design_point_id=f"exp8-enum-{cell}",
            run_code="enumeration", base_instance_id=cell,
            execution_mode="enumeration",
            per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
            notes="Exhaustive fine-grid enumeration baseline (H8.1/H8.2).",
        ))
    return points
