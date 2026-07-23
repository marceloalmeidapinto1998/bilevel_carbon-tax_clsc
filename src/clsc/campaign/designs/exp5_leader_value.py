"""Experiment 5 - Value of the Bilevel Leader (docs/Experimental_Plan.md §7).

Compares the bilevel leader's tax against simpler policy rules on all 12 cells. P3 (tau* bilevel
lexicographic) is Experiment 3's M0 result on the same cell -- not re-solved here. P0/P1/P2 are
one fresh follower-only lexicographic solve each per cell.

NOTE: P4 (plateau right edge) is the LARGEST tax still achieving the certified emissions floor E*,
which is data-dependent (it needs the solved plateau). It is therefore added in a second stage
after the emissions-vs-tax staircase is available, and is NOT emitted here. With P4 that would be
48 follower solves; this static stage emits P0/P1/P2 = 36.
"""
from __future__ import annotations

from clsc.campaign.designs._cells import ALL_CELLS, time_limits
from clsc.campaign.designs._common import DesignPoint

EXPERIMENT_ID = "exp5"

# Policy rules solved as fixed-tax follower runs, on the instance's native coarse grid (index 0..20):
#   P0 no tax; P1 tax ceiling; P2 mid-grid flat tax. (P3 = Exp3 M0; P4 = plateau right edge, stage 2.)
POLICY_RULES = {
    "P0_no_tax": 0,
    "P1_ceiling": 20,
    "P2_mid": 10,
}


def build_design_matrix() -> list[DesignPoint]:
    points: list[DesignPoint] = []
    for cell in ALL_CELLS:
        sub, wall = time_limits(cell)
        for run_code, tax_index in POLICY_RULES.items():
            points.append(DesignPoint(
                experiment_id=EXPERIMENT_ID, design_point_id=f"exp5-{run_code}-{cell}",
                run_code=run_code, base_instance_id=cell,
                execution_mode="fixed_tax", fixed_tax_index=tax_index,
                per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
                notes="Policy-rule follower solve (H5.1/H5.2).",
            ))
    return points
