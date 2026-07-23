"""Experiment 4 - Scalability Analysis (docs/Experimental_Plan.md §6).

The 12-cell core grid is Experiment 3's M0 arm (no separate solves). This experiment adds only one
escalation probe on the empirically dominant axis: M in {8 -> 12} at (I25, T6), one seed, hard-tier
caps.

NOTE: the M12 base instance (STD_I25_M12_T6) is not part of the standard 12-cell base set and must
be generated before this probe can be solved (the generator's benchmark specs currently cover
M in {4, 8}). The design point is emitted so the frontier statement is planned; `run` will fail at
materialization until the M12 base exists.
"""
from __future__ import annotations

from clsc.campaign.designs._cells import HARD_TIER_LIMITS
from clsc.campaign.designs._common import DesignPoint

EXPERIMENT_ID = "exp4"
ESCALATION_CELL = "STD_I25_M12_T6"  # not in the base set yet -- see module docstring.


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
