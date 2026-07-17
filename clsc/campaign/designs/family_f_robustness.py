"""Family F - Robustness checks (RQ6).

Two orthogonal probes on the 4 T3 classes (fast enough to afford replication):
  - 3 additional random seeds per class at the default solver tolerance, to check whether
    RQ3-RQ5's conclusions are an artifact of one random instance draw.
  - 2 additional tolerance settings (tight, loose) per class at the base seed, to check
    whether they are an artifact of the solver gap. The default-tolerance/base-seed point is
    already covered by Family A, so it is not re-run here.

4 classes x (3 seeds + 2 tolerances) = 20 runs, matching the plan's ~20 budget exactly.
"""
from __future__ import annotations

from clsc.campaign.designs._common import DesignPoint
from clsc.campaign.doe.robustness import TOLERANCE_SETTINGS, seed_grid

FAMILY_ID = "F"
EXECUTION_MODE = "bilevel"

T3_INSTANCES: tuple[str, ...] = ("STD_I17_M4_T3", "STD_I17_M8_T3", "STD_I25_M4_T3", "STD_I25_M8_T3")

N_EXTRA_SEEDS = 3
NON_DEFAULT_TOLERANCES = tuple(setting for setting in TOLERANCE_SETTINGS if setting.label != "default")

PER_SUBPROBLEM_TIME_LIMIT_SECONDS = 1800.0
PER_RUN_WALL_CLOCK_CAP_SECONDS = 7200.0


def build_design_matrix() -> list[DesignPoint]:
    points: list[DesignPoint] = []
    index = 0

    for instance_id in T3_INSTANCES:
        for seed_offset in seed_grid(N_EXTRA_SEEDS):
            index += 1
            points.append(
                DesignPoint(
                    family_id=FAMILY_ID,
                    design_point_id=f"F-{index:02d}",
                    run_code=f"seed{seed_offset}",
                    base_instance_id=instance_id,
                    execution_mode=EXECUTION_MODE,
                    per_subproblem_time_limit_seconds=PER_SUBPROBLEM_TIME_LIMIT_SECONDS,
                    per_run_wall_clock_cap_seconds=PER_RUN_WALL_CLOCK_CAP_SECONDS,
                    seed_offset=seed_offset,
                )
            )
        for setting in NON_DEFAULT_TOLERANCES:
            index += 1
            points.append(
                DesignPoint(
                    family_id=FAMILY_ID,
                    design_point_id=f"F-{index:02d}",
                    run_code=f"tol_{setting.label}",
                    base_instance_id=instance_id,
                    execution_mode=EXECUTION_MODE,
                    per_subproblem_time_limit_seconds=PER_SUBPROBLEM_TIME_LIMIT_SECONDS,
                    per_run_wall_clock_cap_seconds=PER_RUN_WALL_CLOCK_CAP_SECONDS,
                    mip_gap=setting.mip_gap,
                    dbp_relative_gap=setting.dbp_relative_gap,
                )
            )
    return points
