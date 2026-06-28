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

# Doubled from the plan's original 7200s/25200s (Phase 3.5 pre-flight check, 2026-06-26):
# STD_I25_M8_T6 hit the original 7200s cap at mip_gap~0.0001 (essentially converged, just
# needed more time) and 2 other classes ran 2-3x slower than the v1 historical baseline under
# the regenerated/bug-fixed instances.
PER_SUBPROBLEM_TIME_LIMIT_SECONDS = 14400.0
PER_RUN_WALL_CLOCK_CAP_SECONDS = 50400.0

# T12 is expected intractable (per the v1 paper finding); the goal is documenting where it
# stalls, not forcing convergence, so it gets one single hard cap instead of the regular
# Family A per-subproblem/wall-clock pair (plan §5b, "G ... incl. T12 probe").
T12_PROBE_HARD_CAP_SECONDS = 21600.0


def build_design_matrix() -> list[DesignPoint]:
    points = []
    for index, instance_id in enumerate(BASE_INSTANCES, start=1):
        is_t12_probe = instance_id.endswith("_T12")
        cap = T12_PROBE_HARD_CAP_SECONDS if is_t12_probe else PER_SUBPROBLEM_TIME_LIMIT_SECONDS
        wall_clock_cap = T12_PROBE_HARD_CAP_SECONDS if is_t12_probe else PER_RUN_WALL_CLOCK_CAP_SECONDS
        points.append(
            DesignPoint(
                family_id=FAMILY_ID,
                design_point_id=f"A-{index:02d}",
                run_code="baseline",
                base_instance_id=instance_id,
                execution_mode=EXECUTION_MODE,
                per_subproblem_time_limit_seconds=cap,
                per_run_wall_clock_cap_seconds=wall_clock_cap,
                notes="tractability probe" if is_t12_probe else "",
            )
        )
    return points
