"""Family A - Baseline benchmark (RQ2, RQ7).

No factors varied: one bilevel solve per base instance at native parameters, on the full 12-
instance grid (I in {17,25} x M in {4,8} x T in {3,6,12}). Establishes the per-class optimal-tax
band, cost, emissions, network structure, and solve time that every other family's results are
read *relative to*. The four T12 instances are tractability probes only -- convergence is not
expected -- documenting where the solver stalls at the tractability boundary across every I x M
combination (EXPERIMENTAL_PLAN.md §4-A; doe_campaign_01's Family A covered only one T12 probe,
STD_I17_M4_T12 -- this campaign completes the T12 row for all four I x M combinations).
"""
from __future__ import annotations

from clsc.campaign.designs._common import DesignPoint

FAMILY_ID = "A"
EXECUTION_MODE = "bilevel"

BASE_INSTANCES: tuple[str, ...] = (
    "STD_I17_M4_T3", "STD_I17_M4_T6", "STD_I17_M4_T12",
    "STD_I17_M8_T3", "STD_I17_M8_T6", "STD_I17_M8_T12",
    "STD_I25_M4_T3", "STD_I25_M4_T6", "STD_I25_M4_T12",
    "STD_I25_M8_T3", "STD_I25_M8_T6", "STD_I25_M8_T12",
)

# Two-tier time-limit scheme, see EXPERIMENTAL_PLAN.md §3.
STANDARD_SUBPROBLEM_SECONDS = 3600.0
STANDARD_WALL_CLOCK_SECONDS = 28800.0
HARD_SUBPROBLEM_SECONDS = 10800.0
HARD_WALL_CLOCK_SECONDS = 50400.0

HARD_TIER_INSTANCES: frozenset[str] = frozenset({
    "STD_I25_M8_T6", "STD_I17_M4_T12", "STD_I17_M8_T12", "STD_I25_M4_T12", "STD_I25_M8_T12",
})


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
