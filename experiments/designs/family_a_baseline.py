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

PER_SUBPROBLEM_TIME_LIMIT_SECONDS = 7200.0
PER_RUN_WALL_CLOCK_CAP_SECONDS = 25200.0


def build_design_matrix() -> list[DesignPoint]:
    return [
        DesignPoint(
            family_id=FAMILY_ID,
            design_point_id=f"A-{index:02d}",
            run_code="baseline",
            base_instance_id=instance_id,
            execution_mode=EXECUTION_MODE,
            per_subproblem_time_limit_seconds=PER_SUBPROBLEM_TIME_LIMIT_SECONDS,
            per_run_wall_clock_cap_seconds=PER_RUN_WALL_CLOCK_CAP_SECONDS,
            notes="tractability probe" if instance_id.endswith("_T12") else "",
        )
        for index, instance_id in enumerate(BASE_INSTANCES, start=1)
    ]
