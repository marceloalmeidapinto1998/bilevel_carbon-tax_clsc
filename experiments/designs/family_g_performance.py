"""Family G - Computational performance (RQ7).

The scaling table itself is read off Family A (solve time vs. I/M/T, including the T12
tractability-boundary probe) and is not re-run here. This family's *own* runs are a dedicated
Gurobi-setting sweep (threads x MIPFocus) on one stress instance, to characterize how much of
the solve-time scaling is the model's intrinsic difficulty vs. solver configuration. The
(threads=6, mip_focus=0) cell is the project default and is already covered by Family A, so it
is excluded here: 2 thread settings x 3 MIPFocus settings - 1 default cell = 5 dedicated runs,
plus Family A's baseline run and T12 probe complete the ~7-run picture this family answers to.
"""
from __future__ import annotations

import itertools

from experiments.designs._common import DesignPoint

FAMILY_ID = "G"
EXECUTION_MODE = "bilevel"

STRESS_INSTANCE = "STD_I25_M8_T6"
THREAD_SETTINGS: tuple[int, ...] = (1, 6)  # 6 is the system maximum
MIP_FOCUS_SETTINGS: tuple[int, ...] = (0, 1, 2)
DEFAULT_CELL = (6, 0)  # already covered by Family A; excluded from this family's dedicated runs

# Hard tier of the two-tier time-limit scheme (2026-07-01), see family_a_baseline.py:
# STRESS_INSTANCE is STD_I25_M8_T6, the campaign's largest cell.
PER_SUBPROBLEM_TIME_LIMIT_SECONDS = 10800.0
PER_RUN_WALL_CLOCK_CAP_SECONDS = 50400.0


def build_design_matrix() -> list[DesignPoint]:
    points: list[DesignPoint] = []
    index = 0
    for threads, mip_focus in itertools.product(THREAD_SETTINGS, MIP_FOCUS_SETTINGS):
        if (threads, mip_focus) == DEFAULT_CELL:
            continue
        index += 1
        points.append(
            DesignPoint(
                family_id=FAMILY_ID,
                design_point_id=f"G-{index:02d}",
                run_code=f"threads{threads}_focus{mip_focus}",
                base_instance_id=STRESS_INSTANCE,
                execution_mode=EXECUTION_MODE,
                per_subproblem_time_limit_seconds=PER_SUBPROBLEM_TIME_LIMIT_SECONDS,
                per_run_wall_clock_cap_seconds=PER_RUN_WALL_CLOCK_CAP_SECONDS,
                threads=threads,
                mip_focus=mip_focus,
            )
        )
    return points
