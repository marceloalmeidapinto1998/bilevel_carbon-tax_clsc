"""Experiment 4 - Scalability Analysis (docs/Experimental_Plan.md §8.2).

The 12-cell core grid is Experiment 3's M0 arm (no separate solves). This experiment adds only one
escalation probe on the empirically dominant axis: M in {8 -> 12} at (I25, T6), one seed, hard-tier
caps. Here M is the materials/products richness code (M12 -> 6 raw materials / 3 products, following
the M4->2/1, M8->4/2 pattern); the technology counts stay fixed at 3.

The escalation base STD_I25_M12_T6 lives alongside the standard 12 under data/instances/base/. It is
NOT part of the standard benchmark set (`python -m clsc.generator benchmark`, which covers M in
{4,8}); it is generated deterministically as a one-off via a BenchmarkSpec with raw_materials=6,
products=3, entity_split(25), periods=6, and the standard deterministic seed.
"""
from __future__ import annotations

from clsc.campaign.designs._cells import HARD_TIER_LIMITS
from clsc.campaign.designs._common import DesignPoint

EXPERIMENT_ID = "exp4"
ESCALATION_CELL = "STD_I25_M12_T6"  # escalation-only base (materials code 12); see module docstring.


def build_design_matrix() -> list[DesignPoint]:
    sub, wall = HARD_TIER_LIMITS
    return [
        DesignPoint(
            experiment_id=EXPERIMENT_ID, design_point_id=f"exp4-escalation-{ESCALATION_CELL}",
            run_code="escalation_M12", base_instance_id=ESCALATION_CELL,
            execution_mode="bilevel",
            per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
            notes="M12 escalation probe (H4.1/H4.2); requires generating the M12 base instance.",
        )
    ]
