"""Family 0 - Solver pre-flight (RQ7).

A dedicated Gurobi-configuration sweep (threads x MIPFocus) on the hardest instance, run before
every other family, to determine and justify the threads/mip_focus settings the rest of the
campaign uses (EXPERIMENTAL_PLAN.md §4-0). Unlike doe_campaign_01's equivalent sweep
(family_g_performance.py, which excluded the (threads=6, mip_focus=0) cell because it was already
covered by that campaign's Family A baseline at the project default), this campaign runs the
full 3x3 grid: Family A here uses a provisional MIPFocus ahead of this sweep's own result, so no
cell can be assumed pre-covered.
"""
from __future__ import annotations

import itertools

from clsc.campaign.designs._common import DesignPoint

FAMILY_ID = "0"
EXECUTION_MODE = "bilevel"

STRESS_INSTANCE = "STD_I25_M8_T6"
THREAD_SETTINGS: tuple[int, ...] = (2, 4, 6)
MIP_FOCUS_SETTINGS: tuple[int, ...] = (0, 1, 2)

# Hard tier of the two-tier time-limit scheme (EXPERIMENTAL_PLAN.md §3): STRESS_INSTANCE is
# STD_I25_M8_T6, the campaign's largest I x M x T combination.
PER_SUBPROBLEM_TIME_LIMIT_SECONDS = 10800.0
PER_RUN_WALL_CLOCK_CAP_SECONDS = 50400.0


def build_design_matrix() -> list[DesignPoint]:
    points: list[DesignPoint] = []
    index = 0
    for threads, mip_focus in itertools.product(THREAD_SETTINGS, MIP_FOCUS_SETTINGS):
        index += 1
        points.append(
            DesignPoint(
                family_id=FAMILY_ID,
                design_point_id=f"0-{index:02d}",
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
