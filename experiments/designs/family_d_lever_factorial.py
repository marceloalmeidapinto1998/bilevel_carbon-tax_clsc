"""Family D - Design-lever factorial (RQ4).

Full 2^4 factorial over the genuinely actionable design levers (technology menu, transport
menu, return/collection rate, demand) on a small and a large representative instance, to read
off interaction effects directly (e.g. does technology breadth only help abatement when returns
are high?) rather than relying on the screening design's aliasing structure.
"""
from __future__ import annotations

from experiments.designs._common import DesignPoint
from tools.experiments.v2.design.full_factorial import full_factorial_signs
from tools.experiments.v2.factors import FACTOR_REGISTRY

FAMILY_ID = "D"
EXECUTION_MODE = "bilevel"

SMALL_INSTANCE = "STD_I17_M4_T3"
LARGE_INSTANCE = "STD_I25_M8_T6"
INSTANCES: tuple[str, ...] = (SMALL_INSTANCE, LARGE_INSTANCE)

LEVER_FACTORS: tuple[str, ...] = ("technology_menu", "transport_menu", "return_availability", "demand")

# Doubled from the plan's original 3600s/14400s (Phase 3.5 pre-flight check, 2026-06-26):
# the large representative instance (STD_I25_M8_T6) hit the original Family A cap at
# mip_gap~0.0001, essentially converged but needing more time.
PER_SUBPROBLEM_TIME_LIMIT_SECONDS = 7200.0
PER_RUN_WALL_CLOCK_CAP_SECONDS = 28800.0


def build_design_matrix() -> list[DesignPoint]:
    design = full_factorial_signs(LEVER_FACTORS)  # 16 rows

    points: list[DesignPoint] = []
    index = 0
    for instance_id in INSTANCES:
        for signs in design:
            index += 1
            factor_levels: dict[str, float] = {}
            technology_menu = "expanded" if signs["technology_menu"] > 0 else "base"
            transport_menu = "expanded" if signs["transport_menu"] > 0 else "base"
            for factor_name in ("return_availability", "demand"):
                spec = FACTOR_REGISTRY[factor_name]
                factor_levels[factor_name] = spec.high if signs[factor_name] > 0 else spec.low
            points.append(
                DesignPoint(
                    family_id=FAMILY_ID,
                    design_point_id=f"D-{index:02d}",
                    run_code=f"run{index:02d}",
                    base_instance_id=instance_id,
                    execution_mode=EXECUTION_MODE,
                    per_subproblem_time_limit_seconds=PER_SUBPROBLEM_TIME_LIMIT_SECONDS,
                    per_run_wall_clock_cap_seconds=PER_RUN_WALL_CLOCK_CAP_SECONDS,
                    factor_levels=factor_levels,
                    technology_menu=technology_menu,
                    transport_menu=transport_menu,
                )
            )
    return points
